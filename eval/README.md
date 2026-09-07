# pi 固定用例评测

使用用户给出的 [20 个原始题目](cases.json) 做有限、可重复的端到端运行。pi 负责调用 skill；这里仅是单文件 runner 和评阅约定，不引入调度平台或自动评分服务。

## 运行

依赖本机 Python 3.9+、pi，以及 skill 已准备好的 Node/Python/浏览器/字体依赖。2026-09-06批次开局记录 pi 0.84.4，但运行期间全局入口变为0.85.1；未逐进程测版本，详见本轮报告。先完成一批 skill 修改和针对性测试，再启动快照；运行中继续修改仓库不会改变本轮副本。

```bash
# 查看题目，或只准备快照与提示词，不调用模型
python3 eval/run_pi.py --list
python3 eval/run_pi.py --provider qihoo --model 360zhinao-turbo-aippt-agent-260824 --case 03,08,20 --dry-run

# 小批次检查链路。--allow-web 表示本轮已授权公开资料和配图检索
python3 eval/run_pi.py --provider qihoo --model 360zhinao-turbo-aippt-agent-260824 --case 03,08,20 --allow-web --concurrency 2 --timeout 3600

# 完整 20 题；完成一次即退出，没有无限循环或后台常驻任务
python3 eval/run_pi.py --provider qihoo --model 360zhinao-turbo-aippt-agent-260824 --allow-web --concurrency 2 --timeout 3600

# 单独重跑标签/题号，或明确指定已有凭据环境变量的名称
python3 eval/run_pi.py --provider qihoo --model 360zhinao-turbo-aippt-agent-260824 --case missing-materials --allow-web
# --key-env SOME_EXISTING_KEY_ENV   # 仅传变量名，不在命令行写密钥
```

默认并发 2，单例硬超时 3600 秒（60分钟），包括同例所有续行，共享一个截止时间。超过后停止 pi 及其仍可识别的子进程（包括独立进程组中的 bash/渲染任务）。每 15 秒打印执行心跳。正常结束也清理本轮已观察到的后台子进程；清理前核对进程启动时间和进程组，避免 PID 复用误杀。采样不能保证识别在首次观察前就完全脱离父树的瞬时子进程，因此不宣称操作系统强隔离。Ctrl-C/SIGTERM 请求停止正在运行的用例并取消队列；操作系统强制 SIGKILL 无法由脚本处理。脚本面向 macOS/Linux，未实现 Windows 进程管理。

`--max-continuations 2`（默认）只处理已观察到 `agent_end`、最后 assistant 为正常 `stop`、退出0但正式三格式未齐的情形。使用 pi 原生 `--session` 保留同一上下文和工作目录，提醒继续未完成步骤；不解析或执行正文中的工具调用标签。最多续行两次，`--max-continuations 0` 可关闭，不限制每次生成内部的工具回合。缺材料、作者明确失败、未恢复的接口错误、`content_filter`、异常结束、超时和取消不触发续行。只在仍有完整私有会话时续行，不能恢复时明确记录。

`--thinking` 可选 off/minimal/low/medium/high/xhigh/max。未指定时不向 pi 命令加入该参数，保持现有默认；指定时写入实际命令与私有设置。`run.json` 的 `thinking` 记录显式选择（未指定为 null），`effectiveThinking` 记录私有设置值，后端是否遵守仍以实际调用表现为准。比较迭代时把模型/思考设置变化单列，不把降低思考量带来的速度变化说成 skill 优化效果。

未指定页数的题目以约 10 页为起点；常州历史建议 12 页、古代史约 3 页，5 分钟汇报建议 6–8 页，题目明确的页数优先。题目原文独立保存，补充执行条件不会替换原始请求。`expected_behavior` 供评阅使用，未把每例答案或评分表塞入生成 prompt。

`--case` 支持完整 ID、两位题号或标签，可重复/逗号分隔；不认识的筛选值直接失败。`--output-root` 默认系统临时目录下 `open-pptd-pi-eval/`，每次新建唯一目录，禁止放入本仓库。可指定仓库外的长期实验目录，避免临时目录被系统清理。续行沿用原题上下文；整题从头重跑形成独立 run。pi 自身的接口重试事件也保留，不与 runner 续行混算。

## 隔离与 pi 配置

