# Changelog

## 2.5.0 — 2026-09-09

### open-pptd skill
- Image source gates: stock-library hosts (`zcool`/`hellorfimg`/`588ku`/`ibaotu`/`51yuansu`/`tu.chinaz`/`huaban` alongside the existing list), platform image hosts that stamp account watermarks (`bdstatic`, `hdslb`, `zhimg`, `sinaimg`, `itc.cn`, `sohucs`, `pstatp`/`byteimg`/`toutiao`) and any URL whose path contains `watermark` are refused before download. Shopping-catalogue hosts are refused unless the outline page asks for a product shot with `"imageRole": "product"`.
- Every rejected host shipped a defective picture in the 2026-09-09 twenty-deck run: a Shutterstock-watermarked photo (`hellorfimg.zcool.cn`), a B-station image whose URL literally contains `/watermark/`, self-media watermarks from `itc.cn`/`sohucs`, a 1688 catalogue shot.
- New blocking rule `source-caption-noise`: retrieval dates, "许可未知/授权待核" and captions reading "资料图" must not be rendered on a slide — 93 text elements across 15 of the 20 decks carried them. The record belongs in speaker notes or the image report; the slide gets institution · year · licence, or no caption.
- Note: 2.4.0 (recorded validate exceptions) is currently 360-intranet only.

## 2.3.1 — 2026-09-09

### open-pptd skill
- Image queries must be written in Chinese. `image_pool.py` refuses a Latin-only intent before the search pass starts and names the outline pages to rewrite; `search_images.py` refuses a Latin-only `search:` placeholder the same way. `--allow-latin-query` exists only for a deck actually written in that language, and the pipeline fixtures pass it explicitly because their queries are ASCII sentinels.
- Evidence from the 2026-09-09 run: Latin scene phrases ("movie projector light beam dark room", "open notebook with pen writing hands") came back empty on both backends, while the Chinese phrasing on the same deck resolved.

## 2.3.0 — 2026-09-09

### open-pptd skill
- New `scripts/image_pool.py`: the deck's pictures are collected in one pass from the confirmed outline (step2.6), before any page is written. Every outline page marked `"image": true` becomes one search intent (`imageQuery`, else the page's `actionTitle`), the pass runs through the existing backends with a single deck-wide hash/URL dedupe set, and the result is `images_pool.json` plus files in `media/`.
- Pages reference `src: "pool:<id>"`; `--resolve` rewrites those to their `media/` paths and reports an id that is not in the pool instead of guessing one. `validate_deck.py` reports a leftover reference as `unresolved-pool-reference`.
- Why: per-slot search during authoring gave each page its own narrow query — the same photo landed twice, pages ended up with nothing, and no picture was ever compared against the rest of the deck. Image fit was the lowest-scoring dimension of the 2026-09 evaluations (3.2/5).
- Per-slot `search:` placeholders stay for pictures the plan did not foresee, single-page edits and replication.

## 2.2.0 — 2026-09-09

### open-pptd skill
- New front stage (step2.5): the page plan is written to `outline.json` *before* any page is authored, shown to the user as a table, and confirmed once. `scripts/outline_contract.py --markdown` prints that table; without `--project` it checks the plan alone (agreed page count, every page has a point and a summary, no content page planned with fewer than two slots).
- With `--project` the same script holds the built deck to the confirmed plan: `outline-deck-count` (the deck came out shorter or longer), `outline-page-type` (a page became a different kind of page) and `outline-missing-image` (a page that promised a picture has none). These are the failures a per-page renderer cannot see — the 2026-09-08 twenty-deck run produced a 7-page deck where more was planned and pages whose figure never appeared, and nothing objected.
- Borrowed from the slide-creator pipeline's staged front end (strategy → research → images → outline with a single mandatory confirmation), kept to one artifact and one script rather than a seven-stage orchestrator.

## 2.1.5 — 2026-09-09

