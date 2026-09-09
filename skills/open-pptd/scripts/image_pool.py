#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect the deck's pictures once, before the pages are written.

Searching per page while authoring gives every page its own narrow query: the same photo lands
twice, a page quietly ends up with nothing, and a picture that only matches its own caption is
never compared against the deck. This builds the pool first — one search pass driven by the
confirmed outline — and pages then reference `pool:<id>` instead of inventing a URL or a query.

    image_pool.py --project deck/ [--outline outline.json] [--backend auto] [--budget 240]
    image_pool.py --project deck/ --resolve          # rewrite pool: references to media paths
    image_pool.py --project deck/ --list             # what is in the pool

Reuses the existing search machinery (`image_search/`), including its deck-wide hash/URL dedupe,
so two pages cannot be handed the same photo.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / 'image_search'))

import pool as backend_pool  # noqa: E402
import search_images  # noqa: E402
import slots as slots_mod  # noqa: E402

POOL_PREFIX = 'pool:'
POOL_FILE = 'images_pool.json'
DEFAULT_BUDGET = 360.0
DEFAULT_LIMIT = 12        # 本分支追求多图：每次检索多看候选
RETRY_TRIM_WORDS = 2      # 首轮空手时把长查询裁短再搜一次


def _find_project(target: Path):
    return search_images._find_project(target)


def _deck_title(pptd: Optional[Path], fallback: str) -> str:
    if pptd is None:
        return fallback
    import re
    match = re.search(r'^\s*title:\s*["\']?([^"\'\n]+)', pptd.read_text(encoding='utf-8'), re.M)
    return match.group(1).strip() if match else fallback


SUFFIXES = 'abcdefghijklmnopqrstuvwxyz'


def page_image_plan(page: dict) -> List[Dict[str, Any]]:
    """The pictures one outline page asks for.

    Rich form (preferred) — a page may want several, each with its own subject:

        "images": [{"query": "云手 动作 分解", "orientation": "portrait"},
                   {"query": "身韵课堂 教学 示范"}]

    Short form, one picture: `"image": true` with `imageQuery`/`imageOrientation`/`imageRatio`.
    """
    plan = page.get('images')
    if isinstance(plan, list) and plan:
        entries = []
        for item in plan:
            if isinstance(item, str):
                entries.append({'query': item})
            elif isinstance(item, dict):
                entries.append(dict(item))
        return entries
    if page.get('image'):
        return [{'query': page.get('imageQuery'), 'orientation': page.get('imageOrientation'),
                 'ratio': page.get('imageRatio'), 'role': page.get('imageRole')}]
    return []


def intents_from_outline(outline: dict) -> List[Dict[str, Any]]:
    """One search intent per picture the outline asked for; a page may ask for several."""
    intents = []
    for position, page in enumerate(outline.get('pages') or [], start=1):
        if not isinstance(page, dict):
            continue
        index = page.get('pageIndex', position)
        wanted = page_image_plan(page)
        for order, entry in enumerate(wanted):
            query = str(entry.get('query') or page.get('actionTitle') or page.get('summary') or '').strip()
            if not query:
                continue
            suffix = SUFFIXES[order] if len(wanted) > 1 and order < len(SUFFIXES) else ''
            intents.append({
                'id': f'p{index}{suffix}',
                'pageIndex': index,
                'query': query,
                'want': str(entry.get('orientation') or 'landscape'),
                'ratio': entry.get('ratio'),
                'role': str(entry.get('role') or '').strip().lower(),
                'note': str(entry.get('note') or '').strip(),
                'context': ' '.join(str(page.get(key, '')) for key in ('actionTitle', 'summary')).strip(),
            })
    return intents


def check_queries(intents: List[Dict[str, Any]]) -> None:
    """Image queries are written in Chinese; a Latin-only query searches the wrong index.

    The backends this branch keeps are Chinese-first, and the September run showed Latin scene
    phrases ("movie projector light beam dark room") coming back empty where the Chinese phrasing
    resolved. Fail here rather than after a fruitless search pass.
    """
    latin = [i for i in intents if not slots_mod.is_cjk_query(i['query'])]
    if latin:
        detail = '; '.join(f"{i['id']}: {i['query'][:40]}" for i in latin)
        raise ValueError('image queries must be written in Chinese — rewrite these outline pages '
                         f'(imageQuery): {detail}')


