---
name: open-pptd
description: Create, edit, replicate, read, and export presentations. For every PPT task, the default deliverables are ALL of: (1) a self-contained PPTD project folder containing the .pptd manifest plus pages/media dependencies, (2) a locally generated .pptx with fade slide transitions, and (3) a `html/` folder with self-contained per-page HTML files plus a combined index.html. Use for any presentation, PowerPoint, PPT/PPTX, slide deck, PPTD, infographic, or poster task unless the user explicitly requests another format. Deliver with normal local file/folder links using absolute paths.
---

# Definition
open-pptd is a local-first presentation creation and export skill built around the PPTD format. It defines a YAML-format intermediate DSL (`.pptd`) that abstracts OOXML and keeps each page self-contained. All exports (PPTX, HTML, images) run fully local — no remote editor, no external service.

**The default output is not PPTD-only.** Unless the user explicitly opts out, always produce both:

1. the complete editable PPTD project directory (`.pptd` + `pages/` + `media/` and other referenced dependencies);
2. the matching locally generated `.pptx`, with fade slide transitions applied by default.

Existing PPTX files may also be converted into PPTD for editing, after which both outputs are delivered again.

## The pptd format
The .pptd format is a simplified abstraction layer over OOXML that follows basic YAML syntax. This abstraction preserves the core content of OOXML (theme, page layout, element positions and definitions, etc.) while removing complex nesting logic such as Masters; every page is self-contained — what you see is what you get. Read reference/pptd.md for the complete definition of this DSL.

## PPT production workflow

### step0. Check local prerequisites
Default delivery includes PPTX export (and optional `npx open-pptd-skills serve`), which need a local toolchain. **Before generating**, verify:

1. **Node.js 18+**: run `node --version`. If `node` is missing or the major version is below 18, **stop immediately**, tell the user to install Node.js 18+ from https://nodejs.org (or their OS package manager), and do not continue with PPTX export / `npx` until it is available. Only continue with PPTD-only output when the user explicitly opts out of PPTX.
2. **npm / npx**: run `npm --version`. They ship with Node.js; if missing, treat Node.js as not installed correctly and guide the user to reinstall/fix PATH.
3. **python3**: run `python3 --version` (on Windows, `python` may be the correct command). Needed for `export_images.py` / `export_html.py`.
4. **Chrome / Chromium / Edge**: needed by `export_images.py` and `export_html.py` for headless rendering and visual QA. If export later fails with a browser-launch error, ask the user to install a Chromium-based browser.
5. Soft deps are auto-handled by the scripts when missing: **PyYAML**, **Pillow**, and **websocket-client** are auto-installed with `pip --user`. The PPTX engine's Node dependencies (yaml, sharp, jszip, fontkit) are auto-installed on first run.

### step1. Read the context thoroughly
Read **all files uploaded by the user**, the provided URLs, and the pptd format guide `reference/pptd.md` to fully understand the user's requirements.

### step2. Understand the user's requirements
Understand the user's requirements based on the context:
1. First determine the purpose of the request
  - Create a PPT: create a new presentation (from scratch, or from an existing pptx template)
  - Edit a PPT: edit the user's uploaded PPT (local modifications, single-page beautification, etc.)
  - Replicate a PPT: replicate a presentation from a non-pptx format (images, PDF, etc.) into pptd format

2. Then determine the design direction
  - Self-directed design: no preference, or only simple style constraints given; you need to fill in or create the design
  - Design system: the user provides a complete and detailed design scheme covering all color, font, layout, and component specifications
  - Use a template: a template is provided and must be used
  - Style transfer: a style reference source is provided (images, web pages, etc.)

3. Then determine the input type
  - Topic only: only a PPT topic direction or content requirements for the presentation are given, with no concrete content
  - Full document: the user provides a complete document (paper, research report, press release, etc.)
  - Outline: the user provides a page-by-page outline, speech script, or similar content
  * When the "user input type" is [Full document] or [Outline] and it is not specified whether expansion is allowed: since a page-by-page outline, speech script, or user document can hardly support the full content of a presentation, prefer using search to expand with more relevant material, cases, etc., unless the user explicitly says not to expand

4. Page count
  - If the user requests a specific page count, the user's requirement takes priority
  - Page-by-page outline/script provided: match the number of pages in the outline/script
  - When a complete and relatively structured document is provided / when only a topic is provided: decide the page count yourself based on the document content / search results

### step3. Generate the presentation based on the user's requirements

Before generating, first read `reference/pptd.md` to understand the pptd format definition and constraints.

#### Replicating a PPT
- Analyze the images to estimate element positions, fonts and sizes, etc., and **replicate 1:1 as closely as possible**.
- When an image contains elements that are hard to replicate directly and cannot be approximated with icons/shapes (e.g., photos, avatars), you may use tools such as bash or python to crop and screenshot the original image

