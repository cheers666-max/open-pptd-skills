# Phase 0 Research: 通用 Skill 质量框架

本研究基于当前源码及上一轮独立复现，并由两个只读研究任务分别检查质量契约和内容/素材契约。决定适用于所有主题；不将样本中的页码、企业、数值或特定版式写入框架规则。

## R1. 统一证据格式，保留旧工具入口

**Decision**: 新增版本化 QualityReport；原始报告保留，工具通过薄适配层输出同一契约。新 quality 命令只读取并校验报告/产物，不替所有工具做自动修复或运行任意任务。
**Rationale**: 当前 validate 只有 valid，PPTX 摘要只有 warning 数量，HTML 失败 JSON 可能 exit 0；结果不能稳定参与交付判断。
**Alternatives considered**: 重写所有脚本或新建工作流引擎过重；仅扩充 SKILL prose 无法拦截静默失败。
**Paths**: validate_deck.py、export_html.py、export_images.py、export_pptx.mjs、bin/open-pptd-skills.js。
**Acceptance**: 缺报告、坏报告、未知告警、过期哈希、部分页面不能得到完整通过；旧字段和有效退出语义保留。

## R2. 先修测试与可观测性，再启用硬门槛

**Decision**: 修测试 helper 的提前返回、CLI 转发不支持参数、子进程 signal/null 被视为成功、HTML JSON 错误退出；建立通用正负 fixtures。
**Rationale**: 当前两条 conversion 测试未执行核心断言；check 永远转发 validator 不接受的 --severity/--level。
**Alternatives considered**: 只增加测试数量无法解决假通过；依赖一个完整行业 case 不可分发且易过拟合。
**Acceptance**: fixture 准备失败即 fail；必需依赖缺失导致 required suite 不完整，可选 skip 计入覆盖。

## R3. Viewer 是浏览器渲染证据入口，PPTX 独立验收

**Decision**: Viewer 通过既有 CDP/export hook 提供 pageRef、elementId、结构化 warnings、异步字体/图片准备状态和实际文本测量。HTML 与截图共用；PPTX adapter 独立报告能力损失。
**Rationale**: 内部 catch 后占位不会成为 uncaught exception；当前 P6 类饼图错误能导出为文件。局部截图的报告还会错误重编号。
**Alternatives considered**: OCR 找“渲染错误”脆弱；PNG 大小和 ZIP 校验都不能证明内容正确。
**Acceptance**: 故意触发图表异常、未知元素、缺图、字体失败和选择页 3/5，均有正确身份与原因；浏览器结果不证明桌面 PowerPoint 兼容。

## R4. 能力表驱动作者约束与交付检查

**Decision**: 记录 feature × format 的 native/vector/raster/fallback/unsupported 表示方式、限制与 fixture 证据。当前支持项逐步验证；声明未验证者标 unknown。
**Rationale**: HTML 中的图标与复杂图表不保证 PPTX 原生支持；现有 16 个图标替换证明单换 fas: 不够。
**Alternatives considered**: 全页截图进 PPTX 违背默认可编辑目标；泛称“13+ 图表全部支持”掩盖后端差异。
**Acceptance**: 已有饼图与 SVG 图标语义保留；任何内容丢失阻断默认交付。有意栅格化只能在任务策略明确允许时记录为 degraded。
**Scope**: 本轮不新建图表引擎，不承诺所有高级图表都可原生编辑；盘点、拦截不支持项及修现有通用故障。

## R5. 共享上下文采用 sidecar，规范要求变成可检查输入

**Decision**: project-context.json 为机器可检查的主文件；DESIGN_CONTEXT.md 与逐页作者说明由独立 prepare_context.py 生成，不让 design_system_loader 承担总编排职责。
**Rationale**: 当前 PPTD 格式不承载来源模型，design_system_loader 仅 list/get/build-index；规范已有引文与 YAML 规则，缺少统一执行约束。
**Alternatives considered**: 修改所有 .page 语法成本高；只有 Markdown 难以检查版本与绑定。
**Acceptance**: 同输入同字节投影；页面任务带 context hash；研究、教学、内部汇报、局部编辑采用同一契约但不同要求。旧项目无 sidecar 仍可预览导出，完整内容检查显示未检查。

## R6. 来源、数值一致性、来源支持关系分别检查

