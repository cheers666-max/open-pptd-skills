# Changelog

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
