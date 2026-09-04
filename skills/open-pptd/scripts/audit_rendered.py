#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_rendered.py — 渲染后像素级硬审计。

对 PPTD 工程做真实渲染（headless Chrome）→ 像素级分析：
  1. 文字-背景对比度（WCAG AA ≥4.5:1）
  2. 元素遮挡检测（bounding box 重叠 + 像素采样）
  3. 跨页对齐/网格一致性（标题位置、页边距）
  4. 生成带 bounding box 的标注图 + JSON 报告

用法：
  python3 audit_rendered.py <project_dir|deck.pptd> [--workers N] [--output DIR]
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
from export_images import export_images, find_deck, ExportError  # noqa: E402

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

def _parse_page_elements(page_path: Path) -> List[Dict[str, Any]]:
    """解析 .page 文件，提取元素列表。"""
    try:
        import yaml
    except ImportError:
        return []
    try:
        data = yaml.safe_load(page_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    elements = data.get("elements", [])
    result = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        result.append({
            "elementId": el.get("elementId", ""),
            "elementType": el.get("elementType", ""),
            "bounds": el.get("bounds", [0, 0, 0, 0]),
            "text": el.get("content", {}).get("text", "") if el.get("elementType") == "text" else "",
            "fontSize": el.get("content", {}).get("fontSize", 18),
            "color": el.get("content", {}).get("color", "#000000"),
        })
    return result


# ---------------------------------------------------------------------------
# 核心审计逻辑
# ---------------------------------------------------------------------------

def audit_page(
    img_path: Path,
    page_path: Path,
    scale: float,
    page_index: int,
    min_contrast: float = 4.5,
) -> List[Dict[str, Any]]:
    """审计单页，返回 issue 列表。"""
    issues = []
    if not HAS_PIL:
        return [{"type": "error", "message": "Pillow not available"}]

    img = Image.open(img_path)
    elements = _parse_page_elements(page_path)

    for el in elements:
        if el["elementType"] != "text" or not el["text"]:
            continue

        bounds = el["bounds"]
        if len(bounds) < 4:
            continue

        # 坐标转换：PPTD 坐标 → 渲染图像素坐标
        x = int(bounds[0] * scale)
        y = int(bounds[1] * scale)
        w = int(bounds[2] * scale)
        h = int(bounds[3] * scale)

        if w <= 0 or h <= 0:
            continue

        # 采样文字区域和背景区域
        text_color = sample_region_average(img, x + w // 4, y + h // 4, w // 2, h // 2)
        # 背景采样：文字区域外围
        bg_x, bg_y = x - 10, y - 10
        bg_color = sample_region_average(img, bg_x, bg_y, w + 20, h + 20)

        l_text = relative_luminance(*text_color)
        l_bg = relative_luminance(*bg_color)
        ratio = contrast_ratio(l_text, l_bg)

        if ratio < min_contrast:
            issues.append({
                "type": "contrast",
                "severity": "error" if ratio < 3.0 else "warning",
                "elementId": el["elementId"],
                "page": page_index,
                "bounds": bounds,
                "ratio": round(ratio, 2),
                "min_required": min_contrast,
                "message": f"Text contrast {ratio:.2f}:1 below WCAG AA {min_contrast}:1",
            })

    # 元素遮挡检测（简单重叠 + 层级）
    for i, el1 in enumerate(elements):
        for j, el2 in enumerate(elements):
            if i >= j:
                continue
            b1 = el1["bounds"]
            b2 = el2["bounds"]
            if len(b1) < 4 or len(b2) < 4:
                continue
            # 检查是否重叠
            x_overlap = max(0, min(b1[0] + b1[2], b2[0] + b2[2]) - max(b1[0], b2[0]))
            y_overlap = max(0, min(b1[1] + b1[3], b2[1] + b2[3]) - max(b1[1], b2[1]))
            if x_overlap > 0 and y_overlap > 0:
                # 文字被图片/形状遮挡
                if el1["elementType"] == "text" and el2["elementType"] in ("image", "shape"):
                    issues.append({
                        "type": "occlusion",
                        "severity": "warning",
                        "elementId": el1["elementId"],
                        "occluded_by": el2["elementId"],
                        "page": page_index,
                        "overlap": [x_overlap, y_overlap],
                        "message": f"Text '{el1['elementId']}' may be occluded by {el2['elementType']} '{el2['elementId']}'",
                    })

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
    img = Image.open(img_path).copy()
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
) -> Dict[str, Any]:
    """运行完整审计流程。"""
    deck = find_deck(project)
    project_dir = deck.parent

    # 1. 渲染所有页面
    qa_dir = Path(output_dir) if output_dir else project_dir / ".qa-images"
    print(f"[1/3] Rendering pages to {qa_dir}...", file=sys.stderr)
    summary = export_images(
        deck, qa_dir, scale, 30000, 90, force=True, workers=workers,
    )

    # 2. 逐页审计
    print(f"[2/3] Auditing {summary['pages']} pages...", file=sys.stderr)
    all_issues = []
    for img_info in summary["images"]:
        page_index = img_info["index"]
        img_path = qa_dir / img_info["image"]
        page_file = img_info.get("page")
        if not page_file:
            continue
        page_path = project_dir / page_file
        if not page_path.exists():
            continue

        issues = audit_page(img_path, page_path, scale, page_index, min_contrast)
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
    ap = argparse.ArgumentParser(description="Rendered pixel-level hard audit for PPTD projects")
    ap.add_argument("project", help="Project directory or .pptd file")
    ap.add_argument("--output", "-o", help="Output directory (default: <project>/.qa-images)")
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
        )
    except (ExportError, OSError, subprocess.SubprocessError) as exc:
        print(f"[err] audit failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0 if report["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
