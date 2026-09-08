import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import JSZip from '../skills/open-pptd/scripts/node_modules/jszip/lib/index.js';
import { pptdToDeck } from '../skills/open-pptd/scripts/vendor/open-ppt-engine/adapters/pptd.mjs';

const scripts = resolve('skills/open-pptd/scripts');
const samples = [
  { name: 'legacy-fill', color: '#171310', fillOpacity: .82, alpha: .82 },
  { name: 'transparent-fill', color: '#171310', fillOpacity: 0, alpha: 0 },
  { name: 'element-only', color: '#171310', opacity: .82, alpha: .82 },
  { name: 'hex8', color: '#17131080', alpha: 128 / 255 },
  { name: 'combined', color: '#17131080', fillOpacity: .5, opacity: .5, alpha: 32 / 255 },
  { name: 'theme-combined', color: '$veil', fillOpacity: .5, opacity: .5, alpha: 32 / 255 },
  { name: 'theme-fill', color: '$ink', fillOpacity: .82, alpha: .82 },
];

function elementsFor(samplesToUse = samples) {
  return ['rect', 'triangle'].flatMap((shapeName, row) => samplesToUse.map((sample, index) => ({
    elementId: `${shapeName}-${sample.name}`,
    elementType: 'shape', shapeName, bounds: [30 + index * 130, 50 + row * 200, 100, 100],
    fill: { type: 'solid', color: sample.color, ...(Object.hasOwn(sample, 'fillOpacity') ? { opacity: sample.fillOpacity } : {}) },
    ...(Object.hasOwn(sample, 'opacity') ? { opacity: sample.opacity } : {}),
  })));
}

function fixture(t, elements = elementsFor()) {
  const dir = mkdtempSync(join(tmpdir(), 'pptd-opacity-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  mkdirSync(join(dir, 'pages'));
  mkdirSync(join(dir, 'media'));
  const manifest = { version: 'v2', title: 'Opacity fixture', size: [960, 540], theme: { colors: { veil: '#17131080', ink: '#171310' } }, pages: ['pages/01.page'] };
  writeFileSync(join(dir, 'deck.pptd'), JSON.stringify(manifest));
  writeFileSync(join(dir, 'pages/01.page'), JSON.stringify({ pageType: 'content', elements: [
    { elementId: 'photo', elementType: 'image', bounds: [0, 0, 960, 540], src: 'media/background.png' }, ...elements,
  ] }));
  const image = spawnSync('python3', ['-c', 'from PIL import Image,ImageDraw\nimport sys\nim=Image.new("RGB",(960,540),(40,120,200))\nImageDraw.Draw(im).rectangle((0,400,960,540),fill=(200,120,40))\nim.save(sys.argv[1])', join(dir, 'media/background.png')], { encoding: 'utf8' });
  assert.equal(image.status, 0, image.stderr);
  return dir;
}

const render = dir => spawnSync('python3', [join(scripts, 'export_images.py'), dir, '--workers', '1', '--scale', '1', '--timeout', '20', '--json'], { encoding: 'utf8', timeout: 60000 });
const exportPptx = dir => spawnSync(process.execPath, [join(scripts, 'export_pptx.mjs'), dir, '--no-embed-fonts', '--json'], { encoding: 'utf8', timeout: 30000 });

test('opacity: Chrome shows the background through DIV and SVG fills, composing HEX8, fill and element alpha', t => {
  const dir = fixture(t);
  const result = render(dir);
  assert.equal(result.status, 0, result.stderr);
  const png = join(JSON.parse(result.stdout).output, 'pages/page_01.png');
  const probe = spawnSync('python3', ['-c', 'from PIL import Image\nimport json,sys\nim=Image.open(sys.argv[1]).convert("RGB")\nprint(json.dumps([im.getpixel((80+i*130,100+row*200)) for row in range(2) for i in range(7)]))', png], { encoding: 'utf8' });
  assert.equal(probe.status, 0, probe.stderr);
  const pixels = JSON.parse(probe.stdout);
  for (const [index, element] of elementsFor().entries()) {
    const alpha = samples[index % samples.length].alpha;
    const expected = [23, 19, 16].map((channel, i) => Math.round(channel * alpha + [40, 120, 200][i] * (1 - alpha)));
    assert.ok(pixels[index].every((value, i) => Math.abs(value - expected[i]) <= 2), `${element.elementId}: expected ${expected}, got ${pixels[index]}`);
  }
});

test('opacity: packaged PPTX uses the same multiplied alpha for DIV and SVG source shapes', async t => {
  const dir = fixture(t);
  const result = exportPptx(dir);
  assert.equal(result.status, 0, result.stderr);
  const zip = await JSZip.loadAsync(readFileSync(join(dir, 'deck.pptx')));
  const slide = await zip.file('ppt/slides/slide1.xml').async('string');
  const shapes = [...slide.matchAll(/<p:sp>.*?<\/p:sp>/g)].map(match => match[0]);
  for (const [index, element] of elementsFor().entries()) {
    const shape = shapes.find(xml => xml.includes(`name="${element.elementId}"`));
    assert.ok(shape, `Missing ${element.elementId}`);
    const fill = shape.match(/<a:solidFill><a:srgbClr val="171310"[^>]*>(.*?)<\/a:srgbClr><\/a:solidFill>/)?.[1];
    assert.notEqual(fill, undefined, shape);
    const alpha = Number(fill.match(/<a:alpha val="(\d+)"/)?.[1] ?? 100000);
    // Native export quantizes alpha to an 8-bit HEX8 channel before OOXML.
    const expected = Math.round(Math.round(samples[index % samples.length].alpha * 255) / 255 * 100000);
    assert.ok(Math.abs(alpha - expected) <= 1, `${element.elementId}: expected alpha ${expected}, got ${alpha}`);
  }
});

for (const property of ['fillOpacity', 'opacity']) test(`opacity: invalid ${property} fails HTML and PPTX export with context`, t => {
  const elements = elementsFor([{ name: 'invalid', color: '#171310', [property]: 'opaque' }]).slice(0, 1);
  const dir = fixture(t, elements);
  for (const exporter of [render, exportPptx]) {
    const result = exporter(dir);
    assert.notEqual(result.status, 0, `${exporter.name} silently accepted invalid ${property}`);
    assert.match(result.stdout + result.stderr, /opacity/i);
    assert.match(result.stdout + result.stderr, /rect-invalid/);
  }
});

test('opacity: numeric strings, null, non-finite and out-of-range solid/element opacity are rejected', () => {
  for (const value of ['0.5', null, NaN, Infinity, -.1, 1.1]) {
    for (const property of ['fillOpacity', 'opacity']) {
      const elements = elementsFor([{ name: 'invalid', color: '#171310', [property]: value }]).slice(0, 1);
      assert.throws(() => pptdToDeck({ manifest: { version: 'v2', size: [960, 540], pages: ['pages/01.page'] }, pages: [{ elements }] }), /opacity.*rect-invalid|rect-invalid.*opacity/i, `${property}=${String(value)}`);
    }
  }
});
