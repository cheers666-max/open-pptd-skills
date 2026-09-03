#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""image_search/pool.py — 配图检索引擎核心（移植自 ppt-skills slide-creator/slide-images/image_pool.py）。

零第三方依赖（stdlib only）：urllib / json / re / hashlib / concurrent.futures。
不依赖 PyYAML / httpx / PIL / imagehash / llm_config——几何门用纯 stdlib 解析
JPEG/PNG/GIF 头，VLM 直接打 360 网关 OpenAI 兼容 chat/completions。

职责（对照 slide-creator 移植关系）：
  - search backends：baidu(/v1/search engine=baidu/imagesearch) / vertical(/saas/vertical)
    / openverse(无 key) / wikimedia(无 key)。auto 链式回退。
  - 几何门：最小尺寸 / 横竖比例（纯 stdlib 读图头）。
  - 去重：canonical URL + sha256。
  - VLM judge：相关性/水印/画质（有 360 key 才启用，否则跳过）。
  - 本地化：下载落 media/。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 配置（env）
# ---------------------------------------------------------------------------

def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return default


def api_key() -> str:
    return _env("PPT_API_KEY", "QIHOO_360_API_KEY", "QIHOO_API_KEY")


def api_base_root() -> str:
    """网关裸 host（无 /v1）。可挂 /saas/* 原生 360 接口。"""
    return _env("PPT_API_BASE", default="https://api.360.cn").rstrip("/")


def api_base_v1() -> str:
    return f"{api_base_root()}/v1"


DEFAULT_MIN_DIM = 360          # 最小边像素（960x540 deck 的配图，低于此模糊）
DEFAULT_MIN_BYTES = 12 * 1024  # 过小文件基本是占位/损坏
MAX_BYTES = 25 * 1024 * 1024   # 下载上限
SEARCH_COUNT = 16              # 多召回留淘汰余量
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 常见图库/素材站水印域名（VLM 之外的前置过滤，宁缺毋滥：只列稳定出戳的）
_WATERMARK_DOMAINS = (
    "vcg.com", "visualchina", "quanjing.com", "dfic.cn", "ppbaike",
    "nipic.com", "699pic.com", "16pic.com", "photophoto.cn", "58pic.com",
    "699pic", "tuchong.com", "hellorf.com", "zsxq.com", "bigbigwork",
    "shutterstock.com", "alamy.com", "dreamstime.com", "123rf.com",
    "istockphoto.com", "gettyimages.", "stock.adobe.com",
)

_IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# upload.wikimedia.org 只接受标准缩略图尺寸（实测白名单，错误提示见 https://w.wiki/GHai）。
# 非白名单宽度（320/640/800/1024/1200/2048...）一律 400，必须改写到白名单档位。
WIKI_THUMB_SIZES = (250, 500, 960, 1280, 1920)

_WIKI_THUMB_RE = re.compile(
    r"^(?P<base>https://upload\.wikimedia\.org/.+/thumb/[^/]+/[^/]+/(?P<fname>[^/?#]+))/(?P<w>\d+)px-[^/?#]+$")


def wikimedia_alt_urls(url: str) -> List[str]:
    """Wikimedia thumb URL 兜底链。

    thumb 结构：.../thumb/<h1>/<h2>/<file>/<W>px-<file>；原图：.../<h1>/<h2>/<file>。
    - 宽度不在白名单 → 先给「≥所求宽度的最小白名单档」（超出上限则给最大档）；
    - 无论宽度是否合规，最后都附原图 URL 作为最终兜底（thumb 渲染失败时原图仍可取）。
    非 wikimedia thumb URL 返回 []。
    """
    m = _WIKI_THUMB_RE.match(url or "")
    if not m:
        return []
    base, fname, w = m.group("base"), m.group("fname"), int(m.group("w"))
    alts: List[str] = []
    if w not in WIKI_THUMB_SIZES:
        bigger = [s for s in WIKI_THUMB_SIZES if s >= w]
        pick = bigger[0] if bigger else WIKI_THUMB_SIZES[-1]
        alts.append(f"{base}/{pick}px-{fname}")
    alts.append(base.replace("/thumb/", "/", 1))
    return alts