def _trimmed(query: str) -> str:
    """A shorter query for the retry: keep the leading terms, drop trailing modifiers."""
    parts = query.split()
    if len(parts) > RETRY_TRIM_WORDS:
        return ' '.join(parts[:RETRY_TRIM_WORDS])
    return ''


def build(project, outline_path=None, *, backend='auto', workers=4, use_vlm=False,
          min_dim=backend_pool.DEFAULT_MIN_DIM, timeout=30.0, budget=DEFAULT_BUDGET,
          json_output=False, allow_latin_query=False, limit=DEFAULT_LIMIT, retry=True) -> int:
    started = time.monotonic()
    if not all(math.isfinite(x) and x > 0 for x in (timeout, budget)) or workers < 1:
        raise ValueError('timeout, budget and workers must be positive')
    pdir, pptd = _find_project(project)
    outline_path = Path(outline_path) if outline_path else pdir / 'outline.json'
    if not outline_path.is_file():
        raise ValueError(f'outline not found: {outline_path}')
    outline = json.loads(outline_path.read_text(encoding='utf-8'))
    intents = intents_from_outline(outline)
    if not intents:
        raise ValueError('the outline asks for no pictures; nothing to collect')
    if not allow_latin_query:
        check_queries(intents)

    brief = _deck_title(pptd, pdir.name)
    slots, texts = [], {}
    for order, intent in enumerate(intents):
        key = f"outline#{intent['id']}"
        slot = slots_mod.Slot(page=key, line_no=order, kind='image', element_id=intent['id'],
                              raw_src=f"search:{intent['query']}", want=intent['want'],
                              ratio=intent['ratio'], fit='cover', bounds=None)
        slot.allow_product = intent.get('role') == 'product'
        slots.append(slot)
        texts[key] = intent['context'] or intent['query']

    use_vlm = bool(use_vlm and backend_pool.vlm_enabled())
    search_images.progress(f'[pool] {len(slots)} intents from {outline_path.name}; '
                           f'backend={backend} vlm={use_vlm} budget={budget}s')
    search_images._attempts(slots, texts, brief, backend, workers, timeout,
                            started + budget, use_vlm, min_dim, limit=limit)

    if retry:
        # A query that came back empty usually over-specified the shot; try the head of it once.
        second = []
        for slot in slots:
            if slot.winner:
                continue
            shorter = _trimmed(slot.query)
            if shorter and shorter != slot.query:
                slot.raw_src = f'search:{shorter}'
                slot.query = shorter
                second.append(slot)
        if second and time.monotonic() < started + budget:
            search_images.progress(f'[pool] retrying {len(second)} empty intent(s) with a shorter query')
            search_images._attempts(second, texts, brief, backend, workers, timeout,
                                    started + budget, use_vlm, min_dim, limit=limit)

    (pdir / 'media').mkdir(exist_ok=True)
    candidates, failed = [], []
    for intent, slot in zip(intents, slots):
        if not slot.winner:
            failed.append(intent['id'])
            continue
        winner = slot.winner
        filename = f"pool-{intent['id']}-{winner['sha256'][:10]}{search_images._EXT[winner['fmt']]}"
        (pdir / 'media' / filename).write_bytes(winner['bytes'])
        candidates.append({
            'id': intent['id'], 'pageIndex': intent['pageIndex'], 'query': intent['query'],
            'local': f'media/{filename}', 'sha256': winner['sha256'],
            'width': winner['w'], 'height': winner['h'],
            'ratio': round(winner['w'] / winner['h'], 3) if winner['h'] else None,
            'backend': winner['backend'], 'source_url': winner['url'],
            'landing': winner.get('landing', ''), 'license': winner.get('license', ''),
            'score': round(float(winner.get('score', 0)), 2),
        })

    planned_pages = {i['pageIndex'] for i in intents}
    covered_pages = {c['pageIndex'] for c in candidates}
    report = {
        'deck': pdir.name, 'deckBrief': brief, 'outline': outline_path.name,
        'backend': backend, 'vlm': use_vlm, 'searchLimit': limit,
        'elapsedSeconds': round(time.monotonic() - started, 3),
        'requested': len(intents), 'collected': len(candidates), 'failedIntents': failed,
        'pagesPlanned': len(planned_pages), 'pagesCovered': len(covered_pages),
        'imagesPerPlannedPage': round(len(candidates) / max(len(planned_pages), 1), 2),
        'candidates': candidates,
    }
    (pdir / POOL_FILE).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    search_images.progress(f"[pool] collected={len(candidates)}/{len(intents)} across "
                           f"{len(covered_pages)}/{len(planned_pages)} pages → {POOL_FILE}")
    if json_output:
        print(json.dumps(report, ensure_ascii=False))
    else:
        for entry in candidates:
            print(f"  {entry['id']:>6}  {entry['width']}x{entry['height']}  {entry['backend']:<10} {entry['query'][:48]}")
        if failed:
            print(f"  unresolved intents: {', '.join(failed)}")
    return 2 if failed else 0


