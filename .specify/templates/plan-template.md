# Implementation Plan: Open-PPTD Skill Optimization

## Phase 1: Foundation & Audit Infrastructure (Week 1-2)

### Task 1.1: Post-Rendering Pixel Audit (`audit_rendered_hard`)
**Owner**: Core Engine  
**Priority**: P0  
**Effort**: 5 days  
**Dependencies**: export_images.py, export_html.py

**Subtasks**:
- [ ] Implement `scripts/audit_rendered.py` (headless Chrome + PIL/Pillow)
  - Render each page to PNG via existing viewer infrastructure
  - Calculate text-background contrast ratio (WCAG AA ≥4.5:1)
  - Detect element occlusion via pixel overlap analysis
  - Detect alignment deviations (grid consistency across pages)
  - Generate annotated PNG with bounding boxes + JSON report
- [ ] Integrate into `validate_deck.py` as new check category `rendered_audit`
- [ ] Add whitelist mechanism for intentional design choices (bleed, overlay, etc.)
- [ ] Add CLI flag `--audit-rendered` to `open-pptd-skills validate`

**Validation**:
- Unit tests with synthetic decks (known contrast violations, occlusion cases)
- Integration test with 10-page deck (verify audit report completeness)

### Task 1.2: Layout Rhythm Constraints (`layout_planner`)
**Owner**: Content Engine  
**Priority**: P0  
**Effort**: 3 days  
**Dependencies**: None

**Subtasks**:
- [ ] Define `page_archetypes.yaml` (cover, toc, section, content, data, quote, closing)
- [ ] Implement `scripts/layout_planner.py`
  - Assign archetype to each page based on content + pageType
  - Enforce no consecutive same-archetype pages (except content with different silhouettes)
  - Calculate silhouette hash (element bounds histogram) for variation detection
  - Generate rhythm plan (page sequence + archetype assignments) as JSON
- [ ] Integrate into SKILL.md step2 (after page count determination)
- [ ] Add user confirmation step (show rhythm plan before generation)

**Validation**:
- Unit tests for archetype assignment logic
- Integration test with 15-page deck (verify rhythm constraints enforced)

## Phase 2: Edit Fidelity & Design System (Week 3-4)

### Task 2.1: Lossless Edit Workflow
**Owner**: Conversion Engine  
**Priority**: P1  
**Effort**: 4 days  
**Dependencies**: export_pptx.mjs, vendor/open-ppt-engine

**Subtasks**:
- [ ] Implement `scripts/convert_fidelity.py`
  - Parse original PPTX (python-pptx or custom parser)
  - Convert to PPTD with fidelity scoring per element
  - Flag elements with confidence <90% for manual review
  - Generate side-by-side diff report (original screenshot vs PPTD render)
- [ ] Add "edit in place" mode to preserve original element IDs and positions
- [ ] Integrate into SKILL.md step3 (editing workflow)

**Validation**:
- Test with 10 real-world PPTX files (varied complexity)
- Measure element preservation rate (target ≥95%)

### Task 2.2: Tiered Design System Loading
**Owner**: Design Engine  
**Priority**: P1  
**Effort**: 3 days  
**Dependencies**: design_system/ directory

**Subtasks**:
- [ ] Create `design_system/index.json` (lightweight registry)
  - Extract name, description, thumbnail path, tags from each design system
  - Merge parallel structures (`01_strategy/` + `consulting/`) into single registry
- [ ] Implement `scripts/design_system_loader.py`
  - Load index on startup (≤100KB)
  - Load full spec only on user selection (lazy loading)
  - Support search/filter by industry, mood, color temperature
- [ ] Update SKILL.md step2 (design system selection workflow)

**Validation**:
- Measure initial context cost (target ≤100KB)
- Measure full spec load time (target ≤2s)

## Phase 3: Chart Vocabulary & Anti-Slop (Week 5-6)

### Task 3.1: Chart Vocabulary Expansion
**Owner**: Chart Engine  
**Priority**: P0  
**Effort**: 6 days  
**Dependencies**: pptd.md schema, kimi-slides reference

