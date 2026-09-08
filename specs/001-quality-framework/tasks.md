# Tasks: open-pptd 轻量优化

## 2026-09-08：减少生成返工与保留修复闭环

- [x] T021 生成 helper 与 validator 提前拒绝错误的页面/元素结构，提供页和字段位置；完成失败样本回归。7 项结构、21 项布局、8 项 Node 功能回归通过；保留数字/布尔文本与零高线条兼容。
- [x] T022 修复 solid fill 透明度的 HTML/PPTX 差异，覆盖颜色/元素 alpha 组合与原生导出证据。5 项 Chrome 像素/PPTX XML 新回归、16 项既有渲染及14项 PPTX 回归通过；不扩称全部跨阅读器透明度兼容。
- [x] T023 保留局部图片重搜的其他槽位/来源记录，重建后复用有效素材缓存，覆盖变更与失败边界。41 项图片搜索回归通过；按文件内容身份保留来源，变化/缺失/歧义素材不会错误沿用旧记录。
- [x] T024 提供复用现有脚本的固定检查/导出入口，支持按页面与依赖变化复检、保留退出码与日志摘要。14 项回归及真实三页 Chrome/PPTX/HTML 导出通过；保护失败时源文件，完整保留 PPTX 警告，PNG 缓存不能代替看图。
- [ ] T025 精简技能重复上下文，接入早期模块检查与批量修复；保留生成内评审修复，默认不自动运行七维独立评分。
- [ ] T026 完成本轮回归、真实通用样页、技能场景与打包验证；逐项提交并推送 GitHub 的 360-intranet 分支。

独立后续实验：字体跨阅读器一致性、服务端真实推理控制与整题速度 A/B。未验证的实验不计为本轮完成项。

## 2026-09-08：360 内网分支适配

- [x] T016 在独立 `360-intranet` 分支实现在线图片下载、校验、去重上传、remote/embed HTML 和可选网页发布；保留原稿与失败时的上次产物。
- [x] T017 完成16项在线回归、真实Chrome最终网页检查、既有回归、打包核对和技能场景复测；记录真实网关404/401，未把模拟服务成功当成360线上发布成功。

用户本次明确授权提交并推送独立分支，覆盖以下历史任务中的“不提交或推送”约束。

**Input**: [spec.md](spec.md)、[plan.md](plan.md)
**状态**: 原轻量实施清单 9 项；用户追加 20 题 pi 验证后增加 2 项评测任务。取代已归档的 40 项方案。

## Phase 1 — 可信基线

- [x] T001 修 test/fusion-features.test.js 的 Python -c 调用与准备失败直接 return，确保 fixture 真正创建、断言执行；使用现有 npm test 建立修复前基线。（FR-008）

## Phase 2 — 共用前置条件

复用现有目录、CLI、依赖与测试设施，无需新基础模块、数据模型或初始化任务。

## Phase 3 — US1: 作者约束与终审 (P1)

**目标**: pi 按可用工具执行，作者共享同一份简短约束，内容在交付前经过终审。
**独立验收**: 检查顺序/可用并行两条路径；研究数字与本地教学资料适用不同来源要求；指定页编辑不扩大范围。

- [x] T002 [US1] 在 skills/open-pptd/SKILL.md 与 skills/open-pptd/reference/authoring-context.md 提供简短共享作者模板，移除固定 task 工具/页数强制并行/O(1) 承诺；注入 YAML 块标量、容量估算、emoji 禁令、目标格式图标限制、页数/风格/逐页职责。（FR-001/002）
- [x] T003 [US1] 在 skills/open-pptd/SKILL.md 与 skills/open-pptd/reference/authoring-context.md 加入数字/单位/时期/口径/来源表及素材改写后的主写手终审，核对重复/跳跃、来源支持关系与编辑范围；用通用错值/异期/理论实测/教学示例走读，不新增事实 registry 或语义 lint 服务。（依赖 T002；FR-002/003）

**第一批完成**: T001–T003。改进日常作者行为，尚不代表工具故障已修复。

## Phase 4 — US2: 素材与输出失败可见 (P1)

**目标**: 使用现有命令完成有预算的搜图和可诊断的导出。
**独立验收**: fake backend 黑洞/下载失败/筛选失败、离线图片、饼图和图标、JSON 非零退出及局部页身份。