**Decision**: Claim 分 external_fact/user_fact/derived/illustrative/assumption；数值有 metricId 与 scope。确定性规则处理绑定、引用、支持单位和简单声明式推导；语义结论由主写手有证据地审阅。
**Rationale**: 相同数字可能不同含义，不同数字可能不同年份；URL 存在不是事实真实。
**Alternatives considered**: 所有数字要求 URL 会误伤用户数据和教学示例；自动 LLM 仲裁不能作为可重复事实核验。
**Acceptance**: 正文、表格、图表均能追踪；来源缺失与未审阅分别标注；不隐式联网，不记录 API key，不执行任意公式代码。review 状态只是带依据的声明，不构成防伪认证。

## R7. 网络预算必须覆盖工作实际生命周期

**Decision**: --timeout 为单后端整次尝试预算，--budget 为整项命令预算；使用单调时钟和可终止的后端 worker，子进程内复用现有检索/有界下载。主进程统一进度、报告及写盘。
**Rationale**: 请求已有 15–45 秒 timeout，但搜索候选有结果后下载失败不回退；线程 cancel 无法终止挂起任务；tried/_tried 还会丢诊断。
**Alternatives considered**: 仅 future.result(timeout) 不能保证进程退出；多加 try/except 不能提供耗时界限。
**Acceptance**: 预算 + 2 秒清理上限，最长 5 秒无心跳；任何单槽失败均保留。旧 0/1/2 exit 契约保留。
**Network governance**: 默认 offline；只有用户任务已明确授权的研究/图片/VLM 才启用对应通道，凭据存在不视为授权。setup 可显式联网准备依赖，运行阶段不隐式安装/下载。

## R8. 离线替代尊重素材用途

**Decision**: 本地素材和缓存优先；仅 decorative 且允许替代的槽生成本地 SVG/渐变。身份相关或复刻指定图片缺失保持 unresolved。许可信息区分 known/unknown，不自动宣称可商用。
**Rationale**: 占位图不能替代真实对象；当前全幅背景硬要求与离线工作流需要在任务/设计约束下对齐。
**Alternatives considered**: 任意槽一律生成渐变会隐瞒内容缺失；让所有离线任务失败又破坏本地优先。
**Acceptance**: offline 零远端调用；代替物可追踪；模板规定素材不可被擅自替换。

## R9. 测量与设计启发式分开

**Decision**: 保留容量估算为预警，真实 DOM 测量为浏览器范围的溢出证据；纯色可解析前景/背景先启用对比度，复杂背景/未知遮挡给复核项。layout_planner 保留页数/内容，仅输出建议。
**Rationale**: 区域平均像素错误地把黑白文本判为 1.14:1；固定元素数、标题长度 silhouette、自动插页与教学和固定页数冲突。
**Alternatives considered**: 未校准 audit 直接阻断会迫使误改；estimatedHeight+4 不保证安全。
**Acceptance**: 已知真值正负样本；复杂范围显示 not_checked；连续教学页不改为 quote；卡片设计原则保留，几何启发式不独自证明违规。

## R10. SpecKit 补齐方式与治理

**Decision**: 保留 constitution v1.0.0，归档旧 feature 内容模板，引入官方固定提交的通用模板/脚本。使用文件/CLI contracts，项目不需要 REST/GraphQL。
**Rationale**: 当前 .specify 没脚本；已安装 Specify CLI 0.0.22 与新版发布资产命名不兼容。直接导入固定来源避免全局升级。
**Evidence**: .specify/upstream/provenance.json；官方来源 https://github.com/github/spec-kit/tree/4a7341a93d944d6efe153b71da4a1adb9c2b578c。
**Compatibility adaptations**: 最新 create-new-feature 不创建 Git branch，故单独创建；agent-context 迁到 extension 且参数变成 plan 路径。均使用实际官方代码，不假称旧命令成功。
**Constitution gate**: 现状存在隐式联网与虚假能力承诺；方案明确修复，不豁免原则、不修改宪章。若后续要求默认在线或允许违背默认编辑性，必须另提治理变更，本规划不包含该变更。

## Post-design consistency review

两次只读跨文档复核发现并已在规划中修正：内容哈希与审阅自引用、禁止降级的优先级、MVP 子进程错误处理前置、报告发现歧义、素材写入与终审顺序、编辑前基线、交付降级策略字段、网络缺省/显式 schema 区分、页级 notes 绑定。具体关系约束见 data-model.md 与 contracts/quality-policy.md；不是实现完成声明。
