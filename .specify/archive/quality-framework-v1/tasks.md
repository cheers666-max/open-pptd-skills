# Tasks: 通用 Skill 质量框架

**Input**: spec.md、plan.md、research.md、data-model.md、contracts/、quickstart.md
**Status**: 规划完成，实施未开始；40 项全部未勾选。
**Tests**: spec FR-021 明确要求通用正负回归；测试任务用于验证真实行为，不以“函数存在”或无断言返回验收。
**Organization**: Setup → Foundation → 按 User Story 交付 → 分发验收。P 仅表示在列明前置满足后可并行；同一文件不并发改。

## Phase 1: Setup

**Purpose**: 建立可信测试入口与自包含样本，不把实战项目纳入必需依赖。

- [ ] T001 修复 Python 内联代码/脚本的测试 helper，在 test/helpers.js 与 test/fusion-features.test.js 中消除准备失败提前 return，增加实际创建 fixture 与执行转换的断言，缺可选依赖用显式 skip。（FR-019/021）
- [ ] T002 [P] 在 skills/open-pptd/tests/fixtures/quality/ 与该目录 README.md 建立研究、教学、内部汇报、局部编辑四类最小样本及已知缺陷清单，使用虚构/公开可复用素材，不拷贝 projects/ 真实数据。（FR-020/021）

## Phase 2: Foundation

**Purpose**: 冻结共享身份、状态与跨语言契约；前置 T001–T002。

- [ ] T003 [P] 在 skills/open-pptd/reference/schemas/、scripts/quality/report.py 与 scripts/quality-report.mjs 落地 contracts 的报告模型与序列化，保留 rawReports 和未知 code；制定 schema 同步检查，避免规划/分发契约漂移。（FR-001/002/018）
- [ ] T004 [P] 在 skills/open-pptd/scripts/quality/identity.py 与 scripts/quality-identity.mjs 实现内容投影 fingerprint（排除审阅/报告）、独立 evidenceFingerprint、稳定 pageRef 与媒体/context/策略身份；共享向量验证跨语言一致及“添加审阅不自失效、修改主张必失效”。（FR-001/003）
- [ ] T005 在 test/quality-contracts.test.js 验证 schema 正负样本、缺覆盖、旧版本、非法路径、损坏报告及未知告警状态；固化 contracts/quality-policy.md 的判定表，包含“缺覆盖 + 禁止降级”仍 blocked。（依赖 T003–T004；FR-001/002/003/021）

**Checkpoint**: 只具有可信测试/契约基础；不能宣称产品质量功能完成。

## Phase 3: US1 — 有依据的交付结论 (P1 / MVP)

**Goal**: 文件成功与内容成功分开，已知丢失和未覆盖可见。
**Independent Test**: 通用 chart/icon 文稿注入失败、缺格式、局部范围、过期结果；结构/导出 profile 能准确判定，未实现内容检查显示未检查。

### Tests

- [ ] T006 [P] [US1] 在 test/cli-quality.test.js 添加失败 JSON/非零退出、child spawn/signal、报告写入失败及 legacy 摘要兼容测试，先复现当前失败传播漏洞。（FR-018/019/021）
- [ ] T007 [P] [US1] 在 test/render-health.test.js 添加饼图图例、未知元素、缺图、图标保留、字体等待和 --page 3,5 身份测试，断言内部 catch 产生的占位也能被观察。（FR-003/004/005/021）

### Implementation

- [ ] T008 [US1] 在 skills/open-pptd/scripts/viewer.html 增加结构化 render-health hook，记录 pageRef/elementId、资源准备和异常占位；修通用饼图图例 const 递增错误，保留调试占位但不返回健康状态。（FR-004）
- [ ] T009 [US1] 在 skills/open-pptd/scripts/export_html.py 与 export_images.py 消费 health hook、修局部页映射及 JSON 异常退出，增加 --report 并用本次临时产物避免旧文件混入。（依赖 T008；FR-003/004/019）
- [ ] T010 [P] [US1] 在 skills/open-pptd/reference/capabilities.json 盘点已有图表/形状/图标的每格式表示方式、限制及 fixture ID；在 scripts/quality/capabilities.py 校验已验证/未知/丢失分类，不把 13+ 类型等同全部原生支持。（FR-005）
- [ ] T011 [US1] 在 skills/open-pptd/scripts/vendor/open-ppt-engine/adapters/pptd.mjs 复用本地 FA sprite/SVG 路径转换图标，修无关字符替换；无支持路径明确报 loss，并验证 PPTX 中图标语义及可编辑边界。（依赖 T007/T010；FR-004/005）
- [ ] T012 [US1] 在 skills/open-pptd/scripts/export_pptx.mjs 输出 --report 完整 warnings/产物身份，JSON 摘要保持旧字段；按能力损失阻断正式导出，异常/临时输出行为与 T009 一致。（依赖 T010/T011；FR-003/004/005/018/019）
- [ ] T013 [US1] 在 skills/open-pptd/scripts/validate_deck.py 添加统一 --report 适配，保留旧 --output/valid/issueCounts 的静态语义，声明 text/table/chart 等当前实际覆盖，解析异常不得返回空结果。（FR-001/002/018）
- [ ] T014 [US1] 在 skills/open-pptd/scripts/quality_gate.py 与 bin/open-pptd-skills.js 增加只读 quality 入口，按 profile 与固定 stage 文件/--reports 清单核验身份及 decision，拒绝重复歧义；同时实现公共 child error/signal/null 非成功处理，使 T006 在 MVP 可通过；缺内容/审阅不得虚构通过。（依赖 T009/T012/T013；FR-001/002/003）

