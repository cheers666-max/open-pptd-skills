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

class ChromeBrowser:
    """One Chrome for the whole deck, one tab per page.

    Launching a browser per page cost a cold start and a full process tree (zygote, GPU, network
    service, renderer) for every slide, so a 22-page deck paid it 22 times and several decks
    exporting at once exhausted memory before they exhausted CPU. The capture itself already
    worked through a per-page CDP target, so the only thing that had to change is who owns the
    process: the deck, not the page. Each worker thread gets its own websocket to the same
    browser, keeping the request/response loop below unchanged and thread-safe.
    """

    # Starting the browser is not rendering a page: --timeout is the budget for one slide, and on
    # a loaded machine a cold start can outlast it while every page would still have rendered fine.
    STARTUP_TIMEOUT = 60.0

    def __init__(self, chrome: str, width: int, height: int, timeout: float) -> None:
        timeout = max(float(timeout), self.STARTUP_TIMEOUT)
        self._websocket = ensure_websocket()
        self._folder = tempfile.TemporaryDirectory(prefix=".chrome-")
        profile = Path(self._folder.name) / "chrome-profile"
        self._errors = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(
            [chrome, "--headless=new", "--no-first-run", "--no-default-browser-check",
             "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=0",
             f"--user-data-dir={profile}", f"--window-size={width},{height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=self._errors, start_new_session=True)
        deadline = time.monotonic() + timeout
        port_file = profile / "DevToolsActivePort"
        while True:
            if self.proc.poll() is not None:
                self._errors.seek(0)
                detail = self._errors.read().decode("utf-8", "replace")[-500:]
                raise ExportError(f"Chrome exited {self.proc.returncode}: {detail}")
            if port_file.exists():
                lines = port_file.read_text().splitlines()
                if len(lines) >= 2:
                    self.ws_url = f"ws://127.0.0.1:{int(lines[0])}{lines[1]}"
                    return
            if time.monotonic() >= deadline:
                raise ExportError("Chrome did not report a DevTools port in time")
            time.sleep(0.05)

    def connect(self, timeout: float):
        return self._websocket.create_connection(
            self.ws_url, timeout=timeout, suppress_origin=True,
            http_no_proxy=["127.0.0.1", "localhost"])

    def close(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        self._errors.close()
        self._folder.cleanup()

    def __enter__(self) -> "ChromeBrowser":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def screenshot_page(
    browser: "ChromeBrowser",
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
    deadline = time.monotonic() + timeout
    ws = None
    target = None

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise ExportError(f"page {page_number}: renderer did not report ready or finish capture within {timeout}s")
        return value

    # Keep a fresh destination so failed rendering/capture never promotes an old PNG.
    with tempfile.TemporaryDirectory(prefix=".render-", dir=output.parent) as folder:
        fresh_output = Path(folder) / "page.png"
        url = f"{viewer_url}&page={page_number}&bare=1"
        try:
            ws = browser.connect(remaining())
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
                if target is not None:
                    try:
                        ws.settimeout(5)
                        ws.send(json.dumps({"id": 10_000_000, "method": "Target.closeTarget",
                                            "params": {"targetId": target}}))
                    except Exception:  # noqa: BLE001 — the browser outlives one bad tab
                        pass
                ws.close()


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


REVIEW_WIDTH = 1280
REVIEW_QUALITY = 80


def write_review_copies(images, output, image_cls):
    """A compressed JPEG beside every page PNG, for the model to look at.

    A 1920×1080 page render is ~630 KB of PNG, which reaches a multimodal model as ~840 KB of
    base64 — a dozen pages reviewed twice is tens of megabytes of context, and that is where long
    vision-driven runs fall over. At 1280 px / q80 the same page is ~57 KB (9%) and still shows
    every layout defect a reviewer looks for. The full-resolution PNG stays on disk for the times a
    detail really needs it.
    """
    review_dir = output / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for path in images:
        target = review_dir / (path.stem + ".jpg")
        with image_cls.open(path) as raw:
            shrunk = raw.convert("RGB")
            shrunk.thumbnail((REVIEW_WIDTH, REVIEW_WIDTH))
            shrunk.save(target, "JPEG", quality=REVIEW_QUALITY, optimize=True)
        written.append(target)
    return written


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
        with ChromeBrowser(chrome, width, height, timeout) as browser:
            if workers > 1 and len(page_indices) > 1:
                # Parallel: one tab per worker inside the deck's single browser
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {}
                    for index in page_indices:
                        target = pages_dir / f"page_{index:02d}.png"
                        fut = pool.submit(
                            screenshot_page, browser, viewer_url, index,
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
                        browser, viewer_url, index, width, height, scale,
                        virtual_time_ms, target, timeout,
                    )
                    check_not_blank(target, image_cls, index)
                    images.append(target)
                    log(f"page {index}/{len(page_files)} → {target.name}")
    finally:
        server.shutdown()
        server.server_close()

    overview = stitch_overview(images, output / "overview.jpg", image_cls, draw_cls, image_font)
    write_review_copies(images, output, image_cls)
    return {
        "pages": len(images),
        "overview": str(overview),
        "output": str(output),
        "renderHealth": [health_by_page[i] for i in page_indices],
        "images": [
            {
                "index": index,
                "image": f"pages/{path.name}",
                "review": f"review/{path.stem}.jpg",
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
