#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""image_search/slots.py — 从 PPTD .page 提取图片槽位 + 本地化回填。

PPTD 的 .page 是 YAML，但我们只需识别/改写 `src:` 字段，因此用"行级文本解析"
而非完整 YAML round-trip——这样保留原始注释/格式，且零 PyYAML 依赖。

槽位识别约定（见 reference/image-search.md）：
  - Image 元素：`src: "search:<query>"`（或 background/fill 的 ImageFill src）
  - 远端 URL（http/https）src：标记为 remote（引擎会 remote-asset-not-fetched 丢弃），
    可由本工具 --localize-remote 一并下载本地化。

提取字段：elementId / kind(image|background|fill) / query / bounds(w,h→横竖) / fit。
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

SRC_RE = re.compile(r'^(?P<indent>\s*)src:\s*(?P<q>["\']?)(?P<val>[^"\'\n#]+?)(?P=q)\s*(?:#.*)?$')
ELEMENT_ID_RE = re.compile(r'^\s*-?\s*elementId:\s*["\']?([^"\'\n#]+?)["\']?\s*$')
ELEMENT_TYPE_RE = re.compile(r'^\s*elementType:\s*["\']?([^"\'\n#]+?)["\']?\s*$')
BOUNDS_RE = re.compile(r'^\s*bounds:\s*\[?\s*([-\d.,\s]+?)\s*\]?\s*$')
FIT_RE = re.compile(r'^\s*fit:\s*\{?\s*mode:\s*([a-zA-Z]+)')

SEARCH_PREFIX = "search:"
REMOTE_RE = re.compile(r"^https?://", re.IGNORECASE)


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    return v


def parse_bounds_ratio(bounds: Optional[List[float]]) -> str:
    """bounds=[x,y,w,h] → landscape|portrait|any。"""
    try:
        if bounds and len(bounds) >= 4:
            w, h = float(bounds[2]), float(bounds[3])
            if h <= 0:
                return "any"
            r = w / h
            if r > 1.25:
                return "landscape"
            if r < 0.8:
                return "portrait"
    except Exception:  # noqa: BLE001
        pass
    return "any"


class Slot:
    __slots__ = ("page", "line_no", "kind", "element_id", "raw_src", "query",
                 "want", "fit", "bounds", "status", "local_path", "winner", "tried")

    def __init__(self, page: str, line_no: int, kind: str, element_id: str,
                 raw_src: str, want: str, fit: str, bounds: Optional[List[float]]):
        self.page = page                # 相对项目根的 page 路径
        self.line_no = line_no          # src 所在行（0 基）
        self.kind = kind                # image | background | fill
        self.element_id = element_id    # image 元素的 elementId（fill/background 可为空）
        self.raw_src = raw_src          # 原始 src 字符串（search:... 或 http...）
        self.query = raw_src[len(SEARCH_PREFIX):].strip() if raw_src.startswith(SEARCH_PREFIX) else ""
        self.want = want                # landscape|portrait|any
        self.fit = fit                  # cover|contain|fill|"" （未知）
        self.bounds = bounds
        self.status = "pending"         # pending|resolved|remote|failed
        self.local_path = ""            # 本地化后的 media/... 相对路径
        self.winner: Optional[Dict] = None
        self.tried: List[Dict] = []

    @property
    def is_search(self) -> bool:
        return self.raw_src.startswith(SEARCH_PREFIX)

    @property
    def is_remote(self) -> bool:
        return bool(REMOTE_RE.match(self.raw_src))

    def __repr__(self):  # noqa: D105
        return f"<Slot {self.page}:{self.line_no} {self.kind} {self.element_id} {self.raw_src[:40]!r}>"


def extract_slots(page_text: str, page_rel: str) -> List[Slot]:
    """行级扫描 .page 文本，抽出图片槽位。

    状态机跟踪最近的 elementId/elementType/bounds/fit，遇到 src: 行定槽。
    background: 块内的 image src 记 kind=background；elements 下 image 元素记 kind=image；
    其它 fill 里的 image src 记 kind=fill。
    """
    slots: List[Slot] = []
    cur_elem_id = ""
    cur_elem_type = ""
    cur_bounds: Optional[List[float]] = None
    cur_fit = ""
    in_background = False
    bg_indent = -1

    lines = page_text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())

        m = ELEMENT_ID_RE.match(line)
        if m:
            cur_elem_id = _unquote(m.group(1))
            cur_elem_type = ""
            cur_bounds = None
            cur_fit = ""
            in_background = False
            continue
        m = ELEMENT_TYPE_RE.match(line)
        if m:
            cur_elem_type = _unquote(m.group(1)).lower()
            continue
        m = BOUNDS_RE.match(line)
        if m:
            try:
                cur_bounds = [float(x) for x in m.group(1).split(",") if x.strip() != ""]
            except Exception:  # noqa: BLE001
                cur_bounds = None
            continue
        m = FIT_RE.match(line)
        if m:
            cur_fit = m.group(1).lower()
            continue
        if re.match(r"^\s*background:\s*$", line):
            in_background = True
            bg_indent = indent
            continue
        if in_background and indent <= bg_indent and line.strip() and not line.strip().startswith("src:"):
            # 离开 background 块
            if not line.strip().startswith(("type:", "color:", "gradient", "image")):
                in_background = False

        m = SRC_RE.match(line)
        if not m:
            continue
        val = _unquote(m.group("val")).strip()
        if not (val.startswith(SEARCH_PREFIX) or REMOTE_RE.match(val)):
            continue  # 本地 src 或 data: —— 不处理
        if in_background:
            kind = "background"
        elif cur_elem_type == "image":
            kind = "image"
        else:
            kind = "fill"
        want = parse_bounds_ratio(cur_bounds)
        slots.append(Slot(page_rel, i, kind, cur_elem_id, val, want, cur_fit, cur_bounds))
    return slots


def patch_src(page_text: str, line_no: int, old_src: str, new_src: str) -> str:
    """把指定行的 src 值替换为 new_src（保留引号风格与行尾注释）。"""
    lines = page_text.splitlines(keepends=True)
    if line_no >= len(lines):
        return page_text
    line = lines[line_no]
    m = SRC_RE.match(line.rstrip("\n"))
    if not m:
        return page_text
    quote = m.group("q") or '"'
    # 保留行尾注释
    tail = ""
    after = line[m.end("val") + (1 if m.group("q") else 0):]
    hash_at = after.find("#")
    if hash_at >= 0:
        tail = " " + after[hash_at:].rstrip("\n")
    nl = "\n" if line.endswith("\n") else ""
    new_line = f'{m.group("indent")}src: {quote}{new_src}{quote}{tail}{nl}'
    lines[line_no] = new_line
    return "".join(lines)
