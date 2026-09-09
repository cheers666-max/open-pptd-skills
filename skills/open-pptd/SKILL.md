---
name: open-pptd
description: >-
  Create, edit, replicate, read, and export presentations. For every PPT task, the default deliverables are ALL of: (1) a self-contained PPTD project folder containing the .pptd manifest plus pages/media dependencies, (2) a locally generated .pptx with fade slide transitions, and (3) a `html/` folder with self-contained per-page HTML files plus a combined index.html. Use for any presentation, PowerPoint, PPT/PPTX, slide deck, PPTD, infographic, or poster task unless the user explicitly requests another format. Deliver with normal local file/folder links using absolute paths.
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

### step2.5. Write the outline, confirm it, then author pages

Before writing any page, put the plan on disk as `outline.json` in the project directory and get the
user's confirmation. The plan is what later tells you the deck came out short, lost a body block or
dropped a promised figure — a page-by-page renderer cannot know any of that.

```json
{
  "title": "deck title", "audience": "who is in the room", "purpose": "what it must achieve",
  "requestedPages": 14,
  "pages": [
    {"pageIndex": 1, "pageType": "cover", "actionTitle": "the sentence this page lands",
     "summary": "what it carries", "slots": ["kicker", "title", "affiliation"],
     "images": [{"query": "常州 淹城 遗址 航拍", "orientation": "landscape"}]}
  ]
}
```

`actionTitle` is the point the page makes, not a label ("身韵八元素与三种圆：风格的最小零件", not "八元素").
`slots` are the content blocks you intend to place; a content page planned with fewer than two of them
is a title over whitespace.

`images` is the list of pictures this page will carry — **plan the pictures page by page, and plan
more than one wherever the page argues with more than one thing**: a before/after pair, three steps
of a movement, a wide shot plus a detail, a scene plus the artefact it produced. Each entry is
`{"query": ..., "orientation": "landscape|portrait", "ratio": 1.78, "role": "product", "note": ...}`;
a bare string is shorthand for its query. `"image": true` with `imageQuery` remains the one-picture
short form. `outline_contract.py` reports `outline-thin-illustration` when fewer than 60% of content
pages plan a picture, and `outline-fewer-images` when a page ends up with fewer than it planned.

A deck that carries one photo every four pages reads as a wall of text no matter how good the words
are. Aim for a picture on most content pages and two or three on the pages that carry comparison,
sequence or evidence — then let the layout use them: a two-up comparison, a three-step strip, a wide
shot with an inset detail, a small gallery under a claim.

1. Show the table and wait. `python3 scripts/outline_contract.py --outline <project>/outline.json --markdown`
   prints the confirmation table. Show it, stop, and only continue once the user accepts it. This is the
   single mandatory pause; page counts, page types and figure decisions are cheap to change here and
   expensive later. When the run is non-interactive and nobody can answer (a batch or eval harness),
   print the table, write `"confirmed": "non-interactive"` into the outline and keep going — never end
   a task holding only a plan.
2. Check the plan on its own: run `outline_contract.py --outline <project>/outline.json` (no `--project`)
   to catch a plan that already disagrees with the agreed page count or leaves pages without a point.
3. Author pages against the confirmed outline. Keep `pageIndex` stable: edits change a page in place,
   inserts take the next free index, deletions leave a gap. Never renumber.
4. When the user changes the plan mid-flight, update `outline.json` first, re-show the table, and only
   then touch pages. An outline that no longer matches the deck is worse than no outline.

For a single-page edit or a small explicit task, this step is a few lines in the outline, not a ceremony.
Replication and template tasks still record the page plan they are reproducing.

### step2.6. Collect the deck's pictures once, from the confirmed outline

Searching per page while authoring gives every page its own narrow query: the same photo lands on two
pages, a page quietly ends up with none, and a picture that matches only its own caption is never
compared against the rest of the deck. Collect them in one pass instead, right after the outline is
confirmed and before pages are written:

```bash
python3 ~/.agents/skills/open-pptd/scripts/image_pool.py --project /abs/path/project --budget 240
```

