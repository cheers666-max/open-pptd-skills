#!/usr/bin/env python3
"""360 online HTML export: download images, upload to OBS or attachments, export stable URLs.

Uses the existing local viewer in a temporary PPTD snapshot. Original project
files are unchanged. PPT_API_KEY authenticates uploads only; S3_API_URL overrides
the attachment endpoint derived from PPT_API_BASE. OBS_CONFIG selects an existing
S3-compatible OBS config instead. No credentials enter HTML.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile

from export_html import VIEWER_DEFAULT, find_chrome, find_deck, run_viewer_export
from obs_upload import OBSClient, ObsError

MAX_IMAGE_BYTES = 20 * 1024 * 1024
UA = 'Mozilla/5.0 (compatible; open-pptd-online/1.0)'


class OnlineError(RuntimeError):
    pass


def progress(message):
    print(f'[online] {message}', file=sys.stderr, flush=True)


def web_url(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise OnlineError('Invalid HTTP(S) URL')
    try:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        parsed.port
    except ValueError:
        raise OnlineError('Invalid HTTP(S) URL') from None
    # Keep query delimiters and existing percent escapes, encode HTML/CSS delimiters.
    return urllib.parse.quote(value, safe=':/?#[]@!$&*+,;=%~_-.')


class NoUploadRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise OnlineError('Upload redirect refused; configure the final S3_API_URL')


class AttachmentClient:
    def __init__(self, timeout=30):
        self.key = next((os.environ[k].strip() for k in ('PPT_API_KEY', 'QIHOO_360_API_KEY', 'QIHOO_API_KEY')
                         if os.environ.get(k, '').strip()), '')
        if not self.key:
            raise OnlineError('Set PPT_API_KEY for 360 attachment uploads')
        base = os.environ.get('PPT_API_BASE', '').strip().rstrip('/') or 'https://aigw.aijjt.com'
        if not base.endswith('/v1'):
            base += '/v1'
        self.endpoint = web_url(os.environ.get('S3_API_URL', '').strip() or base + '/upload/attachment')
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoUploadRedirect())

    def upload(self, data, filename, content_type):
        # Only generated ASCII basenames are used; never use a remote URL as filename.
        if not filename or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.' for c in filename):
            raise OnlineError('Invalid upload filename')
        boundary = 'pptd-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f'Content-Type: {content_type}\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        request = urllib.request.Request(self.endpoint, data=body, method='POST', headers={
            'Authorization': 'Bearer ' + self.key,
            'Content-Type': 'multipart/form-data; boundary=' + boundary,
            'User-Agent': UA,
        })
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise OnlineError('Upload response exceeds 1 MiB')
            result = json.loads(raw)
        except OnlineError:
            raise
        except urllib.error.HTTPError as exc:
            exc.close()
            hint = 'check S3_API_URL/PPT_API_BASE' if exc.code == 404 else 'check upload credentials and endpoint'
            raise OnlineError(f'Upload request failed (HTTP {exc.code}); {hint}') from None
        except Exception as exc:
            # Server bodies and exception URLs may include tokens/signed URLs.
            raise OnlineError(f'Upload request failed ({type(exc).__name__})') from None
        if not isinstance(result, dict) or result.get('errno', 0) != 0:
            raise OnlineError('Attachment API reported failure')
        payload = result.get('data')
        if not isinstance(payload, dict) or not isinstance(payload.get('url'), str):
            raise OnlineError('Attachment response is missing data.url')
        return web_url(payload['url'])


def download(url, timeout, limit=MAX_IMAGE_BYTES):
    """Fetch source or returned URLs without the upload credential."""
    request = urllib.request.Request(web_url(url), headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(limit + 1)
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()
        raise OnlineError(f'Asset download failed ({type(exc).__name__})') from None
    if len(data) > limit:
        raise OnlineError(f'Asset exceeds {limit // (1024 * 1024)} MiB')
    return data


def upload_verified(client, data, filename, mime, timeout, label):
    url = client.upload(data, filename, mime)
    try:
        if download(url, timeout, max(MAX_IMAGE_BYTES, len(data))) != data:
            raise OnlineError(label + ' verification failed: bytes differ')
    except OnlineError as exc:
        if isinstance(client, OBSClient):
            item = client.objects[-1]
            raise ObsError(str(exc), {**client.report(), 'failed_key': item['key'],
                                     'write_succeeded': item['action'] == 'create'}) from None
        raise
    if isinstance(client, OBSClient):
        client.objects[-1]['public_verified'] = True
    return url


def image_type(data):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise OnlineError('Empty or oversized image')
    # Standalone SVG diagrams are supported; external dependencies are not.
    if data.lstrip().startswith((b'<svg', b'<?xml')):
        try:
            root = ET.fromstring(data)
            if root.tag.split('}')[-1] != 'svg':
                raise ValueError()
            for node in root.iter():
                if node.tag.split('}')[-1] in ('script', 'foreignObject'):
                    raise ValueError()
                for name, value in node.attrib.items():
                    if name.lower().startswith('on') or (name.split('}')[-1] == 'href' and not value.startswith(('#', 'data:'))):
                        raise ValueError()
            if re.search(rb'@import|<\?xml-stylesheet', data, re.I):
                raise ValueError()
            for match in re.finditer(rb'url\s*\((.*?)\)', data, re.I | re.S):
                reference = match.group(1).strip().strip(b'\'"').strip()
                if not reference.startswith((b'#', b'data:')):
                    raise ValueError()
            return 'image/svg+xml', 'svg'
        except (ET.ParseError, ValueError):
            raise OnlineError('Invalid or externally dependent SVG image') from None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            kind = image.format
            image.verify()
        # MPO is JPEG with multiple pictures/MPF metadata; browsers display the
        # primary JPEG. Preserve the verified source bytes, including metadata.
        return {'PNG': ('image/png', 'png'), 'JPEG': ('image/jpeg', 'jpg'),
                'MPO': ('image/jpeg', 'jpg'),
                'GIF': ('image/gif', 'gif'), 'WEBP': ('image/webp', 'webp'),
                'BMP': ('image/bmp', 'bmp')}[kind]
    except ImportError:
        raise OnlineError('Online export needs Pillow; install with python3 -m pip install Pillow') from None
    except Exception:
        raise OnlineError('Invalid or unsupported image bytes') from None


def project_path(root, reference, output=None):
    if not isinstance(reference, str) or not reference:
        raise OnlineError('Empty project reference')
    path = (root / reference).resolve()
    if root not in path.parents or not path.is_file():
        raise OnlineError('Missing file or path outside the project')
    if output and (output == path or output in path.parents):
        raise OnlineError('Output would replace referenced project files; use a dedicated directory')
    return path


def object_nodes(value, seen=None):
    seen = set() if seen is None else seen
    if not isinstance(value, (dict, list)) or id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, dict):
        yield value
        children = value.values()
    else:
        children = value
    for child in children:
        yield from object_nodes(child, seen)


def image_nodes(value):
    for node in object_nodes(value):
        if node.get('elementType') == 'image' or node.get('type') == 'image':
            yield node


def materialize_table_styles(page, manifest):
    """Inline effective cell styles using viewer.cellStyleFor's precedence.

    This makes theme images visible to the existing page-only image loader,
    without fetching unused theme styles or images overridden by a cell.
    """
    theme = manifest.get('theme') or {}
    for table in list(object_nodes(page)):
        if table.get('elementType') != 'table':
            continue
        style = table.get('style')
        if not isinstance(style, dict):
            style = (theme.get('tableStyles') or {}).get((style or '$default')[1:], {})
        rows = table.get('rows') or []
        for row_index, row in enumerate(rows):
            col = 0
            for i, cell in enumerate(row):
                if not isinstance(cell, dict):
                    continue
                categories = []
                if row_index == 0:
                    categories.append(style.get('firstRowStyle'))
                if row_index == len(rows) - 1:
                    categories.append(style.get('lastRowStyle'))
                if col == 0:
                    categories.append(style.get('firstColumnStyle'))
                if col == len(table.get('columnWidths') or []) - 1:
                    categories.append(style.get('lastColumnStyle'))
                if style.get('rowOverColumn') is not False:
                    categories.reverse()
                body = style.get('bodyStyles') or []
                text = cell.get('textStyle')
                text_style = (theme.get('textStyles') or {}).get(text[1:], {}) if isinstance(text, str) and text.startswith('$') else {}
                effective = {}
                for layer in [style.get('cellStyle'), body[row_index % len(body)] if body else None,
                              *categories, text_style, cell]:
                    if isinstance(layer, dict):
                        effective.update(copy.deepcopy(layer))
                row[i] = effective
                col += cell.get('colSpan') or 1
        table['style'] = {}


def prepare_snapshot(deck, target, timeout, output=None):
    try:
        import yaml
    except ImportError:
        raise OnlineError('Online export needs PyYAML; install with python3 -m pip install PyYAML') from None
    root = deck.parent
    manifest = yaml.safe_load(deck.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not isinstance(manifest.get('pages'), list) or not manifest['pages']:
        raise OnlineError('PPTD manifest must contain a non-empty pages list')
    pages, references = [], []
    # Validate the whole referenced input before any uploads. Ignore orphan pages.
    for rel in manifest['pages']:
        page = yaml.safe_load(project_path(root, rel, output).read_text(encoding='utf-8'))
        if not isinstance(page, dict):
            raise OnlineError('Invalid PPTD page')
        materialize_table_styles(page, manifest)
        pages.append(page)
        for node in image_nodes(page):
            src = node.get('src')
            if not isinstance(src, str) or not src:
                raise OnlineError('Image is missing src')
            if src.startswith('search:'):
                raise OnlineError('Unresolved search: image; run image_search/search_images.py first')
            if not src.startswith(('http://', 'https://', 'data:')):
                project_path(root, src, output)
            references.append((node, src))
    by_source, assets = {}, {}
    (target / 'media').mkdir(parents=True)
    (target / 'pages').mkdir()
    for node, src in references:
        if src in by_source:
            node['src'] = by_source[src]
            continue
        if src.startswith(('http://', 'https://')):
            progress(f'Downloading image {len(by_source) + 1}/{len(references)}')
            data = download(src, timeout)
        elif src.startswith('data:'):
            try:
                header, body = src.split(',', 1)
                data = base64.b64decode(body, validate=True) if header.endswith(';base64') else urllib.parse.unquote_to_bytes(body)
            except (ValueError, TypeError):
                raise OnlineError('Invalid image data URI') from None
        else:
            path = project_path(root, src)
            with path.open('rb') as file:
                data = file.read(MAX_IMAGE_BYTES + 1)
        mime, ext = image_type(data)
        digest = hashlib.sha256(data).hexdigest()
        filename = digest + '.' + ext
        local = 'media/' + filename
        if digest not in assets:
            (target / local).write_bytes(data)
            assets[digest] = {'sha256': digest, 'filename': filename, 'mime': mime,
                              'bytes': data, 'local': 'assets/' + filename, 'sources': []}
        assets[digest]['sources'].append(src if not src.startswith('data:') else 'data:' + digest)
        by_source[src] = local
        node['src'] = local
    manifest['pages'] = [f'pages/{i + 1}.page' for i in range(len(pages))]
    for rel, page in zip(manifest['pages'], pages):
        (target / rel).write_text(yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding='utf-8')
    prepared = target / 'deck.pptd'
    prepared.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding='utf-8')
    return prepared, list(assets.values())


def unpack_html(raw, page_count):
    expected = {'index.html', *(f'page_{i:02d}.html' for i in range(1, page_count + 1))}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.testzip() or set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise OnlineError('Unexpected or corrupt HTML export ZIP')
        return {name: archive.read(name).decode('utf-8') for name in sorted(expected)}


def fit_online_html(content):
    """Scale the exported fixed canvas to the page width; preserve author coordinates."""
    if 'class="stage"' not in content or '</body>' not in content:
        return content
    script = '''<script>
(() => {
  const stages = Array.from(document.querySelectorAll('.stage')).map(stage => ({
    stage, canvas: stage.firstElementChild,
    width: parseFloat(stage.style.width), height: parseFloat(stage.style.height)
  })).filter(item => item.canvas && item.width > 0 && item.height > 0);
  const print = matchMedia('print');
  function fit() {
    for (const {stage, canvas, width, height} of stages) {
      const parent = stage.parentElement;
      const style = getComputedStyle(parent);
      const available = parent.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const scale = print.matches ? 1 : Math.min(1, Math.max(1, available) / width);
      stage.style.width = `${width * scale}px`;
      stage.style.height = `${height * scale}px`;
      stage.style.overflow = 'hidden';
      canvas.style.transformOrigin = 'top left';
      canvas.style.transform = `scale(${scale})`;
    }
  }
  fit();
  addEventListener('resize', fit);
  print.addEventListener('change', fit);
})();
</script>'''
    content = content.replace('</head>', '<link rel="icon" href="data:,">\n</head>')
    return content.replace('</body>', script + '\n</body>')


def replace_output(staged, output):
    """Publish a complete directory; roll back if its final rename fails."""
    backup = output.with_name(output.name + '.previous-' + uuid.uuid4().hex)
    if output.exists():
        output.rename(backup)
    try:
        staged.rename(output)
    except OSError:
        if backup.exists():
            backup.rename(output)
        raise
    if backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError:
            progress(f'Export succeeded; previous output backup retained: {backup}')


def run(deck_arg, *, output_dir=None, images='remote', publish=False, timeout=180, request_timeout=30, chrome=None,
        upload_backend=None, obs_config=None, obs_profile=None, obs_prefix=None):
    if images not in ('remote', 'embed'):
        raise OnlineError('images must be remote or embed')
    if not all(math.isfinite(x) and x > 0 for x in (timeout, request_timeout)):
        raise OnlineError('Timeouts must be finite positive numbers')
    deck = find_deck(deck_arg)
    output = Path(output_dir).absolute() if output_dir else deck.parent / 'html-online'
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise OnlineError('Output must be a dedicated directory, not a file or symlink')
    output = output.resolve()
    if output == deck.parent or output in deck.parent.parents:
        raise OnlineError('Output cannot replace the project or its parent')
    if output.exists() and any(output.iterdir()):
        try:
            previous = json.loads((output / 'online-report.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = None
        if not isinstance(previous, dict) or previous.get('exporter') != 'open-pptd-online':
            raise OnlineError('Output is not a previous online export; choose an empty dedicated directory')
    obs_config = obs_config or os.environ.get('OBS_CONFIG')
    backend = upload_backend or os.environ.get('PPT_UPLOAD_BACKEND') or ('obs' if obs_config else 'attachment')
    if backend == 'obs':
        client = OBSClient(obs_config, profile=obs_profile or os.environ.get('OBS_PROFILE'),
                           prefix=obs_prefix or os.environ.get('OBS_PREFIX'), timeout=request_timeout)
    elif backend == 'attachment':
        if obs_config or obs_profile or obs_prefix:
            raise OnlineError('OBS options conflict with attachment backend; use --upload-backend obs')
        client = AttachmentClient(timeout=request_timeout)
    else:
        raise OnlineError('upload backend must be attachment or obs')
    chrome = find_chrome(chrome)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pptd-online-') as temporary:
        prepared, assets = prepare_snapshot(deck, Path(temporary), request_timeout, output)
        progress('Rendering and checking local HTML snapshot')
        try:
            raw = run_viewer_export(VIEWER_DEFAULT, prepared, chrome, timeout)
        except RuntimeError as exc:
            # The viewer only sees a local snapshot, never upload credentials.
            raise OnlineError('Local HTML rendering failed: ' + str(exc)[:1500]) from None
        # The prepared manifest has exactly the referenced pages, in original order.
        count = len(list((Path(temporary) / 'pages').glob('*.page')))
        files = {name: fit_online_html(content) for name, content in unpack_html(raw, count).items()}
        for index, asset in enumerate(assets, 1):
            progress(f'Uploading image {index}/{len(assets)}')
            asset['url'] = upload_verified(client, asset['bytes'], asset['filename'], asset['mime'],
                                            request_timeout, 'Uploaded image')
            data_url = 'data:' + asset['mime'] + ';base64,' + base64.b64encode(asset['bytes']).decode('ascii')
            if not any(data_url in content for content in files.values()):
                raise OnlineError('Rendered image missing from HTML; refusing incomplete export')
            if images == 'remote':
                files = {name: content.replace(data_url, html.escape(asset['url'], quote=True))
                         for name, content in files.items()}
        published = {}
        if publish:
            # Publish the combined entry after every page and image has succeeded.
            for name in sorted(files, key=lambda name: (name == 'index.html', name)):
                content = files[name]
                progress(f'Publishing {name}')
                payload = content.encode('utf-8')
                url = upload_verified(client, payload, name, 'text/html; charset=utf-8',
                                      request_timeout, 'Published HTML')
                published[name] = url
        report = {'ok': True, 'exporter': 'open-pptd-online', 'upload_backend': backend,
                  'deck': str(deck), 'output_dir': str(output), 'images': images,
                  'page_count': count, 'files': sorted(files), 'published': published,
                  'assets': [{k: v for k, v in a.items() if k != 'bytes'} for a in assets]}
        if backend == 'obs':
            report['storage'] = client.report()
        # Everything has succeeded before the previous delivery is touched.
        with tempfile.TemporaryDirectory(prefix='.pptd-delivery-', dir=output.parent) as delivery:
            staged = Path(delivery) / 'html'
            (staged / 'assets').mkdir(parents=True)
            for name, content in files.items():
                (staged / name).write_text(content, encoding='utf-8')
            for asset in assets:
                (staged / asset['local']).write_bytes(asset['bytes'])
            (staged / 'online-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            replace_output(staged, output)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('deck', help='PPTD project directory or manifest')
    parser.add_argument('--images', choices=['remote', 'embed'], default='remote', help='HTML images: uploaded URLs (default) or embedded bytes')
    parser.add_argument('--publish', action='store_true', help='Also upload and verify index.html and every page HTML')
    parser.add_argument('--upload-backend', choices=['attachment', 'obs'], help='Default: obs when OBS_CONFIG is set, otherwise attachment; or PPT_UPLOAD_BACKEND')
    parser.add_argument('--obs-config', help='Existing protected OBS YAML config (or OBS_CONFIG); never copied into output')
    parser.add_argument('--obs-profile', help='Profile in profiles/targets config (or OBS_PROFILE)')
    parser.add_argument('--obs-prefix', help='Unique object prefix (or OBS_PREFIX; default open-pptd/<random UUID>); conflicts are never overwritten')
    parser.add_argument('--output-dir', help='Dedicated output directory, replaced on success (default: <deck>/html-online)')
    parser.add_argument('--timeout', type=float, default=180, help='Viewer export timeout in seconds')
    parser.add_argument('--request-timeout', type=float, default=30, help='Per HTTP socket timeout in seconds')
    parser.add_argument('--chrome', help='Chrome executable (or CHROME_BIN)')
    parser.add_argument('--json', action='store_true', help='One JSON result on stdout, progress on stderr')
    args = parser.parse_args(argv)
    try:
        report = run(args.deck, output_dir=args.output_dir, images=args.images, publish=args.publish,
                     timeout=args.timeout, request_timeout=args.request_timeout, chrome=args.chrome,
                     upload_backend=args.upload_backend, obs_config=args.obs_config,
                     obs_profile=args.obs_profile, obs_prefix=args.obs_prefix)
    except (Exception, SystemExit) as exc:
        # Only our own deliberate error messages are safe for machine/user output.
        message = str(exc) if isinstance(exc, (OnlineError, ObsError)) else f'Online export failed ({type(exc).__name__})'
        report = {'ok': False, 'error': message}
        if isinstance(exc, ObsError) and exc.details:
            report['details'] = exc.details
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    elif report['ok']:
        print('HTML exported: ' + report['output_dir'])
        for name, url in report['published'].items():
            print(f'{name}: {url}')
    else:
        progress(report['error'])
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
