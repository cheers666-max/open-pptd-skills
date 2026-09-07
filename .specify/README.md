# 本仓库的 SpecKit 规划入口

当前特性：[open-pptd 轻量优化](../specs/001-quality-framework/plan.md)。用户使用 pi 调度；有效规划为 spec.md、plan.md、tasks.md；已授权实施，最新进度见 tasks.md 与 validation.md。

第一版 40 项质量框架方案已被用户的新约束取代，移至 archive/quality-framework-v1/，不属于当前实施要求。SpecKit 仅用于简短需求与任务拆解，不成为 skill 的运行依赖。

保留了 memory/constitution.md v1.0.0；原 spec/plan 模板实际上是上一轮 kimi-slides 融合的具体文档，完整保存在 archive/kimi-slides-fusion/，新的 templates/ 使用通用官方模板。

本机 Specify CLI 0.0.22 的 init 因新版 release 缺少旧命名资产而失败；没有升级全局 CLI。改为从官方 github/spec-kit 的固定提交导入规划脚本、模板及 agent-context 更新脚本。来源、逐文件校验值和许可证位于 upstream/。

本次已运行 create-new-feature.sh、setup-plan.sh；该固定版本的 create-new-feature 只创建规格及 feature.json，不创建 Git 分支，因此单独创建 001-quality-framework。feature.json 是机器本地指针，不跟踪。

可复用命令（仓库根目录）：

    .specify/scripts/bash/check-prerequisites.sh --json --require-spec --require-tasks --include-tasks
    .specify/scripts/bash/update-agent-context.sh specs/001-quality-framework/plan.md

本版本 update-agent-context 使用 plan 路径，代替旧 skill 文档中的 codex 参数；目标 AGENTS.md 由 extensions/agent-context/agent-context-config.yml 指定，仅更新 SPECKIT 标记区。

下一次新特性运行 create-new-feature 前先检查本地/远端分支及 specs 编号。当前优化没有新数据模型或服务接口，不为模板额外生成 contracts/schema。