#### Editing a PPT
- Convert the user's uploaded pptx file to .pptd format
- Review the converted pages (structure and key visual details). Read a few key pages individually afterwards.
- Locate the pages to edit, and be careful not to affect parts outside the intended scope.
> Conversion from pptx to pptd is not perfectly lossless. If the user later reports format errors, garbled content, etc., compare against the original pptx and repair the pptd with reference to the comparison

#### Generating a PPT
When generating a PPT, adopt different production approaches for different user [design directions]
##### Self-directed design
1. Read the design guide `reference/slides_categories.md`, and read the scenario document corresponding to the user's query
2. Produce the presentation based on the above

#### Generating content in other formats
- When the user explicitly asks for an infographic, poster, or a highly visual single-page design, read `reference/general-poster.md` and implement it as a single-page or few-page editable PPTD; when the user only asks for an image, still build it with PPTD first, then output the image via screenshot or rendering. Do not load this reference file for ordinary PPT requests.

##### Design system
1. Read the general constraints section of the `reference/slides_categories.md` guide, and read the scenario document corresponding to the user's query as the design foundation
2. Read the user-provided design system document as the presentation style. It is strictly forbidden to reference or mix in other design styles
3. Produce the presentation with reference to the above

##### Using a template
1. Convert the user's uploaded pptx file into pptd form
2. Review the converted pages to understand the template's visual style (color scheme, font style, element characteristics, layout characteristics, content density, etc.)
3. Identify page types; focus on reading special pages such as the cover, summary pages, and section dividers (single-page screenshots, .page files), extracting their page layouts, content structures, reusable components (icons, shapes, smartart, reusable body layout schemes, etc.), and element styles (e.g., whitespace/line/card separators, square/rounded corners, etc.)
4. Produce the presentation using the template

##### Style transfer
1. Analyze the reference file's visual style (color scheme, font style, element characteristics, layout characteristics, content density, etc.), page layouts, content structures, reusable components (icons, shapes, smartart, reusable body layout schemes, etc.), and element styles (e.g., whitespace/line/card separators, square/rounded corners, etc.).
- If the user provides a style reference URL, do not only read the text content; refer to and learn from the page's visual effect more to help understand the style
2. Produce the presentation using the reference file's style characteristics. You are encouraged to reuse illustrations, fonts, font-size hierarchies, elements, etc. from the original pdf/url

### step3.5. Resolve image placeholders (required when pages use `search:` or remote image URLs)
1. When generated pages need real photos or illustrations, write `src: "search:<query>"` for image elements and background image fills instead of guessing URLs, then resolve them with `scripts/image_search/search_images.py` (pure stdlib; no pip installs):

   ```bash
   python3 ~/.agents/skills/open-pptd/scripts/image_search/search_images.py \
     /abs/path/project \
     --backend auto --workers 4
   ```

2. The script searches image backends (`baidu`, `openverse`, `wikimedia`, `vertical`; auto-cascaded), downloads candidates, ranks them (landscape-first based on element `bounds` ratio), saves the winner to `media/`, and rewrites the `.page` `src:` lines in place to local relative paths. **Optional VLM visual judging** (relevance / watermark / quality scoring) activates when `PPT_API_KEY` (or `QIHOO_360_API_KEY` / `QIHOO_API_KEY`) is set; without a key the ranking falls back to pure geometry/resolution gates and still works normally. Pass `--no-vlm` to skip VLM explicitly.
3. Pass `--localize-remote` to also download existing `https?://` image `src:` references into `media/` (Wikimedia Commons thumbnail URLs with non-whitelisted widths are rewritten automatically; see `reference/image-search.md`).
4. Exit codes: `0` = every slot resolved; `2` = unresolved slots remain — inspect `<project>/images_report.json`, adjust the `.page` element (query, bounds, or element choice) and re-run; `1` = usage/IO error.
5. Do not leave unresolved `search:` placeholders or broken remote URLs in delivered pages; the renderer and exporters drop remote assets that were not fetched locally. See `reference/image-search.md` for the full CLI reference, slot conventions, and backend caveats.

### step4. PPT validation
1. Validate the generated pptd against the format definition in `reference/pptd.md` (required fields, types, bounds, theme tokens, resource paths, etc.) and repair issues over multiple rounds
2. Visual review with exported page images — **required before PPTX export when the model supports image input (multimodal)**:
   - Run `scripts/export_images.py`. It renders each page through the skill's local viewer with headless Chrome, saves per-page PNGs, and stitches all pages into one overview image:

     ```bash
     python3 ~/.agents/skills/open-pptd/scripts/export_images.py \
       /abs/path/project/deck.pptd \
       --output /abs/path/project/.qa-images
     ```

     The script prints a JSON summary mapping each stitched label (`P1`…`Pn`, 1-based page order) to its `.page` file.
   - Read the stitched overview image (`.qa-images/overview.jpg`) and check every page against this list:
     1. 图片是否清晰、不变形（无拉伸、压缩、模糊）
     2. 文字是否压在关键画面（人脸、产品主体、Logo 等）上
     3. 元素坐标是否超出页面边界
     4. 边界与配色对比是否足够（文字与背景、相邻色块之间）
     5. 排版是否统一（对齐、间距、字号层级、页边距）
     6. 文字是否可能溢出文本框（文本过长、行距过密、字号过大）
     7. 内容是否被上层元素遮挡
   - For any suspicious page, read its full-resolution image (`.qa-images/pages/page_NN.png`) to confirm the problem before editing.
   - Fix issues in the corresponding `.page` file, then re-run `scripts/export_images.py --force` and review the new overview; repeat until every page passes.
   - Do not export the PPTX until the visual review passes. `.qa-images/` is an intermediate QA artifact and may be deleted after delivery.
