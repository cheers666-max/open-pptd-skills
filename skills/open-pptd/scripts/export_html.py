#!/usr/bin/env python3
"""Export a PPTD project to a static HTML folder (<deck>/html/).

Drives the skill's viewer.html — the single source of PPTD rendering truth —
through headless Chrome via CDP (Chrome DevTools Protocol). The viewer's
``?export-test=1`` hook builds a ZIP (index.html = all pages concatenated
vertically, plus one self-contained page_NN.html per page, images inlined
as base64 data URLs) and prints it base64 into a hidden div; this script
polls for that div via CDP, extracts, validates, and unpacks the ZIP.

A temporary localhost HTTP server serves both the viewer and the deck files —
``file://`` protocol blocks the viewer's subresource fetches for decks with
many pages or media.

Dependencies: a Chrome/Chromium binary (``CHROME_BIN`` env or common paths)
and websocket-client (auto-installed with ``pip --user`` when missing).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

from deck_server import start_deck_server

SKILL_DIR = Path(__file__).resolve().parent.parent
VIEWER_DEFAULT = SKILL_DIR / "scripts" / "viewer.html"

_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "google-chrome",
    "chromium",
    "chrome",
]


def find_chrome(explicit: str | None) -> str:
    candidates = ([explicit] if explicit else []) + [os.environ.get("CHROME_BIN", "")] + _CHROME_CANDIDATES
    for c in candidates:
        if not c:
            continue
        if Path(c).exists():
            return c
        resolved = shutil.which(c)
        if resolved:
            return resolved
    raise SystemExit("找不到 Chrome/Chromium（可设置 CHROME_BIN 环境变量指定）")


def find_deck(deck_arg: str) -> Path:
    p = Path(deck_arg)
    if p.is_file():
        return p.resolve()
    if p.is_dir():
        candidates = sorted(p.glob("*.pptd"))
        if len(candidates) == 1:
            return candidates[0].resolve()
        raise SystemExit(f"目录中 .pptd 主文件数量应为 1，实际 {len(candidates)}: {p}")
    raise SystemExit(f"找不到 deck: {deck_arg}")


def ensure_websocket():
    try:
        import websocket
        return websocket
    except ImportError:
        process = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "websocket-client"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
        )
        if process.returncode != 0:
            raise RuntimeError(f"failed to install websocket-client:\n{process.stdout[-2000:]}")
        import websocket
        return websocket


def run_viewer_export(viewer: Path, deck: Path, chrome: str, timeout: int) -> bytes:
    """Drive the viewer's export-test hook via CDP and return the ZIP bytes."""
    websocket = ensure_websocket()
    server, port = start_deck_server(viewer, deck.parent)
    chrome_proc = None
    try:
        deck_url = f"http://127.0.0.1:{port}/deck/{quote(deck.name, safe='')}"
        url = f"http://127.0.0.1:{port}/viewer?{urlencode({'deck': deck_url, 'export-test': 1})}"

        # Launch Chrome with remote debugging — retry up to 3 times
        ws_url = None
        for attempt in range(3):
            chrome_proc = subprocess.Popen(
                [chrome, "--headless=new", "--disable-gpu", "--remote-debugging-port=0", "about:blank"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            # Parse the DevTools WS URL from stderr
            deadline = time.monotonic() + 15
            for raw_line in iter(chrome_proc.stderr.readline, b""):
                line = raw_line.decode("utf-8", errors="replace")
                m = re.search(r"ws://\S+", line)
                if m:
                    ws_url = m.group(0)
                    break
                if time.monotonic() > deadline:
                    break
            if ws_url:
                break
            # Chrome failed to start or output WS URL — clean up and retry
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_proc.kill()
            if attempt < 2:
                time.sleep(1)
        if not ws_url:
            raise RuntimeError("could not determine Chrome DevTools WebSocket URL after 3 attempts")

        # Connect to the browser-level WebSocket, create a page target
        proxy_env = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")
        saved_proxy = {k: os.environ.pop(k) for k in proxy_env if k in os.environ}
        try:
            browser_ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        finally:
            os.environ.update(saved_proxy)

        try:
            _msg_id = 0

            def cdp(ws, method, params=None, session_id=None):
                nonlocal _msg_id
                _msg_id += 1
                msg = {"id": _msg_id, "method": method, "params": params or {}}
                if session_id:
                    msg["sessionId"] = session_id
                ws.send(json.dumps(msg))
                while True:
                    resp = json.loads(ws.recv())
                    if resp.get("id") != _msg_id:
                        continue
                    if "error" in resp:
                        raise RuntimeError(f"CDP {method}: {resp['error']}")
                    return resp.get("result", {})

            # Create page target and attach
            target = cdp(browser_ws, "Target.createTarget", {"url": "about:blank"})
            attached = cdp(browser_ws, "Target.attachToTarget", {
                "targetId": target["targetId"], "flatten": True,
            })
            session_id = attached["sessionId"]

            # Navigate to the viewer URL
            cdp(browser_ws, "Page.navigate", {"url": url}, session_id)

            # Poll for export-test-out via Runtime.evaluate
            extract_js = """
              (() => {
                const el = document.getElementById('export-test-out');
                if (el && el.textContent.trim()) return el.textContent.trim();
                const status = document.getElementById('status-line');
                const statusText = status ? status.textContent.trim() : '';
                if (statusText.includes('失败')) return 'ERROR:' + statusText;
                return null;
              })()
            """
            deadline = time.monotonic() + timeout
            result_b64 = None
            while time.monotonic() < deadline:
                resp = cdp(browser_ws, "Runtime.evaluate", {
                    "expression": extract_js, "returnByValue": True,
                }, session_id)
                value = resp.get("result", {}).get("value")
                if value and isinstance(value, str):
                    if value.startswith("ERROR:"):
                        raise RuntimeError(f"viewer export failed: {value[6:]}")
                    result_b64 = value
                    break
                time.sleep(1)

            if result_b64 is None:
                raise RuntimeError(f"viewer 未产出导出数据（等待 {timeout}s 超时）")
            return base64.b64decode(result_b64)
        finally:
            browser_ws.close()
    finally:
        if chrome_proc:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_proc.kill()
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Font embedding: the viewer bundle only names fonts (e.g. "Noto Sans SC"); on a
# machine without them the browser falls back to PingFang/YaHei, whose metrics
# shift numbered markers, list bullets and line breaks. Embed a per-file subset
# of every bundled font the page uses so the HTML renders like the viewer/PPTX.
# ---------------------------------------------------------------------------
FONTS_DIR = Path(__file__).resolve().parent / "fonts"


def _font_manifest() -> dict:
    manifest = FONTS_DIR / "fonts.json"
    if not manifest.is_file():
        return {}
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("fonts", {})
    except ValueError:
        return {}


def _html_text_chars(html: str) -> set:
    body = re.sub(r"<style.*?</style>|<script.*?</script>", " ", html, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);", lambda m: {"quot": '"', "amp": "&", "lt": "<", "gt": ">", "nbsp": " "}.get(m.group(1), " ") if not m.group(1).startswith("#") else chr(int(m.group(1)[2:], 16) if m.group(1)[1] in "xX" else int(m.group(1)[1:])), body)
    chars = set(body)
    chars.update(chr(c) for c in range(0x20, 0x7F))  # ASCII always, numbers/punctuation included
    chars.update("，。、；：？！“”‘’（）《》〈〉【】—…·")
    return {c for c in chars if not c.isspace() or c == " "}


# Subsetting a CJK face takes about 0.4s, and a deck asks for one per page per weight: the 14-page
# 商丘 deck spent 11.4 of its 19.8 export seconds here. The work is pure CPU over an unchanged input,
# so it parallelises, and a page whose text did not change asks for a byte-identical subset — which
# is what the on-disk cache is for. The cache lives beside the deck, never inside the skill: an eval
# run compares the skill copy before and after, and a cache written there would read as a mutation.
FONT_CACHE_ENV = "OPEN_PPTD_FONT_CACHE"


def _subset_cache_dir(out_dir: Path, explicit: Optional[Path] = None) -> Optional[Path]:
    override = os.environ.get(FONT_CACHE_ENV, "").strip()
    if override:
        folder = Path(override)
    elif explicit is not None:
        folder = Path(explicit)
    else:
        folder = out_dir.resolve().parent / ".font-cache"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return folder


def _subset_cache_key(ttf: Path, chars: set) -> str:
    text = "".join(sorted(chars)).encode("utf-8")
    stamp = f"{ttf.name}:{ttf.stat().st_size}".encode()
    return hashlib.sha256(stamp + b"\x00" + text).hexdigest()[:32]


def _cached_subset(folder: Optional[Path], key: str) -> Optional[tuple]:
    if folder is None:
        return None
    for path in folder.glob(f"{key}.*"):
        try:
            return path.read_bytes(), path.suffix.lstrip(".")
        except OSError:
            return None
    return None


def _store_subset(folder: Optional[Path], key: str, data: bytes, flavor: str) -> None:
    if folder is None:
        return
    target = folder / f"{key}.{flavor}"
    try:
        temporary = target.with_suffix(f".{flavor}.{os.getpid()}")
        temporary.write_bytes(data)
        os.replace(temporary, target)
    except OSError:
        pass


def _subset_font_job(args: tuple) -> tuple:
    """Picklable worker: (ttf path string, sorted chars) -> (bytes, flavor) or an error string."""
    ttf, text = args
    try:
        return _subset_font(Path(ttf), set(text)), None
    except Exception as exc:  # noqa: BLE001 — never fail the export because of a font
        return None, f"{Path(ttf).name}: {exc}"


def _subset_font(ttf: Path, chars: set) -> tuple:
    """Return (bytes, format) of a subset font, woff2 when brotli is available else woff."""
    from fontTools import subset as ft_subset  # fontTools is a declared dependency of the skill toolchain
    from fontTools.ttLib import TTFont
    font = TTFont(str(ttf))
    options = ft_subset.Options()
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.layout_features = ["*"]
    options.hinting = False
    try:
        import brotli  # noqa: F401
        options.flavor = "woff2"
    except ImportError:
        options.flavor = "woff"
    subsetter = ft_subset.Subsetter(options=options)
    subsetter.populate(text="".join(sorted(chars)))
    subsetter.subset(font)
    buf = io.BytesIO()
    font.flavor = options.flavor
    font.save(buf)
    return buf.getvalue(), options.flavor


def _families_in_html(html: str) -> set:
    """Every family named in any font-family declaration, including each fallback in a stack."""
    text = html.replace("&quot;", '"').replace("&#39;", "'")
    generic = {"system-ui", "sans-serif", "serif", "monospace", "cursive", "fantasy", "ui-sans-serif",
               "ui-serif", "ui-monospace", "inherit", "initial", "unset", "undefined"}
    fams = set()
    for m in re.finditer(r"font-family\s*:\s*([^;}\n]+)", text):
        for part in m.group(1).split(","):
            name = part.strip().strip('"').strip("'").strip()
            if name and not name.startswith("-") and name.lower() not in generic:
                fams.add(name)
    return fams


def embed_fonts(out_dir: Path, enabled: bool = True, cache_dir: Optional[Path] = None) -> dict:
    """Inject @font-face subsets into every exported HTML file. Returns a summary dict."""
    summary = {"embedded": [], "missing": [], "skipped": not enabled}
    if not enabled:
        return summary
    manifest = _font_manifest()
    if not manifest:
        summary["missing"].append("fonts/fonts.json")
        return summary
    cache: dict = {}
    cache_folder = _subset_cache_dir(out_dir, cache_dir)
    # Two passes: work out what every page needs, subset each distinct (face, character set) once,
    # then write the pages. One page's worth of text is one job, and most decks repeat both.
    plans: list = []
    for html_path in sorted(out_dir.glob("*.html")):
        html = html_path.read_text(encoding="utf-8")
        if "/* open-pptd embedded fonts */" in html:
            continue
        # Sorted, so two exports of the same deck embed the same faces in the same order: the file
        # is otherwise byte-identical, and a diff that moves 200KB of base64 around hides real changes.
        families = sorted(_families_in_html(html))
        wanted = []  # (css family, weight, manifest entry)
        for fam in families:
            for name, entry in manifest.items():
                if name == fam:
                    wanted.append((fam, 400, entry))
                elif name == f"{fam} Bold":
                    wanted.append((fam, 700, entry))
        if not wanted:
            continue
        # A family with only a bold file still gets that file for weight 400 (better than a foreign fallback).
        have_regular = {fam for fam, w, _ in wanted if w == 400}
        for fam, w, entry in list(wanted):
            if w == 700 and fam not in have_regular:
                wanted.append((fam, 400, entry))
        chars = _html_text_chars(html)
        needed = []
        for fam, weight, entry in wanted:
            ttf = FONTS_DIR / entry.get("file", "")
            if not ttf.is_file():
                summary["missing"].append(str(ttf.name))
                continue
            needed.append((fam, weight, ttf))
        if needed:
            plans.append((html_path, html, chars, needed))

    jobs = {}
    for _path, _html, chars, needed in plans:
        for _fam, _weight, ttf in needed:
            key = (ttf.name, frozenset(chars))
            if key in cache or key in jobs:
                continue
            disk_key = _subset_cache_key(ttf, chars)
            hit = _cached_subset(cache_folder, disk_key)
            if hit is not None:
                cache[key] = hit
            else:
                jobs[key] = (str(ttf), "".join(sorted(chars)), disk_key)
    if jobs:
        keys = list(jobs)
        payload = [(jobs[k][0], jobs[k][1]) for k in keys]
        workers = min(len(keys), os.cpu_count() or 1, 8)
        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                outcomes = list(pool.map(_subset_font_job, payload))
        else:
            outcomes = [_subset_font_job(item) for item in payload]
        for key, (result, error) in zip(keys, outcomes):
            if error:
                summary["missing"].append(error)
                continue
            cache[key] = result
            _store_subset(cache_folder, jobs[key][2], result[0], result[1])

    for html_path, html, chars, needed in plans:
        faces = []
        for fam, weight, ttf in needed:
            entry = cache.get((ttf.name, frozenset(chars)))
            if entry is None:
                continue
            data, flavor = entry
            b64 = base64.b64encode(data).decode("ascii")
            faces.append(f"@font-face{{font-family:\"{fam}\";font-weight:{weight};font-style:normal;font-display:block;"
                         f"src:url(data:font/{flavor};base64,{b64}) format(\"{flavor}\");}}")
            summary["embedded"].append({"file": html_path.name, "family": fam, "weight": weight, "bytes": len(data), "format": flavor})
        if not faces:
            continue
        style = "<style>/* open-pptd embedded fonts */" + "".join(faces) + "</style>"
        if "<head>" in html:
            html = html.replace("<head>", "<head>" + style, 1)
        else:
            html = style + html
        html_path.write_text(html, encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("deck", help="PPTD 项目目录或 deck.pptd 主文件路径")
    ap.add_argument("--output-dir", help="输出目录（默认 <deck 所在目录>/html）")
    ap.add_argument("--viewer", default=str(VIEWER_DEFAULT), help="viewer.html 路径（默认 skill 自带）")
    ap.add_argument("--chrome", help="Chrome 可执行文件路径（默认自动探测/CHROME_BIN）")
    ap.add_argument("--timeout", type=int, default=180, help="导出等待超时秒数")
    ap.add_argument("--no-embed-fonts", action="store_true", help="不把字体子集嵌入 HTML（默认嵌入，保证无 Noto 字体的机器上序号/排版不偏移）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 结果")
    args = ap.parse_args()

    try:
        deck = find_deck(args.deck)
        viewer = Path(args.viewer).resolve()
        if not viewer.is_file():
            raise SystemExit(f"viewer.html 不存在: {viewer}")
        chrome = find_chrome(args.chrome)
        out_dir = Path(args.output_dir).resolve() if args.output_dir else deck.parent / "html"

        zip_bytes = run_viewer_export(viewer, deck, chrome, args.timeout)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise RuntimeError(f"ZIP 校验失败: {bad}")
            names = zf.namelist()
            zf.extractall(out_dir)
        fonts = embed_fonts(out_dir, enabled=not args.no_embed_fonts)

        result = {
            "ok": True,
            "deck": str(deck),
            "output_dir": str(out_dir),
            "files": sorted(names),
            "page_count": sum(1 for n in names if re.fullmatch(r"page_\d+\.html", n)),
            "zip_bytes": len(zip_bytes),
            "fonts": {"embedded": len(fonts["embedded"]), "bytes": sum(f["bytes"] for f in fonts["embedded"]),
                      "families": sorted({f["family"] for f in fonts["embedded"]}), "missing": sorted(set(fonts["missing"]))},
        }
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — 统一转为 JSON/可读错误
        result = {"ok": False, "error": str(exc)}
        if not args.json:
            print(f"❌ HTML 导出失败: {exc}", file=sys.stderr)
            sys.exit(1)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"✅ HTML 导出完成 → {result['output_dir']}")
        for f in result["files"]:
            print(f"   {f}")

    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
