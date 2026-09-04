#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout_planner.py — 分页节奏约束规划器。

在 step2 末尾（确定页数后、逐页生成前）运行，给每页分配原型（archetype），
并强制节奏规则：
  1. 不允许连续两页同原型（除非 silhouette 不同）
  2. 相邻 content 页的 silhouette 必须有变化
  3. 每 N 个 content 页必须插入节奏分隔页（section divider）

用法：
  python3 layout_planner.py <outline.json> [--max-content-between-dividers N]
  python3 layout_planner.py --demo 15

outline.json 格式：
  {
    "title": "...",
    "pages": [
      {"index": 1, "type": "cover", "title": "..."},
      {"index": 2, "type": "content", "title": "..."},
      ...
    ]
  }
"""
from __future__ import annotations

import argparse
import json
import math
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


def compute_silhouette(page: Dict[str, Any]) -> str:
    """计算页面 silhouette 哈希（简化版：基于标题长度和类型）。"""
    title = page.get("title", "")
    page_type = page.get("type", "content")
    # 用标题长度分桶 + 类型作为 silhouette
    title_bucket = min(len(title) // 10, 5)
    return f"{page_type}:{title_bucket}"


def plan_rhythm(
    pages: List[Dict[str, Any]],
    max_content_between_dividers: int = DEFAULT_MAX_CONTENT_BETWEEN_DIVIDERS,
) -> List[Dict[str, Any]]:
    """给每页分配原型，并强制节奏规则。"""
    planned = []
    consecutive_content = 0
    last_archetype = None
    last_silhouette = None

    for i, page in enumerate(pages):
        archetype = classify_archetype(page)
        silhouette = compute_silhouette(page)

        # 规则 1: 不允许连续两页同原型（除非 silhouette 不同）
        if archetype == last_archetype and archetype not in ("cover", "closing", "toc"):
            if silhouette == last_silhouette:
                # 尝试把 content 升级为 data 或 quote
                if archetype == "content":
                    archetype = "data" if i % 2 == 0 else "quote"
                    silhouette = f"{archetype}:forced"

        # 规则 3: 每 N 个 content 页必须插入节奏分隔页
        if archetype in ("content", "data"):
            consecutive_content += 1
            if consecutive_content > max_content_between_dividers and i < len(pages) - 1:
                # 在当前页前插入一个 section divider
                planned.append({
                    "index": f"{i}+",
                    "type": "section",
                    "archetype": "section",
                    "title": "Section Divider",
                    "silhouette": "section:divider",
                    "inserted": True,
                })
                consecutive_content = 0
                last_archetype = "section"
                last_silhouette = "section:divider"
        else:
            consecutive_content = 0

        planned.append({
            "index": page.get("index", i + 1),
            "type": page.get("type", "content"),
            "archetype": archetype,
            "title": page.get("title", ""),
            "silhouette": silhouette,
        })
        last_archetype = archetype
        last_silhouette = silhouette

    return planned


def validate_rhythm(planned: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """验证节奏规则，返回违规列表。"""
    violations = []
    for i in range(1, len(planned)):
        prev = planned[i - 1]
        curr = planned[i]
        if curr["archetype"] == prev["archetype"] and curr["archetype"] not in ("cover", "closing", "toc"):
            if curr["silhouette"] == prev["silhouette"]:
                violations.append({
                    "page": curr["index"],
                    "type": "consecutive-same-archetype",
                    "detail": f"Pages {prev['index']} and {curr['index']} share archetype '{curr['archetype']}' with same silhouette",
                })
    return violations


def generate_demo_outline(n: int) -> Dict[str, Any]:
    """生成 demo outline（用于测试）。"""
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
    violations = validate_rhythm(planned)

    report = {
        "title": outline.get("title", ""),
        "total_pages": len(planned),
        "archetype_counts": {},
        "violations": violations,
        "pages": planned,
    }
    for p in planned:
        arch = p["archetype"]
        report["archetype_counts"][arch] = report["archetype_counts"].get(arch, 0) + 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
