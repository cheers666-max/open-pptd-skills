# Image Search and Placement (image_search)

`image_search` is a zero-dependency (Python standard library only) image retrieval, verification, and localization engine built for PPTD projects. It resolves placeholder image queries (`src: "search:<query>"`) and remote URLs into local assets under `media/`, and updates `.page` files with local relative paths.

For this branch's **360 online export**, see [360-online.md](360-online.md). After resolving `search:` slots, `scripts/export_online.py` downloads referenced remote images into a temporary project, rehosts unique images through OBS/S3 (using an existing `--obs-config`) or the attachment API, and produces HTML with uploaded URLs or embedded bytes. It also handles inline YAML image/background/fill definitions, preserves the original project, and can publish the HTML with `--publish`. Search success alone does not establish upload or publication success.

## Image Usage Principles (merged from kimi-slides)

1. **Images belong on body pages too**: appropriate images should be used not only on covers and section dividers, but also on body pages to enrich the page, aid understanding, or support decision-making.
2. **Substantive imagery only**: images are used to show concrete subjects, explain content, provide evidence, or establish a scene. Logos, icons, decorative textures, and very small thumbnails do not count as substantive imagery.
3. **Prefer real images for concrete subjects**: when a page involves products, people, places, buildings, events, cases, interfaces, experimental subjects, or spatial environments, prioritize corresponding real images or screenshots. If a real subject/evidence image is required and unavailable, leave it unresolved. Only explicitly permitted conceptual or decorative imagery may be generated; it must not impersonate a real product, person or evidence.
4. **Priority chain**: images provided by the user → images from official websites / official reports / credible sources → searched images directly relevant to the content → images generated for conceptual expression or atmosphere.
5. **Plan proportions, then resolve**: define the intended slot and bounds while writing pages, resolve placeholders in step3.5, then review cropping before final content/visual checks. Reuse already available local media first. Never stretch or distort images.
6. **Evidence imagery for analytical decks**: analytical, technical, and academic PPTs should use corresponding evidence images when products, experiments, interfaces, cases, or on-site materials are available. Do not reduce every page to text, color blocks, and shapes.
7. **No filler images**: do not add irrelevant images merely to meet a quantity target. Every image must be directly relevant to the page's conclusion or communication goal.

## Key Features

- **Standard Library Only**: Built using `urllib`, `hashlib`, `struct`, `concurrent.futures`, `json`, and `re`. No external pip dependencies.
- **Header Sniffing**: Fast binary dimension sniffing for PNG, JPEG, WebP, GIF, and BMP to avoid full decoding when evaluating candidate dimensions.
- **Search Backends**:
  - `baidu`: Broad public web image search.
  - `vertical`: Curated vertical photographic and wallpaper collections.
  - `openverse`: CC-licensed creative commons image index.
  - `wikimedia`: Wikimedia Commons open-license image repository.
  - `auto`: Cascade order: `baidu` -> `openverse` -> `wikimedia` -> `vertical`.
- **VLM Quality Gate**: Uses multimodal LLM (via Moonshot / 360 API gateway) to score relevance, aesthetics, and layout suitability, rejecting low-quality candidates.
- **Wikimedia Thumbnail Whitelist Rewrite**: Wikimedia Commons rejects non-whitelisted thumbnail widths with HTTP 400. The engine automatically adapts widths to standard whitelist tiers (`250`, `500`, `960`, `1280`, `1920`) and falls back to original image sources.
- **Remote Asset Localization**: Optional `--localize-remote` flag downloads remote HTTP/HTTPS images into `media/` and patches `.page` references to ensure the project is fully self-contained.

---

## Workflow in PPT Production

In the open-pptd generation workflow, image search runs after structural YAML generation (Step 3) and before visual export / PPTX compilation (Step 4).

```text
Step 3: Generate PPTD (use `src: "search:<keywords>"` in .page files)
   ↓
Step 3.5: Run image_search (downloads images to media/, rewrites .page files)
   ↓
Step 4: PPT validation (export_images.py / visual QA)
   ↓
Step 5: Export PPTX (export_pptx.mjs) / static HTML (export_html.py)
```

---

## Command Usage

```bash
python3 scripts/image_search/search_images.py <project_dir|deck.pptd> [options]
```

### Options

