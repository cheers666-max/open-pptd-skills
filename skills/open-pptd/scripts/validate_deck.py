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
    clean = plain_text(text)
    paragraphs = clean.split("\n")
    lines: List[str] = []
    auto_wrapped: List[bool] = []
    for para in paragraphs:
        if wrap:
            wrapped = wrap_paragraph(para, font_size, max(box_width, 0.01), letter_spacing)
        else:
            wrapped = [para]
        lines.extend(wrapped)
        auto_wrapped.extend([len(wrapped) > 1] * len(wrapped))

    line_count = max(1, len(lines))
    estimated_height = line_count * font_size * line_height
    width_overflow = not wrap and any(text_width(line, font_size, letter_spacing) > box_width + 0.5 for line in lines)
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
                slide_w: float, slide_h: float) -> List[dict[str, Any]]:
    if element.get("elementType") != "text":
        return []
    bounds = valid_bounds(element)
    content = element.get("content") if isinstance(element.get("content"), dict) else {}
    text = plain_text(content.get("text"))
    if bounds is None or not text:
        return []

    font_size = float(content.get("fontSize", 16) or 16)
    line_height = float(content.get("lineHeight", 1.2) or 1.2)
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
        text, font_size, line_height, effective_width, h,
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
    }
    issues: List[dict[str, Any]] = list(viewport_issues)

    if layout["heightOverflow"]:
        issues.append({
            **common,
            "code": "text-capacity-overflow",
            "estimatedHeight": layout["estimatedHeight"],
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

def audit_project(
    project: Path,
    manifest_path: Optional[Path] = None,
    *,
    target_width: int = 1280,
    min_image_scale: float = 0.6,
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

        # Page-level checks
        issues.extend(page_background_issues(page, page_number, str(page_ref), slide_size[0], slide_size[1]))
        issues.extend(unresolved_src_issues(page, page_number, str(page_ref)))
        issues.extend(anti_slop_text_issues(page, page_number, str(page_ref)))
        issues.extend(anti_slop_design_issues(page, page_number, str(page_ref)))

        for element in page.get("elements", []):
            if not isinstance(element, dict):
                continue
            if element.get("elementType") == "text":
                checked_text += 1
                issues.extend(text_issues(element, page_number, str(page_ref), slide_size[0], slide_size[1]))
            elif element.get("elementType") == "image":
                checked_images += 1
                issue = image_resolution_issue(
                    project, element, page_number, str(page_ref),
                    slide_size, target_width, min_image_scale,
                )
                if issue is not None:
                    issues.append(issue)

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
