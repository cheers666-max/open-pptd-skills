#!/usr/bin/env python3
"""Optional independent LibreOffice rendering of a pi run's delivered PPTX files."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

import review
import run_pi as common


def render(pptx, case_dir, executable, timeout=60):
    # Never render back into the author output or accept a previous PDF/PNG.
    parent = case_dir / 'precheck/native-pptx'
    parent.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix='render-', dir=parent))
    report = {'input': review.file_fact(pptx, case_dir), 'renderer': 'LibreOffice Impress',
              'checkedAt': datetime.now(timezone.utc).isoformat(), 'status': 'unavailable',
              'limitation': 'This checks LibreOffice import/rendering; it is not Microsoft PowerPoint playback certification.'}
    started = time.monotonic()
    try:
        import pymupdf
        from PIL import Image, ImageOps, ImageDraw
        with tempfile.TemporaryDirectory(prefix='pptx-review-profile-') as profile:
            command = [executable, '-env:UserInstallation='+Path(profile).as_uri(), '--headless',
                       '--convert-to', 'pdf', '--outdir', str(destination), str(pptx)]
            with (destination/'stdout.log').open('w') as stdout, (destination/'stderr.log').open('w') as stderr:
                proc = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
                report['converterPid'] = proc.pid
                tracker = common.ProcessTracker(proc)
                try:
                    deadline = time.monotonic() + timeout
                    while proc.poll() is None:
                        if common.STOP.is_set():
                            raise RuntimeError('LibreOffice render cancelled')
                        if time.monotonic() >= deadline:
                            raise RuntimeError('LibreOffice render timed out')
                        time.sleep(0.05)
                finally:
                    common.stop_process(proc, tracker)
                    tracker.close()
            pdf = destination / (pptx.stem + '.pdf')
            if proc.returncode != 0 or not pdf.is_file():
                raise RuntimeError('LibreOffice did not produce this run\'s PDF')
        images = []
        with pymupdf.open(pdf) as doc:
            if not len(doc):
                raise RuntimeError('Rendered PDF has no pages')
            for index, page in enumerate(doc, 1):
                if common.STOP.is_set():
                    raise RuntimeError('Native image rendering cancelled')
                output = destination / f'page_{index:02d}.png'
                page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(output)
                images.append(output)
        columns = min(4, len(images))
        rows = (len(images) + columns - 1) // columns
        overview = Image.new('RGB', (columns * 480, rows * 296), '#DDDDDD')
        draw = ImageDraw.Draw(overview)
        for index, path in enumerate(images):
            with Image.open(path) as im:
                thumb = ImageOps.contain(im.convert('RGB'), (480, 270))
                x, y = index % columns * 480, index // columns * 296
                overview.paste(thumb, (x, y + 26))
                draw.text((x+8, y+7), f'P{index+1} / LibreOffice', fill='#111111')
        overview.save(destination/'overview.jpg', quality=90)
        report.update(status='rendered', pageCount=len(images), pdf=review.relative(pdf, case_dir),
                      images=[review.relative(p, case_dir) for p in images],
                      overview=review.relative(destination/'overview.jpg', case_dir))
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        report.update(error=str(exc), status='cancelled' if common.STOP.is_set() else 'unavailable')
    report['elapsedSeconds'] = round(time.monotonic()-started, 3)
    common.write_json(destination/'render.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--libreoffice', default=shutil.which('soffice') or '/Applications/LibreOffice.app/Contents/MacOS/soffice')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    common.STOP.clear()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda _signal, _frame: common.STOP.set())
    run = args.run.resolve()
    metadata = review.load_json(run/'run.json')
    if not metadata:
        parser.error('Expected an existing pi run directory')
    selected = [x.strip() for group in args.case for x in group.split(',') if x.strip()]
    cases = [x for x in metadata['caseIds'] if not selected or any(x == s or x.startswith(s+'-') for s in selected)]
    if not cases or any(not any(x == s or x.startswith(s+'-') for x in cases) for s in selected):
        parser.error('Unknown or empty case selection')
    failed = False
    reports = {}
    for name in cases:
        if common.STOP.is_set():
            failed = True
            break
        case_dir = run/'cases'/name
        files = review.safe_files(case_dir/'work/output', '*.pptx')
        reports[name] = []
        if not files:
            failed = True
            common.progress(f'[{name}] no delivered PPTX to render')
        for pptx in files:
            if common.STOP.is_set():
                failed = True
                break
            report = render(pptx, case_dir, args.libreoffice, args.timeout)
            reports[name].append(report)
            failed |= report['status'] != 'rendered'
            common.progress(f'[{name}] LibreOffice {report["status"]} ({report["elapsedSeconds"]}s)')
    failed |= common.STOP.is_set()
    common.write_json(run/'native-render-summary.json', reports)
    print(json.dumps({'report':str(run/'native-render-summary.json'), 'allRendered':not failed}))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
