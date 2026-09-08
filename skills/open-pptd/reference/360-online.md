# 360 内网 / online 导出

此功能属于 `360-intranet` 分支。沿用 PPTD 作者流程、本地渲染和 PPTX 引擎，在需要在线图片复用或网页交付时调用 `scripts/export_online.py`。无需新增服务端。

## 配置

支持 OBS/S3 直传和 360 网关附件两种上传方式。已有 OBS 配置时优先复用 OBS，不要把 OBS endpoint 填入附件接口的 `S3_API_URL`。指定 `--obs-config` 或 `OBS_CONFIG` 自动选择 OBS；也可用 `--upload-backend obs` / `PPT_UPLOAD_BACKEND=obs` 显式选择。未选择 OBS 时保留附件入口，两者不会在失败时互相切换。

### OBS / XStore（推荐复用现有配置）

通过 boto3 的 S3 协议上传，使用 OBS 的 AK/SK，不需要模型或附件网关的 `PPT_API_KEY`。可直接读取现有受保护 YAML，不需要复制密钥。支持顶层 `obs`（旧配置）、`profiles.<name>`、`targets.<name>`；只有一个 profile 时自动选择，多个时需 `--obs-profile`。配置格式见 `scripts/obs-profiles.example.yaml`。

| 字段 | 用途 |
|---|---|
| `endpoint`、`region`、`bucket` / `bucket_name` | HTTPS 服务地址、签名区域和 bucket。三者分别读取，不从域名推断区域。 |
| `addressing_style` | 默认 `path`；`virtual` 需配 `public_base_url`。 |
| `public_base_url` | 默认 `{endpoint}/{bucket}`；可使用既有 CDN/网站地址。 |
| `access_key_env`、`secret_key_env` | 指向已有环境变量的名称，优先于旧配置中的明文值；声明后变量缺失会报错。也接受 `credentials` 下的这些引用。 |
| `access_key_id`、`access_key_secret` / `secret_access_key` | 兼容现有受保护配置；不要复制到仓库或页面。 |
| `session_token_env` / `session_token` | 可选临时凭证。 |

不自动探测其他项目配置、AWS 默认凭证链或本机 skill 路径。郑州现有配置使用 `endpoint=https://cn-zhengzhou-3.xstore.qihu.com`、`region=cn-north-4`、`bucket=mcp-yue-tool`；北京示例使用 `beijing2.xstore.qihoo.net`、`beijing2`、`agent-ppt`，北京本轮未实测。环境参考示例只存变量名，没有密钥。

```bash
python3 -m pip install 'boto3>=1.36' PyYAML Pillow websocket-client

# 本机已有郑州 OBS skill 配置时，直接读取；默认生成唯一远程目录
python3 scripts/export_online.py /abs/path/deck/deck.pptd \
  --obs-config "$HOME/.skills/obs-zhengzhou-upload/references/profile.yaml" \
  --publish --json

# 其他机器由宿主配置路径，或使用环境变量引用示例（先注入对应的 AK/SK）
python3 scripts/export_online.py /abs/path/deck/deck.pptd \
  --obs-config scripts/obs-profiles.example.yaml --obs-profile zhengzhou \
  --publish --json
```

OBS 默认在 `open-pptd/<随机UUID>/` 下存放 `assets/<SHA256>.<ext>`、各单页和 `index.html`；也可指定新的 `--obs-prefix` / `OBS_PREFIX`。每个对象先 HEAD 检查；相同大小与 SHA256 的对象只读回验证，已有不同或不可核实内容则停止，使用新前缀重跑。该检查不是跨客户端的原子锁，仍应选唯一前缀。不自动覆盖、删除对象或修改 bucket 权限。

上传后校验对象元信息、通过对象接口读回原始字节，再对返回地址做不带凭证的 GET 校验。所有图片先传，各单页随后，合并 `index.html` 最后。若 bucket 本身不允许直接读取，返回验证失败；不会自动改 ACL 或签发临时链接。

### 360 网关附件（兼容入口）

附件使用 multipart 协议：`POST /v1/upload/attachment`，字段 `file`，Bearer 鉴权，读取响应 `data.url`。实际存储地址由服务端决定。

| 环境变量 | 用途 |
|---|---|
| `PPT_API_KEY` | 上传凭证；兼容已有 `QIHOO_360_API_KEY` / `QIHOO_API_KEY`，按此顺序取首个非空值。 |
| `PPT_API_BASE` | 网关根地址；带或不带 `/v1` 均可。默认 `https://aigw.aijjt.com`。 |
| `S3_API_URL` | 可选：完整附件上传地址，优先于 `PPT_API_BASE`。必须指向支持上述响应协议的接口。 |
| `CHROME_BIN` | 可选：本地 Chrome/Chromium 可执行文件。 |

从宿主的环境或秘密管理配置注入附件凭证。脚本不扫描其他项目的 `.env`；不要把真实密钥写入 skill、命令日志、页面或版本库。样例见 `scripts/online.env.example`。OBS 只加载显式选择的配置文件。

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
| `--upload-backend obs\|attachment` | 显式选择上传方式；优先于 `PPT_UPLOAD_BACKEND`。未指定时，有 OBS 配置即用 OBS，否则用附件。 |
| `--obs-config`、`--obs-profile` | 已有配置文件和 profile；兼容 `OBS_CONFIG`、`OBS_PROFILE`。 |
| `--obs-prefix` | OBS 远程对象前缀；兼容 `OBS_PREFIX`，默认生成唯一目录。不可用于附件接口。 |
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
5. `--publish` 同样读回网页核对字节。所有步骤成功后才替换输出目录，保留下载的图片到 `assets/`。online 网页在窄屏按比例缩放画布，保持作者坐标和布局。网页链接无需同行目录里的 assets；`remote` 仍需图片服务可访问，`embed` 图片不依赖网络。字体沿用系统字体。
6. `online-report.json` 保存 `upload_backend`、`assets[]`（本地文件、SHA256、来源、URL）、页数和 `published` URL 映射；OBS 另含 `storage`（bucket、prefix、各对象的创建/复用与校验结果）。它留在本地，脚本不会上传报告、配置或源 PPTD。报告可能包含素材来源 URL，按项目资料管理。

退出 `0` 且 `ok: true` 才代表本次命令完成。上传失败、业务错误、响应缺 URL、URL 无法读取或内容不同均退出 `1`，保留原稿和上次成功的输出；不以本地导出成功替代 online 成功。已成功上传的部分对象或附件不会自动删除。OBS 同前缀的同内容对象可复用，新前缀会重新存储；附件不承诺跨运行上传去重。排查凭证/接口/素材后重跑。

OBS 传输或公开读取失败时，错误 JSON 的 `details` 保留此前对象、`failed_key` 和 `write_succeeded`。对象的 `verified` 表示对象接口校验通过，`public_verified` 表示无凭证读取也通过。`write_succeeded: false` 只表示未收到本次写入成功确认，网络超时后仍可能存在远端对象；不要自动删除或覆盖。

OBS SDK 参数参考：[Boto3 S3 put_object](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html) 与 [Boto3 configuration](https://docs.aws.amazon.com/boto3/latest/guide/configuration.html)。本入口不修改 bucket 配置。

交付前打开 `published["index.html"]` 或本地 `index.html`，查看图片、裁切和页序；HTTP 字节验证不代替实际看图。`--images embed` 的单文件离线图片自包含也不代表包含系统字体。
