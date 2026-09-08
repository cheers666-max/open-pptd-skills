#!/usr/bin/env python3
"""Check a PPTD draft, render changed pages, and optionally export final formats.

No model calls or independent scores. Read the overview, repair confirmed issues,
then run again. --force refreshes screenshots after system font/browser changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from audit_rendered import audit_page
from export_images import export_images, find_deck, stitch_overview, ensure_pillow
from validate_deck import audit_project, load_structured, safe_project_path, write_json, yaml

SCRIPTS = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_dependencies(value, project, *, strict=True):
    """Hash declared local resources, including src and theme font paths.

The document bytes already cover embedded/data sources. Unresolved remote images
are rejected by the existing validator before they can be cached.
"""
    found = {}
    def visit(item, field=None):
        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, key)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str) and field == 'src' and not item.startswith('data:'):
            path = safe_project_path(project, item)
            if item.startswith(('http:', 'https:', 'search:')) or path is None:
                if not strict:
                    return
                raise ValueError(f'Resource must resolve to a local file before checking: {item[:160]}')
            if strict and not path.is_file():
                raise ValueError(f'Resource must resolve to a local file before checking: {item[:160]}')
            found[item] = digest(path) if strict else None
        elif isinstance(item, str) and len(item) < 4096 and not item.startswith(('data:', 'http:', 'https:', '$')):
            try:
                path = safe_project_path(project, item)
                if path is not None and path.is_file():
                    found[item] = digest(path) if strict else None
            except (OSError, ValueError):
                pass
    visit(value)
    return found


def protect_sources(deck, manifest, output):
    """Check all write destinations before even a failed validation can report."""
    root = deck.parent
    protected = {deck.resolve()}
    documents = [manifest]
    for ref in manifest['pages']:
        path = safe_project_path(root, ref)
        if path is None:
            continue
        protected.add(path)
        try:
            documents.append(load_structured(path))
        except (OSError, ValueError, RuntimeError, yaml.YAMLError):
            # The audit already diagnoses missing/malformed pages; protect their paths too.
            pass
    for document in documents:
        protected.update((root / ref).resolve() for ref in local_dependencies(document, root, strict=False))
    names = ('prepare-report.json', 'prepare-report.json.tmp', 'pptx-report.json', 'render-state.json',
             'render-state.json.tmp', 'overview.jpg')
    targets = [output / name for name in names]
    targets += [output / f'pages/page_{i:02d}.png' for i in range(1, len(manifest['pages']) + 1)]
    if any(path.resolve() in protected for path in targets):
        raise ValueError('QA output would overwrite a project source/resource; choose a separate directory')


def fingerprints(deck, manifest, scale):
    shared = {k: v for k, v in manifest.items() if k != 'pages'}
    engine = {name: digest(SCRIPTS / name) for name in
              ('prepare_deck.py', 'export_images.py', 'viewer.html', 'deck_server.py', 'fa-icons.mjs')}
    common = dict(manifest=shared, dependencies=local_dependencies(shared, deck.parent),
                  engine=engine, scale=scale)
    result = {}
    for index, ref in enumerate(manifest['pages'], 1):
        path = safe_project_path(deck.parent, ref)
        page = load_structured(path)
        value = dict(common=common, index=index, ref=ref, pageSha256=digest(path),
                     dependencies=local_dependencies(page, deck.parent))
        result[index] = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def read_state(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def run(project, *, output=None, workers=4, scale=2.0, timeout=90, force=False, export_formats=()):
    if not math.isfinite(scale) or scale <= 0 or workers < 1 or timeout <= 0:
        raise ValueError('scale, workers and timeout must be positive')
    if any(fmt not in ('html', 'pptx') for fmt in export_formats):
        raise ValueError('export formats must be html and/or pptx')
    deck = find_deck(project)
    root = deck.parent
    output = Path(output).expanduser().resolve() if output else root / '.qa-images'
    if output in (root, root / 'pages', root / 'media'):
        raise ValueError('The QA output must be separate from project source files')
    validation = audit_project(root, deck)
    manifest = load_structured(deck)
    protect_sources(deck, manifest, output)
    result = dict(ok=False, deck=str(deck), validation=validation, visualReview='required',
                  renderedPages=[], reusedPages=[], images=[], exports={})
    blocking = [i for i in validation['issues'] if i.get('repairability') == 'format' or
                i['code'] in ('pptd-page-missing', 'unresolved-search-placeholder', 'unresolved-remote-url')]
    if blocking:
        write_json(output / 'prepare-report.json', result)
        return result
    wanted = fingerprints(deck, manifest, scale)
    state = read_state(output / 'render-state.json')
    changed, reused = [], []
    for index, fingerprint in wanted.items():
        previous = state.get(str(index), {})
        image = output / f'pages/page_{index:02d}.png'
        valid = isinstance(previous, dict) and previous.get('fingerprint') == fingerprint
        if not force and valid and image.is_file() and previous.get('imageSha256') == digest(image):
            reused.append(index)
        else:
            changed.append(index)
    output.parent.mkdir(parents=True, exist_ok=True)
    image_cls, draw_cls, image_font = ensure_pillow()
    with tempfile.TemporaryDirectory(prefix='.pptd-check-', dir=output.parent) as folder:
        staged = Path(folder)
        (staged / 'pages').mkdir()
        if changed:
            export_images(deck, staged, scale, 30000, timeout, True, workers,
                          page_spec=','.join(map(str, changed)))
        for index in reused:
            shutil.copyfile(output / f'pages/page_{index:02d}.png', staged / f'pages/page_{index:02d}.png')
        images = [staged / f'pages/page_{i:02d}.png' for i in wanted]
        stitch_overview(images, staged / 'overview.jpg', image_cls, draw_cls, image_font)
        issues = []
        for index, ref in enumerate(manifest['pages'], 1):
            issues.extend(audit_page(staged / f'pages/page_{index:02d}.png', root / ref,
                                     scale, index, theme=manifest.get('theme', {})))
        new_state = {str(i): dict(fingerprint=wanted[i], imageSha256=digest(images[i - 1])) for i in wanted}
        if wanted != fingerprints(deck, load_structured(deck), scale):
            raise RuntimeError('Project changed during checking; rerun after the source edits finish.')
        # Commit only after every changed page and the full auxiliary audit succeeded.
        (output / 'pages').mkdir(parents=True, exist_ok=True)
        for index in changed:
            os.replace(staged / f'pages/page_{index:02d}.png', output / f'pages/page_{index:02d}.png')
        os.replace(staged / 'overview.jpg', output / 'overview.jpg')
        write_json(output / 'render-state.json', new_state)
    result.update(ok=validation['valid'] and not any(i.get('severity') == 'error' for i in issues),
                  renderedPages=changed, reusedPages=reused, overview=str(output / 'overview.jpg'),
                  images=[dict(index=i, page=ref, image=str(output / f'pages/page_{i:02d}.png'))
                          for i, ref in enumerate(manifest['pages'], 1)],
                  audit=dict(issues=issues, errors=sum(i.get('severity') == 'error' for i in issues),
                             scope='Auxiliary contrast/overlap only; does not certify visual quality.'))
    write_json(output / 'prepare-report.json', result)
    # Explicit final export only; generation-time review/repair remains the author's job.
    if result['ok']:
        for fmt in dict.fromkeys(export_formats):
            command = ([sys.executable, str(SCRIPTS / 'export_html.py'), str(deck), '--json'] if fmt == 'html' else
                       ['node', str(SCRIPTS / 'export_pptx.mjs'), str(deck), '--force', '--json',
                        '--report', str(output / 'pptx-report.json')])
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout * 3)
                if completed.stderr:
                    print(completed.stderr, file=sys.stderr, end='')
                exported = json.loads(completed.stdout)
                if not isinstance(exported, dict):
                    raise ValueError('Exporter JSON must be an object')
                if completed.returncode:
                    exported['ok'] = False
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                exported = dict(ok=False, error=f'Export failed: {exc}')
            result['exports'][fmt] = exported
            if exported.get('ok') is False:
                result['ok'] = False
                break
        write_json(output / 'prepare-report.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', help='PPTD project directory or manifest')
    parser.add_argument('--output', type=Path, help='QA directory (default: project/.qa-images)')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--scale', type=float, default=2.0)
    parser.add_argument('--timeout', type=int, default=90, help='Per-page render timeout in seconds')
    parser.add_argument('--force', action='store_true', help='Refresh all screenshots, including after system font/browser changes')
    parser.add_argument('--export', default='', help='Explicit final export: html,pptx; run after reviewing the current overview')
    parser.add_argument('--json', action='store_true', help='Print full machine report instead of a concise summary')
    args = parser.parse_args(argv)
    try:
        result = run(args.project, output=args.output, workers=args.workers, scale=args.scale,
                     timeout=args.timeout, force=args.force,
                     export_formats=[v.strip() for v in getattr(args, 'export').split(',') if v.strip()])
    except Exception as exc:
        result = dict(ok=False, error=str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({k: v for k, v in result.items() if k not in ('validation', 'audit', 'images')}, ensure_ascii=False))
        if 'validation' in result:
            print(f"issues={result['validation']['issueCount']}; details: {args.output or Path(result['deck']).parent / '.qa-images'}/prepare-report.json",
                  file=sys.stderr)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
