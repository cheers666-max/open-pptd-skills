#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_rendered.py — conservative post-render contrast/overlap review.

Pure-color contrast uses declared resolved colors, never region-average pixels.
Complex backgrounds and uncertain overlaps are advisory/not_checked. This tool
neither measures browser text overflow nor proves PPTX playback correctness.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"

# 复用现有导出基础设施
sys.path.insert(0, str(SCRIPTS_DIR))
from export_images import export_images, find_deck, ExportError, ensure_yaml  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ---------------------------------------------------------------------------
# 对比度计算（WCAG 2.1）
# ---------------------------------------------------------------------------

def _srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def contrast_ratio(l1: float, l2: float) -> float:
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def sample_region_average(img: Image.Image, x: int, y: int, w: int, h: int) -> Tuple[int, int, int]:
    """采样区域平均色（带边界裁剪）。"""
    width, height = img.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        return (0, 0, 0)
    region = img.crop((x0, y0, x1, y1))
    pixels = list(region.getdata())
    if not pixels:
        return (0, 0, 0)
    # 跳过透明像素（RGBA 且 alpha < 128）
    opaque = [p[:3] for p in pixels if len(p) < 4 or p[3] >= 128]
    if not opaque:
        return (0, 0, 0)
    r = sum(p[0] for p in opaque) // len(opaque)
    g = sum(p[1] for p in opaque) // len(opaque)
    b = sum(p[2] for p in opaque) // len(opaque)
    return (r, g, b)


# ---------------------------------------------------------------------------
# YAML 解析（轻量，只提取 elementId/bounds/text）
# ---------------------------------------------------------------------------

def _parse_page(page_path: Path) -> Dict[str, Any]:
    yaml = ensure_yaml()
    try:
        data = yaml.safe_load(page_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot parse {page_path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("elements", []), list):
        raise ValueError(f"Invalid page structure: {page_path}")
    if not all(isinstance(el, dict) for el in data.get("elements", [])):
        raise ValueError(f"Invalid element in {page_path}")
    return data


def _parse_page_elements(page_path: Path) -> List[Dict[str, Any]]:
    return _parse_page(page_path).get("elements", [])


def _rgb(value, colors):
    if isinstance(value, str) and value.startswith("$"):
        value = colors.get(value[1:])
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    value = {"black": "#000000", "white": "#ffffff"}.get(value, value)
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        value = "#" + "".join(c * 2 for c in value[1:])
    if not re.fullmatch(r"#[0-9a-f]{6}(?:ff)?", value):
        return None
    return tuple(int(value[i:i+2], 16) for i in (1, 3, 5))


def _bounds(el):
    b = el.get("bounds")
    if not isinstance(b, list) or len(b) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in b):
        return None
    return b if b[2] > 0 and b[3] > 0 else None


def _overlap(a, b):
    return min(a[0]+a[2], b[0]+b[2]) > max(a[0], b[0]) and min(a[1]+a[3], b[1]+b[3]) > max(a[1], b[1])


def _contains(a, b):
    return a[0] <= b[0] and a[1] <= b[1] and a[0]+a[2] >= b[0]+b[2] and a[1]+a[3] >= b[1]+b[3]


def _transparent(el):
    fill = el.get("fill") or {}
    color = fill.get("color", "") if isinstance(fill, dict) else fill
    return el.get("opacity") == 0 or (isinstance(fill, dict) and fill.get("opacity") == 0) or color in ("transparent", "none") or bool(re.fullmatch(r"#[0-9a-fA-F]{6}00", str(color)))


def _solid(fill, colors):
    if not isinstance(fill, dict) or fill.get("type", "solid") != "solid" or fill.get("opacity", 1) != 1:
        return None
    return _rgb(fill.get("color"), colors)


