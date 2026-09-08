import base64
from email.parser import BytesParser
from email.policy import default
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import export_online as online
from export_html import ensure_websocket


def inspect_narrow_html(path, profile):
    """Inspect the actual exported DOM at a narrow viewport via a bounded CDP session."""
    proc = subprocess.Popen([online.find_chrome(None), '--headless=new', '--no-first-run',
        '--no-default-browser-check', '--disable-gpu', '--remote-debugging-port=0',
        '--user-data-dir=' + str(profile), 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        deadline = time.monotonic() + 15
        port_file = profile / 'DevToolsActivePort'
        while not port_file.exists():
            if time.monotonic() > deadline or proc.poll() is not None:
                raise RuntimeError('Test browser failed to start')
            time.sleep(.05)
        port, suffix = port_file.read_text().splitlines()[:2]
        ws = ensure_websocket().create_connection(f'ws://127.0.0.1:{port}{suffix}', timeout=10,
            suppress_origin=True, http_no_proxy=['127.0.0.1'])
        message_id = 0
        def cdp(method, params=None, session=None):
            nonlocal message_id
            message_id += 1
            request = {'id': message_id, 'method': method, 'params': params or {}}
            if session:
                request['sessionId'] = session
            ws.send(json.dumps(request))
            while True:
                result = json.loads(ws.recv())
                if result.get('id') == message_id:
                    if 'error' in result:
                        raise RuntimeError(str(result['error']))
                    return result.get('result', {})
        target = cdp('Target.createTarget', {'url': 'about:blank'})['targetId']
        sid = cdp('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
        cdp('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': False}, sid)
        cdp('Page.navigate', {'url': path.as_uri()}, sid)
        while time.monotonic() < deadline:
            result = cdp('Runtime.evaluate', {'expression': 'document.body && document.body.dataset.fit', 'returnByValue': True}, sid)
            value = result['result'].get('value')
            if value is not None:
                return value
            time.sleep(.05)
        raise RuntimeError('Test browser did not finish loading HTML')
    finally:
        if ws:
            ws.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def png(color):
    stream = BytesIO()
    Image.new('RGB', (480, 270), color).save(stream, 'PNG')
    return stream.getvalue()


class ImageFormatTests(unittest.TestCase):
    def test_mpo_photo_is_accepted_as_jpeg_without_reencoding(self):
        stream = BytesIO()
        Image.new('RGB', (48, 27), '#008866').save(stream, 'MPO', save_all=True,
            append_images=[Image.new('RGB', (48, 27), '#4488cc')])
        raw = stream.getvalue()
        with Image.open(BytesIO(raw)) as photo:
            self.assertEqual(photo.format, 'MPO')
            self.assertEqual(photo.n_frames, 2)
        self.assertEqual(online.image_type(raw), ('image/jpeg', 'jpg'))


class OnlineExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.gets, self.posts, self.uploads = [], [], {}
        self.response_mode = 'ok'
        self.photo = png('#008866')
        self.other = png('#4488cc')
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.gets.append((self.path, self.headers.get('Authorization')))
                raw = owner.photo if self.path.startswith('/photo') else owner.uploads.get(self.path)
                if raw is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                message = BytesParser(policy=default).parsebytes(
                    ('Content-Type: ' + self.headers['Content-Type'] + '\r\n\r\n').encode() + body)
                parts = list(message.iter_parts())
                part = parts[0]
                raw = part.get_payload(decode=True)
                owner.posts.append({'path': self.path, 'auth': self.headers.get('Authorization'),
                                    'field': part.get_param('name', header='content-disposition'),
                                    'filename': part.get_filename(), 'type': part.get_content_type(), 'bytes': raw})
                key = '/stored/' + hashlib.sha256(raw).hexdigest() + '/' + part.get_filename()
                owner.uploads[key] = raw
                response = {'errno': 0, 'data': {'url': owner.base + key}}
                if owner.response_mode == 'error':
                    response = {'errno': 9, 'message': 'SECRET must never appear in CLI errors'}
                elif owner.response_mode == 'array':
                    response = []
                elif owner.response_mode == 'missing':
                    response = {'errno': 0, 'data': {}}
                elif owner.response_mode == 'unsafe':
                    response = {'errno': 0, 'data': {'url': 'javascript:alert(1)'}}
                elif owner.response_mode == 'dead_url':
                    response = {'errno': 0, 'data': {'url': owner.base + '/not-found'}}
                elif owner.response_mode == 'redirect':
                    self.send_response(307)
                    self.send_header('Location', owner.base + '/unexpected')
                    self.end_headers()
                    return
                elif owner.response_mode in ('401', '404'):
                    self.send_response(int(owner.response_mode))
                    self.end_headers()
                    self.wfile.write(b'SECRET diagnostic body')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        inherited = {k: v for k, v in os.environ.items() if k not in ('PPT_UPLOAD_BACKEND', 'OBS_CONFIG', 'OBS_PROFILE', 'OBS_PREFIX')}
        self.env = {**inherited, 'PPT_API_KEY': 'test-only-token', 'S3_API_URL': self.base + '/upload'}
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'pages').mkdir()
        (self.project / 'media').mkdir()
        (self.project / 'media/photo%23.png').write_bytes(self.photo)
        (self.project / 'media/other.png').write_bytes(self.other)
        self.deck = self.project / 'deck.pptd'
        self.deck.write_text('version: v2\ntitle: Online fixture\nsize: [960, 540]\npages: [pages/1.page]\n')
        self.page = self.project / 'pages/1.page'
        self.page.write_text(yaml.safe_dump({
            'pageType': 'content',
            'background': {'type': 'image', 'src': self.base + '/photo?from=background', 'fit': {'mode': 'cover'}},
            'elements': [
                {'elementId': 'title', 'elementType': 'text', 'bounds': [40, 30, 800, 60],
                 'content': {'text': 'Online fixture', 'fontSize': 36}},
                {'elementId': 'remote', 'elementType': 'image', 'bounds': [40, 140, 300, 170],
                 'src': self.base + '/photo?from=background', 'fit': {'mode': 'contain'}},
                {'elementId': 'local', 'elementType': 'image', 'bounds': [370, 140, 300, 170],
                 'src': 'media/photo%23.png'},
                {'elementId': 'fill', 'elementType': 'shape', 'bounds': [700, 140, 200, 170],
                 'shapeName': 'rect', 'fill': {'type': 'image', 'src': 'media/other.png'}},
            ]}, sort_keys=False))
        (self.project / 'pages/orphan.page').write_text('src: https://must-not-fetch.invalid/orphan.png')

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPTS / 'export_online.py'), str(self.deck),
                               '--json', '--timeout', '25', '--request-timeout', '3', *args],
                              env=env or self.env, capture_output=True, text=True, timeout=60)

    def test_full_export_downloads_deduplicates_rehosts_and_publishes(self):
        originals = (self.deck.read_bytes(), self.page.read_bytes())
        result = self.cli('--publish')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['ok'])
        self.assertEqual(report['page_count'], 1)
        self.assertEqual(len(report['assets']), 2)
        html = (Path(report['output_dir']) / 'page_01.html').read_text()
        self.assertNotIn(self.base + '/photo', html)
        self.assertNotIn('data:image/png', html)
        for asset in report['assets']:
            self.assertIn(asset['url'], html)
        self.assertIn('index.html', report['published'])
        self.assertEqual(len(self.posts), 4)  # two unique images + two HTML files
        self.assertTrue(all(p['auth'] == 'Bearer test-only-token' and p['field'] == 'file' for p in self.posts))
        self.assertTrue(all(auth is None for _, auth in self.gets))
        self.assertEqual(sum(path.startswith('/photo') for path, _ in self.gets), 1)
        self.assertEqual(originals, (self.deck.read_bytes(), self.page.read_bytes()))
        self.assertNotIn('test-only-token', result.stdout + result.stderr + html)

    def test_embed_mode_uploads_images_but_html_stays_self_contained(self):
        result = self.cli('--images', 'embed')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        html = (Path(report['output_dir']) / 'page_01.html').read_text()
        self.assertIn(base64.b64encode(self.photo).decode(), html)
        self.assertNotIn(self.base, html)
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(report['published'], {})

    def test_published_html_fits_narrow_browser_without_cropping_slide(self):
        result = self.cli('--images', 'embed')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = Path(json.loads(result.stdout)['output_dir'])
        for name in ['index.html', 'page_01.html']:
            content = (output / name).read_text()
            probe = '''<script>
              const stage = document.querySelector('.stage').getBoundingClientRect();
              const slide = document.querySelector('.slide').getBoundingClientRect();
              document.body.dataset.fit = String(document.documentElement.scrollWidth <= innerWidth &&
                stage.left >= 0 && stage.right <= innerWidth &&
                Math.abs(stage.width - slide.width) < 1 && Math.abs(stage.height - slide.height) < 1);
            </script>'''
            inspected = self.root / name
            inspected.write_text(content.replace('</body>', probe + '</body>'))
            self.assertEqual(inspect_narrow_html(inspected, self.root / ('chrome-' + name)), 'true')
            self.assertIn('rel="icon" href="data:,"', content)

    def test_upload_failures_preserve_previous_delivery_and_hide_server_message(self):
        output = self.project / 'html-online'
        output.mkdir()
        previous = output / 'index.html'
        previous.write_text('previous successful export')
        (output / 'online-report.json').write_text(json.dumps({'exporter': 'open-pptd-online', 'ok': True}))
        self.response_mode = 'error'
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)['ok'])
        self.assertIn('Attachment API reported failure', result.stdout)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(previous.read_text(), 'previous successful export')
        self.assertNotIn('SECRET', result.stdout + result.stderr)

    def test_missing_key_fails_before_network(self):
        env = {k: v for k, v in self.env.items() if k not in ('PPT_API_KEY', 'QIHOO_API_KEY', 'QIHOO_360_API_KEY')}
        result = self.cli(env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PPT_API_KEY', json.loads(result.stdout)['error'])
        self.assertEqual(self.gets + self.posts, [])

    def test_unsafe_paths_and_unresolved_search_fail_before_upload(self):
        for value in ['../private.png', 'search:unresolved subject']:
            with self.subTest(value=value):
                self.page.write_text(yaml.safe_dump({'elements': [{'elementType': 'image', 'src': value}]}))
                result = self.cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.posts, [])

    def test_upload_contract_rejects_bad_responses_and_redirects(self):
        with patch.dict(os.environ, self.env, clear=True):
            client = online.AttachmentClient(timeout=2)
        for mode in ['array', 'missing', 'unsafe', 'redirect']:
            with self.subTest(mode=mode):
                self.response_mode = mode
                with self.assertRaises(online.OnlineError):
                    client.upload(self.photo, 'photo.png', 'image/png')
        self.assertNotIn('/unexpected', [p['path'] for p in self.posts])

    def test_returned_image_must_be_readable(self):
        self.response_mode = 'dead_url'
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)['ok'])
        self.assertIn('Asset download failed', result.stdout)
        self.assertEqual(len(self.posts), 1)

    def test_output_must_not_replace_referenced_source_directories(self):
        before = self.page.read_bytes()
        result = self.cli('--output-dir', str(self.project / 'pages'))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.page.read_bytes(), before)
        self.assertEqual(self.posts, [])

    def test_symlink_image_outside_project_is_rejected(self):
        outside = self.root / 'outside.png'
        outside.write_bytes(self.photo)
        (self.project / 'media/link.png').symlink_to(outside)
        self.page.write_text(yaml.safe_dump({'elements': [{'elementType': 'image', 'src': 'media/link.png'}]}))
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.posts, [])

    def test_endpoint_handles_base_with_or_without_v1(self):
        for base in ['https://api.360.cn', 'https://api.360.cn/v1/']:
            with patch.dict(os.environ, {'PPT_API_KEY': 'test-only-token', 'PPT_API_BASE': base}, clear=True):
                self.assertEqual(online.AttachmentClient().endpoint, 'https://api.360.cn/v1/upload/attachment')

    def test_http_failures_explain_status_without_leaking_body(self):
        with patch.dict(os.environ, self.env, clear=True):
            client = online.AttachmentClient(timeout=2)
        for status in ('401', '404'):
            self.response_mode = status
            with self.assertRaises(online.OnlineError) as caught:
                client.upload(self.photo, 'photo.png', 'image/png')
            self.assertIn('HTTP ' + status, str(caught.exception))
            self.assertNotIn('SECRET', str(caught.exception))

    def test_svg_internal_paint_references_are_valid_external_ones_are_rejected(self):
        for reference in ['url(#paint)', 'url( "#paint" )']:
            data = f'<svg xmlns="http://www.w3.org/2000/svg"><rect fill=\'{reference}\'/></svg>'.encode()
            self.assertEqual(online.image_type(data), ('image/svg+xml', 'svg'))
        with self.assertRaises(online.OnlineError):
            online.image_type(b'<svg xmlns="http://www.w3.org/2000/svg"><style>rect{fill:url(https://outside.invalid/image)}</style></svg>')

    def test_data_image_snapshot_is_local_and_keeps_numeric_string_labels(self):
        self.page.write_text(yaml.safe_dump({'elements': [
            {'elementType': 'image', 'src': 'data:image/png;base64,' + base64.b64encode(self.photo).decode()},
            {'elementType': 'text', 'content': {'text': '08'}}]}))
        with tempfile.TemporaryDirectory() as destination:
            _, assets = online.prepare_snapshot(self.deck, Path(destination), 2)
            page = yaml.safe_load((Path(destination) / 'pages/1.page').read_text())
            self.assertTrue(page['elements'][0]['src'].startswith('media/'))
            self.assertEqual(page['elements'][1]['content']['text'], '08')
            self.assertEqual(assets[0]['bytes'], self.photo)
        self.assertEqual(self.gets + self.posts, [])

    def test_theme_table_fill_is_materialized_and_only_effective_images_are_downloaded(self):
        manifest = yaml.safe_load(self.deck.read_text())
        manifest['theme'] = {'tableStyles': {'photo': {
            'cellStyle': {'fill': {'type': 'image', 'src': 'https://unused.invalid/base.png'}},
            'firstRowStyle': {'fill': {'type': 'image', 'src': self.base + '/photo'}},
        }, 'unused': {'cellStyle': {'fill': {'type': 'image', 'src': 'https://unused.invalid/style.png'}}}}}
        self.deck.write_text(yaml.safe_dump(manifest))
        self.page.write_text(yaml.safe_dump({'elements': [{'elementType': 'table', 'style': '$photo',
            'elementId': 'table', 'bounds': [50, 50, 800, 400], 'columnWidths': [1], 'rows': [[{'text': 'Photo'}]]}]}))
        with tempfile.TemporaryDirectory() as destination:
            _, assets = online.prepare_snapshot(self.deck, Path(destination), 2)
            self.assertEqual(len(assets), 1)
            page = yaml.safe_load((Path(destination) / 'pages/1.page').read_text())
            self.assertTrue(page['elements'][0]['rows'][0][0]['fill']['src'].startswith('media/'))
        result = self.cli('--images', 'embed')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        html = (Path(report['output_dir']) / 'page_01.html').read_text()
        self.assertIn(base64.b64encode(self.photo).decode(), html)
        self.assertNotIn(self.base, html)

    def test_backup_cleanup_failure_does_not_turn_success_into_failed_export(self):
        output = self.root / 'old-output'
        staged = self.root / 'new-output'
        output.mkdir(); staged.mkdir()
        (output / 'index.html').write_text('old')
        (staged / 'index.html').write_text('new')
        with patch.object(online.shutil, 'rmtree', side_effect=PermissionError('fixture')):
            online.replace_output(staged, output)
        self.assertEqual((output / 'index.html').read_text(), 'new')
        backup = next(self.root.glob('old-output.previous-*'))
        self.assertEqual((backup / 'index.html').read_text(), 'old')

    def test_existing_unrelated_output_directory_is_not_replaced(self):
        output = self.root / 'documents'
        output.mkdir()
        note = output / 'important.txt'
        note.write_text('keep this unrelated file')
        result = self.cli('--output-dir', str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(note.read_text(), 'keep this unrelated file')
        self.assertEqual(self.posts, [])


if __name__ == '__main__':
    unittest.main()