class PoolError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# HTTP 基础
# ---------------------------------------------------------------------------

def _req(url: str, *, method: str = "GET", headers: Optional[Dict] = None,
         data: Optional[bytes] = None, timeout: float = 20.0) -> bytes:
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    r = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    with urllib.request.urlopen(r, timeout=timeout) as resp:  # noqa: S310 (公开检索只读)
        return resp.read(MAX_BYTES + 1)


def _json(url: str, *, method: str = "GET", headers: Optional[Dict] = None,
          data: Optional[bytes] = None, timeout: float = 20.0) -> dict:
    raw = _req(url, method=method, headers=headers, data=data, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        raise PoolError(f"json_parse_fail: {exc}") from exc


# ---------------------------------------------------------------------------
# canonical URL / 去重
# ---------------------------------------------------------------------------

_TRACK_PARAMS = re.compile(
    r"^(utm_|spm|from=|fr=|ref=|ref_|source=|src=|campaign|gclid|fbclid|_t=|t=|timestamp=|sign=|token=)",
    re.IGNORECASE)


def canonical_url(url: str) -> str:
    """剥离跟踪参数与 CDN 水印参数，归一化用于去重。

    特殊：bcebos.com 的 query 含 x-bce-process=...watermark,... 时整串剥掉拿原图。
    """
    if not url:
        return url
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:  # noqa: BLE001
        return url
    host = parts.netloc.lower()
    if "bcebos.com" in host and "watermark" in (parts.query or ""):
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    if not parts.query:
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    keep = []
    for kv in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        k = kv[0]
        if _TRACK_PARAMS.match(k + "="):
            continue
        keep.append(kv)
    query = urllib.parse.urlencode(keep)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _is_watermark_domain(url: str) -> bool:
    u = (url or "").lower()
    return any(d in u for d in _WATERMARK_DOMAINS)


# ---------------------------------------------------------------------------
# 纯 stdlib 图片尺寸解析（JPEG/PNG/GIF/WebP/BMP）
# ---------------------------------------------------------------------------

def sniff_size(data: bytes) -> Tuple[Optional[int], Optional[int], str]:
    """返回 (w, h, fmt)。无法解析返回 (None, None, 'unknown')。"""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h), "png"
        if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
            w, h = struct.unpack("<HH", data[6:10])
            return int(w), int(h), "gif"
        if data[:2] == b"BM" and len(data) >= 26:
            w, h = struct.unpack("<ii", data[18:26])
            return abs(int(w)), abs(int(h)), "bmp"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return _webp_size(data)
        if data[:2] == b"\xff\xd8":
            return _jpeg_size(data)
    except Exception:  # noqa: BLE001
        return None, None, "unknown"
    return None, None, "unknown"


def _jpeg_size(data: bytes) -> Tuple[Optional[int], Optional[int], str]:
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # SOF0-SOF15（除 DHT/DAC/RST）：0xC0-0xCF 去掉 C4 C8 CC
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return int(w), int(h), "jpeg"
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if seg_len < 2:
            return None, None, "jpeg"
        i += 2 + seg_len
    return None, None, "jpeg"


def _webp_size(data: bytes) -> Tuple[Optional[int], Optional[int], str]:
    if data[12:16] == b"VP8 " and len(data) >= 30:
        w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return int(w), int(h), "webp"
    if data[12:16] == b"VP8L" and len(data) >= 25:
        b0, b1, b2, b3 = data[21], data[22], data[23], data[24]
        w = 1 + (((b1 & 0x3F) << 8) | b0)
        h = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return int(w), int(h), "webp"
    if data[12:16] == b"VP8X" and len(data) >= 30:
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return int(w), int(h), "webp"
    return None, None, "webp"


# ---------------------------------------------------------------------------
# search backends → [{title,url,description,width,height,license,landing,backend}]
# ---------------------------------------------------------------------------

def _mk(url: str, *, title: str = "", description: str = "",
        width=None, height=None, license: str = "", landing: str = "",
        backend: str = "") -> Dict:
    return {"url": url, "title": title or "", "description": (description or "")[:200],
            "width": width, "height": height, "license": license or "",
            "landing": landing or "", "backend": backend}


