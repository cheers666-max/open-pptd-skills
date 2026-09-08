#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_deck.py — deterministic hard-issue audit for PPTD projects.

Covers measurable failures only:
  - orphan-last-line (孤字): last line has ≤ threshold substantive chars
  - forbidden-line-start-punctuation: closing punctuation at line start
  - text-capacity-overflow: estimated text height exceeds box
  - unexpected-wrap: wrap:false but text wider than box
  - element-overflow-viewport: element bounds exceed slide dimensions
  - low-effective-image-resolution: image too small for its rendered size
  - missing-required-background: cover/final pages lack full-page background
  - unresolved-search-placeholder: leftover search: or remote http(s) src

Pure stdlib + PyYAML. Pillow is optional (image resolution check skips if missing).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None

try:
    from PIL import Image, UnidentifiedImageError
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


SCHEMA_VERSION = "open-pptd-validate/1.0"

# Text audit constants
TEXT_HORIZONTAL_SAFETY = 2.0
DEFAULT_ORPHAN_SUBSTANTIVE_LIMIT = 1
TITLE_ORPHAN_SUBSTANTIVE_LIMIT = 2
TITLE_ROLES = {"deck-title", "slide-title", "section-title"}
CLOSING_PUNCTUATION = set("，。！？；：、）》】〕］〉”’…,.!?;:)]}%")
OPENING_PUNCTUATION = set("（《【〔［〈“‘([{￥$")
TAG_RE = re.compile(r"<[^>]+>")
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
SEARCH_RE = re.compile(r"^search:", re.IGNORECASE)
REMOTE_RE = re.compile(r"^https?://", re.IGNORECASE)

# Anti-AI-slop banned phrases (merged from kimi-slides SKILL.md Content Guidelines)
# 只收真正的 AI 腔/套话，不收行业术语（术语本身不是问题，滥用才是）
BANNED_PHRASES_CN = [
    "不是.*而是",       # "不是X而是Y" 转折腔
    "闭环", "打通.*闭环", "形成闭环",
    "第.件事",          # "第一件事/第二件事"
    "弹药", "武器库",
    "组合拳",
    "颗粒度",
    "降维打击", "升维思考",
    "认知升级", "认知迭代", "认知觉醒",
    "赋能", "抓手",
    "顶层设计", "底层逻辑",
    "从0到1", "从1到N",
    "第二曲线",
    "生态化反",
    "飞轮效应", "增长飞轮",
    "全链路", "端到端",
    "一站式",
    "从.*到.*的闭环",
    "感知度", "心智占领",
    "品效合一",
    "私域流量", "公域流量",
    "护城河",
]

# English AI clichés (regex patterns)
BANNED_PHRASES_EN = [
    r"\bnot\s+\w+,\s*but\s+\w+\b",      # "not X, but Y"
    r"\bX\s+is\s+Y\b",
    r"\bclosed\s+loop\b",
    r"\bkey\s+takeaway\b",
    r"\bthe\s+\d+(?:st|nd|rd|th)\s+thing\b",
    r"\bN\s+battlefronts?\b",
    r"\bN\s+paths?\b",
    r"\bwall\s+clock\b",
    r"\bhands-on\s+practice\b",
    r"\bsecond-class\s+citizens?\b",
    r"\bpoison\s+pill\b",
    r"\ban\s+N-step\s+argument\b",
    r"\beverything\s+at\s+a\s+glance\b",
]

# Design pattern detection (checked at element level, not text)
# Card layout: many same-sized rounded rects arranged in a grid
CARD_LAYOUT_MIN_CARDS = 4  # ≥4 same-size roundRect shapes in a row/grid = suspicious
# AI rainbow scheme: red+purple+yellow+green all present on one page
AI_RAINBOW_COLORS = ["#FF0000", "#800080", "#FFFF00", "#008000"]

# Page types that require a full-page background image
BG_REQUIRED_TYPES = {"cover", "final"}
BG_MIN_COVERAGE = 0.30  # chapter pages need ≥ 30% area image


# ---------------------------------------------------------------------------
# YAML / JSON helpers
# ---------------------------------------------------------------------------