- 每轮记录 commit、工作区 skill diff 的 SHA256、完整快照清单与哈希，包括实际参与运行的本地字体和依赖。密钥文件、缓存和 `.git/.pi` 不进入 skill 快照；外部符号链接拒绝复制。仓库未提交的 skill 修改也进入快照。
- 每例获得独立工作目录和 skill 副本。macOS 用 APFS 写时复制降低空间成本；其他环境普通复制。保留基线快照，在运行结束检查副本是否被修改。安装新依赖或修改 skill 会标为 `skill_mutated`，这一轮不能作为同版本对照。
- 使用 `--no-extensions --no-skills --no-prompt-templates --no-themes --no-context-files --no-approve` 禁用隐式发现，再用显式 `--skill` 只加载副本。项目/全局扩展不参加实验，也不修改其设置。
- 临时 `PI_CODING_AGENT_DIR` 只复制所选 provider/model 必要配置和凭据，运行后删除；不复制所有 auth、用户会话、扩展或个人知识库。凭据不放命令行和报告，已知凭据在 stdout/stderr 日志中脱敏。普通模型 API key 优先用环境变量；凭据 shell 命令不自动执行，需使用 `--key-env`。
- 每例的原生会话单独保存在同一个私有临时目录，结束后删除，不写入用户全局会话库；留作评测证据的是逐次脱敏日志。续行不会加载用户其他会话。
- pi 0.84.4 要用 `$ENV_NAME` 引用环境变量。runner 在私有配置中兼容已有的裸环境变量名称，不修改用户全局配置。只有选定凭据及少量运行环境变量传给子进程。
- pi 的 `--offline` 仅关闭启动时网络操作，**不禁用模型请求或 bash 网络访问**。runner 的 `--allow-web` 是生成提示词中的素材联网条件；未设置时提示使用本地资料。它不是网络沙箱。

这是进程、配置和输出目录的隔离，**不是操作系统文件权限沙箱**。内置 bash 本身有当前用户权限；skill/模型必须遵守只写本例工作目录、不读取凭据或无关私有材料的约束。不要将运行目录未经检查上传或作为公开样例发布。

pi 内置 `read` 可以把本地 jpg/png/gif/webp/bmp 作为图像附件交给支持图像的模型；本机360zhinao配置仅声明text输入，不能由作者read图片推定模型已看图；需要支持视觉的独立评阅或人工查看。关闭扩展后没有专门的网页工具，可用现有 `bash` + curl/Python 读取公开网页，配图调用 skill 的 `image_search/search_images.py`。搜索或来源无法访问时必须保留未核实/缺图状态，不能据此编造。基线运行不额外安装搜索平台或启用全局扩展。

本机已检查 `pi --help`、`pi --offline --no-extensions --list-models` 和安装包的 `docs/skills.md`、`docs/models.md`、`docs/json.md`、`dist/core/tools/read.js`。模型出现在列表只表示配置可用，真实调用成功与否由实际运行结果记录。

## 结果与速度

每轮包含：

```text
run.json / snapshot-manifest.json / cases.json
snapshot/open-pptd/                 固定基线
cases/<id>/prompt.md                实际生成提示词
cases/<id>/stdout.jsonl             脱敏 pi 流式事件
cases/<id>/stderr.log
cases/<id>/attempts/02/             发生续行时的 prompt.md、stdout.jsonl、stderr.log
cases/<id>/result.json              时间、退出码、用量、产物清单
cases/<id>/review.json              待评阅评分与证据位置
cases/<id>/work/skill/              本例独立技能副本
cases/<id>/work/output/             本例交付物
SUMMARY.md / summary.json           本轮完整汇总
```

`elapsedSeconds` 是从首个 pi 启动前至本例所有续行结束的耗时（包括续行间核对），`caseElapsedSeconds` 还包含初始复制和最终快照核对，汇总耗时是整个批次墙钟时间。`attempts` 保留每次命令、日志目录、状态、实际剩余截止和本次指标；`continuationCount` 与 `continuationStopReason` 说明续行次数及停止原因。顶层工具/token/cost 为各次合计，工具时间统一换算到本例起点并标明 attempt；原始首轮日志不会被后续覆盖。旧 run 不回填新字段。

`firstEventSeconds` 不等于首 token；`firstTextSeconds` 从第一条可见文本 delta 测量。token 和 cost 来自最终 assistant message 的 provider 上报，未上报不补估，零价格也不等于实际免费。比较速度应固定模型、thinking、并发、页数条件和联网条件，同时报告超时/失败率，不能只比较成功例的平均值。