def search_baidu(query: str, limit: int = 8) -> List[Dict]:
    """360 网关 baidu/imagesearch。无 key 返回 []。"""
    key = api_key()
    if not key:
        return []
    url = (f"{api_base_v1()}/search?" + urllib.parse.urlencode({
        "engine": "baidu/imagesearch", "query": query, "count": max(limit * 2, SEARCH_COUNT)}))
    try:
        data = _json(url, headers={"Authorization": f"Bearer {key}"}, timeout=15.0)
    except Exception:  # noqa: BLE001
        return []
    out = []
    # 兼容 items (360 search API) 与 references (OpenAI 兼容 schema)
    raw_list = data.get("items") or data.get("references") or []
    for it in raw_list:
        # image 可能是直链 URL 字符串，或 {"url": "..."} 结构
        img_val = it.get("image")
        u = ""
        w, h = it.get("width"), it.get("height")
        if isinstance(img_val, str):
            u = img_val.strip()
        elif isinstance(img_val, dict):
            u = (img_val.get("url") or "").strip()
            w = w or img_val.get("width")
            h = h or img_val.get("height")
        if not u:
            # 回退到 url 字段（若类型为 image）
            if it.get("type") == "image" or re.search(r"\.(jpe?g|png|webp|gif)", it.get("url", ""), re.I):
                u = (it.get("url") or "").strip()
        if not u:
            continue
        u = canonical_url(u) if "bcebos.com" in u else u
        desc = (it.get("title") or it.get("summary") or it.get("desc") or "").strip()
        landing = it.get("url") if it.get("url") != u else ""
        out.append(_mk(u, title=desc, description=desc, width=w, height=h,
                       landing=landing, backend="baidu"))
    return _landscape_first(out)[:limit]


def search_vertical(query: str, limit: int = 8, ratio: Optional[float] = None) -> List[Dict]:
    """360 原生 vertical 文搜图（/saas/vertical）。无 key 返回 []。ratio=w/h 用于对形。"""
    import uuid
    key = api_key()
    if not key:
        return []
    params = {"ref_prom": "360so-v-ik", "sid": str(uuid.uuid4()),
              "q": query, "n": str(max(limit * 2, 10)), "size": 0}
    if ratio and ratio > 0:
        params["whratio"] = round(ratio, 3)
    url = f"{api_base_root()}/saas/vertical?{urllib.parse.urlencode(params)}"
    try:
        data = _json(url, method="POST", data=b"{}",
                     headers={"Authorization": f"Bearer {key}",
                              "Content-Type": "application/json"}, timeout=20.0)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for it in data.get("items") or []:
        u = (it.get("imgurl") or it.get("thumbnail") or "").strip()
        if not u:
            continue
        desc = (it.get("title") or it.get("content") or "").strip()
        w, h = it.get("width"), it.get("height")
        try:
            w = int(w) if w is not None else None
            h = int(h) if h is not None else None
        except (ValueError, TypeError):
            w, h = None, None
        landing = (it.get("url") or it.get("landing") or it.get("pageurl") or "").strip()
        out.append(_mk(u, title=it.get("title", ""), description=desc,
                       width=w, height=h,
                       landing=landing,
                       backend="vertical"))
    return _landscape_first(out)[:limit]


def search_openverse(query: str, limit: int = 8) -> List[Dict]:
    """Openverse（CC 授权聚合，无 key）。"""
    url = ("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode({
        "q": query, "page_size": max(limit * 2, 10), "license_type": "all"}))
    try:
        data = _json(url, timeout=15.0)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for it in data.get("results") or []:
        u = (it.get("url") or "").strip()
        if not u:
            continue
        out.append(_mk(u, title=it.get("title", ""), description=it.get("title", ""),
                       width=it.get("width"), height=it.get("height"),
                       license=(it.get("license") or "") + (" " + it.get("license_version") if it.get("license_version") else ""),
                       landing=it.get("foreign_landing_url") or "", backend="openverse"))
    return _landscape_first(out)[:limit]