- [x] T004 [US2] 在 skills/open-pptd/scripts/image_search/search_images.py、pool.py、slots.py 与 skills/open-pptd/scripts/image_search/tests/test_search.py 实现单后端 --timeout 30/整体 --budget 120、可终止截止、下载/筛选失败回退、stderr 进度与 <=5s 心跳、tried 诊断和 --offline；仅许可装饰可本地替代，凭据不自动授权 VLM。同步 skills/open-pptd/reference/image-search.md 与 SKILL.md 的离线图片/背景规则，补受控短预算和零图片网络调用回归。（FR-004/008）
- [x] T005 [US2] 在 skills/open-pptd/scripts/viewer.html 修饼图图例异常并让调用方看到渲染失败；在 export_html.py、export_images.py 修 JSON 异常退出和局部页编号，在 bin/open-pptd-skills.js 修 child error/signal 成功误报；用 test/render-health.test.js 覆盖对应故障，无新质量报告协议。（FR-005/008）
- [x] T006 [US2] 在 skills/open-pptd/scripts/vendor/open-ppt-engine/adapters/pptd.mjs 修 fas 图标无关字符替代，在 skills/open-pptd/scripts/export_pptx.mjs 增加 --report 原始详情并保证 JSON/stderr/退出结果一致；用 test/pptx-export.test.js 检查实际图标路径与丢失诊断，复用本地资源。（FR-005/008）

## Phase 5 — US3: 可靠检查与保守建议 (P2)

**目标**: 已知排版问题可发现，设计和固定页数不被机械改写。
**独立验收**: 内联大字/固定行高/CJK、黑白与低对比、复杂背景未确定、固定页数/页型保留。

- [x] T007 [US3] 在 skills/open-pptd/scripts/validate_deck.py 修容量估算遗漏，在 audit_rendered.py 修纯色对比/错误解析与不确定遮挡分类；用 skills/open-pptd/tests/test_layout_checks.py 补已知正负样本，保留人工看图，不默认自动扩高、不新建 DOM 布局系统。（FR-006/008）
- [x] T008 [US3] 在 skills/open-pptd/scripts/layout_planner.py 与 test/fusion-features.test.js 将节奏处理改为保留页数/顺序/页型/额外字段的建议输出；允许连续教学布局，说明卡片几何启发式边界，本轮不调整 validate_deck.py 卡片阈值。（依赖 T001；FR-007/008）

## Phase 6 — 整合与复验

- [x] T009 在 skills/open-pptd/SKILL.md 接入修复后的检查顺序、长稿可选节奏建议、渲染后辅助审计及导出 warnings 复核；跑 npm test 与本次 Python 测试，在实际 pi 可用入口完成小型通用文稿 smoke，把命令/结果/未检查项记入 specs/001-quality-framework/validation.md；新能源案例仅副本可选复验，所有改动不 commit/push。（依赖 T001–T008；FR-001–008）

## Dependencies and Execution

T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009 为建议顺序，默认一个 pi 会话顺序完成，按批验证即可。共享 SKILL/test 文件顺序修改，减少合并开销。

并行不是完成条件：US1 两项共用文件，顺序执行；US2 的 T005/T006 满足基线后可分不同文件独立处理；US3 的 T007/T008 可独立实现但最终验证串行。本次不标 [P] 或要求额外子代理配置。

## Requirement Mapping

| 需求 | 任务 | 验收 |
|---|---|---|
| FR-001、FR-002、FR-003 | T002/T003/T009 | SC-001 |
| FR-004 | T004/T009 | SC-002 |
| FR-005 | T005/T006/T009 | SC-003 |
| FR-006、FR-007 | T007/T008/T009 | SC-004 |
| FR-008 | T001/T004–T009 | SC-005 |

## Implementation Boundaries

不沿用旧 T001–T040 的编号含义；归档需求不默认进入后续迭代。代码修复只限对应问题类，发现新问题另记证据再定范围。测试和 smoke 在实施时执行，本轮文档检查不代表这些功能已经通过。

## 用户追加：固定验证集与真实 pi 运行