def load_structured(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required. Install with: pip install pyyaml")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected an object in {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Path / hash helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_project_path(project: Path, relative: Any) -> Optional[Path]:
    if not isinstance(relative, str) or not relative.strip():
        return None
    candidate = (project / relative).resolve()
    try:
        candidate.relative_to(project.resolve())
    except ValueError:
        return None
    return candidate


def discover_manifest(project: Path, explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        manifest = explicit.expanduser().resolve()
        if not manifest.is_file():
            raise RuntimeError(f"PPTD manifest does not exist: {manifest}")
        return manifest
    manifests = sorted(project.glob("*.pptd"))
    if len(manifests) != 1:
        raise RuntimeError(f"Expected one PPTD manifest in {project}, found {len(manifests)}")
    return manifests[0]


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def plain_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    source = BR_RE.sub("\n", value)
    source = re.sub(r"</(?:p|div|li|h[1-6])\s*>", "\n", source, flags=re.I).rstrip("\n")
    return html.unescape(TAG_RE.sub("", source)).replace("\r\n", "\n").replace("\r", "\n")


def glyph_em_width(character: str) -> float:
    """Estimate character width in em units (font-size multiplier)."""
    if character == "\t":
        return 1.12
    if character.isspace():
        return 0.28
    code = ord(character)
    if (
        0x2E80 <= code <= 0x9FFF
        or 0xAC00 <= code <= 0xD7AF
        or 0xF900 <= code <= 0xFAFF
        or 0xFF01 <= code <= 0xFF60
    ):
        return 1.0  # CJK
    if character.isdigit():
        return 0.56
    if "A" <= character <= "Z":
        return 0.64
    if "a" <= character <= "z":
        return 0.52
    if unicodedata.category(character).startswith("P"):
        return 0.32
    return 0.58


def text_width(text: str, font_size: float, letter_spacing: float = 0.0) -> float:
    if not text:
        return 0.0
    return sum(glyph_em_width(c) * font_size for c in text) + max(0, len(text) - 1) * letter_spacing


def wrap_paragraph(text: str, font_size: float, width: float, letter_spacing: float) -> List[str]:
    """Greedy word-wrap simulation (character-level for CJK)."""
    if not text:
        return [""]
    lines: List[str] = []
    current = ""
    current_width = 0.0
    for ch in text:
        ch_width = glyph_em_width(ch) * font_size
        spacing = letter_spacing if current else 0.0
        if current and current_width + spacing + ch_width > width + 1e-6:
            lines.append(current.rstrip())
            current = ch.lstrip() if ch.isspace() else ch
            current_width = text_width(current, font_size, letter_spacing)
        else:
            current += ch
            current_width += spacing + ch_width
    lines.append(current.rstrip())
    return lines


def substantive_characters(line: str) -> List[str]:
    """Return non-space, non-punctuation characters."""
    return [c for c in line if not c.isspace() and not unicodedata.category(c).startswith("P")]


def orphan_limit_for_role(role: Any) -> int:
    return TITLE_ORPHAN_SUBSTANTIVE_LIMIT if role in TITLE_ROLES else DEFAULT_ORPHAN_SUBSTANTIVE_LIMIT


def _line_pixels(value: Any, font_size: float) -> float:
    value = str(value).strip().lower()
    try:
        return float(value[:-2]) if value.endswith("px") else font_size * float(value)
    except ValueError:
        return font_size * 1.2


class _TextRuns(HTMLParser):
    """Estimate inline font/line-height runs; not a browser layout engine."""
    BLOCKS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self, font_size, line_height):
        super().__init__(convert_charrefs=True)
        self.stack = [("root", {"font-size": font_size, "line-height": line_height})]
        self.runs = []

    def newline(self, force=False):
        if force or (self.runs and not self.runs[-1][0].endswith("\n")):
            style = self.stack[-1][1]
            self.runs.append(("\n", style["font-size"], _line_pixels(style["line-height"], style["font-size"])))

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.newline(True)
            return
        if tag in self.BLOCKS:
            self.newline()
        style = dict(self.stack[-1][1])
        css = dict(attrs).get("style") or ""
        for declaration in css.split(";"):
            key, sep, value = declaration.partition(":")
            key, value = key.strip().lower(), value.strip().lower()
            if not sep:
                continue
            if key == "font-size":
                try:
                    if value.endswith("px") or re.fullmatch(r"[\d.]+", value):
                        style[key] = float(value.removesuffix("px"))
                    elif value.endswith("pt"):
                        style[key] = float(value[:-2]) * 4 / 3
                except ValueError:
                    pass
            elif key == "line-height":
                style[key] = value
        if tag not in {"img", "hr", "input", "wbr"}:
            self.stack.append((tag, style))

    def handle_endtag(self, tag):
        if tag in self.BLOCKS:
            self.newline()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not data.strip() and "\n" in data:
            return  # indentation between HTML blocks is not an extra paragraph
        style = self.stack[-1][1]
        self.runs.append((data, style["font-size"], _line_pixels(style["line-height"], style["font-size"])))


def _estimated_lines(text, font_size, line_height, width, wrap, letter_spacing):
    if TAG_RE.search(text):
        parser = _TextRuns(font_size, line_height)
        parser.feed(text)
        runs = parser.runs
        while runs and runs[-1][0] == "\n":
            runs.pop()
    else:
        runs = [(plain_text(text), font_size, _line_pixels(line_height, font_size))]
    lines, heights, widths, auto = [], [], [], []
    current, used, height, wrapped = "", 0.0, 0.0, False
    for segment, font, line_px in runs:
        for char in segment:
            if char == "\n":
                lines.append(current.rstrip()); heights.append(height or line_px); widths.append(used); auto.append(wrapped)
                current, used, height, wrapped = "", 0.0, 0.0, False
                continue
            needed = glyph_em_width(char) * font + (letter_spacing if current else 0)
            if wrap and current and used + needed > max(width, .01):
                lines.append(current.rstrip()); heights.append(height); widths.append(used); auto.append(True)
                current, used, height, wrapped = "", 0.0, 0.0, True
                if char.isspace():
                    continue
                needed = glyph_em_width(char) * font
            current += char
            used += needed
            height = max(height, font, line_px)
    lines.append(current.rstrip()); heights.append(height or _line_pixels(line_height, font_size)); widths.append(used); auto.append(wrapped)
    return lines, heights, widths, auto


def layout_text(
    text: str,
    font_size: float,
    line_height: float,
    box_width: float,
    box_height: float,
    *,
    wrap: bool = True,
    letter_spacing: float = 0.0,
    orphan_limit: int = DEFAULT_ORPHAN_SUBSTANTIVE_LIMIT,
) -> Dict[str, Any]:
    """Simulate text layout and detect orphans / overflow."""
    lines, heights, widths, auto_wrapped = _estimated_lines(text, font_size, line_height, box_width, wrap, letter_spacing)
    line_count = max(1, len(lines))
    estimated_height = sum(heights)
    width_overflow = not wrap and any(width > box_width + 0.5 for width in widths)
    height_overflow = estimated_height > box_height + 0.5

    last_line = lines[-1] if lines else ""
    last_substantive = substantive_characters(last_line)
    orphan = bool(auto_wrapped and auto_wrapped[-1] and len(last_substantive) <= orphan_limit)

    punctuation_starts = [
        i + 1
        for i, line in enumerate(lines)
        if i > 0 and line.lstrip() and line.lstrip()[0] in CLOSING_PUNCTUATION and auto_wrapped[i]
    ]

    return {
        "lines": lines,
        "lineCount": line_count,
        "estimatedHeight": round(estimated_height, 3),
        "heightOverflow": height_overflow,
        "widthOverflow": width_overflow,
        "overflow": height_overflow or width_overflow,
        "orphan": orphan,
        "lastLine": last_line,
        "lastLineSubstantiveCount": len(last_substantive),
        "orphanThreshold": orphan_limit,
        "lineStartPunctuation": punctuation_starts,
    }


# ---------------------------------------------------------------------------
# Element bounds helper
# ---------------------------------------------------------------------------

def valid_bounds(element: dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    bounds = element.get("bounds")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in bounds)
    ):
        return None
    x, y, w, h = (float(v) for v in bounds)
    if w <= 0 or h <= 0:
        return None
    return x, y, w, h