def search_wikimedia(query: str, limit: int = 8) -> List[Dict]:
    """Wikimedia Commons（无 key）。两步：搜文件名→取 imageinfo url+尺寸。

    iiurlwidth 必须走标准白名单（见 WIKI_THUMB_SIZES），选 1280 兼顾高清与成功率。
    """
    api = "https://commons.wikimedia.org/w/api.php"
    q1 = {"action": "query", "format": "json", "generator": "search",
          "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": str(max(limit * 2, 10)),
          "gsrnamespace": "6", "prop": "imageinfo", "iiprop": "url|size|extmetadata",
          "iiurlwidth": "1280"}
    try:
        data = _json(f"{api}?{urllib.parse.urlencode(q1)}", timeout=15.0)
    except Exception:  # noqa: BLE001
        return []
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for p in pages.values():
        info = (p.get("imageinfo") or [{}])[0]
        u = info.get("thumburl") or info.get("url") or ""
        if not u:
            continue
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        out.append(_mk(u, title=p.get("title", ""), description=p.get("title", ""),
                       width=info.get("thumbwidth") or info.get("width"),
                       height=info.get("thumbheight") or info.get("height"),
                       license=lic, landing=info.get("descriptionurl") or "",
                       backend="wikimedia"))
    return _landscape_first(out)[:limit]


def _landscape_first(items: List[Dict]) -> List[Dict]:
    """横图优先（按已知 width/height 分堆，未知视作横）。"""
    land, port = [], []
    for it in items:
        w, h = it.get("width"), it.get("height")
        try:
            if w and h and int(h) > int(w):
                port.append(it)
                continue
        except Exception:  # noqa: BLE001
            pass
        land.append(it)
    return land + port


BACKENDS = {
    "baidu": search_baidu,
    "vertical": search_vertical,
    "openverse": search_openverse,
    "wikimedia": search_wikimedia,
}
AUTO_ORDER = ("baidu", "openverse", "wikimedia", "vertical")


def search(query: str, limit: int = 8, backend: str = "auto",
           ratio: Optional[float] = None) -> List[Dict]:
    """链式回退检索。backend=auto 时按 AUTO_ORDER 逐个直到有结果。"""
    names = [backend] if backend in BACKENDS else list(AUTO_ORDER)
    for name in names:
        fn = BACKENDS[name]
        try:
            if name == "vertical":
                res = fn(query, limit=limit, ratio=ratio)
            else:
                res = fn(query, limit=limit)
        except TypeError:
            res = fn(query, limit=limit)
        except Exception:  # noqa: BLE001
            res = []
        if res:
            return res
    return []


# ---------------------------------------------------------------------------
# VLM judge（360 网关 OpenAI 兼容 chat/completions）
# ---------------------------------------------------------------------------

_VLM_PROMPT = """你是 PPT 配图评审。判断这张图是否适合作为下面这个 PPT 页面的配图。

PPT主题：{deck_brief}
当前页内容：{page_text}
配图需求：{desc}
候选图来源标题（caption，仅供参考，非图内容描述）：{caption}

请只返回 JSON（不要解释）：
{{"relevance": 0或1或2, "image_type": "real_photo|clean_diagram|illustration|screenshot|other", "has_media_chrome": true或false, "has_watermark": true或false, "watermark_loc": "none|corner_tl|corner_tr|corner_bl|corner_br|edge_top|edge_bottom|overlay", "quality": 0或1或2, "reason": "一句话"}}

判定标准：
- relevance: 与「配图需求」指代的那个主体的相关程度（0=完全不相关, 1=沾边, 2=对题）。以配图需求为主体判，不以"出现在当前页内容里"为理由放过。图必须来自 PPT 主题对应的场景/作品，而非该实体在其他场景中的出现；不匹配 relevance=0。
- image_type: real_photo=真实照片; clean_diagram=干净示意图/图解; illustration=卡通/插画/概念图; screenshot=视频/网页截图; other=其它
- has_media_chrome: 是否有非水印的媒体污染（视频播放器UI、进度条、正文排版、浏览器边框、日期戳）。示意图自带标注不算。
- has_watermark: 是否有纯粹外加、与图内容无关的叠加（网站logo/二维码/半透明角标/素材站版权戳/台标）。示意图自带的箭头/编号/路线/图说是图的一部分，不算水印。
- quality: 作为 PPT 配图的画质（0=低清/模糊, 1=可用, 2=清晰专业）"""