- [x] T010 保留用户20条原始题目，建立可选的开发评测 runner：独立 skill 快照、有限并发/截止、隔离 pi 配置、流式日志、速度/产物状态、默认空分的独立评阅。它不进入日常 skill 生成流程，不安装全局扩展。
- [x] T011 完成真实模型链路试跑与完整20题评测，读取实际产物/图像并核对关键来源；使用 LibreOffice 原生打开 PPTX 补查网页预览遗漏。根据共同缺陷修复后复验受影响题，区分模型接入、生成失败、质量问题；记录实际未检查项，不把不同模型运行直接作为 skill 提速对照。

## 2026-09-05 验收结果

T001–T008、T010–T011已完成实施/执行。T009的流程挂接与本地测试已完成，但两页通用pi smoke两次均未完成三格式，因此保留未勾选；不把08题待填框架交付替代此验收条件。首轮20题0/20完成三格式，修订后的06/08复测为1份待填三格式、1份不完整。任务执行结束不等于质量达标，详见[validation.md](validation.md)与[逐题报告](../../eval/reports/2026-09-05.md)。

## 2026-09-06 补充验收

按用户要求只延长整任务截止至3600秒，保持生成回合与检查流程。360zhinao同题两页通用pi smoke在1069.473秒自然完成三格式；独立校验、两页截图查看、LibreOffice打开PPTX及Chrome打开原始HTML均已完成，T009现在勾选。作者模型无视觉输入，独立看图由本助手完成；当时完整20题尚未按新截止重跑，见[复测报告](../../eval/reports/2026-09-06-long-timeout.md)。

## 2026-09-06 完整20题复测

- [x] T012 按用户确认，用pi / qihoo / 360zhinao-turbo-aippt-agent-260824、并发2、3600秒逐题截止完整运行原20题；保留生成回合，不代写或补导出；完成20份独立评阅、四份原PPTX/HTML打开检查、正式稿与实验/研究文件分类，记录事实/专业/图像/排版/交付及执行问题。（用户追加复测）

批次20963.615秒，8 timed_out、8 incomplete、2 execution_failed、1 needs_input、1 generated_unreviewed。4份正式三格式文件；08待填框架和14生成自然结束，06/15仍超时。8份正式PPTD共89页，19另1页实验不计。20份评阅的文件证据哈希均通过一致性检查；不表示质量合格，未检查维度保留null。运行中全局pi入口版本变化，skill副本均未变，不作为单一pi版本的严格控制实验。

[完整报告](../../eval/reports/2026-09-06-full20.md)列出下一轮候选和实际效果。下一轮尚未实施，当前不新增复杂平台、不调整个例阈值、不提交或推送。

## 2026-09-07 执行稳定性改进

- [x] T013 在 eval/run_pi.py 实现同会话有限续行、共享原截止、逐次证据与正式文件判定；区分已恢复与终态接口错误。补受控故障回归及真实本地 pi 会话恢复验证，保持缺材料、拒绝、超时及清理边界。
- [x] T014 精简完善 SKILL.md、pptd-quickstart.md、authoring-context.md：分模块写入、按页纲补齐证据、复用现成检查、文字模型的独立看图边界；保留内容/生成回合/原必需检查。
- [x] T015 用 pi / qihoo / 360zhinao-turbo-aippt-agent-260824 在新快照下并发运行通用两页与原验证集代表题，保留60分钟总截止；如实记录实际完成、续行效果和独立可检查范围，不把小批次当全20题通过。完成本轮本地回归，保持未提交。

本轮执行结果：通用两页849.878秒完成三格式并独立查看；电影题530.187秒content_filter终止；篮球3600.144秒超时，留下12页正式PPTD，无PPTX/HTML，实际页面存在核心战术与六人角色问题。T015勾选表示复测与记录完成，不表示质量通过；三例未触发宿主续行，真实续行协议由本地原生pi验证。实测后仅在authoring-context补概念核验/图示实体一致性两处通用说明，未做新模型复测。详见[本轮报告](../../eval/reports/2026-09-07-continuation.md)。

## 2026-09-08 复用 OBS 配置

- [x] T019 支持显式加载现有 OBS YAML，保留附件接口，新增 S3 上传、唯一前缀、防冲突、对象及公开读回校验、部分失败报告；密钥不写入仓库。
- [x] T020 使用现有郑州 OBS 配置完成真实两页网页发布，验证 5 个对象和 6 个浏览器视口/页面组合；修复 online 出口窄屏溢出，更新 skill、示例和验证记录。29 项在线测试、npm 42 通过/4 字体跳过，打包排除私有配置。