# ---------------------------------------------------------------------------
# Text element audit
# ---------------------------------------------------------------------------

def text_issues(element: dict[str, Any], page_number: int, page_ref: str,
                slide_w: float, slide_h: float, *, theme: Optional[dict] = None) -> List[dict[str, Any]]:
    if element.get("elementType") != "text":
        return []
    bounds = valid_bounds(element)
    content = element.get("content") if isinstance(element.get("content"), dict) else {}
    style = content.get("style")
    if isinstance(style, str) and style.startswith("$"):
        base = (theme or {}).get("textStyles", {}).get(style[1:], {})
        content = {**base, **content}
    text = plain_text(content.get("text"))
    if bounds is None or not text:
        return []

    font_size = float(content.get("fontSize", 18) or 18)
    line_height = (f"{content['lineHeightPx']}px" if content.get("lineHeightPx") is not None
                   else content.get("lineHeight", 1))
    margin_top = float(content.get("marginTop", 0) or 0)
    letter_spacing = float(content.get("letterSpacing", 0) or 0)
    wrap = content.get("wrap", True) is not False
    role = element.get("role")
    orphan_limit = orphan_limit_for_role(role)

    # Viewport overflow check
    x, y, w, h = bounds
    viewport_issues = []
    if x < 0 or y < 0 or x + w > slide_w + 0.5 or y + h > slide_h + 0.5:
        viewport_issues.append({
            "code": "element-overflow-viewport",
            "pageNumber": page_number,
            "pageRef": page_ref,
            "elementId": element.get("elementId"),
            "role": role,
            "bounds": [round(v, 3) for v in bounds],
            "slideSize": [slide_w, slide_h],
            "repairability": "geometry",
        })

    is_intentional_vertical = h >= w * 3 and role in {"micro", "caption", "image-label"}
    horizontal_safety = (
        TEXT_HORIZONTAL_SAFETY
        if wrap and not is_intentional_vertical and role in {"body", "body-compact"}
        else 0.0
    )
    effective_width = max(font_size, w - horizontal_safety)

    layout = layout_text(
        content.get("text", ""), font_size, line_height, effective_width, h - margin_top,
        wrap=wrap, letter_spacing=letter_spacing, orphan_limit=orphan_limit,
    )

    common = {
        "pageNumber": page_number,
        "pageRef": page_ref,
        "elementId": element.get("elementId"),
        "role": role,
        "bounds": [round(v, 3) for v in bounds],
        "fontSize": font_size,
        "lineHeight": line_height,
        "estimatedLines": layout["lines"],
        "measurement": "estimated",
    }
    issues: List[dict[str, Any]] = list(viewport_issues)

    if layout["heightOverflow"]:
        issues.append({
            **common,
            "code": "text-capacity-overflow",
            "estimatedHeight": layout["estimatedHeight"] + margin_top,
            "availableHeight": h,
            "repairability": "text-or-geometry",
        })
    if layout["widthOverflow"]:
        issues.append({
            **common,
            "code": "unexpected-wrap",
            "requiredWidth": round(text_width(text, font_size, letter_spacing), 3),
            "repairability": "text-or-geometry",
        })
    if layout["orphan"] and not is_intentional_vertical:
        issues.append({
            **common,
            "code": "orphan-last-line",
            "lastLine": layout["lastLine"],
            "orphanThreshold": layout["orphanThreshold"],
            "repairability": "text",
        })
    for line_number in layout["lineStartPunctuation"]:
        issues.append({
            **common,
            "code": "forbidden-line-start-punctuation",
            "lineNumber": line_number,
            "line": layout["lines"][line_number - 1],
            "repairability": "text",
        })
    return issues


# ---------------------------------------------------------------------------
# Image element audit
# ---------------------------------------------------------------------------

