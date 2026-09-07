# PPTD authoring quickstart

Read this once for ordinary new decks. It covers text, shapes, lines, icons and local images; use [pptd.md](pptd.md) as an indexed reference when a needed feature is absent. Do not read the whole chart/table/animation specification for a text-and-diagram deck. Also read [authoring-context.md](authoring-context.md) and the relevant design guide.

Quote numeric-looking text labels such as `text: '08'` or `text: '1e3'`; Python and JavaScript YAML readers can resolve unquoted values differently. The authoring helper preserves these strings automatically.

## Files and coordinates

A project contains `deck.pptd`, `pages/*.page`, and `media/*`. Every path is relative to the **manifest directory**, including media paths written in a page. The manifest determines page order. Geometry is `[x, y, width, height]` in a 960 × 540 canvas. Later elements paint above earlier ones. Keep IDs unique within each page.

For a new multi-page deck, reuse `scripts/authoring_helpers.py` rather than writing common constructors again. It emits ordinary PPTD YAML and automatically uses block scalars for multiline/rich text:

```python
import sys
sys.path.insert(0, "/actual/skill/scripts")
from authoring_helpers import text, shape, line, icon, page, write_project

pages = [page([
    text("title", 48, 38, 864, 55, "Presentation title", fontSize=36),
    text("body", 48, 120, 600, 150, '<p>A concrete example</p>', fontSize=20, lineHeight=1.4),
])]
write_project("output/deck", "Presentation title", pages)
```

Run the small example before expanding it into the full deck. When introducing an unfamiliar element, test one instance before copying its pattern to many pages. For HTML inside Python, prefer triple-quoted strings so ordinary quotation marks do not break the authoring script.

Constructors accept native PPTD fields: `text(id,x,y,w,h,value,**content)`, `shape(id,x,y,w,h,name='rect',**fields)`, `icon(id,x,y,w,h,name,**fields)`, `line(id,x,y,w,h,points,**fields)`. `page` accepts `page_type`, `background`, `notes`; `write_project` accepts `theme`, `size`, and explicit `overwrite=True` for regenerating your own draft. Existing-deck edits should preserve original files. Unsupported element types can still be ordinary dictionaries; look up their specification first. The helper chooses no layouts, content or sources. Add permitted search fallback comments to the relevant `.page` src lines after serialization.

Minimal `deck.pptd`:

```yaml
version: v2
title: Presentation title
size: [960, 540]
theme:
  colors:
    ink: "#172554"
    accent: "#0F766E"
  textStyles:
    title: {fontFamily: "Noto Sans SC", fontSize: 36, bold: true, color: "$ink"}
    body: {fontFamily: "Noto Sans SC", fontSize: 20, lineHeight: 1.4, color: "$ink"}
pages:
  - pages/01.page
```

Minimal `pages/01.page` (a syntax example, not a universal layout):

```yaml
pageType: content
background: {type: solid, color: "#FFFFFF"}
notes: "Speaker notes and source locators belong here when not needed on screen."
elements:
  - elementId: title
    elementType: text
    bounds: [48, 38, 864, 55]
    content:
      style: "$title"
      text: Presentation title
  - elementId: accent
    elementType: shape
    bounds: [48, 116, 8, 280]
    shapeName: rect
    fill: {type: solid, color: "$accent"}
  - elementId: body
    elementType: text
    bounds: [80, 122, 600, 170]
    content:
      style: "$body"
      align: [left, top]
      text: |
        <p>One main claim, with evidence.</p>
        <p><span style="font-weight:bold">A concrete example</span> makes it useful.</p>
```

Text belongs in `content.text`; shapes do not contain text. For multiline plain text use `text: |` too. Content fields override a theme style. `lineHeight` is a multiplier; `lineHeightPx` is fixed and takes precedence. Default text is 18px with line height 1. Rich text supports simple paragraphs, spans and semantic tags; arbitrary web layout/CSS is not a substitute for positioned elements. Check capacity and actual rendering after writing.

## Other common elements

Append only what communicates useful information. These examples are independent:

