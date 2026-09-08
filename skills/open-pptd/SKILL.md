---
name: open-pptd
description: Create, edit, replicate, read, and export presentations. For every PPT task, the default deliverables are ALL of: (1) a self-contained PPTD project folder containing the .pptd manifest plus pages/media dependencies, (2) a locally generated .pptx with fade slide transitions, and (3) a `html/` folder with self-contained per-page HTML files plus a combined index.html. Use for any presentation, PowerPoint, PPT/PPTX, slide deck, PPTD, infographic, or poster task unless the user explicitly requests another format. Deliver with normal local file/folder links using absolute paths.
---

# Definition
open-pptd is a local-first presentation creation and export skill built around the PPTD format. It defines a YAML-format intermediate DSL (`.pptd`) that abstracts OOXML and keeps each page self-contained. Rendering and PPTX generation run locally. This **360-intranet branch** also supports authorized image rehosting and HTML publishing through OBS/XStore S3 storage or the 360 attachment API.

For a **360 online / intranet / S3 image / web publishing** request, read `reference/360-online.md` and use `scripts/export_online.py` after the existing content and visual checks. Reuse an existing OBS config with `--obs-config` (or `OBS_CONFIG`); OBS uses its AK/SK and needs no attachment key. Never copy credentials into the skill or project. Its default HTML references uploaded image URLs; `--images embed` uploads the same images while embedding their bytes in HTML. Add `--publish` when web publishing is requested. Keep the editable PPTD's local media and original references. A configured key alone does not request publication. Missing upload credentials or any failed asset/page upload is an incomplete online delivery, even if local export succeeds.

**The default output is not PPTD-only.** Unless the user explicitly opts out, always produce all three:

1. the complete editable PPTD project directory (`.pptd` + `pages/` + `media/` and other referenced dependencies);
2. the matching locally generated `.pptx`, with fade slide transitions applied by default;
3. the matching self-contained `html/` export.

Existing PPTX files may also be converted into PPTD for editing, after which the requested formats are delivered again.

## The pptd format
The .pptd format is a simplified abstraction layer over OOXML that follows basic YAML syntax. This abstraction preserves the core content of OOXML (theme, page layout, element positions and definitions, etc.) while removing complex nesting logic such as Masters; every page is self-contained — what you see is what you get. Start with `reference/pptd-quickstart.md`; the complete `reference/pptd.md` specification is for targeted lookups.

## PPT production workflow

Resolve script/reference paths relative to this installed skill directory. Examples below use `~/.agents/skills/open-pptd`; substitute the actual installation path in pi or another host. Use only tools exposed by the current session. Subagents are optional: without them, research and write sequentially with the same checks. Never require a tool named `task`, install a pi extension, or assume more workers make completion time constant.

### step0. Check local prerequisites
Default delivery includes PPTX export (and optional `npx open-pptd-skills serve`), which need a local toolchain. Batch independent prerequisite checks in one tool invocation where supported; do not repeat checks already established for this session. **Before generating**, verify:

1. **Node.js 18+**: run `node --version`. If `node` is missing or the major version is below 18, **stop immediately**, tell the user to install Node.js 18+ from https://nodejs.org (or their OS package manager), and do not continue with PPTX export / `npx` until it is available. Only continue with PPTD-only output when the user explicitly opts out of PPTX.
2. **npm / npx**: run `npm --version`. They ship with Node.js; if missing, treat Node.js as not installed correctly and guide the user to reinstall/fix PATH.
3. **python3**: run `python3 --version` (on Windows, `python` may be the correct command). Needed for `export_images.py` / `export_html.py`.
4. **Chrome / Chromium / Edge**: needed by `export_images.py` and `export_html.py` for headless rendering and visual QA. If export later fails with a browser-launch error, ask the user to install a Chromium-based browser.
5. Soft deps are auto-handled by the scripts when missing: **PyYAML**, **Pillow**, and **websocket-client** are auto-installed with `pip --user`. The PPTX engine's Node dependencies (yaml, sharp, jszip, fontkit) are auto-installed on first run.

