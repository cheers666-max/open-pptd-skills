# Image Search and Placement (image_search)

`image_search` is a zero-dependency (Python standard library only) image retrieval, verification, and localization engine built for PPTD projects. It resolves placeholder image queries (`src: "search:<query>"`) and remote URLs into local assets under `media/`, and updates `.page` files with local relative paths.

## Image Usage Principles (merged from kimi-slides)

1. **Images belong on body pages too**: appropriate images should be used not only on covers and section dividers, but also on body pages to enrich the page, aid understanding, or support decision-making.
2. **Substantive imagery only**: images are used to show concrete subjects, explain content, provide evidence, or establish a scene. Logos, icons, decorative textures, and very small thumbnails do not count as substantive imagery.
3. **Prefer real images for concrete subjects**: when a page involves products, people, places, buildings, events, cases, interfaces, experimental subjects, or spatial environments, prioritize corresponding real images or screenshots. If real images cannot be obtained, generated images may be used instead.
4. **Priority chain**: images provided by the user → images from official websites / official reports / credible sources → searched images directly relevant to the content → images generated for conceptual expression or atmosphere.
5. **Search first, design around proportions**: after deciding which images are needed, complete image search, generation, and downloading in a batch **before** designing pages around their proportions. Save images in the `media` directory, keep them clear, and never stretch or distort them.
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
| `--workers` | `4` | Number of concurrent worker threads. |
| `--no-vlm` | False | Skip VLM visual quality review (faster, no API key required). |
| `--localize-remote` | False | Also download external HTTP/HTTPS image URLs to `media/` and rewrite to local paths. |
| `--min-dim` | `360` | Minimum width and height (pixels) for accepted images. |
| `--dry-run` | False | Search and report candidates without downloading or modifying `.page` files. |

### Exit Codes

- `0`: All image slots resolved successfully.
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
