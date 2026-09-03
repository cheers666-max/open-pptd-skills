#!/usr/bin/env python3
"""Download open-source fonts for PPTD export.

Manages a local font cache at ``scripts/fonts/``. Fonts are downloaded
on demand from public CDNs and cached locally. The cache is shared across
all PPTD exports.

Usage:
    python3 download-fonts.py --check              # list installed fonts
    python3 download-fonts.py --download <name>    # download specific font
    python3 download-fonts.py --download-all        # download all known fonts
    python3 download-fonts.py --path <name>         # print local path of font

Font registry maps common font names (as used in PPTD) to local TTF/OTF files.
When a deck references a font that has a registered download, the exporter
can auto-download it before embedding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
FONTS_DIR.mkdir(exist_ok=True)
MANIFEST_PATH = FONTS_DIR / "fonts.json"

# ---------------------------------------------------------------------------
# Font registry: name → download URL + metadata
# ---------------------------------------------------------------------------
# Each entry: (filename, download_url, license, aliases)
FONT_REGISTRY = {
    "Noto Sans SC": (
        "NotoSansSC-Regular.ttf",
        "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
        "SIL OFL 1.1",
        ["noto sans sc", "notosanssc", "Source Han Sans SC", "思源黑体"],
    ),
    "Noto Sans SC Bold": (
        "NotoSansSC-Bold.ttf",
        "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Bold.otf",
        "SIL OFL 1.1",
        ["noto sans sc bold", "notosanssc-bold"],
    ),
    "Noto Serif SC": (
        "NotoSerifSC-Regular.ttf",
        "https://github.com/notofonts/noto-cjk/raw/main/Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-Regular.otf",
        "SIL OFL 1.1",
        ["noto serif sc", "notoserifsc", "Source Han Serif SC", "思源宋体"],
    ),
    "Noto Serif SC Bold": (
        "NotoSerifSC-Bold.ttf",
        "https://github.com/notofonts/noto-cjk/raw/main/Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-Bold.otf",
        "SIL OFL 1.1",
        ["noto serif sc bold", "notoserifsc-bold"],
    ),
    "Oranienbaum": (
        "Oranienbaum-Regular.ttf",
        "https://github.com/google/fonts/raw/main/ofl/oranienbaum/Oranienbaum-Regular.ttf",
        "SIL OFL 1.1",
        ["oranienbaum"],
    ),
    "阿里妈妈东方大楷": (
        "AlimamaDongFangDaKai-Regular.ttf",
        "https://cdn.jsdelivr.net/gh/StellarCN/scp_zh@master/fonts/AlimamaDongFangDaKai.ttf",
        "免费商用",
        ["阿里妈妈东方大楷", "alimamadongfangdakai"],
    ),
}

# Build alias → canonical name lookup
_ALIAS_MAP = {}
for name, (_, _, _, aliases) in FONT_REGISTRY.items():
    _ALIAS_MAP[name.lower()] = name
    for a in aliases:
        _ALIAS_MAP[a.lower()] = name


# ---------------------------------------------------------------------------
# System font lookup (fallback when download is unavailable)
# ---------------------------------------------------------------------------
def _system_font_dirs() -> list[Path]:
    """Return platform-specific system font directories."""
    system = platform.system()
    dirs = []
    if system == "Darwin":
        dirs = [
            Path("/Library/Fonts"),
            Path("/System/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
        ]
    elif system == "Windows":
        dirs = [
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        ]
    else:  # Linux
        dirs = [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".local" / "share" / "fonts",
        ]
    return [d for d in dirs if d.exists()]


def _find_system_font(name: str) -> Path | None:
    """Search system font directories for a font matching the name."""
    search_terms = {name.lower(), name.lower().replace(" ", "")}
    for d in _system_font_dirs():
        for ext in ("*.ttf", "*.otf", "*.ttc", "*.TTF", "*.OTF", "*.TTC"):
            for f in d.rglob(ext):
                stem = f.stem.lower().replace(" ", "").replace("-", "")
                if any(t in stem or stem in t for t in search_terms):
                    return f
    return None


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"fonts": {}}


def _save_manifest(m: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_font(name: str) -> str | None:
    """Resolve a font name to its canonical registry name."""
    return _ALIAS_MAP.get(name.lower())


def get_font_path(name: str) -> Path | None:
    """Get the local path of a font file, downloading if needed."""
    canonical = resolve_font(name)
    if not canonical:
        # Try system font lookup for unregistered fonts
        result = _find_system_font(name)
        if result:
            return result
        # Also check fonts/ dir for manually placed files
        for ext in (".ttf", ".otf", ".TTF", ".OTF"):
            local = FONTS_DIR / f"{name}{ext}"
            if local.exists():
                return local
        return None
    entry = FONT_REGISTRY[canonical]
    filename, url, license_, _ = entry
    local = FONTS_DIR / filename
    if local.exists():
        return local
    # Try download first
    result = download_font(canonical)
    if result:
        return result
    # Fallback: check fonts/ dir for manually placed files
    for ext in (".ttf", ".otf", ".TTF", ".OTF"):
        manual = FONTS_DIR / f"{canonical}{ext}"
        if manual.exists():
            return manual
    # Fallback: try system font
    sys_font = _find_system_font(name)
    if sys_font:
        print(f"[warn] using system font for {name}: {sys_font}")
        return sys_font
    return None


def download_font(name: str) -> Path | None:
    """Download a font from its registered URL. Returns local path or None."""
    canonical = resolve_font(name)
    if not canonical:
        print(f"[warn] 未注册的字体: {name}")
        return None
    entry = FONT_REGISTRY[canonical]
    filename, url, license_, _ = entry
    local = FONTS_DIR / filename
    if local.exists():
        print(f"[ok] 已存在: {local}")
        return local
    print(f"[down] {canonical} ← {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "open-pptd-font-downloader/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        local.write_bytes(data)
        size_mb = len(data) / 1024 / 1024
        sha = hashlib.sha256(data).hexdigest()[:12]
        print(f"[ok] {canonical} → {local.name} ({size_mb:.1f}MB, sha:{sha})")
        # Update manifest
        m = _load_manifest()
        m["fonts"][canonical] = {
            "file": filename,
            "sha256": sha,
            "license": license_,
            "source_url": url,
        }
        _save_manifest(m)
        return local
    except Exception as e:
        print(f"[err] 下载失败 {canonical}: {e}")
        return None


def list_fonts() -> None:
    """Print status of all registered fonts."""
    m = _load_manifest()
    print(f"字体目录: {FONTS_DIR}")
    print(f"{'字体名':<30s} {'状态':<8s} {'大小':>8s} {'许可证':<15s} 文件")
    print("-" * 90)
    for name, (filename, url, license_, _) in sorted(FONT_REGISTRY.items()):
        local = FONTS_DIR / filename
        if local.exists():
            size = local.stat().st_size
            print(f"{name:<30s} {'✓':<8s} {size/1024/1024:>7.1f}M {license_:<15s} {filename}")
        else:
            print(f"{name:<30s} {'✗':<8s} {'--':>8s} {license_:<15s} {filename}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="列出已注册字体状态")
    ap.add_argument("--download", help="下载指定字体")
    ap.add_argument("--download-all", action="store_true", help="下载所有已注册字体")
    ap.add_argument("--path", help="打印字体本地路径（不存在则下载）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = ap.parse_args()

    if args.check:
        list_fonts()
        return
    if args.download:
        result = download_font(args.download)
        if result and args.json:
            print(json.dumps({"ok": True, "path": str(result)}, ensure_ascii=False))
        elif not result:
            sys.exit(1)
        return
    if args.download_all:
        ok = 0
        for name in FONT_REGISTRY:
            if download_font(name):
                ok += 1
        print(f"\n[done] {ok}/{len(FONT_REGISTRY)} fonts ready")
        if ok < len(FONT_REGISTRY):
            sys.exit(1)
        return
    if args.path:
        p = get_font_path(args.path)
        if p:
            print(str(p))
        else:
            print(f"not found: {args.path}", file=sys.stderr)
            sys.exit(1)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