**Subtasks**:
- [ ] Extend `reference/pptd.md` with 13+ series types
  - Add waterfall, sankey, treemap, sunburst, funnel, gauge, heatmap schemas
  - Define `encode` field for column-based data mapping
  - Define `seriesDefaults` one-level shallow merge rules
- [ ] Implement chart validation in `validate_deck.py`
  - Sankey requires nodes + links
  - Waterfall requires measure type
  - Treemap requires hierarchical data
- [ ] Add chart examples to `reference/chart-examples/` (one per series type)
- [ ] Update `slides_categories/analysis-decision.md` with chart usage guidance

**Validation**:
- Unit tests for each chart type (valid + invalid cases)
- Integration test with data-heavy deck (verify chart rendering)

### Task 3.2: Anti-AI-Slop Enforcement
**Owner**: Content Engine  
**Priority**: P1  
**Effort**: 2 days  
**Dependencies**: kimi-slides reference

**Subtasks**:
- [ ] Extract banned phrase list from kimi-slides SKILL.md
- [ ] Add content validation to `validate_deck.py`
  - Flag "不是X而是Y", "闭环", "第N件事", etc.
  - Flag "not X, but Y", "closed loop", "key takeaway", etc.
- [ ] Add design pattern detection to `audit_rendered.py`
  - Detect card layouts (rounded rectangles in grid)
  - Detect rainbow color schemes (red + purple + yellow + green on same page)
- [ ] Integrate into SKILL.md step4 (validation workflow)

**Validation**:
- Test with synthetic content containing banned phrases
- Test with real decks (verify no false positives on intentional design choices)

## Phase 4: Integration & Testing (Week 7-8)

### Task 4.1: End-to-End Integration
**Owner**: All  
**Priority**: P0  
**Effort**: 5 days  
**Dependencies**: All previous tasks

**Subtasks**:
- [ ] Update SKILL.md with new workflow steps
  - Add `layout_planner` to step2
  - Add `convert_fidelity` to step3 (editing)
  - Add `audit_rendered_hard` to step4
  - Update step5 with new deliverables (rhythm plan, fidelity report, audit report)
- [ ] Add CLI commands for new features
  - `open-pptd-skills plan-rhythm <deck>`
  - `open-pptd-skills audit-rendered <deck>`
  - `open-pptd-skills convert-fidelity <pptx>`
- [ ] Create comprehensive test suite
  - Unit tests for all new scripts
  - Integration tests with real decks
  - Performance tests (measure audit overhead, design system load time)

**Validation**:
- Full workflow test (create → validate → export) with 20-page deck
- Edit workflow test (convert → edit → export) with 10-page PPTX
- Performance test (measure total generation time for 20-page deck)

### Task 4.2: Documentation & Release
**Owner**: Documentation  
**Priority**: P1  
**Effort**: 2 days  
**Dependencies**: Task 4.1

**Subtasks**:
- [ ] Update README.md with new features
- [ ] Create migration guide for existing users
- [ ] Add examples to `example/` directory
- [ ] Tag release v2.1.0

**Validation**:
- Documentation review by 2+ users
- Example decks render correctly

## Risk Mitigation

### Risk 1: Performance Overhead
**Impact**: Audit adds 30-60s per deck  
**Mitigation**: Make audit optional (`--audit-rendered` flag), optimize with parallel rendering

### Risk 2: False Positives in Audit
**Impact**: Audit flags intentional design choices  
**Mitigation**: Whitelist mechanism, manual review mode, precision tuning

### Risk 3: Backward Compatibility
**Impact**: Existing decks break with new validation  
**Mitigation**: Audit is advisory (not blocking), migration guide for design system changes

### Risk 4: Context Cost
**Impact**: New features increase SKILL.md size  
**Mitigation**: Split detailed reference into separate files, load on demand

## Success Criteria
- [ ] All new features integrated into SKILL.md workflow
- [ ] Audit precision ≥90% (measured on 50+ decks)
- [ ] Edit fidelity ≥95% (measured on 20+ PPTX files)
- [ ] Design system loading ≤100KB initial context
- [ ] 13+ chart types supported with validation
- [ ] User satisfaction: ≤1 revision round (down from 2-3)
