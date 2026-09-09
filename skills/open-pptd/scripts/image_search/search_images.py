#!/usr/bin/env python3
"""Resolve search: images locally, with bounded attempts and explicit offline fallback.

Exit 0: all slots resolved (including disclosed decorative fallback).
Exit 2: unresolved slots remain. Exit 1: invocation/IO error.
Only stdlib; the parent owns project writes, disposable workers own network attempts.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time
import zlib

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import pool
import slots as slots_mod

WORKER = _HERE / 'backend_worker.py'
_EXT = {'jpeg': '.jpg', 'png': '.png', 'webp': '.webp', 'bmp': '.bmp'}


def progress(message):
    print(message, file=sys.stderr, flush=True)


def _find_project(target):
    path = Path(target).expanduser().resolve()
    if path.is_dir():
        decks = sorted(path.glob('*.pptd'))
        if len(decks) > 1:
            raise ValueError('Multiple manifests; pass the intended .pptd file')
        return path, decks[0] if decks else None
    if path.is_file() and path.suffix == '.pptd':
        return path.parent, path
    raise ValueError(f'Not a project directory or .pptd file: {target}')


def _slugify(text):
    return re.sub(r'[^0-9A-Za-z一-鿿]+', '-', text).strip('-').lower()[:40] or 'img'


def _stop(processes):
    """Stop all attempts together; cleanup does not multiply by worker count."""
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + .25
    for proc in processes:
        try:
            proc.wait(timeout=max(.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
    for proc in processes:
        proc.wait(timeout=1)


def _attempts(slots, texts, brief, backend, workers, timeout, deadline, use_vlm, min_dim):
    pending = deque((s, deque(['remote'] if s.is_remote else
                     [backend] if backend != 'auto' else pool.AUTO_ORDER)) for s in slots)
    active = []
    seen_hashes, seen_urls = set(), set()
    heartbeat = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='pptd-images-') as temp:
        attempt_id = 0
        try:
            while (pending or active) and time.monotonic() < deadline:
                while pending and len(active) < workers and time.monotonic() < deadline:
                    slot, names = pending.popleft()
                    if not names:
                        slot.status = 'failed'
                        continue
                    name = names.popleft()
                    attempt_id += 1
                    request_path = Path(temp) / f'{attempt_id}.request.json'
                    result_path = Path(temp) / f'{attempt_id}.result.json'
                    request = dict(backend=name, query=slot.query, url=slot.raw_src, want=slot.want,
                                   ratio=slot.ratio, min_dim=min_dim, use_vlm=use_vlm, brief=brief,
                                   allow_product=getattr(slot, 'allow_product', False),
                                   page_text=re.sub(r'\s+', ' ', texts[slot.page])[:400],
                                   seen_hashes=list(seen_hashes), seen_urls=list(seen_urls))
                    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
                    progress(f'[try] {slot.page}:{slot.line_no + 1} {slot.element_id or slot.kind} backend={name}')
                    proc = subprocess.Popen([sys.executable, str(WORKER), str(request_path), str(result_path)],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL)
                    active.append((proc, slot, names, name, result_path, min(deadline, time.monotonic() + timeout)))
                for item in list(active):
                    proc, slot, names, name, output, end = item
                    if proc.poll() is None and time.monotonic() < end:
                        continue
                    active.remove(item)
                    winner = None
                    if proc.poll() is None:
                        _stop([proc])
                        slot.tried.append({'backend': name, 'fate': 'timeout'})
                    else:
                        try:
                            if proc.returncode != 0:
                                raise ValueError('worker exit')
                            result = json.loads(output.read_text(encoding='utf-8'))
                            slot.tried.extend(result['tried'])
                            winner = result['winner']
                            if winner:
                                data = output.with_suffix('.bin').read_bytes()
                                digest = hashlib.sha256(data).hexdigest()
                                canonical = pool.canonical_url(winner['url'])
                                if digest in seen_hashes or canonical in seen_urls:
                                    slot.tried.append({'backend': name, 'fate': 'duplicate'})
                                    winner = None
                                else:
                                    winner.update(bytes=data, sha256=digest, canonical=canonical)
                                    seen_hashes.add(digest)
                                    seen_urls.add(canonical)
                        except (OSError, ValueError, KeyError, TypeError):
                            slot.tried.append({'backend': name, 'fate': 'worker_error'})
                            winner = None
                    if winner:
                        slot.winner, slot.status = winner, 'resolved'
                        progress(f'[resolved] {slot.page} {slot.element_id or slot.kind} via {name}')
                    elif names:
                        pending.append((slot, names))
                    else:
                        slot.status = 'failed'
                if time.monotonic() - heartbeat >= 4:
                    progress(f'[wait] {len(active)} active, {len(pending)} queued; remaining={max(0, deadline-time.monotonic()):.1f}s')
                    heartbeat = time.monotonic()
                if active:
                    time.sleep(min(.05, max(0, deadline - time.monotonic())))
        finally:
            _stop([item[0] for item in active])
    for slot in slots:
        if slot.status == 'pending':
            slot.status = 'failed'
            slot.tried.append({'fate': 'budget_exhausted'})


def _gradient(slot):
    """A deterministic local decorative PNG, never a substitute for a real subject."""
    ratio = slot.ratio or 16 / 9
    width, height = (960, max(64, min(1920, round(960 / ratio))))
    seed = hashlib.sha256(slot.query.encode()).digest()
    rows = []
    for y in range(height):
        rgb = bytes(25 + int((seed[c] % 75) * y / max(1, height - 1)) for c in range(3))
        rows.append(b'\0' + rgb * width)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    data = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))
    return dict(bytes=data, url='', w=width, h=height, fmt='png', backend='local-gradient',
                license='', score=0, sha256=hashlib.sha256(data).hexdigest())


def _cached(slot, report, project, min_dim):
    for rec in report.get('slots', []):
        if rec.get('query') != (slot.query or slot.raw_src) or rec.get('status') not in ('resolved', 'degraded'):
            continue
        if rec.get('status') == 'degraded' and not slot.allow_fallback:
            continue
        try:
            path = (project / rec['local']).resolve()
            if project not in path.parents:
                continue
            data = path.read_bytes()
            w, h, fmt = pool.sniff_size(data)
            if fmt not in _EXT or not w or not h or min(w, h) < min_dim or not pool._aspect_ok(w, h, slot.want):
                continue
            return dict(bytes=data, url=rec.get('source_url', ''), w=w, h=h, fmt=fmt,
                        backend=rec.get('backend', 'cache'), license=rec.get('license', ''), score=rec.get('score', 0),
                        sha256=hashlib.sha256(data).hexdigest()), rec.get('status', 'resolved')
        except (OSError, KeyError, TypeError):
            continue
    return None, 'pending'


def run(project, *, backend='auto', workers=4, use_vlm=False, localize_remote=False,
        min_dim=pool.DEFAULT_MIN_DIM, dry_run=False, timeout=30, budget=120, offline=False,
        json_output=False, allow_latin_query=False):
    started = time.monotonic()
    if not all(math.isfinite(x) and x > 0 for x in (timeout, budget)) or workers < 1 or min_dim < 1:
        raise ValueError('timeout, budget, workers and min-dim must be positive')
    if backend != 'auto' and backend not in pool.BACKENDS:
        raise ValueError(f'Unknown backend: {backend}')
    pdir, pptd = _find_project(project)
    texts = {f'pages/{p.name}': p.read_text(encoding='utf-8') for p in sorted((pdir / 'pages').glob('*.page'))}
    if not texts:
        raise ValueError(f'No pages/*.page found: {pdir}')
    brief = pdir.name
    if pptd:
        match = re.search(r'^\s*title:\s*["\']?([^"\'\n]+)', pptd.read_text(encoding='utf-8'), re.M)
        if match:
            brief = match.group(1).strip()
    all_slots = [s for page, text in texts.items() for s in slots_mod.extract_slots(text, page)
                 if s.is_search or ((localize_remote or offline) and s.is_remote)]
    if not allow_latin_query:
        # Image queries are written in Chinese; a Latin-only query searches the wrong index.
        latin = [s for s in all_slots if s.is_search and not slots_mod.is_cjk_query(s.query)]
        if latin:
            detail = '; '.join(f'{s.page}:{s.line_no + 1} {s.query[:40]}' for s in latin)
            raise ValueError('image queries must be written in Chinese — rewrite these '
                             f'search: placeholders: {detail}')
    use_vlm = bool(use_vlm and not offline and pool.vlm_enabled())
    progress(f'[scan] {len(texts)} pages, {len(all_slots)} slots; backend={backend} offline={offline} vlm={use_vlm}')
    if dry_run:
        for slot in all_slots:
            progress(f'[slot] {slot.page}:{slot.line_no+1} {slot.raw_src[:80]} fallback={slot.allow_fallback}')
        if json_output:
            print(json.dumps({'dry_run': True, 'total_slots': len(all_slots)}))
        return 0
    report_path = pdir / 'images_report.json'
    try:
        previous = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    for slot in all_slots:
        slot.winner, slot.status = _cached(slot, previous, pdir, min_dim)
    unresolved = [s for s in all_slots if not s.winner]
    if not offline:
        _attempts(unresolved, texts, brief, backend, workers, timeout, started + budget, use_vlm, min_dim)
    for slot in unresolved:
        if slot.winner:
            continue
        if offline:
            slot.tried.append({'fate': 'offline'})
        if slot.allow_fallback:
            slot.winner, slot.status = _gradient(slot), 'degraded'
        else:
            slot.status = 'failed'
    records = []
    originals = dict(texts)
    for slot in all_slots:
        rec = dict(page=slot.page, elementId=slot.element_id, kind=slot.kind,
                   query=slot.query or slot.raw_src, status=slot.status, tried=slot.tried)
        if slot.winner:
            winner = slot.winner
            filename = f"{_slugify(slot.element_id or slot.query)}-{winner['sha256'][:10]}{_EXT[winner['fmt']]}"
            (pdir / 'media').mkdir(exist_ok=True)
            (pdir / 'media' / filename).write_bytes(winner['bytes'])
            local = f'media/{filename}'
            texts[slot.page] = slots_mod.patch_src(texts[slot.page], slot.line_no, slot.raw_src, local)
            rec.update(local=local, source_url=winner['url'], backend=winner['backend'],
                       license=winner.get('license', ''), landing=winner.get('landing', ''),
                       width=winner['w'], height=winner['h'], score=round(float(winner.get('score', 0)), 2),
                       vlm=winner.get('vlm', {}))
            if slot.status == 'degraded':
                rec['fallback'] = 'Explicitly permitted decorative gradient; no real subject represented'
        records.append(rec)
    for page, text in texts.items():
        if text != originals[page]:
            (pdir / page).write_text(text, encoding='utf-8')
    failed = sum(s.status == 'failed' for s in all_slots)
    report = dict(project=pdir.name, deck_brief=brief, backend=backend, vlm=use_vlm, offline=offline,
                  timeout=timeout, budget=budget, elapsed_seconds=round(time.monotonic()-started, 3),
                  total_slots=len(all_slots), resolved=len(all_slots)-failed, failed=failed,
                  degraded=sum(s.status == 'degraded' for s in all_slots), slots=records)
    # Preserve previous provenance on a no-op rerun instead of erasing resolved slots.
    if all_slots or not report_path.exists():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    progress(f"[done] resolved={report['resolved']}/{len(all_slots)} failed={failed} degraded={report['degraded']} → images_report.json")
    if json_output:
        print(json.dumps(report, ensure_ascii=False))
    return 2 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('project')
    ap.add_argument('--backend', default='auto', choices=['auto', *pool.BACKENDS])
    ap.add_argument('--workers', type=int, default=4)
    vlm = ap.add_mutually_exclusive_group()
    vlm.add_argument('--vlm', action='store_true', help='Explicitly enable authorized VLM review; requires a key')
    vlm.add_argument('--no-vlm', action='store_true', help='Disable VLM (the default)')
    ap.add_argument('--offline', action='store_true', help='No image/VLM network calls; only cache or permitted decoration')
    ap.add_argument('--timeout', type=float, default=30, help='Seconds per complete backend attempt')
    ap.add_argument('--budget', type=float, default=120, help='Seconds for the overall image command')
    ap.add_argument('--localize-remote', action='store_true')
    ap.add_argument('--min-dim', type=int, default=pool.DEFAULT_MIN_DIM)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--allow-latin-query', action='store_true',
                    help='only for a deck actually written in that language')
    ap.add_argument('--json', action='store_true', help='One JSON summary on stdout; progress on stderr')
    args = ap.parse_args(argv)
    try:
        return run(args.project, backend=args.backend, workers=args.workers, use_vlm=args.vlm,
                   localize_remote=args.localize_remote, min_dim=args.min_dim, dry_run=args.dry_run,
                   timeout=args.timeout, budget=args.budget, offline=args.offline, json_output=args.json,
                   allow_latin_query=args.allow_latin_query)
    except (OSError, ValueError) as exc:
        progress(f'[error] {exc}')
        if args.json:
            print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
