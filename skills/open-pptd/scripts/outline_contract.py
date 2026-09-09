#!/usr/bin/env python3
"""Hold a deck to the outline it was planned from.

The outline is written and confirmed with the user *before* any page is authored, then this
script checks the built deck against it. It catches the failures a per-page renderer cannot
see: a deck that quietly ends up shorter than the plan, a page whose promised figure was never
placed, a page type that drifted.

Usage:
    outline_contract.py --outline outline.json --markdown          # confirmation table
    outline_contract.py --project deck/ [--outline outline.json]   # check the built deck
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_deck import (  # noqa: E402  (local module, after sys.path setup)
    discover_manifest,
    load_structured,
    safe_project_path,
    write_json,
)

SCHEMA_VERSION = "open-pptd-outline/1.0"
MIN_CONTENT_SLOTS = 2
# 本分支的图片密度目标：内容页中至少这个比例要规划配图。
MIN_ILLUSTRATED_CONTENT = 0.6


def outline_pages(outline: dict) -> List[dict]:
    pages = outline.get("pages")
    if not isinstance(pages, list) or not pages:
        raise RuntimeError("outline has no pages")
    return [page for page in pages if isinstance(page, dict)]


def page_image_count(page: dict) -> int:
    """How many pictures the built page carries (image elements, image fills, page background)."""
    count = 0
    background = page.get("background")
    if isinstance(background, dict) and str(background.get("type", "")).lower() in {"image", "picture"}:
        count += 1
    for element in page.get("elements", []) or []:
        if not isinstance(element, dict):
            continue
        if element.get("elementType") == "image":
            count += 1
            continue
        fill = element.get("fill")
        if isinstance(fill, dict) and str(fill.get("type", "")).lower() in {"image", "picture"}:
            count += 1
    return count


def page_has_image(page: dict) -> bool:
    return page_image_count(page) > 0


def planned_image_count(page: dict) -> int:
    """How many pictures the outline asked this page for."""
    plan = page.get("images")
    if isinstance(plan, list):
        return len([item for item in plan if item])
    return 1 if page.get("image") else 0


def plan_issues(outline: dict) -> List[dict]:
    """Problems visible in the plan alone — checkable before a single page is authored."""
    issues: List[dict] = []
    pages = outline_pages(outline)
    requested = outline.get("requestedPages")
    if isinstance(requested, int) and requested > 0 and len(pages) != requested:
        issues.append({
            "code": "outline-page-count",
            "detail": f"the outline plans {len(pages)} pages but {requested} were agreed with the user",
        })
    content = [p for p in pages if str(p.get("pageType", "")).lower() == "content"]
    with_images = [p for p in content if planned_image_count(p)]
    if content and len(with_images) / len(content) < MIN_ILLUSTRATED_CONTENT:
        issues.append({
            "code": "outline-thin-illustration",
            "contentPages": len(content), "illustrated": len(with_images),
            "detail": f"only {len(with_images)} of {len(content)} content pages plan a picture "
                      f"(target {MIN_ILLUSTRATED_CONTENT:.0%}); a deck that carries one photo every "
                      "four pages reads as a wall of text",
        })
    for position, page in enumerate(pages, start=1):
        index = page.get("pageIndex", position)
        if not str(page.get("actionTitle", "")).strip():
            issues.append({"code": "outline-missing-title", "pageIndex": index,
                           "detail": "every page needs the sentence it is trying to land"})
        if not str(page.get("summary", "")).strip():
            issues.append({"code": "outline-missing-summary", "pageIndex": index,
                           "detail": "every page needs one line saying what it carries"})
        slots = page.get("slots")
        slots = slots if isinstance(slots, list) else []
        kind = str(page.get("pageType", "")).lower()
        if kind == "content" and len(slots) < MIN_CONTENT_SLOTS:
            issues.append({"code": "outline-thin-page", "pageIndex": index, "slots": len(slots),
                           "detail": f"a content page planned with fewer than {MIN_CONTENT_SLOTS} slots "
                                     "usually turns into a title over whitespace"})
    return issues


def deck_issues(project: Path, outline: dict, manifest_path: Optional[Path] = None) -> List[dict]:
    """Differences between the confirmed plan and the deck that was actually built."""
    issues: List[dict] = []
    manifest = load_structured(discover_manifest(project, manifest_path))
    refs = manifest.get("pages")
    if not isinstance(refs, list) or not refs:
        raise RuntimeError(f"PPTD manifest has no pages: {project}")
    plan = outline_pages(outline)

    if len(refs) != len(plan):
        issues.append({
            "code": "outline-deck-count",
            "deckPages": len(refs), "outlinePages": len(plan),
            "detail": "the deck and the confirmed outline disagree on how many pages exist",
        })

    for position, (ref, planned) in enumerate(zip(refs, plan), start=1):
        index = planned.get("pageIndex", position)
        path = safe_project_path(project, ref)
        if path is None or not path.is_file():
            continue  # validate_deck reports the missing page itself
        page = load_structured(path)
        want_type = str(planned.get("pageType", "")).lower()
        got_type = str(page.get("pageType", "")).lower()
        if want_type and got_type and want_type != got_type:
            issues.append({"code": "outline-page-type", "pageIndex": index, "pageRef": str(ref),
                           "planned": want_type, "built": got_type,
                           "detail": "the built page is not the kind of page the outline promised"})
        wanted = planned_image_count(planned)
        placed = page_image_count(page)
        if wanted and not placed:
            issues.append({"code": "outline-missing-image", "pageIndex": index, "pageRef": str(ref),
                           "planned": wanted,
                           "detail": "the outline promised a picture on this page and none was placed"})
        elif wanted > placed:
            issues.append({"code": "outline-fewer-images", "pageIndex": index, "pageRef": str(ref),
                           "planned": wanted, "placed": placed,
                           "detail": f"the outline planned {wanted} pictures for this page and {placed} "
                                     "were placed; drop the extra from the plan or place it"})
    return issues


def to_markdown(outline: dict) -> str:
    """The table the user confirms before any page is written."""
    rows = ["| # | 页型 | 这页要说的话 | 内容槽 | 配图 |", "|---:|---|---|---|:---:|"]
    for position, page in enumerate(outline_pages(outline), start=1):
        slots = page.get("slots")
        slots = ", ".join(str(s) for s in slots) if isinstance(slots, list) else ""
        rows.append("| %s | %s | %s | %s | %s |" % (
            page.get("pageIndex", position),
            page.get("pageType", ""),
            str(page.get("actionTitle", "")).replace("|", "\\|"),
            slots.replace("|", "\\|"),
            (str(planned_image_count(page)) + " 张") if planned_image_count(page) else "—",
        ))
    header = [f"# {outline.get('title', '(untitled)')}"]
    for label, key in (("受众", "audience"), ("目的", "purpose"), ("约定页数", "requestedPages")):
        if outline.get(key):
            header.append(f"- {label}：{outline[key]}")
    return "\n".join(header + [""] + rows)


def audit(outline_path: Path, project: Optional[Path], manifest_path: Optional[Path] = None) -> Dict[str, Any]:
    outline = load_structured(outline_path)
    issues = plan_issues(outline)
    if project is not None:
        issues.extend(deck_issues(project, outline, manifest_path))
    counts: Dict[str, int] = {}
    for issue in issues:
        counts[issue["code"]] = counts.get(issue["code"], 0) + 1
    return {
        "schemaVersion": SCHEMA_VERSION,
        "valid": not issues,
        "outlinePath": str(outline_path),
        "projectPath": str(project) if project else None,
        "pageCount": len(outline_pages(outline)),
        "issueCount": len(issues),
        "issueCounts": counts,
        "issues": issues,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check a deck against the outline it was planned from")
    parser.add_argument("--project", type=Path, help="PPTD project directory (omit to check the plan alone)")
    parser.add_argument("--outline", type=Path, help="outline file (default: <project>/outline.json)")
    parser.add_argument("--manifest", type=Path, help="explicit .pptd manifest")
    parser.add_argument("--markdown", action="store_true", help="print the confirmation table and exit")
    parser.add_argument("--json", action="store_true", help="print the full machine report")
    parser.add_argument("--report", type=Path, help="also write the report to this path")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    project = args.project.expanduser().resolve() if args.project else None
    outline_path = args.outline or (project / "outline.json" if project else None)
    if outline_path is None:
        print("outline_contract: --outline or --project is required", file=sys.stderr)
        return 1
    outline_path = Path(outline_path).expanduser().resolve()
    if not outline_path.is_file():
        print(f"outline_contract: outline not found: {outline_path}", file=sys.stderr)
        return 1

    if args.markdown:
        print(to_markdown(load_structured(outline_path)))
        return 0

    report = audit(outline_path, project, args.manifest)
    if args.report:
        write_json(args.report, report)
    if args.json:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"outline_contract: {'PASS' if report['valid'] else 'FAIL'} "
              f"({report['pageCount']} planned pages, {report['issueCount']} issues)")
        for issue in report["issues"]:
            where = f" page {issue['pageIndex']}" if "pageIndex" in issue else ""
            print(f"  - {issue['code']}{where}: {issue['detail']}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
