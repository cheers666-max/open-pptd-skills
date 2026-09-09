#!/usr/bin/env python3
"""One disposable backend attempt. Only the parent commits project files."""
import json
from pathlib import Path
import sys

import pool


def resolve(request):
    if request['backend'] == 'remote':
        data, url = pool._fetch_with_url(request['url'])
        w, h, fmt = pool.sniff_size(data) if data else (0, 0, '')
        if fmt in ('jpeg', 'png', 'webp', 'bmp') and w and h and min(w, h) >= request['min_dim']:
            return {'url': url, 'bytes': data, 'w': w, 'h': h, 'fmt': fmt,
                    'backend': 'remote', 'license': '', 'landing': request['url'], 'score': 0}, []
        return None, [{'backend': 'remote', 'fate': 'download_or_filter_failed'}]
    return pool.acquire(request['query'], backend=request['backend'], want=request['want'],
                        min_dim=request['min_dim'], use_vlm=request['use_vlm'],
                        ratio=request['ratio'], deck_brief=request['brief'], page_text=request['page_text'],
                        seen_hashes=set(request['seen_hashes']), seen_urls=set(request['seen_urls']),
                        allow_product=bool(request.get('allow_product')))


def main():
    request_path, output = map(Path, sys.argv[1:])
    request = json.loads(request_path.read_text(encoding='utf-8'))
    try:
        winner, tried = resolve(request)
        if winner:
            winner = dict(winner)
            output.with_suffix('.bin').write_bytes(winner.pop('bytes'))
        result = {'winner': winner, 'tried': tried}
    except Exception as exc:
        result = {'winner': None, 'tried': [{'backend': request['backend'], 'fate': 'worker_error',
                                            'error': type(exc).__name__}]}
    output.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