**Checkpoint M1**: T001–T014 是建议 MVP（14 项）。运行 T006/T007 与旧接口回归；交付范围清楚，未实现能力仍可见。不得将此阶段视作本特性全部完成。

## Phase 4: US2 — 共享事实、作者约束和叙事 (P1)

**Goal**: 通用内容来源与跨页协作，不为特定主题编规则。
**Independent Test**: 四类内容场景验证合法来源、同口径冲突、推导、绑定、版本漂移和编辑边界；内容检查可单独运行。

- [ ] T015 [P] [US2] 在 skills/open-pptd/tests/test_content.py 与 test_context.py 建立来源类型、同值异义/异期同指标、比例换算、text/table/chart 绑定、context 变化失效、添加审阅不自失效、编辑前基线及共享资源越权正负样本。（FR-006/007/008/009/010/021）
- [ ] T016 [US2] 在 skills/open-pptd/scripts/prepare_context.py 与 scripts/quality/context.py 读取 project-context sidecar（显式网络/交付降级策略），编辑前捕获且不覆盖 baseline，输出确定性 DESIGN_CONTEXT.md/逐页作者说明；不生成虚假依据或自动勾审阅；不改 design_system_loader 的职责。（FR-006/017/018）
- [ ] T017 [US2] 在 skills/open-pptd/scripts/validate_content.py 与 scripts/quality/content.py 实现来源/口径/绑定/安全声明式派生规则，区分不支持计算与矛盾，旧项目缺 sidecar 为 not_checked。（FR-007/008/009/018）
- [ ] T018 [US2] 在 skills/open-pptd/scripts/quality/review.py 与 reference/authoring-context.md 定义主写手 content/storyline 审阅记录、输入 hash、范围和依据要求，过期审阅无效；以 baseline 检查页面/共享资源白名单及关联页，未编辑历史主张只披露未重核。（FR-008/010）
- [ ] T019 [US2] 在 skills/open-pptd/SKILL.md step2→step3 和 reference/authoring-context.md 注入共享 context hash、核准主张、邻页职责、YAML/容量/目标能力约束；顺序和并行写作使用相同终审协议。（依赖 T016–T018；FR-006/010/015/017）
- [ ] T020 [US2] 在 skills/open-pptd/scripts/quality_gate.py 接入内容/审阅覆盖，验证引用字段通过不等于事实支持，四类场景适用策略不同；记录未绑定事实候选的复核处理。（依赖 T014/T017/T018；FR-002/007/008/009/010）

**Checkpoint M2**: 新作者工作流可追溯，旧项目继续预览导出，缺内容证据不会被完整验收放行。

## Phase 5: US3 — 有预算的素材与离线执行 (P2)

**Goal**: 网络/素材故障可限时恢复，替代可追踪。
**Independent Test**: 可控后端黑洞、下载失败、筛选失败、异常和 offline；不依赖实时外网可用性。

