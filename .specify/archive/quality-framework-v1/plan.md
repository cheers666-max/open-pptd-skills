# Implementation Plan: 通用 Skill 质量框架

**Branch**: 001-quality-framework | **Date**: 2026-09-05 | **Spec**: [spec.md](spec.md)
**Input**: /Users/yuajing/Downloads/open-kimi-ppt-skill-main/specs/001-quality-framework/spec.md
**Status**: 仅规划。任务未实现；不修改实战 case，不 commit/push，不发布 npm。

## Summary

将 open-pptd 从“多脚本加提示词”完善为有共享输入、明确能力边界、可追溯检查和交付判定的本地 skill。保留现有 Python/Node/viewer 主体，以少量 sidecar 契约、薄适配层和通用 fixtures 连接现有工具。

执行链：

    任务边界与本地输入
      → 核准内容/来源 + 页面意图 + 目标格式能力
      → 生成共享作者上下文 → 顺序或并行写 .page
      → 静态/内容预检（诊断性，允许仍有素材占位）
      → 有预算的素材解析并完成所有页面/媒体写入
      → 主写手全稿/变更范围终审 + 最终静态/内容检查
      → 实际渲染检查
      → PPTX / HTML 导出及各自产物报告
      → quality 汇总当前输入与产物证据 → 交付决定

quality 只聚合和验收，拒绝过期/部分/缺失证据；不新增通用 DAG 执行器，不自动修文稿。导出工具各自在临时目录生成并验证后替换目标，失败保留可诊断的报告，禁止旧文件混充新产物。

## Technical Context

**Language/Version**: 现有 JavaScript ESM（Node >=18）与 Python >=3.10 语法基线；本机验证环境 Node 22.23.2 / Python 3.14.5。实现前用通用 suite 核实最低兼容版本，不擅自抬高。
**Primary Dependencies**: 复用 yaml、sharp、jszip、fontkit、PyYAML、Pillow、websocket-client 和本地 Chromium/CDP；不引入 Web 服务、数据库或模型 SDK。JSON Schema 用于契约说明与测试验证，若需依赖仅作为明确的开发依赖选择。
**Storage**: 项目本地 PPTD/pages/media，project-context.json、DESIGN_CONTEXT.md 与 .quality/ 报告；源码仓库只提交通用 fixtures。
**Testing**: node --test + Python unittest；必要浏览器集成测试使用既有 CDP/Chrome。按矩阵验证行为，不要求像素完全一致或新增全部图像 golden。
**Target Platform**: macOS/Linux/Windows 的现有本地 CLI；先在本机实证，其他平台通过可用 CI 验证，未运行不得宣称覆盖。
**Project Type**: Agent skill + local CLI/scripts + vendored render/export adapter。
**Performance Goals**: 素材后端预算默认 30s、命令整体默认 120s；截止清理 <=2s；心跳间隔 <=5s。渲染复用同批结果，不为各检测重复截图；其余耗时记录基线，不许凭空承诺每套文稿固定完成时间。
**Constraints**: 默认离线；联网资料获取遵守明确任务授权；运行阶段不隐式 pip/npm/字体下载。旧 CLI 有效调用及 JSON 字段兼容；新 gate 不虚构旧项目未做的内容核验。
**Scale/Scope**: 四类任务（外部研究/教育/内部汇报/限定编辑），单页与多页，三格式，能力矩阵中的通用组件。既有案例是可选人工压力集，不是 CI 必需数据。

## Constitution Check

| Principle | 现状风险 | 规划约束 | Phase 0 / Phase 1 |
|---|---|---|---|
| Local-First | 导出会隐式装依赖/下载字体，图片凭 key 启用 VLM | 显式 setup 与离线 run 分离；network 策略独立于凭据 | PASS：修复现状，不依赖宪章豁免 |
| Deterministic Validation | 假通过、启发式漏报/误报 | 正负 fixtures、真实状态、测量范围公开；不默认自动扩高 | PASS |
| Multi-Format Delivery | 文件成功不代表内容/页序匹配 | 默认三格式，用户明确裁剪范围除外；报告/产物须与当前输入匹配 | PASS |
| Anti-AI-Slop Design | 几何阈值与设计语义混为一谈 | 保留现有设计原则；启发式证据不足时复核，不简单提阈值/普遍豁免 | PASS |
| Chart-First Expression | 浏览器与 PPTX 图表能力不同 | 公开 13+ 家族的当前能力/未知项，修已有故障；优先受支持图表或可编辑图形，不承诺所有后端原生等价 | PASS |