def load_pool(pdir: Path) -> Dict[str, dict]:
    data = json.loads((pdir / POOL_FILE).read_text(encoding='utf-8'))
    return {entry['id']: entry for entry in data.get('candidates', []) if isinstance(entry, dict)}


def resolve(project, *, json_output=False) -> int:
    """Rewrite every `pool:<id>` reference to the pooled file; an unknown id is never guessed."""
    pdir, _ = _find_project(project)
    by_id = load_pool(pdir)
    rewritten, unknown = [], []
    for path in sorted((pdir / 'pages').glob('*.page')):
        text = path.read_text(encoding='utf-8')
        original = text
        for line_no, line in enumerate(text.splitlines()):
            match = slots_mod.SRC_RE.match(line)
            if not match:
                continue
            src = slots_mod._unquote(match.group('val'))
            if not src.startswith(POOL_PREFIX):
                continue
            entry = by_id.get(src[len(POOL_PREFIX):].strip())
            if entry is None:
                unknown.append({'page': f'pages/{path.name}', 'src': src})
                continue
            text = slots_mod.patch_src(text, line_no, src, entry['local'])
            rewritten.append({'page': f'pages/{path.name}', 'src': src, 'local': entry['local']})
        if text != original:
            path.write_text(text, encoding='utf-8')
    result = {'resolved': rewritten, 'unknown': unknown,
              'resolvedCount': len(rewritten), 'unknownCount': len(unknown)}
    if json_output:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f'image_pool: rewrote {len(rewritten)} reference(s)')
        for item in unknown:
            print(f"  unknown pool id in {item['page']}: {item['src']}")
    return 2 if unknown else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Collect deck pictures once, before pages are written')
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--outline', type=Path, help='default: <project>/outline.json')
    parser.add_argument('--resolve', action='store_true', help='rewrite pool: references instead of searching')
    parser.add_argument('--list', action='store_true', help='print the current pool')
    parser.add_argument('--backend', default='auto', choices=['auto', *backend_pool.BACKENDS])
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--vlm', action='store_true')
    parser.add_argument('--min-dim', type=int, default=backend_pool.DEFAULT_MIN_DIM)
    parser.add_argument('--timeout', type=float, default=30.0, help='seconds per attempt')
    parser.add_argument('--budget', type=float, default=DEFAULT_BUDGET, help='seconds for the whole pass')
    parser.add_argument('--limit', type=int, default=DEFAULT_LIMIT, help='candidates examined per attempt')
    parser.add_argument('--no-retry', action='store_true', help='do not retry an empty intent with a shorter query')
    parser.add_argument('--allow-latin-query', action='store_true',
                        help='only for a deck actually written in that language')
    parser.add_argument('--json', action='store_true')
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.list:
            pdir, _ = _find_project(args.project)
            print(json.dumps(load_pool(pdir), ensure_ascii=False, indent=2))
            return 0
        if args.resolve:
            return resolve(args.project, json_output=args.json)
        return build(args.project, args.outline, backend=args.backend, workers=args.workers,
                     use_vlm=args.vlm, min_dim=args.min_dim, timeout=args.timeout,
                     budget=args.budget, json_output=args.json,
                     allow_latin_query=args.allow_latin_query,
                     limit=args.limit, retry=not args.no_retry)
    except (ValueError, OSError) as exc:
        print(f'image_pool: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