def image_resolution_issue(
    project: Path,
    element: dict[str, Any],
    page_number: int,
    page_ref: str,
    slide_size: Tuple[float, float],
    target_width: int,
    min_image_scale: float,
) -> Optional[dict[str, Any]]:
    if element.get("elementType") != "image":
        return None
    bounds = valid_bounds(element)
    source = safe_project_path(project, element.get("src"))
    if bounds is None or source is None or not source.is_file():
        return None
    if not HAS_PIL:
        return None
    try:
        with Image.open(source) as img:
            source_width, source_height = img.size
    except (OSError, UnidentifiedImageError):
        return None

    target_scale = target_width / slide_size[0]
    target_box_width = bounds[2] * target_scale
    target_box_height = bounds[3] * target_scale
    fit = element.get("fit") if isinstance(element.get("fit"), dict) else {}
    mode = fit.get("mode", "cover")
    if mode == "contain":
        render_scale = min(target_box_width / source_width, target_box_height / source_height)
    else:
        render_scale = max(target_box_width / source_width, target_box_height / source_height)
    effective_scale = math.inf if render_scale <= 0 else 1.0 / render_scale
    if effective_scale + 1e-9 >= min_image_scale:
        return None
    return {
        "code": "low-effective-image-resolution",
        "pageNumber": page_number,
        "pageRef": page_ref,
        "elementId": element.get("elementId"),
        "src": str(source.relative_to(project)),
        "sourcePixels": [source_width, source_height],
        "targetPixels": [round(target_box_width), round(target_box_height)],
        "fitMode": mode,
        "effectiveSourcePixelsPerRenderedPixel": round(effective_scale, 4),
        "minimum": min_image_scale,
        "repairability": "asset-replacement",
    }


# ---------------------------------------------------------------------------
# Page-level audit (background constraints, unresolved placeholders)
# ---------------------------------------------------------------------------

def page_background_issues(page: dict[str, Any], page_number: int, page_ref: str,
                           slide_w: float, slide_h: float) -> List[dict[str, Any]]:
    """Check cover/final pages have full-page background; chapter has ≥ 30% image."""
    issues: List[dict[str, Any]] = []
    page_type = page.get("pageType", "")
    elements = page.get("elements", [])
    if not isinstance(elements, list):
        return issues

    # Find background image (either background.type=image or full-page image element)
    has_full_bg = False
    max_image_area = 0.0

    # Check background block
    bg = page.get("background", {})
    if isinstance(bg, dict) and bg.get("type") == "image":
        bg_src = bg.get("src", "")
        if bg_src and not SEARCH_RE.match(bg_src):
            has_full_bg = True

    # Check image elements
    for el in elements:
        if not isinstance(el, dict):
            continue
        if el.get("elementType") != "image":
            continue
        bounds = valid_bounds(el)
        if bounds is None:
            continue
        x, y, w, h = bounds
        area = w * h
        max_image_area = max(max_image_area, area)
        # Full-page: covers ≥ 95% of slide and starts near origin
        if area >= slide_w * slide_h * 0.95 and x <= 1 and y <= 1:
            src = el.get("src", "")
            if src and not SEARCH_RE.match(src):
                has_full_bg = True

    slide_area = slide_w * slide_h

    if page_type in BG_REQUIRED_TYPES and not has_full_bg:
        issues.append({
            "code": "missing-required-background",
            "pageNumber": page_number,
            "pageRef": page_ref,
            "pageType": page_type,
            "detail": f"{page_type} page must have a full-page background image",
            "repairability": "add-background-image",
        })
    if page_type == "chapter" and not has_full_bg and max_image_area < slide_area * BG_MIN_COVERAGE:
        issues.append({
            "code": "missing-required-background",
            "pageNumber": page_number,
            "pageRef": page_ref,
            "pageType": page_type,
            "detail": f"chapter page must have background or side image covering ≥ {int(BG_MIN_COVERAGE*100)}% area",
            "repairability": "add-background-image",
        })
    return issues


def unresolved_src_issues(page: dict[str, Any], page_number: int, page_ref: str) -> List[dict[str, Any]]:
    """Detect leftover search: placeholders or remote http(s) URLs."""
    issues: List[dict[str, Any]] = []
    elements = page.get("elements", [])
    if not isinstance(elements, list):
        return issues

    def check_src(src: str, element_id: str):
        if SEARCH_RE.match(src):
            issues.append({
                "code": "unresolved-search-placeholder",
                "pageNumber": page_number,
                "pageRef": page_ref,
                "elementId": element_id,
                "src": src[:80],
                "repairability": "run-image-search",
            })
        elif REMOTE_RE.match(src):
            issues.append({
                "code": "unresolved-remote-url",
                "pageNumber": page_number,
                "pageRef": page_ref,
                "elementId": element_id,
                "src": src[:80],
                "repairability": "localize-remote",
            })

    for el in elements:
        if not isinstance(el, dict):
            continue
        src = el.get("src", "")
        if isinstance(src, str) and src:
            check_src(src, el.get("elementId", ""))
        # Also check background/fill image src
        for key in ("background", "fill"):
            block = el.get(key, {})
            if isinstance(block, dict):
                block_src = block.get("src", "")
                if isinstance(block_src, str) and block_src:
                    check_src(block_src, el.get("elementId", ""))

    # Check page-level background
    bg = page.get("background", {})
    if isinstance(bg, dict):
        bg_src = bg.get("src", "")
        if isinstance(bg_src, str) and bg_src:
            check_src(bg_src, "page-background")
    return issues


# ---------------------------------------------------------------------------
# Anti-AI-slop detection
# ---------------------------------------------------------------------------

