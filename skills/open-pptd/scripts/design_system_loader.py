#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""design_system_loader.py — 分层加载设计系统库。

两级结构：
1. index.json（轻量索引，≤100KB）：name/category/description/thumbnail/tags/full_spec_path
2. design.md（完整规范，~17KB each）：仅在用户选中后懒加载

用法：
  python3 design_system_loader.py list [--category consulting] [--tag dark]
  python3 design_system_loader.py get <design-name>
  python3 design_system_loader.py build-index   # 重建 index.json

目录结构（融合后）：
  reference/design_system/
    index.json                        # 自动生成的索引
    <category>/<name>/
      design.md                       # 完整规范
      reference.jpg                   # 缩略图（可选）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DS_ROOT = Path(__file__).resolve().parent.parent / "reference" / "design_system"
INDEX_PATH = DS_ROOT / "index.json"

# 类别映射：把 kimi-slides 的两套平行结构统一成单一 registry
CATEGORY_MAP = {
    "01_strategy": "strategy",
    "02_business": "business",
    "03_work": "work",
    "04_promotion": "promotion",
    "05_academic": "academic",
    "consulting": "consulting",
    "finance": "finance",
    "promotion": "promotion",
    "academic": "academic",
    "work": "work",
}


def _extract_description(md_path: Path) -> str:
    """从 design.md 提取一句话描述（第一个非空行，去除 markdown 标记）。"""
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 去除 markdown 粗体/斜体/链接标记
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"\*([^*]+)\*", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        if len(line) > 10:
            return line[:200]
    return ""


def _extract_tags(md_path: Path) -> list[str]:
    """从 design.md 提取标签（基于关键词启发式）。"""
    try:
        text = md_path.read_text(encoding="utf-8").lower()
    except Exception:
        return []
    tags = []
    tag_keywords = {
        "dark": ["dark background", "dark theme", "dark mode"],
        "light": ["white background", "pure white", "light theme"],
        "colorful": ["vibrant", "colorful", "multi-color"],
        "minimal": ["minimal", "minimalist", "clean", "simple"],
        "data-heavy": ["high-density", "data visualization", "chart", "table"],
        "editorial": ["editorial", "magazine", "publication"],
        "corporate": ["corporate", "business", "professional"],
        "creative": ["creative", "artistic", "brand"],
        "tech": ["technology", "tech", "digital"],
        "academic": ["academic", "research", "thesis"],
    }
    for tag, keywords in tag_keywords.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)
    return tags[:5]  # 最多 5 个标签


def build_index() -> list[dict]:
    """扫描 design_system 目录，生成索引条目。"""
    entries = []
    seen_names = set()

    for category_dir in sorted(DS_ROOT.iterdir()):
        if not category_dir.is_dir():
            continue
        raw_category = category_dir.name
        category = CATEGORY_MAP.get(raw_category, raw_category)

        for design_dir in sorted(category_dir.iterdir()):
            if not design_dir.is_dir():
                continue

            # 处理两种结构：
            # 1. <category>/<name>/design.md (新结构，如 consulting/pine-green-strategy/)
            # 2. <category>/<NN>/en/<name>.md (旧结构，如 01_strategy/01/en/dusk-violet-consulting.md)
            design_md = design_dir / "design.md"
            ref_jpg = design_dir / "reference.jpg"
            name = design_dir.name

            if not design_md.exists():
                # 检查旧结构
                en_dir = design_dir / "en"
                if en_dir.is_dir():
                    md_files = list(en_dir.glob("*.md"))
                    if md_files:
                        design_md = md_files[0]
                        name = design_md.stem
                        jpg_files = list(en_dir.glob("*.jpg"))
                        ref_jpg = jpg_files[0] if jpg_files else Path()
                    else:
                        continue
                else:
                    continue

            # 去重：同名设计只保留一个（优先新结构）
            dedup_key = f"{category}/{name}"
            if dedup_key in seen_names:
                continue
            seen_names.add(dedup_key)

            entry = {
                "name": name,
                "category": category,
                "description": _extract_description(design_md),
                "tags": _extract_tags(design_md),
                "spec_path": str(design_md.relative_to(DS_ROOT)),
                "thumbnail": str(ref_jpg.relative_to(DS_ROOT)) if ref_jpg.exists() else None,
            }
            entries.append(entry)

    return entries


def cmd_build_index():
    entries = build_index()
    index = {
        "version": 1,
        "count": len(entries),
        "designs": entries,
    }
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    size_kb = INDEX_PATH.stat().st_size / 1024
    print(f"[ok] index.json rebuilt: {len(entries)} designs, {size_kb:.1f}KB")
    return 0


def _load_index() -> dict:
    if not INDEX_PATH.exists():
        print("[info] index.json not found, building...", file=sys.stderr)
        cmd_build_index()
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def cmd_list(category: str | None, tag: str | None):
    index = _load_index()
    designs = index["designs"]
    if category:
        designs = [d for d in designs if d["category"] == category]
    if tag:
        designs = [d for d in designs if tag in d.get("tags", [])]

    print(f"# Design Systems ({len(designs)} matches)\n")
    for d in designs:
        tags_str = f" [{', '.join(d['tags'])}]" if d.get("tags") else ""
        print(f"- **{d['name']}** ({d['category']}){tags_str}")
        if d["description"]:
            print(f"  {d['description'][:120]}")
        print(f"  spec: `reference/design_system/{d['spec_path']}`")
        print()
    return 0


def cmd_get(name: str):
    index = _load_index()
    matches = [d for d in index["designs"] if d["name"] == name]
    if not matches:
        # 模糊匹配
        matches = [d for d in index["designs"] if name.lower() in d["name"].lower()]
    if not matches:
        print(f"[err] design not found: {name}", file=sys.stderr)
        return 1
    d = matches[0]
    spec_path = DS_ROOT / d["spec_path"]
    print(spec_path.read_text(encoding="utf-8"))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Design system tiered loader")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List available design systems")
    p_list.add_argument("--category", help="Filter by category")
    p_list.add_argument("--tag", help="Filter by tag")

    p_get = sub.add_parser("get", help="Get full design spec by name")
    p_get.add_argument("name", help="Design system name")

    sub.add_parser("build-index", help="Rebuild index.json")

    args = ap.parse_args()

    if args.cmd == "list":
        return cmd_list(args.category, args.tag)
    elif args.cmd == "get":
        return cmd_get(args.name)
    elif args.cmd == "build-index":
        return cmd_build_index()


if __name__ == "__main__":
    sys.exit(main())
