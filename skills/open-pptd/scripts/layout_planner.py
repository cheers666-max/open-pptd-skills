#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout_planner.py — read-only rhythm suggestions for an existing outline.

Preserves page count, sequence, types and user metadata. Layout similarity
requires explicit layoutIntent/silhouette; title length is not layout evidence.
Usage: python3 layout_planner.py outline.json --json
"""
from __future__ import annotations

import argparse
import json
import copy
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 页面原型分类
ARCHETYPES = ["cover", "toc", "section", "content", "data", "quote", "closing"]

# pageType → archetype 映射
PAGE_TYPE_TO_ARCHETYPE = {
    "cover": "cover",
    "final": "closing",
    "chapter": "section",
    "toc": "toc",
    "content": "content",
    "data": "data",
    "quote": "quote",
}

# 默认节奏参数
DEFAULT_MAX_CONTENT_BETWEEN_DIVIDERS = 5


def classify_archetype(page: Dict[str, Any]) -> str:
    """根据 page 的 type/title 推断原型。"""
    page_type = page.get("type", "content")
    if page_type in PAGE_TYPE_TO_ARCHETYPE:
        return PAGE_TYPE_TO_ARCHETYPE[page_type]
    title = page.get("title", "").lower()
    if any(kw in title for kw in ["data", "chart", "metric", "kpi", "number", "统计", "数据", "图表"]):
        return "data"
    if any(kw in title for kw in ["quote", "引用", "名言", "观点"]):
        return "quote"
    return "content"


def compute_silhouette(page: Dict[str, Any]) -> Optional[str]:
    """Only explicit author layout information can support a similarity hint."""
    return page.get("silhouette") or page.get("layoutIntent")


def plan_rhythm(pages: List[Dict[str, Any]],
                max_content_between_dividers: int = DEFAULT_MAX_CONTENT_BETWEEN_DIVIDERS) -> List[Dict[str, Any]]:
    """Return the outline unchanged; suggestions are a separate report field."""
    if not isinstance(pages, list) or not all(isinstance(p, dict) for p in pages):
        raise ValueError("pages must be an array of page objects")
    if max_content_between_dividers < 1:
        raise ValueError("max-content-between-dividers must be positive")
    return copy.deepcopy(pages)


def validate_rhythm(planned: List[Dict[str, Any]],
                    max_content_between_dividers: int = DEFAULT_MAX_CONTENT_BETWEEN_DIVIDERS) -> List[Dict[str, Any]]:
    """Compatibility entry point: returns advisory suggestions, never edits."""
    suggestions = []
    content_run = 0
    for i, page in enumerate(planned):
        prev = planned[i - 1] if i else {}
        same_group = bool(page.get("continuityGroup") and page.get("continuityGroup") == prev.get("continuityGroup"))
        archetype = classify_archetype(page)
        if same_group:
            content_run = 0
            continue
        content_run = content_run + 1 if archetype in ("content", "data") else 0
        if content_run == max_content_between_dividers + 1:
            suggestions.append({"page": page.get("index", i + 1), "type": "long-content-run",
                                "severity": "info", "detail": "Consider a transition within existing pages if it helps the narrative; preserve page count."})
        intent = compute_silhouette(page)
        if i and intent and intent == compute_silhouette(prev) and archetype in ("content", "data"):
            suggestions.append({"page": page.get("index", i + 1), "type": "repeated-layout-intent",
                                "severity": "info", "detail": "Review repeated layout only if unintended; mark a teaching continuityGroup to preserve purposeful repetition."})
    return suggestions


def generate_demo_outline(n: int) -> Dict[str, Any]:
    """生成 demo outline（用于测试）。"""
    if n < 1:
        raise ValueError("demo page count must be positive")
    if n == 1:
        return {"title": "Demo", "pages": [{"index": 1, "type": "cover", "title": "Title"}]}
    pages = [{"index": 1, "type": "cover", "title": "Title"}]
    for i in range(2, n):
        pages.append({"index": i, "type": "content", "title": f"Content page {i} with some text"})
    pages.append({"index": n, "type": "final", "title": "Thank You"})
    return {"title": "Demo", "pages": pages}


def main():
    ap = argparse.ArgumentParser(description="Page rhythm layout planner")
    ap.add_argument("outline", nargs="?", help="Outline JSON file")
    ap.add_argument("--max-content-between-dividers", type=int, default=DEFAULT_MAX_CONTENT_BETWEEN_DIVIDERS)
    ap.add_argument("--demo", type=int, help="Run with a demo outline of N pages")
    ap.add_argument("--json", action="store_true", help="Print JSON only")
    args = ap.parse_args()

    if args.demo:
        outline = generate_demo_outline(args.demo)
    elif args.outline:
        outline = json.loads(Path(args.outline).read_text(encoding="utf-8"))
    else:
        print("error: provide an outline JSON file or --demo N", file=sys.stderr)
        return 1

    planned = plan_rhythm(outline["pages"], args.max_content_between_dividers)
    suggestions = validate_rhythm(planned, args.max_content_between_dividers)

    report = {
        "title": outline.get("title", ""),
        "total_pages": len(planned),
        "archetype_counts": {},
        "violations": [],
        "suggestions": suggestions,
        "mode": "advisory",
        "pages": planned,
    }
    for p in planned:
        arch = classify_archetype(p)
        report["archetype_counts"][arch] = report["archetype_counts"].get(arch, 0) + 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