```yaml
- elementId: marker
  elementType: shape
  bounds: [700, 130, 60, 60]
  shapeName: ellipse
  fill: {type: solid, color: "$accent"}
  border: {width: 2, color: "$ink"}

- elementId: direction
  elementType: line
  bounds: [700, 220, 160, 80]
  viewBox: [160, 80]
  points: "0,80 160,0"
  curve: sharp
  arrow: [null, arrow]
  border: {width: 3, color: "$accent"}

- elementId: idea
  elementType: icon
  bounds: [800, 130, 48, 48]
  iconName: "fas:lightbulb"
  fill: {type: solid, color: "$accent"}

- elementId: photo
  elementType: image
  bounds: [650, 310, 250, 160]
  src: "media/photo.jpg"
  fit: {mode: cover}
```

Common shapes: `rect`, `roundRect`, `ellipse`, `triangle`, `diamond`, `rightArrow`. Check [shapes.md](shapes.md) for other names. Verify an icon exists in `scripts/fa-icons.mjs`; do not substitute emoji. Use local PNG/JPEG images and preserve aspect ratio. If images need searching, follow [image-search.md](image-search.md), including its explicit decorative fallback marker. Do not invent existing media files, photos, logos or sources.

## Read only the missing feature

Search headings in [pptd.md](pptd.md), then read the matching section and example:

| Need | Section |
|---|---|
| Gradients, transparency, crop | Shared Types → Fill / ImageFit; Image. A gradient has top-level `gradientType`, `angle`, `stops` with `position` and `color`; no nested `gradient` wrapper or `offset` field. |
| Complex text, lists, superscripts | Text → TextContent / Rich Text Rules |
| Custom vector path | Shape; [shapes.md](shapes.md) |
| Table | Table → Cell (dimensions and cells are required) |
| Data chart | Chart → ChartData, the selected series type, and matching example |
| Animation | Animations, only when requested or needed |

Charts use `data: {cols: [...], rows: [...]}` and `series: [{type: ..., encode: {...}}]`; never guess a `labels/values` schema from another library. A tactical/teaching diagram usually uses shapes, labels and arrows instead of a data chart.

## Efficient execution

Resolve the installed skill path once. Read relevant guides once and exact sections on demand. Use documented CLI commands and `--help` before reading script internals. Serialize rich text as YAML block scalars (`text: |`) with the helper instead of hand-escaping HTML.

For an ordinary multi-page new deck, split tool payloads, not substance or generation/review rounds:

1. Write a small shared file, e.g. `deck_common.py`, importing bundled `authoring_helpers.py` constructors and defining the chosen shared styles/components. Do not recreate those constructors or copy all slide content into this file.
2. Write modules of **2–3 pages**, e.g. `pages_01_03.py`, `pages_04_06.py`, each returning its page dictionaries. Keep each page's argument, notes, evidence, layout and visual explanation specific. A thin `build_deck.py` assembles completed modules in order and calls `write_project`. Run it after the first module for an early renderable draft, then extend to the full planned page count; use `overwrite=True` only to regenerate your own draft.
3. Every file-write call must contain both a complete explicit `path` and complete `content`; supply the destination first when forming the call. If a write fails or is truncated, inspect that destination and resend only the affected module with both arguments. Reuse successful modules; do not resend the whole deck or reduce its content. Re-run the assembler after a repair so the actual `.page` files reflect it before validation. Existing-deck edits retain their existing organization and edit scope.

Use the existing `validate_deck.py` → `export_images.py` → `audit_rendered.py` checks. Treat estimated layout warnings as candidates for rendered inspection, not a reason to build another DOM/pixel checker or iterate until a heuristic count is zero. Text-only authors follow the SKILL's explicit fallback and preserve current images for independent visual review; a textual image-read result or auxiliary report is not seeing the slide. Do not add a separate framework, rasterize the whole deck, or skip sources or visual review to reduce tool calls.

Follow the normal SKILL workflow for assets, validation, rendered review and all requested exports. This quickstart changes how much format reference is loaded, not the acceptance criteria.
