# Changelog

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