`artifacts` 保留完整文件清单；`deliveryArtifacts` 只按约定检查 `output/deck/`（兼容根 `output/`）中的同一 `.pptd`、对应 `.pptx` 和同名 HTML/`index.html`/`html/index.html`。单项目仅有一个 PPTX 时允许自定义文件名；多 manifest 时不把通用 index 自动归给某一稿。研究 HTML、隐藏实验目录、空文件以及不同项目的零散格式不能凑成三格式。这只是文件存在检查，实际有效性、页数、检查报告是否对应当前版本及质量仍需独立评阅。生成提示词会明确正式稿、研究和实验位置。

新运行还记录 `toolTimings`：按 toolCallId 匹配工具开始/结束事件的本地 monotonic 收达秒，不附参数或结果内容；没有结束保留 pending，没有开始保留 unmatched_end。`toolDurationSumSeconds` 仅相加已匹配的完成区间，重叠调用会重复计时，不能当作批次墙钟占比。工具区间以外的时间还包含模型/API、调度与流式开销，不能直接命名为网关排队。旧运行没有这些时间，不回填估计值。

| 状态 | 含义 |
|---|---|
| `dry_run` | 只准备，没有模型生成 |
| `generated_unreviewed` | 进程结束且发现同一正式稿的三格式文件；内容、布局和文件有效性尚未判定 |
| `needs_input` | 作者明确指出缺材料；是否恰当需按题目评阅 |
| `incomplete` | 交付物不全或未观察到完成事件 |
| `execution_failed` | 非零退出，或结束时仍有 API/中断错误、出现 content_filter；不能被 exit 0 掩盖。已恢复错误仍保留在 streamErrors 历史中，由 terminalStreamError 区分终态 |
| `author_reported_failure` | 作者自述失败 |
| `timed_out` / `cancelled` | 超时或用户停止 |
| `skill_mutated` | 本例运行修改了技能副本，不是固定版本对照 |
| `runner_error` | runner 本身异常 |

进程退出码：0 表示批次完成且没有已识别执行失败（包含正确请求材料和未评阅生成）；1 表示批次完成但至少一例失败/不完整；2 表示运行准备失败。**没有任何退出码表示质量合格。**

## 质量评阅与迭代

每例 `review.json` 的分数初始为 null，必须先读实际内容、核对关键来源、看渲染图并检查 PPTX/HTML。引用具体页码、元素、截图或来源位置，记录评阅人/模型与日期。文件存在、文字多、截图生成成功、作者自评均不能代替质量评分。

| 维度 | 要看什么 |
|---|---|
| `request_fulfillment` | 受众、页数、必讲内容、禁止图表、留空案例页、历史比例等明确约束 |
| `factual_grounding` | 来源是否支持表述；口径/时间是否一致；虚构是否标注；缺材料是否保留 |
| `professional_depth` | 原理、边界、术语和专业示意是否正确，有没有停留在泛泛标题 |
| `content_richness` | 有效例子、论证、对比与叙事层次，避免重复堆字和无关百科 |
| `image_relevance` | 配图是否对应实体/场景；真实照片和示意/占位区分；来源能否定位 |
| `layout_legibility` | 溢出、遮挡、字号、对比度、留白、阅读顺序和全篇节奏 |
| `delivery_integrity` | PPTX/HTML 实际可打开，图表/图标/文本是否丢失，warnings 是否解释 |
| `teaching_or_actionability` | 培训、科普、旅行、战术等内容能否被目标受众理解并使用 |

使用 1–5 分：1 有重大错误或无法使用；2 需大量重做；3 基本满足、需明显修改；4 可用、仅少量修改；5 完整且准确，表达和细节出色。无配图需求/有意无图可记 null 并写适用性理由，不能机械扣零分。缺主持稿等题目，识别缺材料并交付清楚待填结构可以得高分；编造经营数据、错误史实、错误时事前提或真实汞实验步骤应记阻断问题，不能被高美观分平均掉。

轻量循环：一批针对性修改 → 本地故障测试 → 代表题 smoke → 20 题并发完整运行 → 按以上证据评阅 → 只修共性问题 → 新 run 做同条件对照。记录每例的变化与仍失败的检查，再决定是否继续下一批；一次调用只跑一轮，不会自行无限迭代。新能源旧 case 可另作回归样本，但不修改题目或阈值以让单例通过。

## 对已有 run 做预检和独立评阅