### step1. Read the context thoroughly
Read **all files uploaded by the user** and the provided URLs to understand the user's requirements. For a new deck, read `reference/pptd-quickstart.md` once; consult the relevant sections of `reference/pptd.md` only for features outside the quickstart. Do not load the entire format catalog repeatedly.

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
  * For a full document or outline, preserve its scope. Use it as the primary source; do not silently add external claims or pages.
  * If necessary materials are missing, list them early. When the task specifically adapts an absent source/script, request it and do not claim a generic replacement fulfills that task. If a useful pending draft is possible, use clearly labelled fields. Keep unsupported qualitative conclusions pending too (experience, growth, capacity, credit), not just numbers. An empty data slot should be a labelled text/table area, not a zero-valued chart. If producing a pending draft, it still needs visual review and the requested formats; state what must be supplied before external use.

> **Research and synthesis.** Use supplied material first; search only when needed and allowed. Tie each lookup to a key conclusion or required example in the short page plan, using the source-sufficiency rule in `reference/authoring-context.md`. Start writing supported pages while checking remaining local gaps; keep dependent claims explicitly pending. Once the plan has supporting evidence or identified blockers, stop broad research rather than collecting more background. Do not expand a complete outline or scoped edit without authorization. Optional research workers receive the assigned claim, scope and source locators (file/page or URL/date/measurement basis); the main writer reconciles findings before asserting them. An API key is not authorization to contact a service.

4. Page count
  - If the user requests a specific page count, the user's requirement takes priority
  - Page-by-page outline/script provided: match the number of pages in the outline/script
  - When a complete and relatively structured document is provided / when only a topic is provided: decide the page count yourself based on the document content / search results

### step3. Generate the presentation based on the user's requirements

Follow the quickstart's modular writing strategy: reuse `scripts/authoring_helpers.py`, write shared setup, then complete 2–3-page modules with explicit `path` and `content`; retry only a failed module. `write_project` rejects malformed page/element structures before writing any pages. After the **first completed module**, run its assembler, resolve that draft's images (step3.5), then run `prepare_deck.py` (step4) and inspect the current render before expanding the pattern. Preserve planned content, page-specific layouts and the final whole-deck review. Look up and test one instance of an unfamiliar element; keep plans brief rather than duplicating slide prose.

For a small task with an explicit simple design, the quickstart and shared author rules are enough to start. Skip unrelated scenario catalogs and optional icon searches; consult a design reference only for a concrete design decision. Use an actual available tool to write and run the authoring script, in one invocation when supported. An unexecuted script or tool-call markup in prose is not a generated deck.
Keep the generator and actual pages consistent: after repairing a module, rebuild the draft, resolve any restored `search:`/remote sources, then check. If editing a `.page` directly, update the matching generator before any later rebuild so it cannot undo the fix. Preserve successful modules, local media and `images_report.json`.

> **Shared author instructions.** Read `reference/authoring-context.md`. For a multi-page deck, write a short `DESIGN_CONTEXT.md` containing task boundaries, chosen design, page responsibilities and sourced metrics; for a simple single page, keep the same information in the working context. Use the same instructions for sequential and parallel writing. Any worker receives the shared context, assigned page/outline, format rules and available local assets. Workers edit only their assigned pages. Search placeholders are resolved in step3.5, after writing.
>
> Rich text containing `style=` uses a YAML block scalar (`text: |`), never a double-quoted YAML string. No emoji; use supported `fas:` icons or meaningful local shapes and inspect PPTX warnings. Capacity estimates are hints: respect paragraphs, inline font sizes and fixed line heights, then review the rendered result. Follow the selected design's density; do not impose a universal element count.
>
> For longer decks (typically >10 pages), optionally run `scripts/layout_planner.py <outline.json> --json` between the outline and writing. Its suggestions must preserve page count, order and intended teaching continuity; do not insert pages automatically.

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
1. Use `reference/slides_categories.md` to select a design direction when one is needed; read the matching scenario's relevant sections. Small tasks with an explicit simple design can use the quickstart directly.
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

**Backgrounds and real subjects:**

- Apply the selected design/template and explicit user image restrictions. Cover/final/chapter backgrounds normally use a local image. In self-directed design, the main writer may designate a purely atmospheric slot as decorative in DESIGN_CONTEXT.md and permit a local gradient if search fails. Mark only that slot `# pptd-image: decorative fallback=gradient` on its `src:` line (see the image-search reference). Base this choice on the image's purpose, not page type alone; a required authentic subject remains required.
- A product, person, evidence screenshot or required template image must remain authentic. If unavailable, report the unresolved slot; a decorative gradient cannot stand in for it.
- Offline work uses existing local assets and `--offline`; use online search only within the task's existing authorization. Missing dependencies/fonts must be prepared before offline export; the image script's offline flag does not make all other scripts offline.

