#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""image_search/search_images.py — 把 PPTD 工程里的图片占位符解析为本地 media/ 真实图。

用法：
  python3 search_images.py <project_dir|deck.pptd> [--backend auto|baidu|vertical|openverse|wikimedia]
                           [--workers N] [--no-vlm] [--localize-remote] [--min-dim N] [--dry-run]

工作流（open-pptd step3.5）：
  1. 读 <project>.pptd（或直接给工程目录）→ 找到 pages/*.page。
  2. 扫每个 .page 的 `src: "search:<query>"` 占位（image/background/fill）与（可选）远端 URL。
  3. 对每个槽位并发检索+下载+(VLM)选优，落盘到 media/，并把 .page 的 src 改成本地相对路径。
  4. 写 images_report.json（逐槽 provenance：query/backend/source_url/license/尺寸/得分/命运）。
  5. exit 0=全部解决；2=有未解决槽（报告里列出，需人工/模型改元素）；1=用法/IO 错误。

依赖：仅 stdlib（pool.py + slots.py）。VLM 需 PPT_API_KEY / QIHOO_360_API_KEY。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pool  # noqa: E402
import slots as slots_mod  # noqa: E402


def _find_project(target: str):
    """返回 (project_dir, pptd_path)。target 可是目录或 .pptd 文件。"""
    if os.path.isdir(target):
        pdir = target
        pptds = [f for f in os.listdir(pdir) if f.endswith(".pptd")]
        pptd = os.path.join(pdir, pptds[0]) if pptds else None
        return pdir, pptd
    if os.path.isfile(target) and target.endswith(".pptd"):
        return os.path.dirname(os.path.abspath(target)), target
    raise SystemExit(f"[err] 不是工程目录或 .pptd：{target}")


def _list_pages(pdir: str) -> List[str]:
    pages_dir = os.path.join(pdir, "pages")
    if not os.path.isdir(pages_dir):
        return []
    return sorted(f for f in os.listdir(pages_dir) if f.endswith(".page"))


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _deck_brief(pdir: str, pptd: Optional[str]) -> str:
    """从 .pptd manifest 的 title 提取主题（VLM 消歧用）。"""
    if pptd and os.path.isfile(pptd):
        m = re.search(r"^\s*title:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", _read(pptd), re.MULTILINE)
        if m:
            return m.group(1).strip()
    return os.path.basename(pdir.rstrip("/"))


def _slugify(text: str, fallback: str) -> str:
    s = re.sub(r"[^0-9A-Za-z一-鿿]+", "-", text).strip("-").lower()
    return (s[:40] or fallback)


_EXT = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "bmp": ".bmp"}


def run(project: str, *, backend: str = "auto", workers: int = 4, use_vlm: bool = True,
        localize_remote: bool = False, min_dim: int = pool.DEFAULT_MIN_DIM,
        dry_run: bool = False) -> int:
    pdir, pptd = _find_project(project)
    pages = _list_pages(pdir)
    if not pages:
        print(f"[err] 未找到 pages/*.page：{pdir}")
        return 1
    brief = _deck_brief(pdir, pptd)
    media_dir = os.path.join(pdir, "media")
    os.makedirs(media_dir, exist_ok=True)

    # 收集所有槽位
    all_slots: List[slots_mod.Slot] = []
    page_texts: Dict[str, str] = {}
    for pg in pages:
        rel = f"pages/{pg}"
        text = _read(os.path.join(pdir, rel))
        page_texts[rel] = text
        for s in slots_mod.extract_slots(text, rel):
            if s.is_search or (localize_remote and s.is_remote):
                all_slots.append(s)

    if not all_slots:
        print("[ok] 无 search: 占位符（" + ("也无远端 URL" if not localize_remote else "且未开 --localize-remote") + "），无需配图检索。")
        return 0

    n_search = sum(1 for s in all_slots if s.is_search)
    n_remote = len(all_slots) - n_search
    print(f"[scan] {len(pages)} 页，{len(all_slots)} 个待解析图片槽（search:{n_search} remote:{n_remote}）"
          f" backend={backend} vlm={'on' if use_vlm and pool.vlm_enabled() else 'off'}"
          + (" [dry-run]" if dry_run else ""))
    if dry_run:
        for s in all_slots:
            r = f" ratio={s.ratio:.3f}" if s.ratio else ""
            print(f"  - {s.page}:{s.line_no} [{s.kind}] {s.element_id or '-'} want={s.want}{r} :: {s.raw_src[:60]}")
        return 0

    # 全 deck 级去重集合
    seen_hashes: set = set()
    seen_urls: set = set()

    def _resolve(s: slots_mod.Slot) -> slots_mod.Slot:
        if s.is_remote and not s.is_search:
            # 远端 URL 本地化：直接下载（wikimedia 非法缩略图尺寸自动改写重试）
            b, final_url = pool._fetch_with_url(s.raw_src)  # noqa: SLF001
            if b:
                w, h, fmt = pool.sniff_size(b)
                if fmt in _EXT and w and h and min(w, h) >= min_dim:
                    s.winner = {"url": final_url, "bytes": b, "w": w, "h": h, "fmt": fmt,
                                "backend": "remote", "license": "", "landing": s.raw_src,
                                "score": 0, "vlm": {},
                                "sha256": hashlib.sha256(b).hexdigest(),
                                "canonical": pool.canonical_url(final_url)}
                    s.status = "resolved"
                    return s
            s.status = "failed"
            return s
        page_text = page_texts.get(s.page, "")
        # 取该页正文前若干字供 VLM 消歧
        snippet = re.sub(r"\s+", " ", re.sub(r"[{}#*\[\]]", " ", page_text))[:400]
        winner, tried = pool.acquire(
            s.query, backend=backend, want=s.want, min_dim=min_dim, use_vlm=use_vlm,
            ratio=s.ratio,
            deck_brief=brief, page_text=snippet, seen_hashes=seen_hashes, seen_urls=seen_urls)
        s.tried = tried
        if winner:
            s.winner = winner
            s.status = "resolved"
        else:
            s.status = "failed"
        return s

    results: List[slots_mod.Slot] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(_resolve, s): s for s in all_slots}
        for fut in as_completed(futs):
            results.append(fut.result())

    # 落盘 + 回填 .page + 登记去重
    resolved = 0
    report_slots = []
    for s in sorted(results, key=lambda x: (x.page, x.line_no)):
        if s.status == "resolved" and s.winner:
            w = s.winner
            base = s.element_id or _slugify(s.query or os.path.basename(s.page), "img")
            fname = f"{_slugify(base, 'img')}{_EXT.get(w['fmt'], '.jpg')}"
            fpath = os.path.join(media_dir, fname)
            # 同名冲突加短 hash
            if os.path.exists(fpath):
                stem, ext = os.path.splitext(fname)
                fname = f"{stem}-{hashlib.sha256(w['bytes']).hexdigest()[:6]}{ext}"
                fpath = os.path.join(media_dir, fname)
            _write_bytes(fpath, w["bytes"])
            rel_media = f"media/{fname}"
            s.local_path = rel_media
            page_texts[s.page] = slots_mod.patch_src(page_texts[s.page], s.line_no, s.raw_src, rel_media)
            seen_hashes.add(w["sha256"])
            seen_urls.add(w.get("canonical") or pool.canonical_url(w["url"]))
            resolved += 1
            report_slots.append({
                "page": s.page, "elementId": s.element_id, "kind": s.kind,
                "query": s.query or s.raw_src, "status": "resolved", "local": rel_media,
                "source_url": w["url"], "backend": w.get("backend"), "license": w.get("license", ""),
                "landing": w.get("landing", ""), "width": w["w"], "height": w["h"],
                "score": round(float(w.get("score", 0)), 2),
                "vlm": {k: w.get("vlm", {}).get(k) for k in ("relevance", "image_type", "has_watermark", "quality", "reason") if w.get("vlm")},
            })
        else:
            report_slots.append({
                "page": s.page, "elementId": s.element_id, "kind": s.kind,
                "query": s.query or s.raw_src, "status": "failed",
                "tried": getattr(s, "_tried", [])[:6],
            })

    # 写回改过的 .page
    for rel, text in page_texts.items():
        _write(os.path.join(pdir, rel), text)

    failed = len(all_slots) - resolved
    report = {
        "project": os.path.basename(pdir.rstrip("/")),
        "deck_brief": brief,
        "backend": backend,
        "vlm": bool(use_vlm and pool.vlm_enabled()),
        "total_slots": len(all_slots),
        "resolved": resolved,
        "failed": failed,
        "slots": report_slots,
    }
    _write(os.path.join(pdir, "images_report.json"), json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(f"[done] resolved={resolved}/{len(all_slots)} → images_report.json")
    if failed:
        print(f"[warn] {failed} 个槽未解决（见 images_report.json failed 项），请改 .page 元素或放宽条件：")
        for s in report_slots:
            if s["status"] == "failed":
                print(f"  - {s['page']} [{s['kind']}] {s.get('elementId') or '-'} :: {s['query'][:60]}")
        return 2
    return 0


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Resolve PPTD image search: placeholders into local media/")
    ap.add_argument("project", help="PPTD 工程目录或 .pptd 文件路径")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "baidu", "vertical", "openverse", "wikimedia"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-vlm", action="store_true", help="禁用 VLM 评审（纯几何/分辨率门）")
    ap.add_argument("--localize-remote", action="store_true",
                    help="同时把 http(s) 远端 src 下载本地化")
    ap.add_argument("--min-dim", type=int, default=pool.DEFAULT_MIN_DIM)
    ap.add_argument("--dry-run", action="store_true", help="只扫描列出槽位，不检索/下载/改写")
    args = ap.parse_args(argv)
    return run(args.project, backend=args.backend, workers=args.workers,
               use_vlm=not args.no_vlm, localize_remote=args.localize_remote,
               min_dim=args.min_dim, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