- [ ] T021 [P] [US3] 在 skills/open-pptd/tests/test_assets.py 与 scripts/image_search/tests/test_search.py 添加可终止 fake backend、截止清理、回退、单槽异常、无隐藏联网和诊断保留测试。（FR-011/012/013/014/021）
- [ ] T022 [US3] 在 skills/open-pptd/scripts/image_search/backend_worker.py、pool.py 与 search_images.py 实现单调时钟 --timeout/--budget、可终止子进程和全槽有界调度；搜索/下载/筛选失败均可回退，禁止用线程 cancel 冒充硬截止。（FR-011/012）
- [ ] T023 [US3] 在 skills/open-pptd/scripts/image_search/slots.py 与 search_images.py 增加 semanticRole/allowFallback、--offline/--network 策略、本地/缓存优先和仅装饰槽替代；身份/证据/模板槽缺失保持 unresolved。（依赖 T022；FR-013/014）
- [ ] T024 [US3] 在 skills/open-pptd/scripts/image_search/search_images.py 修 tried/_tried 诊断链，输出及时进度/心跳和 JSON/--report；主进程统一文件提交、候选去重及部分失败清单，保留原 0/1/2 语义。（依赖 T022/T023；FR-011/012/014/019）
- [ ] T025 [US3] 在 skills/open-pptd/scripts/export_html.py、export_images.py、export_pptx.mjs 与 download-fonts.py 分离显式 setup 和 offline run，运行时缺依赖/字体明确报告，不隐式 pip/npm/远程下载；保留显式准备入口。（依赖 T009/T012；FR-013）
- [ ] T026 [US3] 在 skills/open-pptd/scripts/quality_gate.py 与 tests/test_assets.py 复核预算 +2s、心跳 <=5s、key 不改变网络策略、降级可定位和许可未知不被标已授权；与内容/作者策略保持一致。（依赖 T020/T024/T025；FR-011/012/013/014）

## Phase 6: US4 — 可靠测量与保守节奏建议 (P2)

**Goal**: 真实问题可测量，设计语义和固定页数保留。
**Independent Test**: 已知真值的富文本/CJK/固定行高/纯色对比/复杂叠层/教学连续页；不修改 case。

- [ ] T027 [P] [US4] 在 skills/open-pptd/tests/fixtures/quality/layout/ 与 test/render-layout.test.js 建立真实 overflow、正确布局、黑白/低对比、透明覆盖与复杂背景未检查样本，定义浏览器范围真值。（FR-015/016/021）
- [ ] T028 [US4] 在 skills/open-pptd/scripts/validate_deck.py 修段落、固定行高和内联字号的估算遗漏并明确 estimated 方法；不实现默认 estimatedHeight+4 自动修复。（FR-015）
- [ ] T029 [US4] 在 skills/open-pptd/scripts/viewer.html 扩展已存在的 health hook，读取实际文本几何/溢出与字体状态，保留 pageRef/elementId；DOM 测量不得替代 PPTX 证据。（依赖 T008/T027；FR-015）
- [ ] T030 [US4] 在 skills/open-pptd/scripts/audit_rendered.py 以可解析样式和背景测纯色对比，修解析失败为空结果、透明相交误判；复杂背景/未知遮挡明确 advisory/not_checked，不使用区域均色冒充文字颜色。（依赖 T029；FR-016）
- [ ] T031 [P] [US4] 在 skills/open-pptd/scripts/layout_planner.py 与 test/fusion-features.test.js 改为保留页数/字段/页型的建议输出，以 layoutIntent/continuityGroup 判断适用性；卡片启发式取证后只改善分类证据，不简单提阈值或按 cover/final 普遍豁免。（FR-017）
- [ ] T032 [US4] 在 skills/open-pptd/scripts/quality_gate.py 与 reference/quality-workflow.md 接入测量覆盖/required 与 advisory 策略，校验已知真值误报为零、固定页数不变及无安全修复时保持只读。（依赖 T028/T030/T031；FR-002/015/016/017）

**Checkpoint M3**: US3/US4 均满足受控验收，复杂未知范围公开；没有全景视觉“百分百正确”的承诺。

## Phase 7: US5 — 分发、接口与默认工作流 (P2)

**Goal**: 安装后的 skill 能执行同样的契约，不依赖源码目录或实战 case。
**Independent Test**: 从本地包隔离安装后执行四类场景，检查 CLI/help/失败路径/多格式范围。

