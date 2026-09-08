## 2026-09-08 — Earlier checks, incremental PNGs and optional scoring

Implemented on the separate `360-intranet` branch, with a staged commit for each change. Generation-time content review, visual inspection, repair and recheck remain required. Seven-dimension benchmark scoring is explicitly opt-in; this task did not run it or change historical reports, original benchmark decks, pi configuration or backend thinking settings.

- **Structure:** helper and validator reject malformed pages/elements before writing/rendering. RED fixtures covered nested/scalar elements, duplicate/missing IDs, unsupported types and invalid bounds. Seven structure tests pass, preserving numeric/boolean text and zero-height lines.
- **Opacity:** solid shape fills now compose HEX8, fill and shape-element alpha consistently in HTML and PPTX. Five new tests use actual Chrome pixels and packaged PPTX XML; the existing render-health and native PPTX tests pass. This does not establish all table/text/border/shadow opacity behavior or PowerPoint/WPS equivalence.
- **Images:** partial searches merge other live provenance records; rebuilding matching placeholders can reuse verified local bytes. Changed/missing bytes, changed queries, incompatible orientation/minimum size, removed slots and ambiguous identities do not inherit old provenance. Image search suite: **41/41 passed**, 6.621 s.
- **Fixed entry:** `prepare_deck.py` invokes existing validation, image rendering and auxiliary auditing. It hashes each page, declared local dependencies, shared theme/order/scale and rendering code; unchanged verified PNGs are reused, while every current page remains in the full overview and audits. `--force` covers browser/system-font changes. Explicit `--export html,pptx` preserves the full PPTX warning report. Fourteen focused tests pass, including source changes during rendering, export timeout, corrupt/missing PNGs and source/resource collision protection before failed reports are written. Source-overwrite and missing detailed-report failures were reproduced before their fixes.
- **Skill behavior:** baseline pressure walkthrough exposed mandatory full rerender after a single-page fix and the lack of a fixed first-module check. Updated read-only agent walkthroughs cover first 3 pages of a 12-page deck, a P7 repair with restored search placeholders, and a text-only author with machine-pass outputs. They retain early checks, verified cache reuse, content/visual repair and honest pending visual status without automatic scoring. These are instruction scenario tests, **not a fresh pi/model generation run**.
- **Aggregate regression:** `PATH=/opt/homebrew/opt/python@3.14/bin:$PATH npm test` — **51 passed, 0 failed, 0 skipped**, 47.164 s, including actual Chrome rendering, native LibreOffice icon/arrow checks and fake-pi isolation/review regressions. `python3 -m unittest discover -s skills/open-pptd/tests -p 'test_*.py'` with the same Python — **75/75 passed**, 34.046 s. Image-search tests are the separate 41-test suite above. Initial use of another Python failed because python-pptx was absent; the supported local interpreter resolved that environment issue without weakening tests.
- **Actual generic smoke:** a local three-page fixture (`/private/tmp/pptd-efficiency-smoke-rz3slq3t`) produced current PPTD, PNG overview, self-contained HTML and PPTX. Final stable-code measurements: full PNG refresh **3.081 s**, unchanged recheck **0.136 s** (all 3 PNGs reused), P2 text edit **2.627 s** (only P2 rendered; P1/P3 reused). A preceding cold run measured 5.380 / 0.221 / 3.109 s. These small local tool measurements are not end-to-end model speed or five-question quality gains. Final explicit exports returned `ok: true`, 3 HTML pages and a 3-slide valid PPTX ZIP with root fade transitions and zero engine warnings. The full overview and actual exported HTML P2 screenshot were visually inspected. A standalone Chrome `--screenshot` command wrote that current image but did not exit within 45 s and was stopped by the subprocess timeout; no successful CLI-exit claim is made. The skill's CDP exporters and regression tests completed successfully.
- **Packaging:** `npm pack --dry-run --json` listed **202 entries**, including the new scripts and references. No private config, credential value, generated project report, node_modules or Python bytecode path was found; the committed `online.env.example` contains empty values/placeholders only. The existing package rule includes locally cached public font files (about 158 MB compressed package in this worktree); these caches are not staged or pushed. No npm publication or new OBS upload was performed.