def anti_slop_text_issues(page: dict[str, Any], page_number: int, page_ref: str) -> List[dict[str, Any]]:
    """Scan all text content on a page for banned AI-slop phrases."""
    issues: List[dict[str, Any]] = []
    elements = page.get("elements", [])
    if not isinstance(elements, list):
        return issues

    cn_patterns = [re.compile(p) for p in BANNED_PHRASES_CN]
    en_patterns = [re.compile(p, re.IGNORECASE) for p in BANNED_PHRASES_EN]

    def scan_text(text: str, element_id: str):
        plain = plain_text(text)
        if not plain:
            return
        for pat in cn_patterns:
            m = pat.search(plain)
            if m:
                issues.append({
                    "code": "anti-slop-phrase",
                    "pageNumber": page_number,
                    "pageRef": page_ref,
                    "elementId": element_id,
                    "matched": m.group(0),
                    "detail": f"AI-cliché phrase detected: '{m.group(0)}'",
                    "repairability": "rewrite-text",
                })
                break  # one match per element is enough
        for pat in en_patterns:
            m = pat.search(plain)
            if m:
                issues.append({
                    "code": "anti-slop-phrase",
                    "pageNumber": page_number,
                    "pageRef": page_ref,
                    "elementId": element_id,
                    "matched": m.group(0),
                    "detail": f"AI-cliché phrase detected: '{m.group(0)}'",
                    "repairability": "rewrite-text",
                })
                break

    for el in elements:
        if not isinstance(el, dict):
            continue
        if el.get("elementType") != "text":
            continue
        content = el.get("content", {})
        if not isinstance(content, dict):
            continue
        text = content.get("text", "")
        if isinstance(text, str) and text:
            scan_text(text, el.get("elementId", ""))
    return issues


INTERNAL_TOKEN_PATTERNS = [
    # Internal artifact names and workflow words that must never reach audience-facing text.
    r"images_report\.json", r"DESIGN_CONTEXT", r"downloads\.json", r"images_manifest",
    r"材料包", r"资料包", r"待与.{0,12}核对后再使用", r"待核对后再使用", r"主写手",
]


DEFAULT_MAX_PAGE_CHARS = 360
DENSITY_EXEMPT_PAGE_TYPES = {"cover", "final", "chapter", "toc", "section", "closing", "ending"}


def page_text_chars(page: dict[str, Any]) -> int:
    """Plain-text character count of all text elements on a page (speaker notes excluded)."""
    total = 0
    for el in page.get("elements", []) or []:
        if isinstance(el, dict) and el.get("elementType") == "text":
            content = el.get("content", {})
            text = content.get("text", "") if isinstance(content, dict) else ""
            if isinstance(text, str):
                total += len(re.sub(r"\s+", "", plain_text(text)))
    return total


def text_density_advisory(page: dict[str, Any], page_number: int, page_ref: str,
                          max_chars: int = DEFAULT_MAX_PAGE_CHARS) -> Optional[dict[str, Any]]:
    """Advisory (never blocks): a content page carrying more text than an audience can read on screen.

    Threshold is a heuristic from the 2026-09 twenty-deck evaluation: judged-dense pages averaged
    above ~360 characters; tables and evidence pages legitimately exceed it, so this is advice only.
    """
    if str(page.get("pageType", "")).lower() in DENSITY_EXEMPT_PAGE_TYPES:
        return None
    chars = page_text_chars(page)
    if chars <= max_chars:
        return None
    return {
        "code": "text-density",
        "pageNumber": page_number,
        "pageRef": page_ref,
        "chars": chars,
        "maxChars": max_chars,
        "detail": f"{chars} text characters on one page (advice threshold {max_chars}); consider splitting or moving detail to notes",
        "repairability": "split-page",
    }


MIN_EMPTY_BAND_RATIO = 0.25


def empty_band_issue(page: dict[str, Any], page_number: int, page_ref: str,
                     slide_height: float,
                     min_ratio: float = MIN_EMPTY_BAND_RATIO) -> Optional[dict[str, Any]]:
    """A full-width horizontal band between elements that nothing covers — the signature of a
    body block that was never written into the page (a layout helper whose return value the
    authoring script forgot to append), which renders as a title, a lead-in and a footer around
    a hole.

    Only bands *between* elements count; top and bottom margins are design. A page-filling
    element (a full-bleed photo or backdrop) covers every band, so those pages never match.

    Threshold from 477 pages of the 2026-09 evaluations: the airiest page nobody flagged spans
    0.228 of the slide height, the one page whose body was silently dropped spans 0.537.
    """
    spans: List[Tuple[float, float]] = []
    for element in page.get("elements", []) or []:
        if not isinstance(element, dict):
            continue
        box = valid_bounds(element)
        if box is None:
            continue
        _, y, width, height = box
        spans.append((y, y + height))
    if len(spans) < 2:
        return None

    spans.sort()
    widest = 0.0
    band: Optional[Tuple[float, float]] = None
    covered_to = spans[0][1]
    for start, end in spans[1:]:
        if start > covered_to and start - covered_to > widest:
            widest, band = start - covered_to, (covered_to, start)
        covered_to = max(covered_to, end)

    if band is None or slide_height <= 0 or widest / slide_height < min_ratio:
        return None
    return {
        "code": "empty-body-band",
        "pageNumber": page_number,
        "pageRef": page_ref,
        "bandTop": round(band[0], 1),
        "bandHeight": round(widest, 1),
        "bandRatio": round(widest / slide_height, 3),
        "detail": (f"nothing is placed between y={band[0]:.0f} and y={band[1]:.0f} "
                   f"({widest / slide_height:.0%} of the slide height); the page body looks missing"),
        "repairability": "upstream-layout",
    }


VALID_H_ALIGN = {"left", "center", "right", "justify", "distributed"}
VALID_V_ALIGN = {"top", "middle", "bottom"}
# Mirrors normalizeAlign() in vendor/open-ppt-engine/adapters/pptd.mjs and viewer.html: the
# renderers flatten nested pairs, map synonyms (start/end, center↔middle) and read numbers as
# positions, so only values they cannot resolve are reported.
H_ALIGN_SYNONYMS = {"start": "left", "end": "right", "middle": "center"}
V_ALIGN_SYNONYMS = {"start": "top", "end": "bottom", "center": "middle"}