def vlm_enabled() -> bool:
    return bool(api_key())


def _extract_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


def call_vlm(prompt: str, image_bytes: bytes, *, model: str = "",
             timeout: float = 45.0) -> str:
    """打 360 网关 chat/completions（vision）。失败返回 ''。"""
    key = api_key()
    if not key:
        return ""
    model = model or _env("PPT_VLM_MODEL", "QIHOO_VLM_MODEL",
                          default="bytedance/doubao-seed-1-6-vision")
    b64 = base64.b64encode(image_bytes).decode("ascii")
    fmt = sniff_size(image_bytes)[2]
    mime = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
            "webp": "image/webp", "bmp": "image/bmp"}.get(fmt, "image/jpeg")
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        "max_tokens": 800,
    }
    try:
        data = _json(f"{api_base_v1()}/chat/completions", method="POST",
                     data=json.dumps(payload).encode("utf-8"),
                     headers={"Authorization": f"Bearer {key}",
                              "Content-Type": "application/json"}, timeout=timeout)
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    except Exception:  # noqa: BLE001
        return ""


def judge_image(query: str, image_bytes: bytes, *, deck_brief: str = "",
                page_text: str = "", caption: str = "") -> Dict:
    """返回 {relevance,image_type,has_watermark,quality,reject,composite,reason}。"""
    prompt = _VLM_PROMPT.format(deck_brief=deck_brief or "（未知）",
                                page_text=page_text or "（未知）",
                                desc=query, caption=caption or "（无）")
    raw = call_vlm(prompt, image_bytes)
    v = _extract_json(raw)
    if not isinstance(v, dict):
        return {"relevance": 0, "image_type": "other", "has_watermark": False,
                "quality": 0, "reject": True, "composite": -1, "reason": "vlm_unavailable"}
    rel = int(v.get("relevance", 0) or 0)
    qual = int(v.get("quality", 0) or 0)
    itype = str(v.get("image_type", "other"))
    wm = bool(v.get("has_watermark"))
    chrome = bool(v.get("has_media_chrome"))
    reject = rel == 0 or chrome or itype == "screenshot"
    composite = rel * 10 + qual * 3 - (8 if wm else 0) - (100 if reject else 0)
    return {"relevance": rel, "image_type": itype, "has_watermark": wm,
            "quality": qual, "reject": reject, "composite": composite,
            "reason": str(v.get("reason", ""))[:120]}


# ---------------------------------------------------------------------------
# 下载 + 门 + 选优
# ---------------------------------------------------------------------------

def _fetch_with_url(url: str, timeout: float = 20.0) -> Tuple[Optional[bytes], str]:
    """下载 URL；wikimedia 缩略图尺寸非法(HTTP 400)时自动改写白名单档/原图重试。

    返回 (bytes|None, 实际抓取成功的 URL)。全部失败返回 (None, 原 url)。
    """
    for cand in [url] + wikimedia_alt_urls(url):
        try:
            data = _req(cand, timeout=timeout)
        except Exception:  # noqa: BLE001
            continue
        if data and DEFAULT_MIN_BYTES <= len(data) <= MAX_BYTES:
            return data, cand
    return None, url


def _fetch(url: str, timeout: float = 20.0) -> Optional[bytes]:
    data, _ = _fetch_with_url(url, timeout=timeout)
    return data


def _aspect_ok(w: int, h: int, want: str) -> bool:
    """want: landscape|portrait|any。接近方形(0.8~1.25)两可。"""
    if not w or not h or want == "any":
        return True
    r = w / max(h, 1)
    if 0.8 <= r <= 1.25:
        return True
    return r > 1.0 if want == "landscape" else r < 1.0