Remaining separate experiments: controlled whole-question speed A/B, server-side inference/queue metrics and effective thinking controls, and cross-reader font/other opacity fidelity. Content checks and image-relevance inspection still require the author/reviewer; caching does not turn a machine pass into visual acceptance.

# Implementation and validation log

## 2026-09-08 — Existing OBS configuration, real publication

The follow-up uses the existing protected Zhengzhou OBS YAML directly, without copying its credentials. The new optional `obs_upload.py` backend supports legacy `obs`, `profiles` and `targets`, environment credential references, independent endpoint/signing region/bucket, safe unique prefixes, conflict refusal and object/public readback verification. The attachment backend remains available; OBS needs no model/attachment key.

- New OBS tests first failed for the absent backend; partial-transfer reporting tests also failed before implementation. Narrow-browser regression reproduced the fixed canvas overflow, then passed after an online-only scaling script was added.
- Online suite: **29 passed** (17 attachment/export/browser tests, 12 OBS tests), Python 3.14. Final `npm test`: **42 passed, 0 failed, 4 skipped**, 47.823 s. The four existing font tests require uncached fonts and were not downloaded. OBS tests use botocore Stubber and synthetic credentials, not the user's config.
- Real final upload: existing Zhengzhou config, region `cn-north-4`, bucket `mcp-yue-tool`. Created **5 objects** in a fresh UUID prefix: two unique images (remote Wikimedia JPG and local SVG) plus two page HTMLs and the combined index. Every object's metadata, authenticated byte readback and unauthenticated public byte readback passed. No existing remote objects were replaced.
- [Verified two-page demo](https://cn-zhengzhou-3.xstore.qihu.com/mcp-yue-tool/open-pptd/bf028b2e4a9b4b44b8871cc9b6c6b288/index.html): headless Chrome opened index and both pages at **1280px and 390px**. All document/image responses were HTTP 200, all images decoded, no console/network errors, and scroll width equalled viewport width in all six checks. Desktop/mobile screenshots were inspected: title, JPG, SVG and caption visible, both pages intact.
- `npm pack --dry-run --json`: **190 entries**, including the OBS adapter and credential-free example; no protected config, private `.env` or online report. Real credentials were never printed or written into repository files.
- The earlier attachment HTTP 404/401 result below still describes that service. **OBS publication is now verified**; Beijing's example profile and other providers were not tested. No bucket/ACL/DNS changes, remote deletion or npm publication.

## 2026-09-08 — 360-intranet branch

New `scripts/export_online.py` uses a temporary PPTD snapshot and the existing viewer, uploads validated images through the attachment protocol, and writes remote-URL or embedded HTML. `--publish` additionally uploads each HTML file. The original branch and source deck are preserved. User explicitly authorized committing and pushing this separate branch; historical no-push statements below describe earlier work.

- Baseline installation tests: 5 passed; existing image search tests: 26 passed.
- Online tests: **16 passed**, included in the final **40/40** Python suite (Homebrew Python 3.14, 25.523 s); the first 15 also passed on Python 3.9.6. Includes real Chrome rendering, remote/background/fill images, data URIs and SVG, theme table styles, content deduplication, upload/read-back, missing credentials, invalid responses, redirect refusal, upload failure, path/symlink protection, non-export output protection, and backup-cleanup failure. Reproduced missing entry point, unsafe output overlap, SVG whitespace handling and missing theme images before their fixes. Existing image-search suite also passed **26/26** on the final branch.
- Full `npm test` using Homebrew Python 3.14: **42 passed, 0 failed, 4 skipped**, 48.745 s. The existing four font tests require cached fonts absent from the isolated worktree. Native LibreOffice rendering passed. Initial runs used system Python without python-pptx, then Anaconda whose MuPDF diagnostics polluted JSON; the project-compatible Homebrew interpreter resolved those environment failures without changing existing tests.
- `npm pack --dry-run --json`: 188 entries; online script, reference and credential-free example included. No node_modules, Python bytecode or private `.env` included. No npm publication.
- Final-page smoke: public Wikimedia Example.jpg plus a locally authored SVG, repeated on two pages. A local attachment-protocol service received two unique images and three HTML files. The resulting hosted page was loaded in headless Chrome; both remote image references decoded (172×178 and 480×270). Screenshot inspected: both images, title and caption visible. This was a local service test, not a successful 360 production upload.
- Real 360 probe: the existing model configuration's `api.360.cn/v1/upload/attachment` returned HTTP 404; the reference gateway `aigw.aijjt.com/v1/upload/attachment` returned HTTP 401 with the available key. Actual production publication remains unverified until the upload service's endpoint/credentials are supplied. No credential values stored in code, reports or logs.
- Independent review found and verified fixes for theme table image materialization and post-success backup cleanup. Six table-style combinations matched the viewer's original JavaScript precedence. Skill baseline failed all online requirements; updated instructions cover remote, embed and failed-credential scenarios.

2026-09-05. Lightweight SpecKit plan implemented in the existing skill and scripts; the optional pi evaluation lives under `eval/`. No global pi extension/configuration changes, no commit/push/npm publication.

## Final verification

- `npm test`: **45/45 pass, no skips**, 48.026 s. Includes the original 13 fusion tests, fake-pi runner / readonly review safeguards, actual browser rendering and PPTX regressions. Fake-pi tests do not count as model success.
- `python3 -m unittest discover -s skills/open-pptd/tests -p 'test_*.py' -v`: **17/17 pass**, 1.548 s.
- `python3 -m unittest discover -s skills/open-pptd/scripts/image_search/tests -p 'test_*.py' -v`: **26/26 pass**, 6.512 s.
- Faults were reproduced before fixing: silent test setup failure, image acquisition cascade/deadline, pie legend, premature screenshot, missing/incorrect icon and line arrows, malformed gradient fallback, numeric-looking YAML strings, font scanning and literal percent/Unicode local paths. No case-specific thresholds or automatic text-height expansion.
- Generic one-page quickstart produced PPTD/PPTX/HTML; independent LibreOffice PNGs verified icon/arrow fixes. This was a tool smoke, not a successful pi authoring run.

## Actual pi results

Full record, per-case evidence scores and run identifiers: [2026-09-05 evaluation report](../../eval/reports/2026-09-05.md).

- pi **0.84.4**, qihoo / anthropic/claude-opus-4.8, thinking off, web allowed. Full 20 cases, concurrency 4, limit 1200 s/case: **18 timed out, 2 incomplete**, total **6011.114 s**. **0/20 author-delivered PPTD + PPTX + HTML**; 16 cases left drafts, four left no pages. The frozen snapshot predates final fixes; evaluator diagnostics are separate from author delivery.
- Final-skill functional rerun, same model/thinking, concurrency 2: **08 needs_input, 545.140 s**, ten-page pending-input framework in all three formats; **06 incomplete, 690.117 s**, eleven pages without PPTX/HTML. Batch 692.778 s. These are two affected cases, not a second full 20-case benchmark.
- 08 independently opened via LibreOffice (10 pages), compared overview and P1/P5/P10 to PPTD screenshots, and opened the original exported HTML P1/P5/P10 in Chrome. No obvious missing body content in the viewed samples, but PPTX heading typography differs from the web view. Not a PowerPoint/WPS certification. Original hosting script remains missing, and identity/time/service assumptions still need correction.
- 06 improved some hypothetical labels but still generalized genders and added an attribution-concept error. After reading failed validation, its final visible response contained literal tool-call markup with no dispatched edit; this is an execution/protocol failure, not a completed repair.
- Two generic two-page pi smokes (600 s each) both timed out. First only wrote a generator; second wrote two pages and validated, but did **not** render images or export PPTX/HTML. T009's successful generic pi smoke criterion remains unmet.

No controlled speed improvement is claimed: full and affected runs used different concurrency and overlapped with other jobs. Second two-page smoke recorded 14 tool calls totaling 0.413842 s (sum may overlap); longest no-tool interval 190.221 s. Tool intervals do not explain model/API/scheduling overhead. File count and author self-evaluation are not quality scores.

## Earlier exploratory runs, kept separate

- Kimi K3 `20260905-114611-a6lpndm0`: 03/08/20 each timed out at 1200 s, no complete three-format delivery.
- Deepseek v4 `20260905-120337-ruhcffxe`: 01 incomplete 267.990 s (one actual page / 12 declared), 02 stream error 325.355 s, 03/04 cancelled; 16 other cases never started. Not a completed benchmark.
- Claude Opus 4.8 `20260905-121022-2urf3tl6`: 03/08 timed out at 900 s. Evaluator exported copied basketball pages for diagnosis only.

## Scope and remaining limits

- Fact consistency uses a short shared basis/source table and a main-writer review of actual text, tables, charts and sources. No automatic semantic fact registry/lint service; real drafts still show unsupported facts and inappropriate causal certainty.
- Text capacity remains estimated. Audit supports resolved solid-color contrast; complex background/occlusion is unmeasured and requires viewing. Card geometry thresholds remain unchanged; planner preserves page count/order/type.
- Images have hard per-backend/overall deadlines, progress/heartbeat and full search/download/filter fallback. Offline acquisition only uses local/cache or explicitly authorized decorative placeholders; real-subject images remain unresolved when unavailable. Image offline is not a promise that all runtime dependencies/font downloads are offline.
- CJK fonts are embedded as full data, not subsets; files can approach 39 MB. Font scanning was fixed, but cross-application typography still differs. Smooth lines with four or more points remain flattened in native PPTX and produce an explicit warning. SVG icons remain movable/resizable images, not individually editable native paths.
- Readonly review and run snapshots do not constitute an OS permissions sandbox. Bash has user permissions. Independent diagnostics are outside author output; reviewers bind scores to file hashes and leave unchecked dimensions null.
- Original 20-page new-energy project was copied only: PPTX 2.02 s, HTML 5.27 s, screenshots 20 pages / 16.10 s, all exit 0. Two orphan-line estimates remain. No fact certification and no original edits.

The implementation and first bounded evaluation cycle are recorded. Remaining priorities are stable actual tool dispatch/completion, source-backed content review and cross-format font fidelity; they must be remeasured in a fresh, comparable run before claiming quality/speed gains.

## 2026-09-06: longer timeout, unchanged authoring rounds

The user requested more waiting time without reducing generation rounds. Changed the runner default from 1200 to **3600 seconds**, retaining prompts, skill, checks and pi settings. No global configuration changes or commit/push.

Real pi / qihoo / 360zhinao-turbo-aippt-agent-260824 reran the same generic two-page case, with the same skill snapshot, concurrency 1 and no web research. It naturally completed in **1069.473 s**, 32 assistant turns / 34 tool calls, exit 0, no tool/stream errors, skill unchanged. PPTD/PPTX/HTML and page screenshots were all delivered by the author. The new timeout default was used without an explicit CLI override.

Independent prechecks passed; both PPTD page images were viewed. LibreOffice opened the original PPTX as two pages (3.217 s), and Chrome opened both original exported HTML pages. All four independently rendered images were viewed against the PPTD images: no obvious clipping, overlap or content loss; minor typography differences remain. PPTX/HTML hashes were rechecked after pi exited. The author model is text-only and explicitly skipped image visual judgment; its pixel checks are not visual review. This does not certify PowerPoint/WPS playback or the 20-case suite.

Runner regression tests: **14/14 pass**, 9.929 s; `git diff --check` passes. T009's generic pi smoke is now complete; the earlier failed runs remain historical evidence. Only the two-page case was rerun, not the full 20-case benchmark; no quality/speed improvement is inferred. [Detailed report](../../eval/reports/2026-09-06-long-timeout.md) and [file-bound evidence](../../eval/reports/2026-09-06-long-timeout-evidence.json).

## 2026-09-06: full20 with the longer deadline

The user approved the new full run: pi / qihoo / 360zhinao-turbo-aippt-agent-260824, thinking off, web allowed, concurrency 2, 3600 s per case. Authoring rounds and the frozen skill were retained. Batch wall time **20963.615 s** (5 h 49 min 24 s); all 20 cases ended. Statuses: **8 timed_out, 8 incomplete, 2 execution_failed, 1 needs_input, 1 generated_unreviewed**. No implicit whole-case reruns or evaluator-authored delivery files. pi's own API retries remain recorded.

Four formal projects contain PPTD/PPTX/HTML: 06/08/14/15. Only 08 (a justified pending-input host-script framework, 2467.714 s) and 14 (generation ended, 2668.151 s) naturally finished; 06/15 timed out despite existing files. Eight cases left formal PPTD, **89 pages**. Case19's additional one-page pattern test and case17's 29 saved research HTML files are excluded from formal output counts. Original runner inventories/statuses remain unchanged.

All 20 independent review records pass local evidence-hash validation; unchecked/unavailable dimensions remain null. Four original PPTX files were opened with LibreOffice and sampled against original exported HTML opened in Chrome. The author360 model accepts text only; its image read and custom pixel/DOM scripts do not prove visual review. A direct PowerPoint UI connection blocked for an abnormal duration and never opened a task file, so no Microsoft PowerPoint certification is claimed.

Observed blockers include wrong source-to-claim mappings, unsupported company capabilities, misleading health/safety advice, source-image relevance/final crop problems, font differences and opacity loss. Bounded read-only diagnostics verified that the existing GUID/XOR font payload does not match the EOT structure referenced by Microsoft's PowerPoint implementation documentation; CFF is allowed by that format, and a packaging-only fix has not yet been demonstrated to resolve all LibreOffice substitution. The opacity diagnosis distinguishes invalid author field placement, cross-format acceptance differences and a genuine text-alpha writeout omission. These new findings are recorded, not claimed fixed.

Execution findings are separated: 04/05/11/20 ended with literal tool-call text that was never dispatched; 18 ended with provider content_filter. Case10 had a stream error, pi's retry succeeded, and it later stopped with no pages; the existing runner's historical-error classification remains execution_failed. A large case19 write lacked its required path and failed; smaller modules were subsequently written. No undocumented upstream limit is inferred.

The run recorded pi 0.84.4 at startup, while the global executable was replaced during the batch and subsequently reported 0.85.1. Per-process versions were not captured, so timestamps only support before/after entry-change groups. **All 20 skill copies were unchanged**, but this is not a single-pi-version controlled experiment and no speed/quality improvement is claimed.

This continuation added evidence/reports/documentation and a narrow gitignore exception for eval/reports Markdown linked by these docs. It made no authoring runtime changes during the batch. `git diff --check` passes; earlier runtime test results above are historical, not rerun claims. No commit/push/npm publication. See [full report](../../eval/reports/2026-09-06-full20.md) and [bound evidence](../../eval/reports/2026-09-06-full20-evidence.json).

## 2026-09-07：续行与执行流程

本轮实现同会话有限续行、共享60分钟、分模块写入和现成检查工具/文字模型视觉边界；原20题与历史结果保留。npm test 45/45通过（实际包含39个eval Python测试），50.178秒，无跳过；真实本地pi 0.85.1回环协议验证确认上下文恢复及实际工具派发。

360代表题均已结束：两页题849.878秒自然完成三格式，独立看过全部两页PPTD/原HTML/原PPTX图像，存在箭头大小、圆角差异；电影题530.187秒content_filter，无正式稿；篮球3600.144秒超时，12页正式PPTD，无PPTX/HTML，静态复查仍有14项预警，实际页面的核心战术与六人角色错误未修正。篮球和电影未具备视觉评分材料；未使用格式实验代替正式交付。三例评阅均绑定实际文件哈希，未检查项保留null。

三例没有触发宿主续行，真实360完成率的续行增益尚未证实；未减少生成回合，未重跑完整20题。实测中发现的新内容问题仅追加到authoring-context的通用核定义/角色一致性说明，发生在冻结快照之后，未做新模型复测。详见[本轮记录](../../eval/reports/2026-09-07-continuation.md)。未commit/push。
