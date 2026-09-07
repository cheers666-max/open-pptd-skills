#!/usr/bin/env python3
"""Export a PPTD project as page images for visual QA — fully local.

Renders each page through the skill's own viewer.html (the single source of
PPTD rendering truth) with headless Chrome screenshots in bare mode, then
stitches all pages into a single overview image that a multimodal model can
review. No browser automation framework, no network service.

A temporary localhost HTTP server is started to serve both the viewer and
the deck files — ``file://`` protocol blocks the viewer's subresource
fetches for decks with many pages or media.

Dependencies: a Chrome/Chromium binary (``CHROME_BIN`` env or common paths),
the same websocket-client CDP dependency used by export_html.py, PyYAML,
and Pillow for the overview stitch (auto-installed when missing).
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import signal
import subprocess
import tempfile
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode

from deck_server import start_deck_server
from export_html import ensure_websocket, find_chrome, find_deck

SKILL_DIR = Path(__file__).resolve().parent.parent
VIEWER_DEFAULT = SKILL_DIR / "scripts" / "viewer.html"

OVERVIEW_THUMB_WIDTH = 640
OVERVIEW_LABEL_HEIGHT = 32
OVERVIEW_GAP = 12


def _overview_columns(page_count: int) -> int:
    """Pick a sensible column count based on the number of pages."""
    if page_count <= 3:
        return page_count
    if page_count <= 6:
        return 3
    if page_count <= 12:
        return 4
    return 5


class ExportError(Exception):
    pass


def log(message: str) -> None:
    print(f"[export_images] {message}", file=sys.stderr, flush=True)


def ensure_yaml() -> Any:
    try:
        import yaml

        return yaml
    except ImportError:
        log("PyYAML is required; installing pyyaml with pip --user")
        process = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "pyyaml"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        if process.returncode != 0:
            raise ExportError(f"failed to install PyYAML:\n{process.stdout[-2000:]}")
        import yaml

        return yaml


def ensure_pillow() -> Tuple[Any, Any, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont

        return Image, ImageDraw, ImageFont
    except ImportError:
        log("Pillow is required for stitching; installing pillow with pip --user")
        process = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "pillow"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        if process.returncode != 0:
            raise ExportError(f"failed to install Pillow:\n{process.stdout[-2000:]}")
        from PIL import Image, ImageDraw, ImageFont

        return Image, ImageDraw, ImageFont


def read_manifest(deck: Path, yaml: Any) -> Dict[str, Any]:
    manifest = yaml.safe_load(deck.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ExportError(f"manifest is not a YAML mapping: {deck}")
    pages = manifest.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ExportError(f"manifest has no pages: {deck}")
    return manifest


def manifest_size(manifest: Dict[str, Any]) -> Tuple[int, int]:
    size = manifest.get("size")
    if isinstance(size, (list, tuple)) and len(size) == 2:
        try:
            width, height = int(size[0]), int(size[1])
            if width > 0 and height > 0:
                return width, height
        except (TypeError, ValueError):
            pass
    return 960, 540


# ---------------------------------------------------------------------------
# Screenshot + stitch
# ---------------------------------------------------------------------------

def screenshot_page(
    chrome: str,
    viewer_url: str,
    page_number: int,
    width: int,
    height: int,
    scale: float,
    virtual_time_ms: int,
    output: Path,
    timeout: int,
) -> Dict[str, Any]:
    # CDP waits for real async decode/font readiness. --dump-dom can finish its
    # virtual-time budget while those promises are still pending on image decks.
    websocket = ensure_websocket()
    deadline = time.monotonic() + timeout
    proc = None
    ws = None

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise ExportError(f"page {page_number}: renderer did not report ready or finish capture within {timeout}s")
        return value

    # Keep a fresh destination so failed rendering/capture never promotes an old PNG.
    with tempfile.TemporaryDirectory(prefix=".render-", dir=output.parent) as folder:
        fresh_output = Path(folder) / "page.png"
        profile = Path(folder) / "chrome-profile"
        url = f"{viewer_url}&page={page_number}&bare=1"
        cmd = [
            chrome,
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--hide-scrollbars",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            "about:blank",
        ]
        with tempfile.TemporaryFile() as chrome_errors:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=chrome_errors, start_new_session=True)
                port_file = profile / "DevToolsActivePort"
                while True:
                    remaining()
                    if proc.poll() is not None:
                        chrome_errors.seek(0)
                        detail = chrome_errors.read().decode("utf-8", "replace")[-500:]
                        raise ExportError(f"page {page_number}: Chrome exited {proc.returncode}: {detail}")
                    if port_file.exists():
                        lines = port_file.read_text().splitlines()
                        if len(lines) >= 2:
                            break
                    time.sleep(min(0.05, remaining()))
                # Explicit loopback no-proxy avoids mutating os.environ while workers connect.
                ws = websocket.create_connection(f"ws://127.0.0.1:{int(lines[0])}{lines[1]}",
                    timeout=remaining(), suppress_origin=True, http_no_proxy=["127.0.0.1", "localhost"])
                message_id = 0

                def cdp(method, params=None, session_id=None):
                    nonlocal message_id
                    message_id += 1
                    request = {"id": message_id, "method": method, "params": params or {}}
                    if session_id:
                        request["sessionId"] = session_id
                    ws.settimeout(remaining())
                    ws.send(json.dumps(request))
                    while True:
                        ws.settimeout(remaining())
                        response = json.loads(ws.recv())
                        if response.get("id") != message_id:
                            continue
                        if "error" in response:
                            raise ExportError(f"page {page_number}: CDP {method}: {response['error']}")
                        return response.get("result", {})

                target = cdp("Target.createTarget", {"url": "about:blank"})["targetId"]
                session = cdp("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
                cdp("Page.enable", session_id=session)
                cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": height,
                    "deviceScaleFactor": scale, "mobile": False}, session)
                cdp("Page.bringToFront", session_id=session)
                navigation = cdp("Page.navigate", {"url": url}, session)
                if navigation.get("errorText"):
                    raise ExportError(f"page {page_number}: navigation failed: {navigation['errorText']}")
                probe = """(() => {
                    const health = document.querySelector('body > pre#render-health');
                    if (health) return JSON.parse(health.textContent);
                    const status = document.getElementById('status-line')?.textContent || '';
                    if (status.includes('失败')) return {ready: true, ok: false, errors: [status]};
                    return null;
                })()"""
                while True:
                    result = cdp("Runtime.evaluate", {"expression": probe, "returnByValue": True}, session)
                    if result.get("exceptionDetails"):
                        raise ExportError(f"page {page_number}: invalid renderer health response")
                    health = result.get("result", {}).get("value")
                    if isinstance(health, dict) and health.get("ready"):
                        if not health.get("ok"):
                            raise ExportError(f"page {page_number}: render failed: {health.get('errors')}")
                        if health.get("pageNumber") != page_number:
                            raise ExportError(f"page {page_number}: renderer page identity mismatch: {health.get('pageNumber')}")
                        break
                    time.sleep(min(0.1, remaining()))
                # Preserve the legacy virtual-time animation position without using
                # virtual time as a network/image/font readiness deadline.
                settle = f"""(async () => {{
                    for (const animation of document.getAnimations()) {{
                        const end = animation.effect?.getComputedTiming().endTime;
                        try {{ animation.pause(); animation.currentTime = Math.min({max(0, virtual_time_ms)}, Number.isFinite(end) ? end : {max(0, virtual_time_ms)}); }} catch {{}}
                    }}
                    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                    return true;
                }})()"""
                painted = cdp("Runtime.evaluate", {"expression": settle, "awaitPromise": True, "returnByValue": True}, session)
                if painted.get("exceptionDetails"):
                    raise ExportError(f"page {page_number}: renderer did not finish painting")
                capture = cdp("Page.captureScreenshot", {"format": "png", "fromSurface": True,
                    "captureBeyondViewport": False, "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}}, session)
                fresh_output.write_bytes(base64.b64decode(capture["data"], validate=True))
                if fresh_output.stat().st_size < 1024:
                    raise ExportError(f"page {page_number}: screenshot missing or suspiciously small: {output}")
                fresh_output.replace(output)
                return health
            except ExportError:
                raise
            except Exception as exc:
                raise ExportError(f"page {page_number}: Chrome readiness/capture failed: {exc}") from exc
            finally:
                if ws is not None:
                    ws.close()
                if proc is not None:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()  # Reap the browser even when graceful termination timed out.


def check_not_blank(image_path: Path, image_cls: Any, page_number: int) -> None:
    with image_cls.open(image_path) as opened:
        frame = opened.convert("RGB")
        colors = frame.getcolors(maxcolors=64)
    if colors is not None and len(colors) <= 2:
        raise ExportError(f"page {page_number}: screenshot looks blank: {image_path}")


def label_font(image_font: Any) -> Any:
    try:
        return image_font.load_default(size=18)
    except TypeError:  # older Pillow without the size argument
        return image_font.load_default()


def stitch_overview(
    images: Sequence[Path],
    output: Path,
    image_cls: Any,
    draw_cls: Any,
    image_font: Any,
) -> Path:
    thumbs: List[Tuple[str, Any]] = []
    for index, path in enumerate(images, start=1):
        with image_cls.open(path) as opened:
            frame = opened.convert("RGB")
            ratio = OVERVIEW_THUMB_WIDTH / frame.width
            thumb = frame.resize(
                (OVERVIEW_THUMB_WIDTH, max(1, round(frame.height * ratio)))
            )
        thumbs.append((f"P{int(path.stem.split('_')[-1])}", thumb))

    columns = _overview_columns(len(thumbs))
    rows = math.ceil(len(thumbs) / columns)
    cell_height = OVERVIEW_LABEL_HEIGHT + max(thumb.height for _, thumb in thumbs)
    width = columns * OVERVIEW_THUMB_WIDTH + (columns + 1) * OVERVIEW_GAP
    height = rows * cell_height + (rows + 1) * OVERVIEW_GAP

    overview = image_cls.new("RGB", (width, height), "#e5e7eb")
    draw = draw_cls.Draw(overview)
    font = label_font(image_font)
    for position, (label, thumb) in enumerate(thumbs):
        column = position % columns
        row = position // columns
        x = OVERVIEW_GAP + column * (OVERVIEW_THUMB_WIDTH + OVERVIEW_GAP)
        y = OVERVIEW_GAP + row * (cell_height + OVERVIEW_GAP)
        draw.rectangle(
            (x, y, x + OVERVIEW_THUMB_WIDTH, y + OVERVIEW_LABEL_HEIGHT - 4),
            fill="#111827",
        )
        draw.text((x + 8, y + 5), label, fill="#ffffff", font=font)
        overview.paste(thumb, (x, y + OVERVIEW_LABEL_HEIGHT))

    overview.save(output, "JPEG", quality=85)
    return output


def export_images(
    deck: Path,
    output: Path,
    scale: float,
    virtual_time_ms: int,
    timeout: int,
    force: bool,
    workers: int,
    page_spec: str | None = None,
) -> Dict[str, Any]:
    yaml = ensure_yaml()
    manifest = read_manifest(deck, yaml)
    page_files: List[str] = [str(entry) for entry in manifest["pages"]]
    width, height = manifest_size(manifest)

    output = output.expanduser().resolve()
    if output.exists() and any(output.iterdir()) and not force:
        raise ExportError(
            f"output directory already exists (pass --force to replace it): {output}"
        )

    # Parse page spec (e.g. "1,3,5" or "2-10")
    if page_spec:
        selected = set()
        for part in str(page_spec).split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                selected.update(range(int(a), int(b) + 1))
            else:
                selected.add(int(part))
        page_indices = sorted(selected)
        if not page_indices:
            raise ExportError(f"empty page selection: {page_spec}")
        if any(i < 1 or i > len(page_files) for i in page_indices):
            raise ExportError(f"page numbers out of range: {page_spec} (deck has {len(page_files)} pages)")
    else:
        page_indices = list(range(1, len(page_files) + 1))

    viewer = VIEWER_DEFAULT.resolve()
    if not viewer.is_file():
        raise ExportError(f"viewer.html not found: {viewer}")
    chrome = find_chrome(None)
    ensure_websocket()  # Prepare the existing CDP dependency once before parallel workers.
    image_cls, draw_cls, image_font = ensure_pillow()

    deck_dir = deck.parent
    deck_name = deck.name

    log(f"deck: {deck} ({len(page_files)} pages, {width}x{height}, scale {scale:g})")

    server, port = start_deck_server(viewer, deck_dir)
    try:
        deck_url = f"http://127.0.0.1:{port}/deck/{quote(deck_name, safe='')}"
        viewer_url = f"http://127.0.0.1:{port}/viewer?{urlencode({'deck': deck_url})}"
        pages_dir = output / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        images: List[Path] = []
        health_by_page = {}
        if workers > 1 and len(page_indices) > 1:
            # Parallel: launch multiple Chrome processes concurrently
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {}
                for index in page_indices:
                    target = pages_dir / f"page_{index:02d}.png"
                    fut = pool.submit(
                        screenshot_page, chrome, viewer_url, index,
                        width, height, scale, virtual_time_ms, target, timeout,
                    )
                    futures[fut] = (index, target)
                for fut in as_completed(futures):
                    index, target = futures[fut]
                    health_by_page[index] = fut.result()  # raises on error
                    check_not_blank(target, image_cls, index)
                    images.append(target)
                    log(f"page {index}/{len(page_files)} → {target.name}")
            # Restore page order (as_completed returns in completion order)
            images.sort(key=lambda p: int(p.stem.split("_")[1]))
        else:
            for index in page_indices:
                target = pages_dir / f"page_{index:02d}.png"
                health_by_page[index] = screenshot_page(
                    chrome, viewer_url, index, width, height, scale,
                    virtual_time_ms, target, timeout,
                )
                check_not_blank(target, image_cls, index)
                images.append(target)
                log(f"page {index}/{len(page_files)} → {target.name}")
    finally:
        server.shutdown()
        server.server_close()

    overview = stitch_overview(images, output / "overview.jpg", image_cls, draw_cls, image_font)
    return {
        "pages": len(images),
        "overview": str(overview),
        "output": str(output),
        "renderHealth": [health_by_page[i] for i in page_indices],
        "images": [
            {
                "index": index,
                "image": f"pages/{path.name}",
                "page": page_files[index - 1] if index - 1 < len(page_files) else None,
            }
            for index, path in zip(page_indices, images)
        ],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render each page of a PPTD project to PNG via the local viewer + "
            "headless Chrome, then stitch an overview image for visual QA."
        )
    )
    parser.add_argument("input", type=Path, help=".pptd manifest or project directory")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="output directory (default: <project>/.qa-images)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=2.0,
        help="device scale factor for screenshots (default: 2.0)",
    )
    parser.add_argument(
        "--virtual-time",
        type=int,
        default=30000,
        help="animation seek position in ms (default: 30000); real readiness is bounded by --timeout",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="per-page Chrome timeout in seconds (default: 90)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="parallel Chrome screenshot workers (default: 4, set 1 for serial)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output directory",
    )
    parser.add_argument(
        "--page",
        "-p",
        help="page numbers to render, 1-based; supports 3, 1,2, 2-10",
    )
    parser.add_argument("--json", action="store_true", help="print JSON summary only")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        deck = find_deck(str(args.input))
        output = args.output or deck.parent / ".qa-images"
        summary = export_images(
            deck, output, args.scale, args.virtual_time, args.timeout, args.force, args.workers,
            page_spec=args.page,
        )
    except (ExportError, OSError, subprocess.SubprocessError, SystemExit) as exc:
        message = exc if isinstance(exc, SystemExit) else str(exc)
        print(f"open-pptd image export failed: {message}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