```bash
# 默认只做预检，无模型请求，不修改 work/output 中的生成产物
python3 eval/review.py /tmp/open-pptd-pi-eval/<run目录>

# 人工填写 cases/<id>/review.json 后，重跑上条命令汇总分数与证据
# 也可显式请求一次独立 pi 评阅：默认沿用该 run 的 provider/model
python3 eval/review.py /tmp/open-pptd-pi-eval/<run目录> --pi-review --concurrency 2 --timeout 600 --thinking low

# 仅看指定题目；已有完成的评阅默认保留，显式 --replace-review 才可替换
python3 eval/review.py /tmp/open-pptd-pi-eval/<run目录> --case 03,20
```

默认生成 `REVIEW.md`、`review-summary.json`，以及每例的 `precheck/`。先核对固定 snapshot 校验器哈希，再调用该版 `validate_deck.py` 并将报告写入 precheck，避免覆盖作者的报告。另独立读取 manifest 页数、PPTX ZIP 中的页面清单/字体引用/图片媒体、HTML 的 slide/stage 数量，记录已有 renderHealth/warnings、NEEDS_INPUT 和作者备注。未发现报告或校验器不可用明确写“未检查”；不会据此生成八维分数。已有作者报告也不会被标为独立复验或保证未过期。

人工评分格式沿用每例的 `review.json`：填写 reviewer、scope、blockingFindings 和 dimensions，并在本次实际检查后填写顶层 `evidenceHashes`（相对文件路径 → SHA256）；旧记录无哈希标为 unbound，文件变化标为 stale，保留评语但不接受其分数，不能给旧评分自动补新哈希。每个非 null 分数必须附实际文件/页码证据，例如：

```json
{
  "score": 3,
  "evidence": [{"file": "work/output/pages/3.page", "page": 3, "observation": "掩护次序明确，但没有解释防守换防后的处理。"}]
}
```

`--pi-review` 每例使用全新非交互上下文，仅开放 read/grep/find/ls。显式加载本目录的小型 `read_only_guard.js`，在 pi 的 tool_call 前拦截写工具、目录外路径及越界符号链接；不安装或改动全局扩展。评阅需阅读总览、至少3张可用重点页（不足3张则全看）、相应页面与来源文件。通过实际工具结果记录成功读取的文件和图像，非 null 分数必须引用读过的证据；视觉分必须引用实际查看的图片。

这一模式只做本地证据与视觉样本评阅，`factual_grounding` 和 `delivery_integrity` 必须保持 null：没有独立访问原始外部来源，也没有在 PowerPoint 中实际查看导出结果。允许列出局部事实疑点、结构差异和未核实边界。要完整核实这些维度，仍需人工或另行授权的资料/多格式视觉检查。

模型原始候选、独立日志、读取覆盖范围、thinking 和校验问题保存在 `independent-review*/`；记录通过证据检查后才写入 `review.json`，不通过则保留原评分，并记录本次 rejected、CLI 非零退出。通过仅表示评阅记录符合取证要求，不是断言评分客观正确。已完成人工/模型评阅不会被默认覆盖。未给分的维度继续 null，不生成加权总分。

## runner 测试

```bash
python3 -m unittest discover -s eval -p 'test_*.py' -v
node --test test/pi-eval.test.js
```

测试使用本地 fake pi，不调用付费模型：验证并发重叠、超时清理独立子进程、exit 0 的流式错误、缺材料、凭据隔离与脱敏、快照独立、dry-run，以及“产物存在仍未评阅”。这些测试不代表 20 题已实际生成或内容已通过。

### 可选：真实 PPTX 打开检查

```bash
python3 eval/render_pptx.py /abs/path/run --case 03,08
```

本机安装 LibreOffice、PyMuPDF、Pillow 时，可用独立临时配置把交付 PPTX 打开为 PDF/逐页 PNG/总览，保存到各例 `precheck/native-pptx/`；不修改作者产物，不安装依赖，不接受旧 PDF。每次记录输入哈希、时间和实际结果，缺失/超时/取消返回非零，停止本轮已识别的转换进程。全量可省略 `--case`。人工或独立评阅应与网页截图对照，查图标/箭头/文字/图表丢失。LibreOffice 成功打开不等于 PowerPoint/WPS 播放认证，也不等于页面视觉通过。

## 已完成的实际评测

