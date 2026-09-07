# Data Model: 通用质量与作者协议

本文件为设计契约，尚未进入产品实现。数据存储在项目本地；新 sidecar 不改变 PPTD v2 渲染语法。

## ProjectContext

- schemaVersion: open-pptd-context/1.0。
- task: id、operation(create/edit/replicate)、purpose、audience、targetFormats、pageCount(mode=fixed/flexible,value)、editablePageIds、expansionPolicy、network(research/images/vlm，默认 false)、allowDecorativeFallback。
- design: referencePath、约束摘要、tokens；只包含已选设计，不复制全库。
- pages: PageIntent[]；顺序对应 manifest。
- sources: Source[]；claims: Claim[]。
- contextHash: 由规范化的待制作内容投影生成，排除自身、claims[].review、AuthorReview、来源 accessStatus 和非语义时间戳；包含任务/设计、主张正文/指标/绑定、来源定位与快照身份。写入审阅记录不会改变它；该哈希不用于身份认证。
- task.deliveryPolicy: version、origin(default/user_instruction)、authorizationRef(有例外时必需)、allowedDegradations[]；每项明确 featureId、format、representation、pageIds/elementIds 与 reason。无例外时数组为空。必需检查集合来自受版本约束的策略，工具报告不能自行关闭。
- editBaseline（operation=edit 时必需）: 修改前 manifestHash、pageHashes、mediaHashes、来源/主题身份及 page→resource 引用清单；task.editableResourcePaths 明确允许改动的共享资源，默认空。prepare_context 在任何内容写入前捕获，已有 baseline 不能在同一次编辑中被覆盖。缺 baseline 的已有编辑只能显示范围未检查。

**Rules**: 页 ID 与路径唯一且对应 manifest；fixed 值与实际页数一致；编辑白名单不得越界；新的显式 sidecar 必须填写 network 的三个布尔值，缺字段为 schema 错误；生成器创建时默认 false，独立 CLI 未指定网络策略也默认 offline；显式新增 sidecar 错误必须报错，不能假装是旧项目无元数据。

## PageIntent / Binding

PageIntent: id、pageRef、role、objective、takeaway、prerequisites(pageIds)、claimIds、layoutIntent、continuityGroup(可选)。

Binding: claimId、pageId、contentPath、representation；元素级绑定还必须有 elementId。text/table/chart 的 JSON Pointer 相对该元素，如 /content/text、/rows/2/1/text、/data/rows/0/1；notes 是页级绑定，不允许虚构 elementId，contentPath 固定为相对整页的 /notes。大段富文本若不能可靠定位数字，还需显式 expectedText/value；无法确定时报告复核项，不能自动替换。

**Rules**: 引用存在；前提图无循环或明确允许的复述关系；固定页数及额外用户字段保留。page index 仅为显示序号，不作为身份主键；局部截图继续使用原 index/pageRef。

## Source

id、kind(web/local/user)、title、uri、locator、publishedAt/period(适用时)、snapshotPath/sha256(可选)、accessStatus(accessed/unavailable/not_checked)。

- web 允许 URL，但 validator 不联网；原始网页/报告的具体章节或表格写 locator。
- local/user 采用项目相对路径及页/表/工作表定位，禁止依赖开发机外部绝对路径。
- 没有快照时记录审阅时使用的定位信息，不伪造 snapshot hash。
- accessStatus 和“内容支持主张”分开；200 响应不证明来源可信。

## Claim

id、kind(external_fact/user_fact/derived/illustrative/assumption)、statement、sourceIds、metric(可选)、derivation(可选)、bindings[]、review。

metric: id、value、unit、scope(period/geography/population/denominator/method/basis)。basis 为 actual/estimate/forecast/target/theoretical/measured 中明确适用者，不能省略有实质区别的口径。

derivation: inputClaimIds、operation(sum/difference/product/ratio/percent_change/unit_convert)、parameters。使用有限运算，不允许 eval 或任意表达式；除零、无支持换算、未知公式给出失败或未检查。

review: status(unreviewed/supported/disputed/inconclusive)、method(author/material_check)、sourceLocators[]、reviewedInputHash、note。supported 必须有相应证据说明；记录声明而非防伪证明。illustrative/assumption 应显著标注，不能通过类型字段掩盖正文把示例写成实绩。

**Rules**:

