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
PyYAML (auto-installed with ``pip --user`` when missing), and Pillow for the
overview stitch (also auto-installed).
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from deck_server import start_deck_server
from export_html import find_chrome, find_deck

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
) -> None:
    url = f"{viewer_url}&page={page_number}&bare=1"
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--virtual-time-budget={virtual_time_ms}",
        f"--window-size={width},{height}",
        f"--force-device-scale-factor={scale:g}",
        f"--screenshot={output}",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ExportError(f"page {page_number}: headless Chrome timed out ({timeout}s)") from exc
    if proc.returncode != 0:
        raise ExportError(
            f"page {page_number}: Chrome exited {proc.returncode}: {proc.stderr[-500:]}"
        )
    if not output.is_file() or output.stat().st_size < 1024:
        raise ExportError(f"page {page_number}: screenshot missing or suspiciously small: {output}")


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
        thumbs.append((f"P{index}", thumb))

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
    source: Path,
    output: Path,
    scale: float = 2.0,
        virtual_time_ms: int = 30000,
    timeout: int = 90,
    force: bool = False,
) -> Dict[str, Any]:
    deck = find_deck(str(source))
    yaml = ensure_yaml()
    manifest = read_manifest(deck, yaml)
    page_files: List[str] = [str(entry) for entry in manifest["pages"]]
    width, height = manifest_size(manifest)

    output = output.expanduser().resolve()
    if output.exists() and any(output.iterdir()) and not force:
        raise ExportError(
            f"output directory already exists (pass --force to replace it): {output}"
        )

    viewer = VIEWER_DEFAULT.resolve()
    if not viewer.is_file():
        raise ExportError(f"viewer.html not found: {viewer}")
    chrome = find_chrome(None)
    image_cls, draw_cls, image_font = ensure_pillow()

    deck_dir = deck.parent
    deck_name = deck.name

    log(f"deck: {deck} ({len(page_files)} pages, {width}x{height}, scale {scale:g})")

    server, port = start_deck_server(viewer, deck_dir)
    try:
        viewer_url = f"http://127.0.0.1:{port}/viewer?deck=http://127.0.0.1:{port}/deck/{deck_name}"
        pages_dir = output / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        images: List[Path] = []
        for index in range(1, len(page_files) + 1):
            target = pages_dir / f"page_{index:02d}.png"
            screenshot_page(
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
        "images": [
            {
                "index": index,
                "image": f"pages/{path.name}",
                "page": page_files[index - 1] if index - 1 < len(page_files) else None,
            }
            for index, path in enumerate(images, start=1)
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
        help="virtual-time budget per page in ms (default: 30000)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="per-page Chrome timeout in seconds (default: 90)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output directory",
    )
    parser.add_argument("--json", action="store_true", help="print JSON summary only")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        deck = find_deck(str(args.input))
        output = args.output or deck.parent / ".qa-images"
        summary = export_images(
            deck, output, args.scale, args.virtual_time, args.timeout, args.force
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