- [ ] T033 [P] [US5] 在 test/packaged-workflow.test.js 建立隔离安装的 CLI/文件契约 smoke，检查所有新增 reference/schema/scripts 被分发、旧项目无 sidecar 可用，以及坏参数/缺依赖不会成功。（FR-018/019/020/021）
- [ ] T034 [US5] 在 bin/open-pptd-skills.js 与 skills/open-pptd/scripts/validate_deck.py 对齐 check 的 --page/--severity 实际筛选、--level keep/auto 边界，复核 T014 已实现的公共 child error/signal 处理；核对 convert/screenshot 帮助与实际能力，不保留宣称可用却静默不执行的入口。（FR-018/019）
- [ ] T035 [US5] 在 package.json 与 test/packaged-workflow.test.js 仅按实际缺项修分发清单/运行入口，执行本地 pack 后隔离安装；不 publish，不更改已有 npm 版本承诺。（FR-020）
- [ ] T036 [US5] 在 skills/open-pptd/SKILL.md 与 reference/quality-workflow.md 落实最终主流程、显式 offline/setup、素材语义、所有改写完成后的最终终审/校验及 delivery gate；细节按需加载，不强制特定模型、统一元素数或用户每步确认。（依赖 US1–US4；FR-006/010/013/017/020）
- [ ] T037 [US5] 在 test/packaged-workflow.test.js 和 specs/001-quality-framework/quickstart.md 执行四类完整场景并记录适用/未检查能力；验证改页后报告失效和格式一致，真实 case 仅在副本上可选复验。（依赖 T033–T036；FR-003/018/019/020/021）

**Checkpoint M4**: 本框架特性才具备完整验收条件，所有 required 阶段需实际完成。

## Phase 8: Polish & Cross-Cutting

- [ ] T038 [P] 在 docs/quality-migration.md、README.md 与 README_EN.md 说明旧 JSON/退出码、新报告/状态、offline 准备、图表/图标能力、旧项目补充内容覆盖及取消自动插页的迁移；删除未经验证的功能承诺。（FR-005/018/020）
- [ ] T039 在 .github/workflows/quality.yml 与 package.json 明确 required/optional 测试层与可用平台/Node/Python 矩阵；验证现有最低版本，缺必需依赖不得 silent skip，未运行平台不宣称通过。（FR-019/020/021）
- [ ] T040 在 specs/001-quality-framework/checklists/implementation.md 汇总 FR/SC 证据、四场景验收、误报/漏报/未检查边界及分发结果；审查 git diff 不包含案例定制规则、敏感素材或越权发布，并给出实际剩余风险。（FR-001–021）

## Dependencies & Execution Order

- T001/T002 → T003/T004 → T005 是共同基础。
- US1 T006/T007 先复现；T008→T009，T010→T011→T012，与 T013 合到 T014。
- US2 依赖基础契约；T016/T017 的独立模块可分工，T018/T019/T020 顺序合入。T020 依赖 T014。
- US3 核心 worker 可在基础后开发；导出 offline 改动 T025 必须等 US1 导出改动稳定；T026 集成依赖 T020。
- US4 T029 依赖 T008 hook；T031 的 planner 与测量模块可并行，但其 fusion 测试修改需等 T001。
- US5 T033 可先写安装测试；T034 涉及 CLI/validator，必须在对应 US1/US4 改动之后合入；T036/T037 在 US1–US4 之后。
- T038 可与最终复验并行，T039/T040 为收口。P 不授权同文件并发写入。

### Parallel examples by story

- US1：T006 与 T007；T010 在 schema 冻结后可与 T008 并行。
- US2：T015 的内容/上下文测试可拆给不同文件；T016 context 与 T017 content 模块独立，但共享接口先冻结。
- US3：T021 先完成可控后端；T025（导出准备）与 T022–T024（image_search）分属不同文件，满足前置后可并行。
- US4：T031 planner 可与 T028–T030 测量开发并行。
- US5：T033 安装测试与 T038 文档可并行，最终 T037 必须等待实现与分发齐备。

## Traceability

| Requirements | Story / tasks | Outcome |
|---|---|---|
| FR-001、FR-002 | T003–T005、T013/T014、T020/T032 | SC-001/005 |
| FR-003、FR-004、FR-005 | T007–T014、T037/T038 | SC-001/005 |
| FR-006、FR-007、FR-008、FR-009、FR-010 | T015–T020、T036 | SC-002/003/007 |
| FR-011、FR-012、FR-013、FR-014 | T021–T026、T036 | SC-004/008 |
| FR-015、FR-016、FR-017 | T027–T032、T016/T019 | SC-002/007 |
| FR-018、FR-019、FR-020、FR-021 | T001/T002/T005/T006、T033–T040 | SC-006/008 |

## Implementation Strategy

1. 先执行 14 项 MVP，得到有范围的真实验收，不追求一次重写全部架构。
2. US2 的内容与主写手协议进入默认生成步骤；不因数字 lint 通过宣称所有事实已核实。
3. US3/US4 通过受控真值验收后启用，避免误报驱动作者改坏内容。
4. US5 验证分发后的完整流程；最终只报告实际覆盖的平台和能力。
5. 本轮仅规划。用户后续进入实施后才执行；commit/push/npm 发布不由这些任务自动授权。