| Flag | Default | Description |
|---|---|---|
| `<target>` | Required | Path to the PPTD project directory or `.pptd` file. |
| `--backend` | `auto` | Search backend: `auto`, `baidu`, `vertical`, `openverse`, `wikimedia`. |
| `--workers` | `4` | Maximum concurrent disposable backend processes. |
| `--timeout` | `30` | Seconds for one complete backend attempt: search, download and optional VLM. |
| `--budget` | `120` | Overall command budget in seconds; remaining work is terminated at the deadline. |
| `--offline` | False | No image/VLM network calls. Reuse this project’s matching cached provenance or explicitly permitted decorative fallback. |
| `--vlm` | False | Explicitly enable VLM within task authorization; a key must also be configured. |
| `--json` | False | One JSON summary on stdout; progress and heartbeats on stderr. |
| `--no-vlm` | Default behavior | Retained compatibility flag; a key alone never enables VLM. |
| `--localize-remote` | False | Also download external HTTP/HTTPS image URLs to `media/` and rewrite to local paths. |
| `--min-dim` | `360` | Minimum width and height (pixels) for accepted images. |
| `--dry-run` | False | Scan slots only; no searches, downloads or project changes. |

### Exit Codes

- `0`: All image slots resolved, including any explicitly marked decorative substitutes. Check `degraded` and per-slot provenance.
- `2`: One or more image slots failed to resolve (details written to `images_report.json`).
- `1`: Invocation or I/O error.

---

## Specifying Search Slots in `.page` Files

### 1. Element Image

```yaml
- elementId: hero-image
  elementType: image
  bounds: [100, 120, 760, 420]
  src: "search:现代城市天际线 夜景 霓虹"
  fit:
    mode: cover
```

### 2. Background ImageFill

```yaml
background:
  type: image
  src: "search:极简 渐变 科技背景"
  fit:
    mode: cover
```

### Explicit decorative fallback

For a self-directed design, the main writer can designate a purely atmospheric slot as decorative in DESIGN_CONTEXT.md, provided the user/template does not require an authentic subject there. For that permitted slot only, annotate the specific src line:

```yaml
background:
  type: image
  src: "search:calm blue atmosphere" # pptd-image: decorative fallback=gradient
```

`--offline` can create a deterministic local PNG gradient for this slot. Online mode tries real candidates first, then the same allowed fallback if all attempts fail. Do not apply this marker to required products, people, screenshots or evidence. Unmarked unresolved slots exit 2. A local gradient is recorded as `status: degraded`, `backend: local-gradient`, with the reason; it is not a real photograph. Local source paths need no search command.

Progress starts immediately and long work emits a heartbeat at most every 5 seconds. Download or filtering failure moves to the next backend as well as search failure. The parent process writes files/reports and handles duplicate winners; workers cannot continue changing the project after a deadline. `tried` records each failure, including deadline and worker errors.

This offline flag governs the image script, not dependency installation or font resolution in other commands. Prepare local dependencies/fonts before a fully offline session. Existing task authorization can be reused; the agent does not need to ask again for each image. Public-source license metadata is retained as supplied, and an empty license remains unknown rather than commercial-use approval.

### Aspect Ratio Detection

The engine automatically parses `bounds: [x, y, w, h]` on image elements to deduce preferred aspect ratio:
- `w / h > 1.25`: Prefers landscape images.
- `w / h < 0.8`: Prefers portrait images.
- Otherwise: Accepts any aspect ratio.

---

## Output Artifacts

1. **Local Media Assets**:
   Saved in `<project_dir>/media/<slug>.jpg` (or `.png`, `.webp`).
2. **Updated `.page` Files**:
   `src: "search:..."` lines are rewritten in-place to `src: "media/<filename>"` while preserving line indentation, quotation style, and trailing comments.
3. **Audit Report (`images_report.json`)**:
   Emitted at project root, recording per-slot provenance:
   - `query` / `source_url`
   - `backend` used (`baidu`, `wikimedia`, `remote`, etc.)
   - `license` metadata
   - Image dimensions and sniffed format
   - VLM evaluation score and verdict

### Rebuilds and partial re-search

Keep `images_report.json` beside the draft and its `media/`. Re-running resolution after a generator restores matching search placeholders can reuse existing verified image bytes; it need not repeat network search. Reuse matches page, element ID and slot kind, original query/URL, file content hash, orientation and minimum size. Anonymous/ambiguous slots are not guessed. Legacy generated filenames with a matching short content hash can be upgraded to a full SHA256 record.

Re-searching one slot merges its result with other live local slots, retaining their source/landing URL, supplied license, VLM result and attempt history. Deleted slots, manually replaced paths, missing files or changed bytes at the same path cannot inherit old provenance. A failed new search does not erase unrelated valid records. This is a content-identity check, not a new license or image-relevance judgment: inspect the actual crop/subject after changes, and keep unknown licenses unknown.
