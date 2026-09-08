# Shared author context

Use this short reference before writing. For multiple pages, keep one `DESIGN_CONTEXT.md` in the project; for a simple single page, state the same essentials in the working context. Do not load all design references or build a separate metadata system.

## Contents to fill

- Task: purpose, audience, requested page count, source material, permitted expansion/network use, and exact edit scope.
- Design: chosen reference/template, dimensions, fonts, palette, hierarchy and margins. User requirements take priority; no universal 25–40 element target.
- Page plan: page/file → main takeaway → supporting evidence or specific unresolved source → relationship to the previous/next page. Keep intentional teaching sequences together.
- Shared metrics: use the compact table below only for figures/claims that need it. Include facts in charts and tables, not just prose.

| Claim/metric | Value + unit | Period, geography, denominator, basis | Source locator | Used on pages |
|---|---|---|---|---|
| Example conversion | 2 / 4 = 50% | Illustrative teaching example, not observed data | Label as example | Worked example page |

A source locator is a user file with page/sheet/cell, or an authorized external source with URL, publication date and relevant passage. Policy clauses/quotes require the original passage. Label estimates, forecasts and assumptions explicitly. Missing evidence stays unresolved; never fabricate a URL or a plausible number. This includes qualitative claims about an organization’s or person’s growth, experience, skills, capacity or credit: missing numbers do not authorize confident conclusions. A labelled teaching example permits invented scenario inputs; it does not exempt the underlying professional rule or theory from verification.

Before expanding background or drawing diagrams for a named concept, technique or theory central to the topic, verify its core definition/mechanism and relevant roles, sequence and applicable conditions from material that directly explains it. Build diagram labels and arrows from that verified mechanism. Distinguish adaptations or variants from the base mechanism; label proposed changes as such. Related-topic background, a source link or “general knowledge” cannot substitute for support of the named concept. If that material is unavailable, mark the dependent explanation/diagram pending, identify the needed evidence and stop generic background searches; continue with supported sections.

Research is sufficient to draft when every planned key conclusion and required example has either a source passage supporting its actual scope/date/basis, or a precise unresolved item naming the missing evidence and next check. Stop broad background searches at that point. Conflicting sources remain unresolved until reconciled; a link collection alone does not satisfy this condition. Write supported pages now and search only the remaining claim-specific gaps alongside writing. Keep dependent content clearly labelled pending instead of asserting it; marking a gap does not waive an available source check. If essential user material is absent or permitted retrieval cannot supply it, request that material and build a useful pending draft where possible; do not keep searching for a generic substitute. Resolve or disclose these gaps before delivery, and do not call the pending draft complete.

## Author rules

Use YAML block scalars for HTML/rich text, especially when it includes `style=`:

```yaml
content:
  fontSize: 12
  lineHeight: 1.5
  text: |
    <p><span style="font-weight:700">Key point</span> with its evidence.</p>
```

No emoji. Use supported `fas:` icons or meaningful local shapes; inspect the exported result and engine warnings. A missing icon must not become an unrelated bullet.

Capacity quick reference (slide px, estimates only):

| fontSize | lineHeight multiplier | Single-line height |
|---|---|---|
| 11 | 1.4 | 15.4 |
| 12 | 1.5 | 18 |
| 13 | 1.5 | 19.5 |

`needed_height ≈ fontSize × lineHeight × lines + vertical padding` for uniform text. A CSS `line-height: 20px` is a fixed 20 px; paragraphs, spacing and larger inline spans change the estimate. Never wrap unknown-length content in a tiny box or automatically increase height without checking nearby elements. Prefer shortening, splitting or adjusting layout over shrinking all text.

Parallel writing is optional and host-dependent. Each worker reads this same context and the relevant PPTD guidance, receives its assigned pages and available media, and writes only those pages. With no subagent tool, follow the same plan sequentially using the quickstart's shared setup and 2–3-page modules. Module boundaries do not remove planned content, generation rounds or the final whole-deck review.

Keep audience-facing content on the slide; put private speaker cues and facilitation instructions in notes unless the requested deck is itself a facilitator guide.

Audience-facing text (titles, body, captions, footnote sources) never mentions internal artifacts or workflow vocabulary: no `images_report.json`, `DESIGN_CONTEXT`, "材料包/资料包", "主写手", "待核对后再使用", and no bare internal source codes such as "(S1)" unless the same page or a sources page spells the code out. Write sources the way the audience would read them: institution or author · year · licence (for photos: "Wikimedia Commons, CC BY-SA 4.0, photographer"). Draft markers belong in notes or in `NEEDS_INPUT`, not on the slide. `validate_deck.py` reports `internal-token-leak` for these tokens and `duplicate-image` when one media file appears on more than one page; a cover/closing pair may share an image only with a different crop or overlay.

Alignment and lines: `align` is one flat pair, `align: [center, middle]` — never a list inside a list, and do not let a YAML dumper turn shared lists into `&id` anchors. `line` element `points` are in the element's `viewBox` units, not percentages: an arrow filling a `viewBox: [12, 18]` is `points: "0,0 0,18"`. `validate_deck.py` reports both mistakes as `invalid-align` and `line-points-outside-viewbox`.

## Final review by the main writer

After image resolution and all page rewrites, inspect actual pages and sources:

1. Reconcile repeated metrics by unit/year/scope. Same metric + same basis + different values is a conflict; different years need not conflict. Same number labelled theoretical on one page and measured on another still needs evidence.
2. Check that each source actually supports the claim. Distinguish user data, illustrative numbers, assumptions and external facts. Citation presence and model agreement are not factual verification. For professional instruction, verify when a technique/procedure is valid, its prerequisites and limits against the relevant source; a memorable simplification must not reverse a rule. Check diagram roles, sequence and labels against the prose. Keep distinct entity/role counts and states consistent at each depicted moment; label partial views and movement traces rather than counting graphical marks as entities.
   Keep observed events, possible explanations and general research findings separate. Without case evidence, do not turn a theory into a diagnosis of someone's motives, a claim about a whole group, or a guaranteed causal effect. Label scenario reconstruction and explain what evidence would distinguish competing explanations.
3. Read takeaways in order; remove accidental repetition and supply missing logical transitions. Keep purposeful teaching continuity. Check that numbered headings match the actual items, and that the requested emphasis is carried by substantive explanation, examples and evidence rather than section titles alone.
4. For edits, compare original and changed files; preserve unrequested pages and shared resources, then inspect affected references.
5. Note unresolved claims and actual review scope briefly. Re-run affected checks and exports after any later edit. Do not label a document fully verified while facts or required real images remain unresolved.