def acquire(query: str, *, backend: str = "auto", want: str = "any",
            min_dim: int = DEFAULT_MIN_DIM, use_vlm: bool = True,
            deck_brief: str = "", page_text: str = "",
            seen_hashes: Optional[set] = None, seen_urls: Optional[set] = None,
            limit: int = 8) -> Tuple[Optional[Dict], List[Dict]]:
    """检索→过滤→下载→(VLM)选优。

    返回 (winner, tried)。winner={url,bytes,w,h,fmt,backend,license,landing,score,vlm}。
    无合适返回 (None, tried)。tried 记录每个候选的命运（诊断/报告用）。
    """
    ratio = None  # 由调用方按 bounds 推（可选）
    cands = search(query, limit=limit, backend=backend, ratio=ratio)
    tried: List[Dict] = []
    if not cands:
        return None, tried

    # 预过滤：域名水印 / 重复 URL / 已知尺寸不过关
    pool: List[Dict] = []
    for c in cands:
        u = c.get("url") or ""
        cu = canonical_url(u)
        c["canonical"] = cu
        rec = {"url": u, "backend": c.get("backend"), "fate": ""}
        if _is_watermark_domain(u):
            rec["fate"] = "watermark_domain"
            tried.append(rec)
            continue
        if seen_urls is not None and cu in seen_urls:
            rec["fate"] = "dup_url"
            tried.append(rec)
            continue
        w, h = c.get("width"), c.get("height")
        try:
            if w and h and min(int(w), int(h)) < min_dim:
                rec["fate"] = "too_small_meta"
                tried.append(rec)
                continue
            if w and h and not _aspect_ok(int(w), int(h), want):
                rec["fate"] = "aspect_meta"
                tried.append(rec)
                continue
        except Exception:  # noqa: BLE001
            pass
        pool.append(c)

    # 下载（并发）
    fetched: List[Dict] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_fetch, c["url"]): c for c in pool[:10]}
        for fut in as_completed(futs):
            c = futs[fut]
            b = fut.result()
            rec = {"url": c["url"], "backend": c.get("backend"), "fate": ""}
            if not b:
                rec["fate"] = "fetch_fail"
                tried.append(rec)
                continue
            w, h, fmt = sniff_size(b)
            if fmt not in ("jpeg", "png", "webp", "bmp"):  # gif 动画/动图不用
                rec["fate"] = f"bad_fmt:{fmt}"
                tried.append(rec)
                continue
            if not w or not h or min(w, h) < min_dim:
                rec["fate"] = f"too_small:{w}x{h}"
                tried.append(rec)
                continue
            if not _aspect_ok(w, h, want):
                rec["fate"] = f"aspect:{w}x{h}"
                tried.append(rec)
                continue
            sha = hashlib.sha256(b).hexdigest()
            if seen_hashes is not None and sha in seen_hashes:
                rec["fate"] = "dup_bytes"
                tried.append(rec)
                continue
            fetched.append({**c, "bytes": b, "w": w, "h": h, "fmt": fmt, "sha256": sha})

    if not fetched:
        return None, tried

    # 打分选优
    def _base_score(c: Dict) -> float:
        s = float(min(c["w"] * c["h"], 8_000_000)) / 1_000_000  # 分辨率（封顶）
        if c.get("license"):
            s += 0.5  # 有明确授权信息加分
        if c.get("backend") in ("openverse", "wikimedia"):
            s += 0.3  # 授权干净源加分
        return s

    winner = None
    if use_vlm and vlm_enabled():
        top = sorted(fetched, key=_base_score, reverse=True)[:3]
        judged: List[Dict] = []
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(judge_image, query, c["bytes"],
                              deck_brief=deck_brief, page_text=page_text,
                              caption=(c.get("title", "") + " " + c.get("description", "")).strip()): c
                    for c in top}
            for fut in as_completed(futs):
                c = futs[fut]
                v = fut.result()
                c["vlm"] = v
                c["score"] = v.get("composite", -1)
                judged.append(c)
        ok = [c for c in judged if not c["vlm"].get("reject")]
        pool_pick = ok or judged
        winner = max(pool_pick, key=lambda c: c.get("score", -1)) if pool_pick else None
        if winner and winner["vlm"].get("reject") and winner["vlm"].get("relevance", 0) == 0:
            winner = None  # 全部不相关 → 不硬塞
    else:
        winner = max(fetched, key=_base_score)
        winner["score"] = _base_score(winner)

    return winner, tried
