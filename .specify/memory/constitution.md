# Open-PPTD Skill Optimization Constitution

## Project Identity
- **Project**: open-pptd (PPT skill for AI coding agents)
- **Purpose**: Local-first PPTD-based presentation generation/editing/export skill
- **Scope**: Optimize the skill by integrating best practices from kimi-slides while preserving local-first strengths

## Core Principles

### Principle 1: Local-First Execution
All PPT generation, validation, and export operations MUST run locally without remote dependencies. This includes:
- PPTX export (no remote editor)
- HTML export (no remote rendering)
- Image search and localization (no remote services unless explicitly requested by user)
- Font embedding (local font resolution and subsetting)

**Rationale**: Users need reproducible, offline-capable PPT generation that doesn't depend on external services or network availability.

### Principle 2: Deterministic Validation
PPT validation MUST be deterministic and automated where possible. The system SHOULD catch measurable failures (text overflow, bounds violations, missing backgrounds) before visual review. Auto-fixes MUST be safe and non-destructive.

**Rationale**: AI-generated content requires deterministic gates to catch common failures before human/visual review, reducing iteration cycles.

### Principle 3: Multi-Format Delivery
The default deliverable MUST include ALL of:
1. Editable PPTD project directory (.pptd + pages/ + media/)
2. Locally generated .pptx with fade transitions
3. HTML folder with per-page self-contained HTML files

**Rationale**: Users need both editable source and immediately usable output formats without additional conversion steps.

### Principle 4: Anti-AI-Slop Design
Generated PPTs MUST avoid common AI-generated design anti-patterns:
- No "not X, but Y" phrasing
- No "closed loop" / "第N件事" clichés
- No rounded-rectangle card layouts for hierarchy
- No "red + purple + yellow + green" color schemes on the same page

**Rationale**: AI-generated designs often follow recognizable patterns that reduce perceived quality and professionalism.

### Principle 5: Chart-First Expression
When presenting data, charts MUST be the primary expression method. The system SHOULD support a rich chart vocabulary (13+ series types including waterfall, sankey, treemap, sunburst) and encourage data-driven layouts over text-heavy layouts.

**Rationale**: Data-heavy presentations require robust chart support to communicate insights effectively without overwhelming text.

## Governance

### Amendment Procedure
1. Propose changes via PR with rationale
2. Review by maintainers
3. Update constitution version (semantic versioning)
4. Propagate changes to dependent templates and prompts

### Versioning Policy
- **MAJOR**: Backward-incompatible governance changes
- **MINOR**: New principles or materially expanded guidance
- **PATCH**: Clarifications, wording, non-semantic refinements

### Compliance Review
- All spec.md files MUST pass quality checklist validation
- All plan.md files MUST align with constitution principles
- All tasks.md files MUST reflect principle-driven task categories

## Current Version
- **Version**: 1.0.0
- **Ratified**: 2026-09-04
- **Last Amended**: 2026-09-04