[2026-09-05首轮报告](reports/2026-09-05.md)：20题完整执行与独立评阅、工具修复、06/08功能复测。首轮0/20三格式交付，复测08只完成缺稿待填框架；不作为整体质量或提速已达标的证明。

## 360zhinao超时诊断

后续项目实测按用户要求显式选择`qihoo / 360zhinao-turbo-aippt-agent-260824`。[诊断记录](reports/2026-09-05-timeout-diagnosis.md)包含两页真实运行、工具时间分解及pi请求参数取证。当前`--thinking off`不代表后端关闭推理，尚无验证有效的关闭参数。

2026-09-06：按用户要求，将生成任务默认截止提高为3600秒；保持既有生成回合、提示词、skill和检查流程。只改变整份pi任务的等待上限，图片后端等已有工具截止各自保留。

[延长等待后的真实复测](reports/2026-09-06-long-timeout.md)：360zhinao两页通用题在17分49秒自然完成三格式，独立检查两页PPTD/PPTX/HTML；原有生成回合保留。该smoke仅运行两页；后续完整20题结果见下文。

## 2026-09-06 完整20题复测

[完整报告](reports/2026-09-06-full20.md)与[文件证据](reports/2026-09-06-full20-evidence.json)：360zhinao、并发2、每题3600秒，保留生成回合，整批20963.615秒（约5小时49分）。20题全部结束：8 timed_out、8 incomplete、2 execution_failed、1 needs_input、1 generated_unreviewed；4份正式稿有三格式，其中06/15仍超时。08为缺主持稿的待填框架，14自然完成生成但有内容问题。8题留下正式PPTD，共89页；19另有1页格式实验、17有29个研究HTML，均不计正式交付。

原始执行终态保留：10接口断流后pi内置重试成功，但runner因历史streamErrors仍标execution_failed；18是content_filter。04/05/11/20最终字面tool_call没有被真正派发。运行期间pi入口版本变化，不能视为同一pi版本的严格控制实验；20份skill副本均未变化。

效果页、原始文件及取证位于报告链接的仓库外run目录。事实准确性、图片语义与裁剪、字体和透明度仍有已证实问题；文件存在或校验零错误不代表可正式交付。当前没有据此新增整题重跑、修改本轮作者产物或减少检查流程。

## 2026-09-07 有限续行与写作流程

[本轮实施与实测记录](reports/2026-09-07-continuation.md)：开发 runner 现在对正常提前停止且缺正式交付的任务最多同会话续行2次，共享原60分钟截止；保留历史错误并单独判断当前终态。skill 增加分模块写入、按页纲补证据和复用现有检查的要求。真实两页通用题完成三格式并做独立多格式检查；电影题被服务端 content_filter 终止。代表题进度和最终结果以该记录为准，不代表新的完整20题通过，也不自动改变日常 pi 的全局行为。


## 自动化判官（auto_judge.py）

对已完成的成稿目录做双模型评审：内容判官读逐页文字（对照原题与 `expected_behavior`），视觉判官看整套页面拼图；7 个维度 1–5 分取判官均值，保留分歧与逐题问题，输出 `summary.json`、`summary.md` 与 `auto-eval.html`。2026-09-07 的 20 题实测与优化分析见 [reports/2026-09-07-production20.md](reports/2026-09-07-production20.md)。

```bash
# 成稿目录里每题一个子目录：deck.pptd + pages/ + .qa-images/pages/*.png（先跑 export_images.py）
python3 eval/auto_judge.py judge  --presentations /path/presentations --cases-file eval/cases.json \
    --out /path/presentations/_auto_eval --key-env QIHOO_API_KEY --workers 3 \
    --context-dir /path/inputs      # 可选：已核实的资料包，避免判官把训练截止后的事件判成编造
python3 eval/auto_judge.py report --presentations /path/presentations --out /path/presentations/_auto_eval
```

判官读的是文字和拼图，不是原生 PPTX；它不是质量通过证明。并发 4 曾在 24GB 内存的本机触发 OOM，建议 3。

## 图搜凭据透传（--pass-env）

runner 默认只给 pi 最小环境；`image_search` 的 baidu/vertical 后端读取 `PPT_API_KEY` / `QIHOO_360_API_KEY` / `QIHOO_API_KEY`，不透传时模型只能退到 Commons/Openverse，配图贴题度明显下降（20 题实测配图维度均分 3.18）。需要时显式传入，值会在所有日志中脱敏：

```bash
python3 eval/run_pi.py ... --pass-env QIHOO_API_KEY
```