def _flatten_align(value: Any) -> List[Any]:
    """Flatten the shapes authors produce: "right", [h, v], [[h, v]], [0.5, 0.5]."""
    if value is None:
        return []
    if not isinstance(value, list):
        return [value]
    flat: List[Any] = []
    for item in value:
        flat.extend(item if isinstance(item, list) else [item])
    return flat


def _align_resolves(word: Any, valid: set, synonyms: Dict[str, str]) -> bool:
    if isinstance(word, bool):
        return False
    if isinstance(word, (int, float)):
        return True  # renderers read a number as a position on the axis
    if not isinstance(word, str):
        return False
    key = word.lower()
    return key in valid or key in synonyms




def element_schema_issues(page: dict[str, Any], page_number: int, page_ref: str) -> List[dict[str, Any]]:
    """Structural mistakes renderers silently degrade: nested/invalid align pairs and line points
    outside their viewBox (points are viewBox units, not percentages)."""
    issues: List[dict[str, Any]] = []
    for el in page.get("elements", []) or []:
        if not isinstance(el, dict):
            continue
        eid = el.get("elementId", "")
        content = el.get("content")
        if isinstance(content, dict) and "align" in content:
            align = content.get("align")
            flat = _flatten_align(align)
            resolves = (len(flat) <= 2
                        and (not flat or _align_resolves(flat[0], VALID_H_ALIGN, H_ALIGN_SYNONYMS))
                        and (len(flat) < 2 or _align_resolves(flat[1], VALID_V_ALIGN, V_ALIGN_SYNONYMS)))
            canonical = (isinstance(align, list) and 1 <= len(align) <= 2
                         and all(isinstance(a, str) for a in align)
                         and align[0] in VALID_H_ALIGN
                         and (len(align) == 1 or align[1] in VALID_V_ALIGN))
            if not resolves:
                issues.append({
                    "code": "invalid-align",
                    "pageNumber": page_number, "pageRef": page_ref, "elementId": eid,
                    "value": str(align)[:60],
                    "detail": "the renderers cannot read this align value and fall back to left/top, so text spills out of its shape; use a horizontal word and an optional vertical word",
                    "repairability": "text",
                })
            elif not canonical:
                issues.append({
                    "code": "non-canonical-align",
                    "pageNumber": page_number, "pageRef": page_ref, "elementId": eid,
                    "value": str(align)[:60],
                    "detail": "align renders correctly but is not written as a flat [h, v] pair of words; prefer [center, middle] over nested lists, numbers or synonyms",
                    "repairability": "style",
                })
        if el.get("elementType") == "line" and el.get("points") and isinstance(el.get("viewBox"), list) and len(el["viewBox"]) >= 2:
            try:
                vw, vh = float(el["viewBox"][0]), float(el["viewBox"][1])
                pts = [tuple(float(v) for v in pair.split(",")) for pair in str(el["points"]).split()]
            except (TypeError, ValueError):
                continue
            if any(x < -0.5 or y < -0.5 or x > vw + 0.5 or y > vh + 0.5 for x, y in pts):
                issues.append({
                    "code": "line-points-outside-viewbox",
                    "pageNumber": page_number, "pageRef": page_ref, "elementId": eid,
                    "viewBox": el["viewBox"][:2], "points": str(el["points"])[:60],
                    "detail": "line points are viewBox units, not percentages; points beyond the viewBox draw far outside the element bounds and cross other content",
                    "repairability": "geometry",
                })
    return issues


def internal_token_leak_issues(page: dict[str, Any], page_number: int, page_ref: str) -> List[dict[str, Any]]:
    """Audience-facing text must not carry internal artifact names or workflow vocabulary.

    Speaker notes are exempt: they are private by design.
    """
    issues: List[dict[str, Any]] = []
    elements = page.get("elements", [])
    if not isinstance(elements, list):
        return issues
    patterns = [re.compile(pat) for pat in INTERNAL_TOKEN_PATTERNS]
    for el in elements:
        if not isinstance(el, dict) or el.get("elementType") != "text":
            continue
        content = el.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else ""
        plain = plain_text(text) if isinstance(text, str) else ""
        if not plain:
            continue
        for pat in patterns:
            m = pat.search(plain)
            if m:
                issues.append({
                    "code": "internal-token-leak",
                    "pageNumber": page_number,
                    "pageRef": page_ref,
                    "elementId": el.get("elementId", ""),
                    "matched": m.group(0),
                    "detail": f"Internal artifact/workflow token in audience-facing text: '{m.group(0)}'",
                    "repairability": "rewrite-text",
                })
                break
    return issues


def _page_image_sources(page: dict[str, Any]) -> List[str]:
    sources: List[str] = []
    bg = page.get("background", {})
    if isinstance(bg, dict) and isinstance(bg.get("src"), str) and bg.get("src"):
        sources.append(bg["src"])
    for el in page.get("elements", []) or []:
        if isinstance(el, dict) and el.get("elementType") == "image" and isinstance(el.get("src"), str) and el["src"]:
            sources.append(el["src"])
    return sources


