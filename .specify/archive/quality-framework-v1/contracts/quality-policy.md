# 质量状态与交付策略契约

版本：open-pptd-quality/1.0。实现必须以本文件语义为准；JSON Schema 只保证结构，不能代替这些关系约束。

## 状态与覆盖

| check.status | 含义 | 禁止推断 |
|---|---|---|
| passed | 在声明范围内实际执行且满足规则 | 不代表未声明的其他检查也通过 |
| degraded | 实际发生可定位的替代/能力降低 | 不等于任意降级都可交付 |
| not_checked | 未运行、证据不足、不支持或结果过期 | 不能变成 passed |
| failed | 有确定反证或执行导致检查失败 | 不能只保留 warningCount |

issue.severity 与 check.status 分开：heuristic 可以是 warning，不因此声称确定不合格。工具执行失败还要保留 origin 与 error 类型。

## Profile

- structural: 验证项目结构、引用资源和声明范围，保留未做的内容/渲染检查说明。其 ready 只表示 structural ready。
- delivery: 默认要求 PPTD、PPTX、HTML；只有明确任务策略可以缩减格式。必需覆盖包括结构/资源、适用的内容依据与主写手终审、全范围 render health、可测文本布局、所选格式能力与产物完整性。
- 对比度/遮挡的复杂范围一期属于 advisory；报告其未检查，不把它们伪装成已经全覆盖。所有 enabled/required 检查来自版本化任务策略，不允许适配器自行降低要求。
- 不涉及外部事实仍需明确的任务类型/内容审阅证明，不用生成虚假外部来源。旧项目缺上下文的 delivery 为 incomplete。
- 离线无素材需求可以资源检查通过；不能把“图片查询没返回”当“文稿不需要图片”。
- 编辑任务先验证 editBaseline 和修改白名单；内容/叙事检查的必需范围为修改页及关联内容，未编辑历史主张不强迫重新证实且须披露。render/export 仍覆盖完整交付页面集合。
- required 检查及范围由版本化 deliveryPolicy 推导；每个例外必须列在 allowedDegradations 并有任务授权依据。报告的 required 仅作回显，不具有放宽策略的效力。

## Decision（按此顺序）

1. 证实内容丢失、渲染错误占位、错误页序/页数、未解析必需素材、格式缺失等 required 检查 failed → blocked。
2. required 检查 degraded，且替代未被任务策略明确允许或损失内容含义 → blocked；即使同时缺审阅也不能降成 incomplete。
3. required 检查缺失、not_checked、报告过期、覆盖不足，且无确定失败或禁止降级 → incomplete。
4. required 检查都满足，存在允许的 degraded、普通 warning 或 advisory 未检查 → ready_with_warnings，并列出其实际含义。
5. required 检查都通过且没有待披露项 → ready。

例：未知 exporter code 属于能力检查，必须保留并令能力检查 not_checked；默认 delivery 因覆盖缺失 incomplete。复杂照片背景对比度若未列为 required，可产生 ready_with_warnings，公开该检查未完成。

## 输入/产物身份

- 每个输入 manifest/page/media/context/source snapshot 与实际导出的产物都需与报告身份对应。
- 部分页面选择不得重新编号或冒充全稿；同一 pageRef 在报告和产物中保持稳定。
- 所有素材解析/页面改写必须先完成，再生成最终审阅与校验报告；前置检查仅作预检。
- 原始文稿或策略变化使旧报告过期。一期保守地要求重新执行必要阶段，不实现智能增量调度。内容 fingerprint 排除审阅结果；审阅引用该 fingerprint，证据本身另算 evidenceFingerprint，避免自引用。
- 默认阶段输入为 .quality/stages/<stage>.json，或 --reports 显式指定清单；拒绝重复 stage/歧义，不按 mtime 选择。gate 的输出不是下一次阶段输入。
- 旧文件存在、PNG 可打开、PPTX ZIP 无损坏均不足以证明新交付成功。
- 多格式同时交付时，只有同一输入版本的产物可以一起验收。

## 失败行为

报告写入失败、坏参数、报告 JSON 不可解析为执行错误；非零退出。单工具的旧合法退出码不统一重写，quality adapter 做解释。

metadata/哈希用于可重现和追踪，不是防篡改认证；来源审阅的可信度取决于记录的证据和作者实际核对，不由 schema 自动担保。