def audit_page(img_path: Path, page_path: Path, scale: float, page_index: int,
               min_contrast: float = 4.5, theme: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """Inspect declared colors after successful rendering, with bounded certainty."""
    if not HAS_PIL:
        raise ExportError("Pillow not available")
    with Image.open(img_path) as image:
        image.verify()
    page = _parse_page(page_path)
    elements = page.get("elements", [])
    colors = (theme or {}).get("colors", {})
    base = _solid(page.get("background", {"type": "solid", "color": "#FFFFFF"}), colors)
    issues = []
    for i, el in enumerate(elements):
        content = el.get("content") or {}
        b = _bounds(el)
        if el.get("elementType") != "text" or not content.get("text") or not b or el.get("opacity") == 0:
            continue
        common = {"elementId": el.get("elementId"), "page": page_index, "bounds": b}
        bg = base
        for under in elements[:i]:
            ub = _bounds(under)
            if not ub or not _overlap(b, ub) or _transparent(under):
                continue
            fill = under.get("fill")
            if (under.get("elementType") == "shape" and under.get("shapeName", "rect") == "rect"
                    and _contains(ub, b) and under.get("opacity", 1) == 1 and not under.get("rotation")):
                bg = _solid(fill, colors)
            else:
                bg = None  # image, partial fill, rounded edges, other text, etc.
        style = content
        ref = content.get("style")
        if isinstance(ref, str) and ref.startswith("$"):
            style = {**(theme or {}).get("textStyles", {}).get(ref[1:], {}), **content}
        fg = _rgb(style.get("color", "#1e1e1e"), colors)
        if style.get("backgroundColor"):
            bg = _rgb(style["backgroundColor"], colors)
        rich = str(content["text"])
        uncertain = (el.get("opacity", 1) != 1 or el.get("rotation") or style.get("gradient")
                     or re.search(r"(?:color|background|opacity)\s*:", rich, re.I)
                     or (ref and not isinstance(ref, str)))
        if fg is None or bg is None or uncertain:
            issues.append({**common, "type": "contrast-unchecked", "severity": "info", "status": "not_checked",
                           "message": "Complex or unresolved colors/background; review the rendered page."})
        else:
            ratio = contrast_ratio(relative_luminance(*fg), relative_luminance(*bg))
            if ratio < min_contrast:
                issues.append({**common, "type": "contrast", "severity": "error" if ratio < 3 else "warning",
                               "method": "declared-solid-colors", "ratio": round(ratio, 2), "min_required": min_contrast,
                               "message": f"Declared text/background contrast {ratio:.2f}:1 below {min_contrast}:1"})
        for over in elements[i+1:]:
            ob = _bounds(over)
            if ob and _overlap(b, ob) and not _transparent(over) and over.get("elementType") in ("image", "shape"):
                issues.append({**common, "type": "occlusion", "severity": "info", "status": "not_checked",
                               "occluded_by": over.get("elementId"), "method": "bounds-only",
                               "message": "Bounds overlap; actual occlusion requires visual review."})
    return issues


def annotate_image(
    img_path: Path,
    issues: List[Dict[str, Any]],
    output_path: Path,
    scale: float,
) -> None:
    """在渲染图上标注 issue 位置。"""
    if not HAS_PIL:
        return
    with Image.open(img_path) as source:
        img = source.copy()
    draw = ImageDraw.Draw(img)

    for issue in issues:
        if "bounds" not in issue:
            continue
        b = issue["bounds"]
        x, y = int(b[0] * scale), int(b[1] * scale)
        w, h = int(b[2] * scale), int(b[3] * scale)

        color = "#FF0000" if issue["severity"] == "error" else "#FFA500"
        draw.rectangle([x, y, x + w, y + h], outline=color, width=3)

        label = f"{issue['type']}: {issue.get('ratio', '')}"
        draw.text((x, max(0, y - 15)), label, fill=color)

    img.save(output_path)


def run_audit(
    project: str,
    output_dir: Optional[str] = None,
    workers: int = 4,
    min_contrast: float = 4.5,
    scale: float = 2.0,
    images_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """运行完整审计流程。"""
    deck = find_deck(project)
    project_dir = deck.parent

    manifest = ensure_yaml().safe_load(deck.read_text(encoding="utf-8"))
    theme = manifest.get("theme", {})
    qa_dir = Path(output_dir) if output_dir else project_dir / ".qa-images"
    if images_dir:
        # Caller must supply current images; no claim that old screenshots are fresh.
        qa_dir = Path(images_dir)
        refs = manifest.get("pages", [])
        summary = {"pages": len(refs), "images": [
            {"index": i, "image": f"pages/page_{i:02d}.png", "page": ref}
            for i, ref in enumerate(refs, 1)]}
        if not all((qa_dir / item["image"]).is_file() for item in summary["images"]):
            raise ExportError("--images requires current screenshots for every manifest page")
        print(f"[1/3] Reusing supplied images from {qa_dir}; freshness is caller-verified", file=sys.stderr)
    else:
        print(f"[1/3] Rendering pages to {qa_dir}...", file=sys.stderr)
        summary = export_images(deck, qa_dir, scale, 30000, 90, force=True, workers=workers)

    # 2. 逐页审计
    print(f"[2/3] Auditing {summary['pages']} pages...", file=sys.stderr)
    all_issues = []
    for img_info in summary["images"]:
        page_index = img_info["index"]
        img_path = qa_dir / img_info["image"]
        page_file = img_info.get("page")
        if not page_file:
            raise ExportError("Image has no corresponding page")
        page_path = project_dir / page_file
        if not page_path.exists():
            raise ExportError(f"Page missing: {page_path}")

        issues = audit_page(img_path, page_path, scale, page_index, min_contrast, theme)
        all_issues.extend(issues)

        # 标注问题页
        if issues:
            annotated = qa_dir / f"annotated_page_{page_index:02d}.png"
            annotate_image(img_path, issues, annotated, scale)

    # 3. 生成报告
    print(f"[3/3] Generating report...", file=sys.stderr)
    report = {
        "project": str(project_dir),
        "total_pages": summary["pages"],
        "total_issues": len(all_issues),
        "not_checked": sum(i.get("status") == "not_checked" for i in all_issues),
        "scope": "Declared solid-color contrast; overlap is advisory. No text overflow or PPTX playback measurement.",
        "images_reused": bool(images_dir),
        "errors": sum(1 for i in all_issues if i["severity"] == "error"),
        "warnings": sum(1 for i in all_issues if i["severity"] == "warning"),
        "issues": all_issues,
        "qa_dir": str(qa_dir),
    }

    report_path = qa_dir / "audit_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] Audit complete: {len(all_issues)} issues ({report['errors']} errors, {report['warnings']} warnings)", file=sys.stderr)
    print(f"     Report: {report_path}", file=sys.stderr)

    return report


def main():
    ap = argparse.ArgumentParser(description="Conservative post-render contrast and overlap review")
    ap.add_argument("project", help="Project directory or .pptd file")
    ap.add_argument("--output", "-o", help="Output directory (default: <project>/.qa-images)")
    ap.add_argument("--images", help="Reuse current export_images output; caller must verify freshness")
    ap.add_argument("--workers", "-w", type=int, default=4, help="Parallel render workers")
    ap.add_argument("--min-contrast", type=float, default=4.5, help="Minimum contrast ratio (default: 4.5)")
    ap.add_argument("--scale", type=float, default=2.0, help="Render scale factor (default: 2.0)")
    ap.add_argument("--json", action="store_true", help="Print JSON report only")
    args = ap.parse_args()

    try:
        report = run_audit(
            args.project,
            output_dir=args.output,
            workers=args.workers,
            min_contrast=args.min_contrast,
            scale=args.scale,
            images_dir=args.images,
        )
    except (ExportError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[err] audit failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0 if report["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