def duplicate_image_issues(pages: List[Tuple[int, str, dict[str, Any]]]) -> List[dict[str, Any]]:
    """Deck-wide image uniqueness: the same media file on more than one page.

    A cover/closing pair reusing one image is reported as repairability 'style' (acceptable with a
    different crop or overlay); any other repeat is 'asset-replacement'.
    """
    usage: Dict[str, List[int]] = {}
    for page_number, _ref, page in pages:
        for src in set(_page_image_sources(page)):
            if src.startswith(("search:", "http://", "https://")):
                continue
            usage.setdefault(src, []).append(page_number)
    issues: List[dict[str, Any]] = []
    last = max((n for n, _r, _p in pages), default=0)
    for src, numbers in sorted(usage.items()):
        if len(numbers) < 2:
            continue
        cover_closing = sorted(numbers) == [1, last] and last > 1
        issues.append({
            "code": "duplicate-image",
            "pageNumber": numbers[0],
            "pageRef": next(r for n, r, _p in pages if n == numbers[0]),
            "src": src[:80],
            "pages": numbers,
            "detail": f"Image used on pages {numbers}" + (" (cover/closing pair: vary crop or overlay)" if cover_closing else ""),
            "repairability": "style" if cover_closing else "asset-replacement",
        })
    return issues


def anti_slop_design_issues(page: dict[str, Any], page_number: int, page_ref: str) -> List[dict[str, Any]]:
    """Detect AI-style design patterns: card layouts, rainbow color schemes."""
    issues: List[dict[str, Any]] = []
    elements = page.get("elements", [])
    if not isinstance(elements, list):
        return issues

    # --- Card layout detection: ≥ N same-size roundRect shapes ---
    round_rects: List[dict[str, Any]] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        if el.get("elementType") != "shape":
            continue
        shape_name = el.get("shape", "") or el.get("shapeName", "")
        if shape_name in ("roundRect", "round1Rect", "round2SameRect", "round2DiagRect"):
            bounds = valid_bounds(el)
            if bounds is not None:
                round_rects.append({"elementId": el.get("elementId", ""), "bounds": bounds})

    if len(round_rects) >= CARD_LAYOUT_MIN_CARDS:
        # Check if they are roughly the same size (tolerance ±15%)
        sizes = [(b[2], b[3]) for _, b in [(r["elementId"], r["bounds"]) for r in round_rects]]
        avg_w = sum(s[0] for s in sizes) / len(sizes)
        avg_h = sum(s[1] for s in sizes) / len(sizes)
        similar = [s for s in sizes if abs(s[0] - avg_w) / max(avg_w, 1) < 0.15
                   and abs(s[1] - avg_h) / max(avg_h, 1) < 0.15]
        if len(similar) >= CARD_LAYOUT_MIN_CARDS:
            issues.append({
                "code": "anti-slop-card-layout",
                "pageNumber": page_number,
                "pageRef": page_ref,
                "detail": f"{len(similar)} same-size rounded rectangles form a card wall; "
                          f"consider using lines/whitespace/typography instead",
                "repairability": "redesign-layout",
            })

    # --- AI rainbow scheme detection: red+purple+yellow+green all on one page ---
    colors_on_page: set[str] = set()
    for el in elements:
        if not isinstance(el, dict):
            continue
        # Collect all color values from the element (fill, border, text color, etc.)
        for key in ("fill", "border", "line"):
            block = el.get(key, {})
            if isinstance(block, dict):
                c = block.get("color", "")
                if isinstance(c, str) and c:
                    colors_on_page.add(c.upper().lstrip("#"))
        content = el.get("content", {})
        if isinstance(content, dict):
            c = content.get("color", "")
            if isinstance(c, str) and c:
                colors_on_page.add(c.upper().lstrip("#"))

    rainbow_hits = 0
    for rc in AI_RAINBOW_COLORS:
        rc_norm = rc.lstrip("#").upper()
        # Fuzzy match: same hue family (rough hex prefix match)
        for c in colors_on_page:
            if len(c) >= 6 and c[:2] == rc_norm[:2]:
                rainbow_hits += 1
                break

    if rainbow_hits >= 4:
        issues.append({
            "code": "anti-slop-rainbow-scheme",
            "pageNumber": page_number,
            "pageRef": page_ref,
            "detail": "Red + purple + yellow + green all detected on one page (AI rainbow scheme); "
                      "use a single primary color with a neutral ladder instead",
            "repairability": "recolor-page",
        })

    return issues


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------

def gradient_issues(page: dict, page_number: int, page_ref: str) -> List[dict[str, Any]]:
    """Reject malformed native gradients that otherwise silently become black fills."""
    issues, visited = [], set()

    def visit(value, location, element_id=None):
        if not isinstance(value, (dict, list)) or id(value) in visited:
            return
        visited.add(id(value))
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{location}/{index}", element_id)
            return
        element_id = value.get("elementId", element_id)
        if value.get("type") == "gradient":
            stops = value.get("stops")
            valid = isinstance(stops, list) and len(stops) >= 2 and all(
                isinstance(stop, dict) and isinstance(stop.get("position"), (int, float))
                and not isinstance(stop.get("position"), bool) and 0 <= stop["position"] <= 1
                and isinstance(stop.get("color"), str) and bool(stop["color"])
                for stop in stops)
            if not valid:
                issues.append(dict(code="invalid-gradient", pageNumber=page_number, pageRef=page_ref,
                    elementId=element_id, location=location, repairability="format",
                    message="Gradient requires at least two top-level stops with position [0,1] and color; see PPTD Fill."))
        for key, item in value.items():
            visit(item, f"{location}/{key}", element_id)

    visit(page, "")
    return issues

