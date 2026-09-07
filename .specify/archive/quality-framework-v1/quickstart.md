# Planned Verification Quickstart

以下为实现后的验收步骤，不是本轮已经运行的产品功能。以仓库根目录为起点；所有生成产物放临时目录/fixture 副本，不修改 example 或私有 case。

## 1. 可信基线

    npm test
    python3 -m unittest discover -s skills/open-pptd/scripts/image_search/tests -p 'test_*.py'
    python3 -m unittest discover -s skills/open-pptd/tests -p 'test_*.py'

预期：转换 fixture 真实创建并执行断言；准备失败 fail；required 套件缺 Chrome/依赖时明确失败/未完成，不能靠普通 return 变绿。旧 image_search 18 个测试保留，新增预算/回退路径。

## 2. 结构与交付契约（US1）

- 通用两页样本：一页图表、一页图标/文本；先输出统一结构/渲染/HTML/PPTX 报告。
- 注入 pie 图例异常、未知图标、缺图和导出异常，检查 elementId/pageRef 与非零退出。
- --page 3,5 的多页样本断言身份保持；其报告送 delivery 应 incomplete。
- 修改一个页面或素材后使用旧报告，应拒绝过期结果；同时缺审阅与发生禁止降级时必须 blocked。
- 同阶段两条报告或自定义路径未被显式清单引用不得按 mtime 猜选择，gate 输出不得被当作 stage 输入。
- 移除一个必需格式，再把旧文件留在输出目录，应 blocked/incomplete，不能匹配本次 fingerprint。
- PPTX 解包检查对应 icon 的语义路径/图形及 slide 数；HTML 检查同一 pageRef 的 health；不把 ZIP 通过当作桌面播放测试。

拟用入口：

    node bin/open-pptd-skills.js quality <fixture-copy> --profile structural --report <fixture-copy>/.quality/structural.json --json
    node bin/open-pptd-skills.js quality <fixture-copy> --profile delivery --report <fixture-copy>/.quality/delivery.json --json

预期：尚未执行的内容或排版检查明确未检查；MVP 不能伪造 delivery ready。

## 3. 四类内容场景（US2）

- research：外部主张带本地来源快照/定位；同口径异值报冲突，不同年份不报；理论/实测标签交给可追溯终审。
- education：教学示例显式标记，连续推导允许同布局，不要求外部 URL。
- internal-report：用户本地表格为依据，支持的派生计算可复算；比例除零明确错误。
- template-edit：editablePageIds 仅包含指定页，未知原始主张不被自动盖章；不改未授权页面。
- 每类覆盖 text/table/chart 至少一种绑定；合并构成三类全覆盖。
- context 内容变化使旧作者/终审记录失效；添加支持证据不会令审阅自失效；同一 sidecar 的作者内容投影字节一致。
- 修改共享资源但不改 .page 时，编辑 baseline 仍能发现未授权影响；未编辑历史事实不强迫补公网来源。
- 素材解析完成后再生成最终内容/审阅结果，避免正常首次执行就导致旧 hash。

## 4. 离线与预算（US3）

- fake backend 提供成功、首后端全下载失败、筛选失败、黑洞请求与单槽异常。
- --timeout 1 --budget 2 的受控测试应在整体 2s+2s 清理内结束；同时验证默认预算的配置传递，不在 CI 等待真实 120s。
- 长阶段观测 stderr 心跳间隔 <=5s，stdout 仍可解析。
- 禁网 fixture 检查图片/VLM/字体/pip/npm 无隐式远端调用。
- 仅 decorative 且策略允许的背景替代成功并记 degraded；产品/证据图缺失仍 unresolved。
- 失败原因包括 search/download/filter/deadline；报告不因 tried 字段错误而丢失。

## 5. 已知真值测量与节奏（US4）

- 内联大字、小框固定行高、多段及 CJK：实际 overflow 与 element 对齐。
- 黑字白底、低对比纯色：正确分类；照片/渐变/透明叠层无可靠测量时 not_checked/advisory。
- 透明覆盖不按矩形交叠自动认定文字丢失。
- 固定 1/4/14/20/30 页样本以及连续教学组：数量、顺序、页型、额外字段不变。
- 多信息单表格和极简封面不能因元素数低而阻断。
- 不运行默认自动扩高或豁免全部 cover/final 的修复。

## 6. 分发与端到端（US5）

- npm pack 到临时目录，仅本地打包，不 npm publish。
- 在隔离目录安装，断开对开发源码目录与 projects/ 的访问。
- 检查新 schemas/reference/scripts 均已分发，命令 --help、JSON/exit 与文档一致。
- 依照 SKILL 的准备→写作→素材解析与改写完成→最终内容终审/校验→渲染与多格式导出→quality 顺序运行四类场景。
- required 检查完整且 source/outputs 对应才 delivery ready；未支持复杂检查在报告中公开。
- 既有新能源项目或 example 项目可在副本上做人工压力复验，但不作为绿色 CI 的外部依赖，也不把真实数字写入规则。

## 本轮规划自检（已可执行）

    .specify/scripts/bash/check-prerequisites.sh --json --require-spec --require-tasks --include-tasks

另检查：所有 FR/SC/US 在 tasks 有映射；tasks 均未勾选；contracts JSON 可解析且示例通过；规划引用存在；没有源码/case 改动；无 commit/push。