**Image sizing strategy:**

- Plan `bounds` aspect ratio **before** writing `src: search:...`. The image search pipeline (since v2.1) passes the exact `bounds` ratio to backends that support it and gives strong scoring preference to candidates matching that ratio, which prevents `fit: cover` truncation.
- For full-page backgrounds, always use `bounds: [0, 0, W, H]` (the slide dimensions) so the search targets the correct aspect ratio.
- For side images, use the actual planned aspect ratio (e.g., `[560, 0, 400, 540]` → ratio ≈ 0.74, portrait-ish) so the search returns images that don't need heavy cropping.

1. When generated pages need real photos or illustrations, write `src: "search:<query>"` for image elements and background image fills instead of guessing URLs, then resolve them with `scripts/image_search/search_images.py` (pure stdlib; no pip installs):

   ```bash
   python3 ~/.agents/skills/open-pptd/scripts/image_search/search_images.py \
     /abs/path/project \
     --backend auto --workers 4 --timeout 30 --budget 120
   ```

2. The script searches, downloads and filters candidates with a complete-attempt timeout and an overall budget, then saves local media and rewrites `src:`. Partial re-search preserves other live slots and their provenance; restored matching placeholders reuse verified local bytes. Keep the report with its media; reuse requires the same query/slot and bytes that still meet orientation/minimum-size constraints. Download/filter failure also tries the next backend. Progress and heartbeats go to stderr; inspect `images_report.json`. VLM judging requires explicit `--vlm` plus a configured key and task authorization; `--no-vlm` remains supported. `--offline` never calls image backends or VLM and permits only marked decorative substitutes.
3. Pass `--localize-remote` to also download existing `https?://` image `src:` references into `media/` (Wikimedia Commons thumbnail URLs with non-whitelisted widths are rewritten automatically; see `reference/image-search.md`).
4. Exit codes: `0` = every slot resolved; `2` = unresolved slots remain — inspect `<project>/images_report.json`, adjust the `.page` element (query, bounds, or element choice) and re-run; `1` = usage/IO error.
   After an automatic attempt has exhausted all backends, do not rerun the same backends individually without a meaningful query/asset/access change. Use the designated decorative fallback where allowed, or report the missing required image and preserve the completed content.
5. Do not leave unresolved `search:` placeholders or broken remote URLs in delivered pages. The HTML viewer only embeds local/data images; the PPTX exporter separately prefetches remote images, and a failed fetch can lose that image. For a 360 online deliverable, use `export_online.py` to resolve image elements, backgrounds and fills in a temporary copy, upload each unique image and choose remote or embedded HTML explicitly. See `reference/image-search.md` for the full CLI reference, slot conventions, and backend caveats.

### step4. PPT validation

**Main-writer final review comes first**, after all material/page rewrites. Compare actual text, tables and charts with the shared metrics and source passages: check unit, year, denominator, theoretical/measured/forecast labels and policy wording. For professional instruction, check prerequisites and applicable limits, and ensure diagrams teach the same sequence and roles as the text. Review the page sequence for repeated claims, missing transitions and unsupported conclusions. For editing, compare changed files with the original scope and check affected references. Local user data and labelled teaching examples need no invented public URL. A source link or a static pass does not certify truth. Record unresolved content briefly in DESIGN_CONTEXT.md and resolve it before claiming a complete delivery. Any later edit requires rechecking affected content and re-exporting.