def audit_project(
    project: Path,
    manifest_path: Optional[Path] = None,
    *,
    target_width: int = 1280,
    min_image_scale: float = 0.6,
    max_page_chars: int = DEFAULT_MAX_PAGE_CHARS,
) -> dict[str, Any]:
    project = project.expanduser().resolve()
    manifest_path = discover_manifest(project, manifest_path)
    manifest = load_structured(manifest_path)
    size = manifest.get("size", [960, 540])
    if not isinstance(size, list) or len(size) != 2 or any(not isinstance(v, (int, float)) for v in size):
        raise RuntimeError(f"PPTD manifest size is invalid: {manifest_path}")
    slide_size = (float(size[0]), float(size[1]))
    page_refs = manifest.get("pages")
    if not isinstance(page_refs, list) or not page_refs:
        raise RuntimeError(f"PPTD manifest has no pages: {manifest_path}")

    issues: List[dict[str, Any]] = []
    page_hashes: List[dict[str, Any]] = []
    loaded_pages: List[Tuple[int, str, dict[str, Any]]] = []
    advisories: List[dict[str, Any]] = []
    checked_text = 0
    checked_images = 0

    for page_number, page_ref in enumerate(page_refs, start=1):
        page_path = safe_project_path(project, page_ref)
        if page_path is None or not page_path.is_file():
            issues.append({
                "code": "pptd-page-missing",
                "pageNumber": page_number,
                "pageRef": page_ref,
                "repairability": "upstream-layout",
            })
            continue
        page_hashes.append({"pageNumber": page_number, "pageRef": page_ref, "sha256": sha256_file(page_path)})
        page = load_structured(page_path)
        loaded_pages.append((page_number, str(page_ref), page))

        # Page-level checks
        issues.extend(gradient_issues(page, page_number, str(page_ref)))
        issues.extend(page_background_issues(page, page_number, str(page_ref), slide_size[0], slide_size[1]))
        issues.extend(unresolved_src_issues(page, page_number, str(page_ref)))
        issues.extend(anti_slop_text_issues(page, page_number, str(page_ref)))
        issues.extend(internal_token_leak_issues(page, page_number, str(page_ref)))
        for schema_issue in element_schema_issues(page, page_number, str(page_ref)):
            (advisories if schema_issue["code"] == "non-canonical-align" else issues).append(schema_issue)
        band = empty_band_issue(page, page_number, str(page_ref), slide_size[1])
        if band is not None:
            issues.append(band)
        density = text_density_advisory(page, page_number, str(page_ref), max_page_chars)
        if density is not None:
            advisories.append(density)
        issues.extend(anti_slop_design_issues(page, page_number, str(page_ref)))

        for element in page.get("elements", []):
            if not isinstance(element, dict):
                continue
            if element.get("elementType") == "text":
                checked_text += 1
                issues.extend(text_issues(element, page_number, str(page_ref), slide_size[0], slide_size[1],
                                          theme=manifest.get("theme", {})))
            elif element.get("elementType") == "image":
                checked_images += 1
                issue = image_resolution_issue(
                    project, element, page_number, str(page_ref),
                    slide_size, target_width, min_image_scale,
                )
                if issue is not None:
                    issues.append(issue)

    # Deck-level checks: content-page image reuse blocks; a cover/closing pair is advice only.
    for dup in duplicate_image_issues(loaded_pages):
        (advisories if dup["repairability"] == "style" else issues).append(dup)

    advisory_counts: Dict[str, int] = {}
    for advisory in advisories:
        advisory_counts[advisory["code"]] = advisory_counts.get(advisory["code"], 0) + 1
    issue_counts: Dict[str, int] = {}
    for issue in issues:
        issue_counts[issue["code"]] = issue_counts.get(issue["code"], 0) + 1

    return {
        "schemaVersion": SCHEMA_VERSION,
        "valid": not issues,
        "manifestPath": str(manifest_path.relative_to(project)),
        "manifestSha256": sha256_file(manifest_path),
        "pageCount": len(page_refs),
        "pageHashes": page_hashes,
        "checkedTextElements": checked_text,
        "checkedImageElements": checked_images,
        "targetRenderWidth": target_width,
        "minimumImageScale": min_image_scale,
        "issueCount": len(issues),
        "issueCounts": issue_counts,
        "issues": issues,
        "advisoryCount": len(advisories),
        "advisoryCounts": advisory_counts,
        "advisories": advisories,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path, help="Path to PPTD project directory")
    parser.add_argument("--manifest", type=Path, help="Explicit .pptd manifest path")
    parser.add_argument("--target-width", type=int, default=1280, help="Expected rendered width for image scale check")
    parser.add_argument("--min-image-scale", type=float, default=0.6, help="Minimum effective source-pixels-per-rendered-pixel")
    parser.add_argument("--max-page-chars", type=int, default=DEFAULT_MAX_PAGE_CHARS,
                        help=f"Advisory text-density threshold per content page (default {DEFAULT_MAX_PAGE_CHARS}); advisories never affect validity")
    parser.add_argument("--output", type=Path, help="Output JSON path (default: <project>/validate-report.json)")
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    project = args.project.expanduser().resolve()
    report = audit_project(
        project,
        args.manifest,
        target_width=args.target_width,
        min_image_scale=args.min_image_scale,
        max_page_chars=args.max_page_chars,
    )
    output = args.output.expanduser().resolve() if args.output else project / "validate-report.json"
    write_json(output, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report["valid"] else "FAIL"
        print(f"validate_deck: {status} ({report['issueCount']} issues)")
        if report["issueCounts"]:
            for code, count in sorted(report["issueCounts"].items()):
                print(f"  {code}: {count}")
        print(output)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(2)