It reads every picture the outline planned (`images` entries, or the `"image": true` short form) — using `imageQuery` when the plan names the shot,
otherwise the page's `actionTitle` — runs the existing search backends once for the whole deck, and
writes `images_pool.json` plus the files in `media/`. It examines 12 candidates per attempt on this
branch and retries an empty intent once with the head of its query, and the report carries
`pagesPlanned` / `pagesCovered` / `imagesPerPlannedPage` so a thin result is visible before the pages
are written.

Source gates before a picture is ever downloaded: stock-library and platform image hosts (they
carry site or account watermarks) and shopping-catalogue hosts are refused by URL. A page that
genuinely needs a product shot says so in the outline with `"imageRole": "product"`, which lifts the
shopping-host gate for that intent only.

**Write every image query in Chinese.** The backends are Chinese-first: a Latin scene phrase
("movie projector light beam dark room") comes back empty where the Chinese phrasing resolves, and
the pass refuses to start with one. Name concrete subjects rather than abstractions — "电影院 观众席
背影" resolves, "心理观影氛围" does not. `--allow-latin-query` exists only for a deck actually written
in that language. The pass shares one hash/URL dedupe set, so two
pages cannot be handed the same photo. `imageOrientation` (`landscape`/`portrait`) and `imageRatio`
steer the geometry gate.

Caption from what the pool actually recorded: `images_pool.json` carries the backend, source URL and licence for every picture. A slide caption is 机构／作者 · 年份 · 许可 or nothing — never a retrieval date, never "许可未知", never a bare "资料图". If the pool entry cannot support a real credit line, that is a reason to drop the picture, not to caption it vaguely.

Pages then reference the pool instead of a query or a URL: `src: "pool:p6"`. After authoring, run
`image_pool.py --project <dir> --resolve` to rewrite those references to their `media/` paths. An id
that is not in the pool is reported, never guessed, and `validate_deck.py` reports any leftover
reference as `unresolved-pool-reference`.

Per-slot `search:` placeholders (step3.5) remain available for a picture the plan did not foresee, for
a single-page edit, and for replication work. Use the pool for a new deck: it is what keeps the figures
distinct, comparable and decided before the layout hardens around them.

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

2. Write the query in Chinese and name a concrete subject; the script refuses a Latin-only
   `search:` query (`--allow-latin-query` only for a deck written in that language).
   The script searches, downloads and filters candidates with a complete-attempt timeout and an overall budget, then saves local media and rewrites `src:`. Partial re-search preserves other live slots and their provenance; restored matching placeholders reuse verified local bytes. Keep the report with its media; reuse requires the same query/slot and bytes that still meet orientation/minimum-size constraints. Download/filter failure also tries the next backend. Progress and heartbeats go to stderr; inspect `images_report.json`. VLM judging requires explicit `--vlm` plus a configured key and task authorization; `--no-vlm` remains supported. `--offline` never calls image backends or VLM and permits only marked decorative substitutes.