### open-pptd skill
- `validate_deck.py`: `invalid-align` now blocks only values the renderers cannot read. Since 2.1.2 both renderers flatten nested pairs, map synonyms (`start`/`end`, `center`↔`middle`) and read numbers as positions, so `align: right`, `[[center, middle]]` and `[left, center]` render exactly as written — blocking them forced edits with no visual effect. Those shapes are now the non-blocking advisory `non-canonical-align`; unknown words such as `centre` and lists longer than two still block. Checked against 20 evaluation decks: 5 of them carried 154 such values and none rendered wrong.

## 2.1.4 — 2026-09-08

### open-pptd skill
- `validate_deck.py`: new blocking rule `empty-body-band`. A layout helper whose return value the authoring script never appends leaves a page with its title, lead-in and footer around a hole; the deck still exported three formats and no check objected. The rule unions the vertical spans of a page's elements and reports the widest gap *between* them, so `prepare_deck.py` stops before export. Threshold 0.25 of the slide height comes from 477 pages of the 2026-09 evaluations: the airiest page nobody flagged spans 0.228, the page whose body was dropped spans 0.537. Margins never count and a page-filling element covers every band.

## 2.1.3 — 2026-09-08

### open-pptd skill
- `viewer.html`: element styles are written with a helper that skips `undefined` instead of `Object.assign`, which stringified it. `font-family: undefined` is a *valid* custom-ident, so those elements stopped inheriting the slide font stack and fell back to the browser default font — 12 of the 25 evaluated decks carried it on up to 222 elements per deck, and their exported HTML rendered in the wrong font with the wrong metrics.
- The slide fallback stack now ends with the bundled `Noto Sans SC` before `system-ui`, and `export_html.py` reads every family in a stack (not just the first), so decks that never name a font still get a deterministic embedded subset.
- Tests: exported HTML must contain no `font-family: undefined` and must embed faces; PPTX adapter align variants.

## 2.1.2 — 2026-09-08

### open-pptd skill
- `validate_deck.py`: new blocking rules `invalid-align` (align must be a flat `[h, v]` pair; nested `[[center, middle]]` used to fall back to left/top and push text out of its shape) and `line-points-outside-viewbox` (line `points` are viewBox units, not percentages; `0,0 0,100` in a 12×18 viewBox drew a line across the whole column).
- `viewer.html` and the PPTX adapter flatten nested align pairs instead of silently ignoring them.
- `reference/authoring-context.md`: notes on align pairs and line points.

## 2.1.1 — 2026-09-08

### open-pptd skill
- `export_html.py` now embeds per-file subsets of the bundled fonts (`@font-face`, base64 woff/woff2) into `index.html` and every `page_NN.html`. Previously the HTML only named "Noto Sans SC"; on machines without it the browser fell back to PingFang/YaHei, whose bold weight and metrics shift numbered markers, bullets and line breaks. `--no-embed-fonts` restores the old behaviour. Subsets add roughly 100–300 KB per page.
- Tests: `tests/test_export_html_fonts.py` (skips when the gitignored fonts are not downloaded).

## 2.1.0 — 2026-09-07

Driven by the 20-case production run and automated two-judge review (`eval/reports/2026-09-07-production20.md`).

### open-pptd skill
- `validate_deck.py`: new blocking rules `internal-token-leak` (internal artifact names / workflow vocabulary in audience-facing text) and `duplicate-image` (one media file on several pages; cover/closing pair reported as style). New non-blocking `advisories` with `text-density` (`--max-page-chars`, default 360).
- `reference/authoring-context.md`: audience-facing source style, forbidden internal tokens, deck-wide image uniqueness.
- `SKILL.md`: documents the new codes and how to treat advisories.

### eval
- `run_pi.py --pass-env NAME`: forward image-search credentials to pi with log redaction (baidu/vertical backends were silently unavailable in earlier runs).
- `auto_judge.py`: content + visual judges through an OpenAI-compatible endpoint, verified-source context for time-sensitive cases, HTML/Markdown/JSON report.
- Reports: 2026-09-07 production batch, findings and optimization plan.

## 2.0.0

- pi eval runner with snapshots, hard timeouts and bounded same-session continuation; HTML as default third delivery format; authoring helpers and shared authoring context; kimi-slides fusion.
