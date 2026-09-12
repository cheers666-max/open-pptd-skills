#!/usr/bin/env python3
"""Rasterise exported page HTML through a remote html2png service.

The local renderer has to start a browser and paint every slide on this machine; the service takes
the same self-contained page HTML and returns a PNG, so the pages cost remote CPU instead of local
memory and can be asked for many at a time. Measured on a 21-page deck: 6 concurrent requests
average 0.87s per page against 6.2s per page for local Chrome at two workers.

It renders what `export_html.py` already produced — self-contained HTML with fonts and images
inlined — so nothing about the deck has to be reachable from the service.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_SELECTOR = ".slide"
DEFAULT_WORKERS = 6
ENDPOINT_ENV = "PPT_HTML2PNG_URL"


class RenderServiceError(RuntimeError):
    pass


def endpoint_from(explicit: Optional[str] = None) -> str:
    value = explicit or os.environ.get(ENDPOINT_ENV, "")
    if not value:
        raise RenderServiceError(
            f"no html2png endpoint: pass --endpoint or set {ENDPOINT_ENV}")
    return value


def _opener() -> urllib.request.OpenerDirector:
    """The service and its storage are internal; an ambient proxy only breaks them."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def capture(html: str, *, endpoint: str, selector: str = DEFAULT_SELECTOR,
            timeout: float = 180.0) -> bytes:
    """One page in, PNG bytes out."""
    payload = json.dumps({
        "type": "html2png",
        "html_pages": [html],
        "options": {"captureSelector": selector, "returnCaptureSize": True},
    }).encode()
    request = urllib.request.Request(endpoint, data=payload,
                                     headers={"Content-Type": "application/json"})
    with _opener().open(request, timeout=timeout) as response:
        body = json.loads(response.read())
    if body.get("errno") not in (0, None):
        raise RenderServiceError(f"html2png failed: {body.get('errmsg') or body}")
    data = body.get("data") or {}
    url = data.get("s3url")
    if not url:
        raise RenderServiceError(f"html2png returned no image url: {body}")
    with _opener().open(url, timeout=timeout) as response:
        image = response.read()
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RenderServiceError("html2png returned something that is not a PNG")
    return image


def capture_pages(html_dir: Path, output_dir: Path, *, endpoint: str,
                  selector: str = DEFAULT_SELECTOR, workers: int = DEFAULT_WORKERS,
                  timeout: float = 180.0,
                  pages_wanted: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """Every page_NN.html in a deck's html/ folder, rendered concurrently.

    `pages_wanted` renders only those page numbers, so a repair that touched one slide pays for
    one request instead of the whole deck.
    """
    pages = sorted(html_dir.glob("page_*.html"))
    if pages_wanted is not None:
        keep = {int(n) for n in pages_wanted}
        pages = [p for p in pages if int(p.stem.split("_")[1]) in keep]
    if not pages:
        raise RenderServiceError(f"no page_NN.html found in {html_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    def one(source: Path) -> Dict[str, Any]:
        target = output_dir / f"{source.stem}.png"
        target.write_bytes(capture(source.read_text(encoding="utf-8"),
                                   endpoint=endpoint, selector=selector, timeout=timeout))
        return {"page": source.name, "image": str(target), "bytes": target.stat().st_size}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, pages))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_dir", type=Path, help="a deck's html/ folder")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", help=f"html2png URL (or {ENDPOINT_ENV})")
    parser.add_argument("--selector", default=DEFAULT_SELECTOR)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rendered = capture_pages(args.html_dir, args.output,
                                 endpoint=endpoint_from(args.endpoint),
                                 selector=args.selector, workers=args.workers,
                                 timeout=args.timeout)
    except (RenderServiceError, OSError) as exc:
        print(f"render_service: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"pages": len(rendered), "images": rendered}, ensure_ascii=False, indent=2))
    else:
        print(f"render_service: {len(rendered)} page(s) → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