1. **Check and render through one entry point:**

   ```bash
   python3 ~/.agents/skills/open-pptd/scripts/prepare_deck.py /abs/path/project/deck.pptd
   ```

   This runs the existing deterministic validator, renders changed pages, rebuilds a **complete current overview**, and runs the existing auxiliary contrast/overlap audit across every page. It makes no model or scoring calls. Read the concise result and `.qa-images/prepare-report.json` for page/field errors, advisories, image paths, rendered/reused page numbers and export results. `ok` means machine checks passed; `visualReview: required` is not a visual pass. Preserve the exit code; when piping logs, use `set -o pipefail` or capture the original status.

   Invalid page/element structures and unresolved image sources stop before rendering. Fix YAML/types, required fields, theme tokens, resources and confirmed geometry issues; consult exact feature specifications when needed. Capacity, orphan-line, wrapping, density and card-layout estimates are candidates for visual inspection: inspect rendered pages before batch-editing them, and record justified exceptions in DESIGN_CONTEXT.md. Do not iterate to zero heuristic counts or change thresholds to satisfy a design. The auxiliary audit measures limited pure-color contrast/overlap, not actual text overflow, complex backgrounds or image relevance.

2. **Read the rendered result.** With image input, inspect `.qa-images/overview.jpg` for every page, then each suspicious `.qa-images/pages/page_NN.png` at full resolution. Check:
   - 图片清晰、比例与裁剪合适，关键主体未被文字遮住。
   - 元素不越界，文字不溢出、不被遮挡，字号与对比度可读。
   - 对齐、间距、层级、页边距及整篇节奏符合选定风格。
   - 图片实际内容支持本页论点；核对主体、场景、图注和来源。别家实绩不能当作本公司证据，资料图需标注；不能用无关图填满版面。

   Batch confirmed fixes in the affected modules/pages, resolve any changed sources, then **rerun the same `prepare_deck.py` command** and review the updated full overview. Unchanged pages reuse their verified PNGs; page text, local image/font bytes, theme, order, scale or rendering-code changes invalidate the affected cache. Use `--force` after system font/browser changes or when cache freshness is uncertain. Do not add `--force` to every single-page repair. `--json` prints the full report; existing individual scripts remain available for diagnosis or custom options.

   Repeat content/visual checks and repair until confirmed issues are resolved. With image input, finish this visual review before PPTX export. A justified heuristic exception can use the individual exporters after its actual visual check; preserve the original failing report and the reason, rather than claiming a clean machine pass.

3. **Text-only authors:** accepting an image path does not mean the model received pixels. Run the same `prepare_deck.py` checks and review source bounds, long text, contrast, hierarchy and density. Send the current overview/full images to an available authorized image-capable reviewer; otherwise retain them, state visual inspection is pending and produce the requested formats with that limitation. Never claim a visual pass or create another DOM/pixel detector to replace inspection.

**Generation review and repair remain required.** The separate seven-dimension benchmark judge (意图、事实与来源、结构、内容边界、版式、配图、密度) is optional extra evaluation, run only when explicitly requested. Do not start it automatically when generation ends, wait for its scores before delivery, or replace the author’s content/visual repair loop with it.

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
   After the applicable step4 review, use the fixed entry point for default exports:

   ```bash
   python3 ~/.agents/skills/open-pptd/scripts/prepare_deck.py /abs/path/project/deck.pptd --export html,pptx
   ```

   It rechecks the current source, reuses current PNGs, and writes HTML/PPTX only when machine checks pass. This explicit command refreshes generated outputs; it does not perform or certify visual review. Inspect `.qa-images/prepare-report.json` → `exports`, and the linked `.qa-images/pptx-report.json` for full PPTX warnings. For custom paths, transition/font options or documented heuristic exceptions, use the individual commands below. Do not export twice if the requested files already match this checked draft. The text-only fallback does not waive independent visual inspection or export checks.
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
   - font embedding: enabled by default. The exporter scans the deck for `fontFamily` references, resolves each to a local font file (auto-downloading open-source fonts on first use), and embeds font data into the PPTX. Full CJK fonts can substantially increase file size; confirm appearance in the target presentation application.
   - override with `--no-embed-fonts` to disable font embedding.
   - default delivery also includes `html/`; the combined command above already produces it.
6. Export command:

   ```bash
   node ~/.agents/skills/open-pptd/scripts/export_pptx.mjs \
     /abs/path/project/deck.pptd \
     --output /abs/path/project/deck.pptx \
     --report /abs/path/project/pptx-report.json
   ```

   A project directory may be passed instead of the manifest only when it contains exactly one `.pptd` file.
   Existing output files are not overwritten unless `--force` is passed.
