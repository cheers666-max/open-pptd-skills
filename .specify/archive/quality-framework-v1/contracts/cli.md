# CLI / File Contracts

这是拟实现接口，当前尚不可执行。采用本地 CLI/文件契约，无 REST/GraphQL 服务。

## 通用约定

- --json 模式 stdout 只输出一个 JSON 对象；进度/诊断到 stderr 并及时 flush。
- --report <path> 写完整 open-pptd-quality/1.0；原 --json 摘要及旧字段保持。
- 项目内路径在报告中相对化；CLI 可接受绝对项目路径，不把开发机路径固化进包。
- input error、dependency error、child spawn/signal、export exception 非零。未知错误码保留。
- 原始工具报告继续保留，禁止只输出告警计数。
- 导出写入本次临时目录，完整成功后替换对应最终产物；失败报告不引用旧产物为本次结果。

## New commands

| Command | Input / output | Exit |
|---|---|---|
| quality <project> --profile structural\|delivery --report <path> [--reports <manifest.json>] [--json] | 只读采集 .quality/stages/<stage>.json 或清单明确指定的阶段报告，核验输入/产物哈希，输出交付报告；缺阶段给 incomplete，不自动运行/修复 | 0 ready/ready_with_warnings；1 blocked/incomplete；2 参数/执行错误 |
| prepare_context.py --project <path> [--context <file>] | 验证 project-context.json，生成 DESIGN_CONTEXT.md 与 .quality/authoring/pages/<pageId>.md；不自动造来源/勾选审阅 | 0 成功；1 上下文违规；2 执行错误 |
| validate_content.py --project <path> [--report <file>] [--json] | 检查引用/口径/绑定/受支持推导/审阅覆盖；无 sidecar 返回 not_checked | 0 适用范围满足；1 内容违规或要求覆盖缺失；2 执行错误 |

quality 对缺必需阶段报告 exit 1；如果报告存在但无法解析、存在重复/歧义 stage 则 exit 2，并写结构化原因。报告清单结构为 {schemaVersion: open-pptd-report-set/1.0, stages: [{stage, path}]}，path 相对清单所在目录；禁止路径逃逸允许的项目/显式报告根目录。默认 stage 名为 structure/content/author-review/assets/render/html/pptx，不递归扫描旧文件，不按 mtime 猜最新；output report 不得覆盖其输入报告。profile 默认 structural，SKILL 最终交付显式要求 delivery。

## Existing commands

| Entry | 兼容与新增行为 |
|---|---|
| validate / validate_deck.py | 保留 --output 的 legacy report 与 valid/issueCount/issueCounts；新增 --report 写统一 sidecar，不悄悄把旧 valid 改成完整交付结论。保留 0=无旧规则问题、1=规则问题、2=运行错误 |
| check | --page/--severity 筛选须在实际 validator 中实现，报告说明被筛选范围；部分报告不能满足 delivery。--level keep 无副作用；auto 未实现安全策略前明确非零“不支持自动修复”，不静默忽略 |
| screenshot / export_images.py | 保留命令；--page 3,5 输出仍映射物理第 3/5 页。新增 --report，采集 viewer health；CLI 不把截图等同像素审计 |
| export_html.py | --json 错误也非零；新增 --report；读取 viewer health，渲染异常阻断默认正式导出 |
| export_pptx.mjs | 新增 --report 完整 engine findings 与 artifact identity；--json 保留 ok/deck/output/bytes/warnings/fonts。内容丢失默认阻断正式导出，明确诊断模式可产出 incomplete 供检查 |
| audit_rendered.py | --json/--output 保留；统一报告可用 --report；解析失败、Pillow/Chrome 不可用明确 failed/not_checked；advisory 不当作确定错误 |
| layout_planner.py | 保留旧 outline 输入；新默认只输出建议并保留所有页/字段，旧强制插页行为不作为默认；迁移文档说明行为变化 |
| convert-fidelity | 修测试/报告/退出契约，不承诺任意无损往返；已有 element confidence 与保真边界保留 |

## Image search

路径为 skills/open-pptd/scripts/image_search/search_images.py。

新增 --timeout 30（每个后端的搜索+下载+可选 VLM 完整尝试）、--budget 120（本命令全部槽整体预算）、--offline、--json、--report。默认网络策略 offline；直接显式调用搜图且传 --network allow 代表调用方已获任务授权。VLM 必须单独被上下文授权，API key 存在不自动启用。

所有剩余时间由 monotonic deadline 计算。每个失败尝试完整记录，无候选/下载失败/筛选失败均可回退。整体预算结束时关闭 worker 并记录未处理项，最多 2s 清理，不依赖 thread cancel 冒充终止。长阶段 <=5s 有心跳。

保留 exit 0=全部槽得到适用结果（可含策略允许的装饰降级）、2=有 unresolved、1=usage/IO。降级不是静默成功：报告 degraded，最终 gate 按策略判定。identity/evidence/template 槽不能用通用渐变补齐。

## Offline / setup

已安装依赖的运行入口禁止自动 pip/npm/font download。缺依赖输出安装/准备方法并失败或未检查；准备阶段必须由用户任务明确授权联网后调用。fonts 的本地候选和缺失名单可离线生成。现有显式 download-fonts 工具保留；任何安装步骤不进入默认离线回归。

## File placement

- project-context.json：任务/设计/来源/主张 sidecar；包含 deliveryPolicy，编辑任务含修改前 editBaseline。显式新 sidecar 的 network 字段必须完整，生成时默认 false。
- DESIGN_CONTEXT.md：生成投影，提示编辑源 sidecar。
- .quality/：stages/<stage>.json 是固定阶段报告入口；作者任务、审阅记录、临时产物单独存放。自定义 --report 路径必须通过 --reports 清单交给 gate，输入和最终产物身份仍需可解析。
- reference/schemas/：分发包中的正式契约；从经核准的本目录 contracts 同步，避免两份手写漂移。
