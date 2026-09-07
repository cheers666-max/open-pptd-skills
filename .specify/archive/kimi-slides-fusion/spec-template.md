# Feature Specification: Open-PPTD Skill Optimization

## Overview
Optimize the `open-pptd` skill by integrating proven patterns from `kimi-slides` (Moonshot AI's first-party PPT skill) while preserving and extending its local-first strengths. The optimization targets five specific gaps identified through comparative analysis: (1) post-rendering hard audit, (2) deterministic layout rhythm constraints, (3) lossless edit workflow, (4) design system architecture, and (5) chart vocabulary expansion.

## User Stories

### Story 1: Post-Rendering Hard Audit
**As a** quality-conscious user,  
**I want** the skill to validate rendered output at the pixel level (not just mock-dimension heuristics),  
**So that** I can trust the visual output matches the design intent without manual screenshot inspection.

### Story 2: Deterministic Layout Rhythm
**As a** user creating multi-page decks,  
**I want** the skill to enforce page-type rhythm constraints (no consecutive same-archetype pages, silhouette variation),  
**So that** the deck has professional pacing without me manually planning each page transition.

### Story 3: Lossless Edit Workflow
**As a** user editing existing PPTX files,  
**I want** the skill to preserve original formatting fidelity during PPTX→PPTD→PPTX round-trips,  
**So that** I can confidently edit without introducing style corruption.

### Story 4: Tiered Design System Loading
**As a** user selecting a design style,  
**I want** the skill to load design system metadata incrementally (index first, full spec on demand),  
**So that** context costs stay low even with 60+ available design systems.

### Story 5: Rich Chart Vocabulary
**As a** data-heavy presenter,  
**I want** the skill to support 13+ chart series types (waterfall, sankey, treemap, sunburst, etc.) with ECharts-style configuration,  
**So that** I can express complex data relationships without resorting to text-heavy layouts.

## Functional Requirements

### FR-1: Post-Rendering Pixel Audit
- [ ] Add a `audit_rendered_hard` step that renders pages via headless Chrome and performs pixel-level checks
- [ ] Detect text-background contrast violations (WCAG AA minimum)
- [ ] Detect element occlusion via rendered pixel analysis
- [ ] Detect alignment/grid inconsistencies across pages
- [ ] Generate annotated audit report with issue bounding boxes

### FR-2: Layout Rhythm Constraints
- [ ] Define page archetype taxonomy (cover, toc, section, content, data, quote, closing)
- [ ] Implement `layout_planner` that enforces:
  - No consecutive same-archetype pages (except content pages with different silhouettes)
  - Minimum silhouette variation between adjacent content pages
  - Required rhythm breaks (section dividers) every N content pages
- [ ] Expose rhythm plan in outline phase for user confirmation

### FR-3: Lossless Edit Fidelity
- [ ] Implement PPTX→PPTD conversion with explicit fidelity scoring per element
- [ ] Flag elements with low conversion confidence for manual review
- [ ] Provide side-by-side diff view (original PPTX screenshot vs converted PPTD render)
- [ ] Support "edit in place" mode that preserves original element IDs and positions

### FR-4: Tiered Design System Architecture
- [ ] Create lightweight design system index (name, description, thumbnail, tags) ~2KB per system
- [ ] Load full design spec (colors, fonts, layouts, components) only on user selection
- [ ] Merge parallel directory structures (`01_strategy/` + `consulting/`) into single registry
- [ ] Add search/filter by industry, mood, color temperature

### FR-5: Chart Vocabulary Expansion
- [ ] Extend PPTD schema to support 13+ series types: bar, line, area, pie, scatter, radar, funnel, gauge, heatmap, treemap, sunburst, sankey, waterfall
- [ ] Implement `seriesDefaults` one-level shallow merge (matching kimi-slides behavior)
- [ ] Add `encode` field for column-based data mapping (ECharts-style)
- [ ] Add chart-specific validation (e.g., sankey requires nodes + links, waterfall requires measure type)

### FR-6: Anti-AI-Slop Enforcement
- [ ] Integrate kimi-slides' banned phrase list into content validation
- [ ] Add design pattern detection (card layouts, rainbow color schemes) to visual audit
- [ ] Enforce "no irrelevant images" rule via image-content relevance scoring

## Acceptance Criteria

### AC-1: Post-Rendering Audit
- [ ] Given a generated deck, when `audit_rendered_hard` runs, then it reports pixel-level contrast violations with ≥90% precision
- [ ] Given a deck with intentional bleed effects, when audit runs, then it does NOT flag bleed as an error (whitelist mechanism)

### AC-2: Layout Rhythm
- [ ] Given a 20-page deck, when generated, then no two consecutive pages share the same archetype+silhouette combination
- [ ] Given a user request for "10 pages all with same layout", when generated, then the skill warns and suggests rhythm variation

### AC-3: Edit Fidelity
- [ ] Given a PPTX with 50+ elements, when converted to PPTD and back, then ≥95% of elements retain original position (±2px) and size (±1%)
- [ ] Given a conversion with low-confidence elements, when delivered, then the report flags elements needing manual review

### AC-4: Design System Loading
- [ ] Given 60+ design systems, when the skill loads, then initial context cost is ≤100KB (index only)
- [ ] Given a user selects a design system, when loaded, then full spec is available within 2 seconds

### AC-5: Chart Vocabulary
- [ ] Given a data table, when the user requests a waterfall chart, then the skill generates valid PPTD with `type: waterfall` and correct `encode` mapping
- [ ] Given a sankey chart request without nodes/links, when validated, then the skill reports a clear error before rendering

### AC-6: Anti-AI-Slop
- [ ] Given generated content containing "不是X而是Y", when validated, then the skill flags it as a style violation
- [ ] Given a page with 4+ cards in a row, when audited, then the skill suggests alternative layouts

## Assumptions
- Headless Chrome is available for pixel-level rendering (already required by existing export_html.py)
- Users accept slightly longer generation time in exchange for higher quality (audit adds ~30-60s per deck)
- Design system consolidation is backward-compatible (old paths redirect to new registry)
- Chart expansion is additive (existing charts continue to work unchanged)

## Dependencies
- Existing `export_images.py` and `export_html.py` for rendering infrastructure
- Existing `validate_deck.py` for deterministic checks (audit extends, not replaces)
- kimi-slides reference files for chart schema and anti-slop patterns (attribution required)

## Success Metrics
- **Audit Precision**: ≥90% of pixel-level audit findings are true positives (not false alarms)
- **Edit Fidelity**: ≥95% element preservation in round-trip conversion
- **Context Cost**: Design system loading stays ≤100KB until user selection
- **Chart Coverage**: 13+ series types supported with validation
- **User Satisfaction**: Post-optimization decks require ≤1 revision round (down from current ~2-3)
