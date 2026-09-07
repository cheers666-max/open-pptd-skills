# Implementation and validation log

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