7. Local export requirements and boundaries:
   - requires **Node.js 18+** (`node` / `npm`);
   - the engine's Node dependencies (yaml, sharp, jszip, fontkit) are auto-installed into `scripts/node_modules` on first run;
   - remote images referenced by the deck are fetched from their respective hosts during export;
   - local PNG/JPEG/GIF/SVG files inside the PPTD project are embedded directly;
   - do not claim PowerPoint/WPS/Keynote playback compatibility solely because ZIP validation succeeds.
8. Font strategy:
   - Fonts are embedded into the PPTX by default. The exporter scans the deck for `fontFamily` references and resolves each to a local font file.
   - Open-source fonts (Noto Sans SC, Noto Serif SC, Oranienbaum, etc.) are auto-downloaded on first use to `scripts/fonts/` and cached for reuse. See `scripts/download-fonts.py --check` for the registry.
   - If a font cannot be auto-downloaded (e.g., CDN unavailable), the exporter falls back to: (1) manually placed files in `scripts/fonts/`, (2) system font directories. You can also pre-download fonts with `python3 scripts/download-fonts.py --download-all`.
   - To disable font embedding, pass `--no-embed-fonts` to the exporter. The resulting PPTX will reference font names only and depend on the viewer's machine having those fonts installed.
   - The HTML export and browser preview always use the system's local font stack (MiSans, PingFang SC, Microsoft YaHei, etc.) and do not embed fonts.
8. After export, check the exit code and PPTX warnings (the full report linked by `exports.pptx.report`, or `pptx-report.json` from the individual command), including the affected page/element. Verify this run's PPTX/HTML files, page count/order and important charts/icons; a file existing or a warning count alone is not acceptance. Verify ZIP integrity and root-level fade transitions in valid CT_Slide order. Do not claim these checks passed without running them. For higher-risk decks, additionally inspect font parts and representative rendered/opened pages as appropriate.
   Write completion statements only after checking the actual outputs. Early input-request or planning notes must distinguish intended deliverables from files already produced.
9. When the user wants to open, edit, or preview a PPTD project manually, start the local viewer with `npx open-pptd-skills serve`. Ask the user to open `http://127.0.0.1:55173/` and select the complete PPTD project directory. The viewer runs entirely in the browser with no server-side processing.
10. Static HTML export (default local deliverable): localize remote images first, then use `scripts/export_html.py` to produce a `html/` folder next to the deck. It renders through the skill's own deterministic HTML5 renderer (`scripts/viewer.html`) via headless Chrome. A remaining remote `src` can still access the network and is not automatically embedded:

    - `html/index.html` — every page concatenated vertically in one file (scroll to view the whole deck);
    - `html/page_NN.html` — one self-contained page per slide, images inlined as base64 data URLs, opens directly by double-click.

    ```bash
    python3 ~/.agents/skills/open-pptd/scripts/export_html.py /abs/path/deck/deck.pptd
    ```

    A project directory may be passed instead of the manifest when it contains exactly one `.pptd` file. The output directory is `<deck dir>/html/` unless `--output-dir` is given; it is rebuilt on each run and the export is deterministic (same deck → byte-identical output). Requires a local Chrome/Chromium binary (`CHROME_BIN` or common install paths).

    For requested **360 online delivery**, use the branch's separate entry point:

    ```bash
    python3 ~/.agents/skills/open-pptd/scripts/export_online.py /abs/path/deck/deck.pptd --obs-config /abs/path/protected-obs.yaml --publish --json
    ```

    OBS reads the explicitly selected protected config, defaults to a unique object prefix, and refuses conflicting remote objects. For the attachment API, omit the OBS config and supply its environment credentials as documented. It produces `html-online/index.html`, per-page HTML, downloaded `assets/`, and `online-report.json`. `--publish` returns `published["index.html"]` plus page URLs; omit it when only local HTML with rehosted images is requested. Use `--images embed` for uploaded images plus self-contained HTML. Check exit 0, `ok: true`, page count, asset URLs, and the actual opened webpage before reporting online success. Give the user the combined page URL when published. For an online-specific request, `html-online/` can fulfill the HTML deliverable; still provide PPTD/PPTX unless the user narrows formats. See `reference/360-online.md` for credentials, options and failure behavior.
11. After completing and delivering any presentation, always end the final response with a concise optional next step telling the user that they can run `npx open-pptd-skills serve` to view the PPTD project in the local browser viewer. Keep this reminder in addition to, not instead of, the required project and file links.