上述 PASS 是对设计的检查，不是对当前实现的通过声明。宪章不修改；默认联网、撤销设计原则或承诺任意无损转换均不在本特性范围内。

## Project Structure

### Documentation (this feature)

    specs/001-quality-framework/
      spec.md
      plan.md
      research.md
      data-model.md
      contracts/
        quality-report.schema.json
        project-context.schema.json
        cli.md
        quality-policy.md
        examples/
      quickstart.md
      tasks.md
      checklists/requirements.md
      checklists/planning.md

### Source Code (planned changes; not yet implemented)

    skills/open-pptd/
      SKILL.md
      reference/quality-workflow.md
      reference/authoring-context.md
      reference/capabilities.json
      reference/schemas/                    # 发布用契约，来源为经核准的 contracts
      scripts/
        quality/                            # 小型共享模块：报告、身份、内容规则
        quality_gate.py                     # 只读聚合器
        prepare_context.py                  # 共享上下文/作者说明投影
        validate_content.py                 # 来源、口径、派生与绑定校验
        validate_deck.py                    # 保留静态入口
        audit_rendered.py                   # 修测量和状态
        layout_planner.py                   # 保留语义的建议器
        image_search/{pool,search_images,slots}.py
        image_search/backend_worker.py      # 可终止尝试；主进程统一写盘
        viewer.html
        export_{html,images}.py
        export_pptx.mjs
        vendor/open-ppt-engine/adapters/pptd.mjs
      tests/
        fixtures/quality/                  # 新通用样本，不使用项目 case
        test_{content,context,quality,assets}.py
    test/
      helpers.js
      {fusion-features,quality-contracts,render-health,cli-quality,packaged-workflow}.test.js
    bin/open-pptd-skills.js
    docs/quality-migration.md

**Structure Decision**: 扩展既有目录；不拆新独立产品，不更换 PPTD DSL，不把所有逻辑塞入 validate_deck 或 design_system_loader。

## Phase 0: Research

已完成 [research.md](research.md) R1–R10：统一报告、可信测试、viewer hook、格式能力、sidecar、事实边界、可终止预算、语义降级、测量/设计分层、SpecKit 初始化。所有设计选择均有默认决策，无待回答的必要澄清。

## Phase 1: Design & Contracts

1. **身份和版本**：稳定 pageRef/pageId/elementId；内容 fingerprint 包含 manifest、全部 page、引用媒体、上下文内容投影/来源快照、能力/策略版本，显式排除审阅状态和报告。审阅/阶段结果另用 evidenceFingerprint 标识，不反向改变内容 fingerprint；本地报告保存实际工具/字体信息。
2. **报告语义**：check.status = passed/degraded/not_checked/failed；issue.severity = error/warning/info；evidenceMethod 明示 static/dom/export/author_review/heuristic。最终 decision = ready/ready_with_warnings/incomplete/blocked，详见 quality-policy。
3. **薄适配器**：validate 保留旧 --output 报告和字段；新增 --report 写统一报告；export --json 保持摘要、--report 提供完整详情。quality 不对旧空报告臆造未覆盖的检查。
4. **内容契约**：项目 sidecar 不改 .page 语法；显式绑定正文/table/chart 数据及页级 notes。编辑前捕获 editBaseline 的页面/共享资源清单，依据白名单检查未授权变化；内容审阅只覆盖修改与关联内容，交付全稿仍检查渲染/产物。仅有限声明式推导运算；未知公式显示未检查，不执行任意表达式。
5. **终审记录**：主写手基于实际输出及证据写审阅记录，包含检查范围和 input hash；改动后失效。模型共识不等于事实验证；无强制二次模型调用。
6. **作者上下文**：任务范围、核准事实、设计语义、YAML 约定、容量提示、目标能力和邻页职责按需投影；不复制全部设计库，不设置统一元素数。
7. **真实渲染**：viewer health 向 HTML/PNG 导出器暴露渲染异常与资源状态；DOM 测量不替代 PPTX 端验证；修 pie 图例 const 递增与完整图标路径转换作为通用故障类。
8. **资源策略**：后端子进程截止覆盖搜索/下载/VLM，整项预算约束全槽并发；主进程顺序写盘与报告。offline 包括禁网安装/字体/VLM；生成替代仅适用许可装饰槽。
9. **兼容迁移**：旧静态 validate 退出码保留；新增 quality 为只读 gate。check 的不支持参数必须实现或明确报不支持，--level auto 在没有安全修复前明确拒绝。所有失败 JSON 非零。
10. **证据过期处理**：一期保守地使整次验收失效，重新运行必要阶段；不新增增量调度系统。报告引用不改变文稿内容。
11. **未知能力与策略**：未知 engine code、复杂背景对比度、来源支持关系未审阅等必须留痕。版本化 task.deliveryPolicy 显式记允许的降级及授权依据；gate 从策略推导 required 检查及其逐阶段范围，不信任报告自行关闭 required。确定失败/禁止降级优先于覆盖不足。
12. **报告读取**：默认只读 .quality/stages/<stage>.json；自定义位置使用 --reports <manifest.json> 的显式 stage→path 清单。重复阶段、歧义或输入过期拒绝；不按修改时间选择旧结果，不读取自身 delivery 报告作为阶段输入。