- external_fact 要求至少一个可定位 source；user_fact 接受用户文档，不要求公网 URL。
- derived 要求输入存在且可追溯，计算规则受支持；派生来源通过输入关系继承。
- metricId + 完整 scope + 规范单位才可作数值冲突比较；不全时只提候选提醒。
- 同值异义需 basis/语义终审；同指标不同 period 不判同口径冲突。
- 正文/table/chart 都检查绑定，不只扫 text 元素。
- 未绑定的疑似事实只生成 author-review-needed，不能据正则判断“所有主张都已核验”。

## AuthorReview

type(content/storyline)、scope(pageRefs/claimIds)、status、reviewedInputHash、checks[]、findings[]、note。

checks 至少覆盖章节/页码、术语与统计口径、前提/承接、图表结论与数据、复述是否有意、编辑范围。编辑任务依据 editBaseline 比较未授权页面/共享资源；内容审阅覆盖修改页及受影响关联，不强迫重核全部未编辑历史事实，渲染和产物完整性仍覆盖实际交付全稿。由主写手实际重读后填写；不是由准备工具自动勾选。输入变化后状态为 stale，必须重新审阅。

## AssetSlot / BackendAttempt

AssetSlot: pageRef、elementId、kind、semanticRole(decorative/identity/evidence/template)、queryOrSource、targetRatio、allowFallback。
BackendAttempt: slotId、backend、stage、startedAt、elapsedMs、budgetMs、outcome、reason、candidates[]。
ResolvedAsset: localPath、sha256、sourceUri、licenseStatus(known/unknown)、licenseText、landing、representation(original/generated_decorative)、dimensions。

**State**: pending → resolving → resolved / degraded / unresolved。预算耗尽仍要为未开始槽生成 unresolved 记录。只有主进程写入页面和素材；提交改写前验证全部变化，避免 worker 超时后仍改文件。对不可替代槽未找到素材时保留原请求。

## Capability

featureId、targetFormat、representation(native/vector/raster/fallback/unsupported)、verification(verified/unknown)、limitations、fixtureIds、lossClass(none/appearance/meaning/editability)。

能力声明不等于检查结果。原生也可能渲染错误；矢量图标可保留语义；无关字符代替图标是 meaning 损失。未验证项不能因声明 supported 而通过。

## QualityReport / Check / Issue / Artifact

schemaVersion=open-pptd-quality/1.0、runId、tool(name/version)、input(fingerprint、manifestHash、pageHashes、mediaHashes、contextHash、policyHash)、scope(profile/pageRefs/formats/requiredChecks)、checks[]、issues[]、artifacts[]、rawReports[]、decision、summary。

Check: id、status(passed/degraded/not_checked/failed)、required、method、pageRefs、reason、evidence[]。
Issue: code、severity(error/warning/info)、checkId、pageRef/elementId、message、evidence[]。
Artifact: format、path、sha256、pageRefs、representation、status；path 为项目内相对路径，临时路径不得冒充最终交付物。

- input.fingerprint 是被制作内容的版本：覆盖 manifest/page/media、上述 context 内容投影、实际来源快照、能力表与策略，排除全部报告/审阅结果及其哈希。没有 context 时 contextHash 为 null，不能编造默认内容核验。
- evidenceFingerprint 单独覆盖本次选中的阶段报告与审阅记录，不反向参与 input.fingerprint。审阅的 reviewedInputHash 必须匹配内容 fingerprint；添加有效审阅不使自身过期，改页面/主张仍会使其过期。
- 图像或字体处理参数/实际字体名单进入原始报告；工具版本变化需重新核验能力。
- 原始证据 retained，不能只保留数量。默认阶段报告固定写 .quality/stages/<stage>.json；非默认位置通过 --reports 指向显式清单。禁止按 mtime 扫描猜最新报告，重复阶段/歧义直接报错；gate 自身输出与阶段输入分开。
- 最终 decision = ready / ready_with_warnings / incomplete / blocked；汇总规则见 contracts/quality-policy.md。
- unknown warning code → 对应检查 not_checked，保留原 code；若该检查是 required，decision 至少 incomplete。
- 解析错误不是“空元素”或“0 issues”。

## Migration

旧项目不要求马上增加 sidecar；旧 validate/preview/export 继续工作。新增 delivery profile 发现缺少必要内容/审阅证据时为 incomplete；structural profile 可独立运行，但其 ready 仅针对声明范围。手工 sidecar 可通过 prepare_context 验证，不能自动推断事实为 verified。
