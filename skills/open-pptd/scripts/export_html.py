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
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

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
        url = f"http://127.0.0.1:{port}/viewer?deck=http://127.0.0.1:{port}/deck/{deck.name}&export-test=1"

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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("deck", help="PPTD 项目目录或 deck.pptd 主文件路径")
    ap.add_argument("--output-dir", help="输出目录（默认 <deck 所在目录>/html）")
    ap.add_argument("--viewer", default=str(VIEWER_DEFAULT), help="viewer.html 路径（默认 skill 自带）")
    ap.add_argument("--chrome", help="Chrome 可执行文件路径（默认自动探测/CHROME_BIN）")
    ap.add_argument("--timeout", type=int, default=180, help="导出等待超时秒数")
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

        result = {
            "ok": True,
            "deck": str(deck),
            "output_dir": str(out_dir),
            "files": sorted(names),
            "page_count": sum(1 for n in names if re.fullmatch(r"page_\d+\.html", n)),
            "zip_bytes": len(zip_bytes),
        }
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — 统一转为 JSON/可读错误
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


if __name__ == "__main__":
    main()