3. Pass `--localize-remote` to also download existing `https?://` image `src:` references into `media/`. This branch refuses Wikimedia/Wikipedia sources (backend, direct URL, redirect target, or a cached asset whose report names that origin); pick another source instead of retrying. See `reference/image-search.md`.
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

   When a heuristic finding (card layout, orphan line, capacity, wrapping, rainbow scheme, image
   resolution) turns out to be wrong on the rendered page, record it instead of reshaping a sound
   design: `validate-exceptions.json` in the project holds `{"exceptions": [{"code": ...,
   "pageNumber": ..., "reason": "what the render showed"}]}`. Accepted findings move to
   advisories carrying that reason, so they stay in the report; an exception that no longer matches
   anything is reported as `stale-exception`; and structural defects (a missing body, an unresolved
   source, a leaked internal token) can never be acknowledged this way.
   Blocking codes include orphan-last-line （孤字）, forbidden-line-start-punctuation, text-capacity-overflow, unexpected-wrap, element-overflow-viewport, low-effective-image-resolution, invalid-gradient, missing-required-background (cover/final/chapter), unresolved search/remote image placeholders, invalid-align (align must be a flat [h, v] pair), line-points-outside-viewbox (line points are viewBox units), empty-body-band (a full-width gap between elements wider than a quarter of the slide — usually a body block that was never written), internal-token-leak and duplicate-image; text-density stays a non-blocking advisory.

   Then hold the deck to its plan: `python3 ~/.agents/skills/open-pptd/scripts/outline_contract.py --project /abs/path/project`
   reports `outline-deck-count` (the deck is shorter or longer than the confirmed outline),
   `outline-page-type` (a page became a different kind of page) and `outline-missing-image` (a page that
   promised a picture has none). Exit code 1 means the deck and the confirmed plan disagree: fix the deck,
   or update the outline with the user and say what changed. Skip it only when no outline was agreed.

   Invalid page/element structures and unresolved image sources stop before rendering. Fix YAML/types, required fields, theme tokens, resources and confirmed geometry issues; consult exact feature specifications when needed. Capacity, orphan-line, wrapping, density and card-layout estimates are candidates for visual inspection: inspect rendered pages before batch-editing them, and record justified exceptions in DESIGN_CONTEXT.md. Do not iterate to zero heuristic counts or change thresholds to satisfy a design. The auxiliary audit measures limited pure-color contrast/overlap, not actual text overflow, complex backgrounds or image relevance.

2. **Read the rendered result.** With image input, inspect `.qa-images/overview.jpg` for every page, then each suspicious `.qa-images/pages/page_NN.png` at full resolution. Check:
   - 图片清晰、比例与裁剪合适，关键主体未被文字遮住。
   - 元素不越界，文字不溢出、不被遮挡，字号与对比度可读。
   - 对齐、间距、层级、页边距及整篇节奏符合选定风格。
   - 图片实际内容支持本页论点；核对主体、场景、图注和来源。别家实绩不能当作本公司证据；不能用无关图填满版面。
   - 图注只写观众读得懂的署名：机构／作者 · 年份 · 许可。**页面上不写检索日期、"许可未知／授权待核"、"资料图"这类台账**——查不清出处就换一张图或不写图注，台账留在 notes 与 `images_report.json`／`images_pool.json`。`validate_deck.py` 的 `source-caption-noise` 会拦。

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
    - Both embed per-file subsets of the bundled fonts (`@font-face`) so numbered markers, bullets and line breaks look the same on machines without Noto Sans SC; pass `--no-embed-fonts` only when the recipient is known to have the fonts installed.

    ```bash
    python3 ~/.agents/skills/open-pptd/scripts/export_html.py /abs/path/deck/deck.pptd
    ```

    A project directory may be passed instead of the manifest when it contains exactly one `.pptd` file. The output directory is `<deck dir>/html/` unless `--output-dir` is given; it is rebuilt on each run and the export is deterministic (same deck and font files → byte-identical output). Requires a local Chrome/Chromium binary (`CHROME_BIN` or common install paths).

    For requested **360 online delivery**, use the branch's separate entry point:

    ```bash
    python3 ~/.agents/skills/open-pptd/scripts/export_online.py /abs/path/deck/deck.pptd --obs-config /abs/path/protected-obs.yaml --publish --json
    ```

    OBS reads the explicitly selected protected config, defaults to a unique object prefix, and refuses conflicting remote objects. For the attachment API, omit the OBS config and supply its environment credentials as documented. It produces `html-online/index.html`, per-page HTML, downloaded `assets/`, and `online-report.json`. `--publish` returns `published["index.html"]` plus page URLs; omit it when only local HTML with rehosted images is requested. Use `--images embed` for uploaded images plus self-contained HTML. Check exit 0, `ok: true`, page count, asset URLs, and the actual opened webpage before reporting online success. Give the user the combined page URL when published. For an online-specific request, `html-online/` can fulfill the HTML deliverable; still provide PPTD/PPTX unless the user narrows formats. See `reference/360-online.md` for credentials, options and failure behavior.
11. After completing and delivering any presentation, always end the final response with a concise optional next step telling the user that they can run `npx open-pptd-skills serve` to view the PPTD project in the local browser viewer. Keep this reminder in addition to, not instead of, the required project and file links.