3. When the model cannot read images, fall back to a structural review of the generated pages (bounds, overflow-prone long text, contrast, hierarchy, layout density) over multiple rounds, and state that image-based visual QA was skipped.

### step5. PPT output and delivery
1. Always produce a self-contained project directory. Keep the `.pptd` manifest and every referenced dependency together; never deliver a standalone manifest without its referenced files. Use this layout unless an existing project already has a valid equivalent structure:

   ```text
    deck/
      deck.pptd
      pages/
        *.page
      media/
        *                # when the deck has local media
      deck.pptx          # generated by default
      html/              # generated by default
        index.html
        page_NN.html
    ```

2. Generate the `.pptx` by default after PPTD validation, even when the user only asks to create or edit a presentation. Skip PPTX export only when the user explicitly requests PPTD-only output or the environment cannot run the exporter; in the latter case, report the exact blocker and still deliver the complete PPTD project.
3. Deliver with normal clickable local links using absolute paths. In the final response, link all of the following:
   - the project directory;
   - the `.pptd` manifest;
   - the `pages/` directory and `media/` directory when present;
   - the generated `.pptx` file;
   - the `html/` directory.
4. PPTX conversion: use `scripts/export_pptx.mjs`. It compiles the PPTD project into an editable PPTX using the bundled local OOXML engine (`scripts/vendor/open-ppt-engine/`) — no browser, no remote editor, no network service. Remote http(s) images are prefetched into a local cache so they embed as real bytes.
5. Default PPTX options:
   - page transition: `fade` (淡入淡出), written to every slide by the engine;
   - override with `--transition none` to disable transitions.
   - after PPTX export, also run HTML export (step 5.10) by default to produce `html/` alongside the PPTX.
6. Export command:

   ```bash
   node ~/.agents/skills/open-pptd/scripts/export_pptx.mjs \
     /abs/path/project/deck.pptd \
     --output /abs/path/project/deck.pptx
   ```

   A project directory may be passed instead of the manifest only when it contains exactly one `.pptd` file.
   Existing output files are not overwritten unless `--force` is passed.
7. Local export requirements and boundaries:
   - requires **Node.js 18+** (`node` / `npm`);
   - the engine's Node dependencies (yaml, sharp, jszip, fontkit) are auto-installed into `scripts/node_modules` on first run;
   - remote images referenced by the deck are fetched from their respective hosts during export;
   - local PNG/JPEG/GIF/SVG files inside the PPTD project are embedded directly;
   - do not claim PowerPoint/WPS/Keynote playback compatibility solely because ZIP validation succeeds.
8. After export, verify that the output exists and report the generated path. The PPTX ZIP passes integrity checks and every slide has a root-level fade transition in valid CT_Slide order. For higher-risk decks, additionally inspect font parts and representative rendered/opened pages as appropriate.
9. When the user wants to open, edit, or preview a PPTD project manually, start the local viewer with `npx open-pptd-skills serve`. Ask the user to open `http://127.0.0.1:55173/` and select the complete PPTD project directory. The viewer runs entirely in the browser with no server-side processing.
10. Static HTML export (default deliverable): use `scripts/export_html.py` to produce a `html/` folder next to the deck. It renders through the skill's own deterministic HTML5 renderer (`scripts/viewer.html`) via headless Chrome, with no network access:

    - `html/index.html` — every page concatenated vertically in one file (scroll to view the whole deck);
    - `html/page_NN.html` — one self-contained page per slide, images inlined as base64 data URLs, opens directly by double-click.

    ```bash
    python3 ~/.agents/skills/open-pptd/scripts/export_html.py /abs/path/deck/deck.pptd
    ```

    A project directory may be passed instead of the manifest when it contains exactly one `.pptd` file. The output directory is `<deck dir>/html/` unless `--output-dir` is given; it is rebuilt on each run and the export is deterministic (same deck → byte-identical output). Requires a local Chrome/Chromium binary (`CHROME_BIN` or common install paths).
11. After completing and delivering any presentation, always end the final response with a concise optional next step telling the user that they can run `npx open-pptd-skills serve` to view the PPTD project in the local browser viewer. Keep this reminder in addition to, not instead of, the required project and file links.
