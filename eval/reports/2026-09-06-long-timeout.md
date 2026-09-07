# 延长 pi 任务等待时间：复测完成（2026-09-06）

按用户“不要减少生成回合，调用时间长一些”的要求，`eval/run_pi.py` 默认整份任务截止从 1200 秒提高到 **3600 秒（60 分钟）**。生成提示词、skill、修稿/检查流程保持不变；没有加入回合限制，也没有调整全局 pi 配置或试验性推理参数。README 和轻量 SpecKit 计划同步更新。

## 真实运行

使用 **pi 0.84.4 / qihoo / 360zhinao-turbo-aippt-agent-260824**，重复此前两页通用课堂交接题。原始题目和 skill 快照保持一致；每轮工作路径和执行日期由 runner 正常生成。单例运行，不检索网络素材。命令刻意不传 `--timeout`，验证新的默认值：

```bash
python3 eval/run_pi.py --provider qihoo --model 360zhinao-turbo-aippt-agent-260824 --thinking off --cases-file /tmp/open-pptd-two-page-smoke.json --concurrency 1
```

| 项目 | 实测结果 |
|---|---|
| 整任务截止 | 3600 秒 |
| 实际耗时 | **1069.473 秒，17 分 49 秒** |
| 助手响应 / 工具调用 | 32 / 34 |
| 结束 | 自然结束，exit 0，agentEnded=true，无超时 |
| 工具错误 / 流式错误 | 0 / 0 |
| 作者交付 | 恰好 2 页 PPTD + PPTX + HTML，以及逐页 PNG |
| skill 副本 | 未修改；SHA256 与此前 360 两页 smoke 相同 |

作者自行完成校验、截图、像素采样、导出及产物核对，未由评测器补做交付文件。之前同题的 600 秒截止会在作者完成全部流程前中断；本次延长等待后流程完整走完。单次成功不能保证所有题目在 60 分钟内完成，也不代表生成速度已经提升。

`--thinking off` 保持此前取值；该模型配置下它仍不能证明服务端关闭推理，见[此前参数取证](2026-09-05-timeout-diagnosis.md)。本轮无需依赖关闭推理来完成。

## 独立验证

- 独立运行 `eval/review.py`：两页 PPTD 校验通过，0 issues；PPTX ZIP/XML 和 HTML 页数一致，无结构 findings。作者导出报告 warnings 为空。
- 独立查看作者两张 PPTD 截图：三项交接动作、虚构示例徽章和脚注明确，文字与简单几何形状符合题目，无明显溢出或遮挡。
- 用 LibreOffice 打开作者原始 PPTX，3.217 秒转换为两页；查看两页图像，与 PPTD 对照无明显内容丢失。另用 Chrome 打开作者原始逐页 HTML 并查看两页截图，内容和布局完整。跨格式有轻微字距差异，仍在边界内。
- pi 自然结束后重新核对 PPTX 和 HTML 哈希，确认与独立打开时一致。评测图像和转换结果放在 `precheck/`，没有修改作者输出。
- runner 现有测试 **14/14 通过**（9.929 秒）；`git diff --check` 通过。此前整套功能测试结果保留在 [validation.md](../../specs/001-quality-framework/validation.md)，本次运行时行为只改超时默认值。

本机此模型仅声明文本输入，作者如实记录未做图像目视检查；其像素采样不等于看图。这里的视觉结论来自本助手独立查看两页、三种格式；LibreOffice 检查不等于 PowerPoint/WPS 认证。保留 runner 的 `generated_unreviewed` 与空数值评分，本报告另记通用 smoke 的人工式检查结果。专业深度、事实依据、配图相关性及 20 题总体质量未在本轮重评。

## 证据与范围

[机器证据与文件哈希](2026-09-06-long-timeout-evidence.json)。原始 run：

```text
/var/folders/kf/j2_kwtmj30q6xf4tz527_mxw0000gn/T/open-pptd-pi-eval/20260906-095335-hx9ytsu_
```

交付文件在该目录的 `cases/smoke-two-page-handoff/work/output/deck/`。T009 的通用 pi smoke 条件至此完成；历史失败记录保留。**本次没有重跑完整 20 题验证集**，后续执行沿用 360 模型、60 分钟上限和原有生成回合。未 commit、push 或发布 npm。
