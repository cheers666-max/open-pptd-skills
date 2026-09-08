# 360 内网 / online 导出

此功能属于 `360-intranet` 分支。沿用 PPTD 作者流程、本地渲染和 PPTX 引擎，在需要在线图片复用或网页交付时调用 `scripts/export_online.py`。无需新增服务端。

## 配置

上传使用 360 网关的 multipart 附件协议：`POST /v1/upload/attachment`，字段 `file`，Bearer 鉴权，读取响应 `data.url`。实际存储地址由服务端决定，不是客户端用 S3 SDK 指定 bucket/key。

| 环境变量 | 用途 |
|---|---|
| `PPT_API_KEY` | 上传凭证；兼容已有 `QIHOO_360_API_KEY` / `QIHOO_API_KEY`，按此顺序取首个非空值。 |
| `PPT_API_BASE` | 网关根地址；带或不带 `/v1` 均可。默认 `https://aigw.aijjt.com`。 |
| `S3_API_URL` | 可选：完整附件上传地址，优先于 `PPT_API_BASE`。必须指向支持上述响应协议的接口。 |
| `CHROME_BIN` | 可选：本地 Chrome/Chromium 可执行文件。 |

从宿主的环境或秘密管理配置注入凭证。脚本不扫描其他项目的 `.env`，不自动加载配置文件；不要把真实密钥写入 skill、命令日志、页面或版本库。样例见 `scripts/online.env.example`。

模型网关与上传网关可能不同。`api.360.cn` 的模型凭证/根地址不保证支持该附件协议；出现 HTTP 404 时核对完整 `S3_API_URL`，HTTP 401/403 时核对该上传服务认可的凭证。不要静默切换服务或反复重试相同配置。

需要 Python 3.9+、PyYAML、Pillow、websocket-client 和 Chrome；Python 依赖与现有截图流程相同。缺少时可安装：

```bash
python3 -m pip install PyYAML Pillow websocket-client
```

## 命令

先完成页纲、真实素材选择、`search:` 槽位解析、内容终审和视觉检查。已有任务授权覆盖图片上传/网页发布时直接执行；凭证存在本身不代表用户要求发布。

默认交付完整、自包含 PPTD 时，先用 `image_search/search_images.py <project> --localize-remote` 把原稿图片本地化，再跑原有检查。若只要求在线导出并保留原稿远程引用，原稿的 `unresolved-remote-url` 提示由本入口临时副本的解码/渲染检查及最终网页检查核验；不能据此声称原始 PPTD 已自包含。`search:` 未解析或其他内容/布局问题仍须处理。

```bash
# 在线 HTML：图片下载并上传，HTML 引用上传后的地址；同时上传网页，返回访问链接
python3 scripts/export_online.py /abs/path/deck/deck.pptd --publish --json

# 图片也上传，但交付 HTML 内嵌图片字节，下载后的网页不依赖图片 URL
python3 scripts/export_online.py /abs/path/deck/deck.pptd --images embed --json
```

省略 `--publish` 只上传图片并写本地 HTML。纯本地/离线导出仍使用 `export_html.py`，不需要上传凭证。

| 参数 | 默认 / 说明 |
|---|---|
| `--images remote\|embed` | 默认 `remote`：使用公网图片地址；`embed`：图片内嵌。两种模式均上传图片。 |
| `--publish` | 另上传并验证合并页和每张单页的 HTML。 |
| `--output-dir` | 默认 `<deck>/html-online/`；须为空目录或本工具上次产物目录，成功时整目录替换。含其他资料的非产物目录会拒绝覆盖。 |
| `--timeout` | 180 秒，本地 viewer 导出等待时间。 |
| `--request-timeout` | 30 秒，每个 HTTP socket 的等待超时；不是整任务总截止。 |
| `--chrome` | 覆盖 Chrome 路径。 |
| `--json` | stdout 一份 JSON，进度写 stderr。 |

## 行为与交付

1. 只读 manifest 实际引用的 `.page`，递归识别图片元素、背景、填充和分组内图片，包括 YAML 行内写法。表格主题样式先按现有 viewer 优先级展开为有效单元格样式，因此主题图片也会处理，未使用的样式不会下载。同一 URL 只下载一次，相同字节在本次导出只上传一次。
2. 本地/远程/data 图片统一验证格式；下载限制 20 MiB。支持 PNG/JPEG/GIF/WebP/BMP 及独立 SVG；有脚本或外部引用的 SVG 不支持。`search:` 未解析、文件丢失、越出项目目录或无效图片均报错。
3. 在临时副本中使用本地图片，经现有 viewer 渲染检查。原 manifest、pages 和 media 不改写为上传 URL。
4. 上传图片后，不带上传凭证读回 URL，核对原始字节。`remote` HTML 替换已内嵌图片为上传 URL；`embed` HTML 保留内嵌字节。公网图不需要浏览器跨域 fetch 转 base64。
5. `--publish` 同样读回网页核对字节。所有步骤成功后才替换输出目录，保留下载的图片到 `assets/`。网页链接无需同行目录里的 assets；`remote` 仍需图片服务可访问，`embed` 图片不依赖网络。字体沿用系统字体。
6. `online-report.json` 保存 `assets[]`（本地文件、SHA256、来源、URL）、页数和 `published` URL 映射。它留在本地，脚本不会上传报告或源 PPTD。报告可能包含素材来源 URL，按项目资料管理。

退出 `0` 且 `ok: true` 才代表本次命令完成。上传失败、业务错误、响应缺 URL、URL 无法读取或内容不同均退出 `1`，保留原稿和上次成功的输出；不以本地导出成功替代 online 成功。已成功上传的部分附件不会自动删除，也不承诺跨运行上传去重。排查凭证/接口/素材后重跑。

交付前打开 `published["index.html"]` 或本地 `index.html`，查看图片、裁切和页序；HTTP 字节验证不代替实际看图。`--images embed` 的单文件离线图片自包含也不代表包含系统字体。