已输出 [data-model.md](data-model.md)、[contracts/](contracts/)、[quickstart.md](quickstart.md)。接口为本地文件与 CLI，无服务端 endpoint；不为套用模板引入 REST/GraphQL。agent context 用官方扩展脚本更新。

## Phase 2: Task Strategy & Milestones

| Milestone | 可审查的增量 | 主要故事 | 退出标准 |
|---|---|---|---|
| M0 可信基线与契约 | 修测试入口、建立通用 fixtures 和身份/状态契约 | Setup/Foundation | setup 失败可见，契约正负样本可判定 |
| M1 交付错误不会静默 | 失败传播、viewer health、格式能力、只读 gate | US1 | 已知渲染/图标/缺页/旧报告被拦；内容尚未覆盖明确显示 |
| M2 内容与作者协议 | sidecar、来源/口径、共同作者上下文、终审 | US2 | 四类场景规则适用；全稿主张可追踪 |
| M3 有界资源与可靠测量 | offline、预算/回退、DOM/对比度、节奏建议 | US3/US4 | 截止与零隐式联网达标；已知真值样本无错误阻断 |
| M4 分发与完整验收 | SKILL 默认流程、CLI 迁移、隔离包回归 | US5 | 安装后的全流程覆盖完整；所有必需阶段实际执行 |

**MVP**: M0 + M1。它提供可信的结构/导出检查，不宣称内容准确性与复杂视觉审计已经全部完成。M4 才作为本次框架特性的完整完成条件。

**Dependency order**: 契约与身份 → 错误传播/渲染观测 → US1 gate；US2/US3 可按已冻结契约独立开发；US4 DOM 测量依赖 US1 hook；US5 整合全部。共享 SKILL/CLI/viewer/validator 文件顺序合入，不能因任务标 P 而同时覆盖同一文件。

**Delivery discipline**: 每个增量独立复核；不因当前计划而授权自动 commit/push/发布。用户后续明确进入实现后再执行 tasks；本轮任务均保持未勾选。

## Risks & Deferred Work

- DOM 与 PPTX 有字体和布局差异：分别提供证据，不作跨后端等价保证。
- schema 过度扩张：先只支持实际规则所需字段，保留版本；不加入任务调度/用户管理/数据库。
- 研究主张覆盖无法仅靠正则穷举：显式绑定 + 候选提醒 + 主写手审阅；未绑定不能宣称全量验证。
- 源媒体/字体内容变化会影响渲染：报告记录身份，过期后重新验收。
- 当前能力表中高级图表可能被标 unsupported：本轮保证说明与拦截，新增图表实现单独排期。
- 不包含任意无损 PPTX 往返、默认自动修布局、设计库全面合并、付费模型调用或案例内容重写。
