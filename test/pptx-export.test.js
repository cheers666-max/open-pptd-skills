import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { pathToFileURL } from 'node:url';
import JSZip from '../skills/open-pptd/scripts/node_modules/jszip/lib/index.js';
import { pptdToDeck } from '../skills/open-pptd/scripts/vendor/open-ppt-engine/adapters/pptd.mjs';

function fixture(t, icon) {
  const dir=mkdtempSync(join(tmpdir(),'pptd-icon-'));
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  mkdirSync(join(dir,'pages'));
  writeFileSync(join(dir,'deck.pptd'),`version: v2\ntitle: Icon fixture\nsize: [960, 540]\npages:\n  - pages/01.page\n`);
  writeFileSync(join(dir,'pages/01.page'),`pageType: content\nelements:\n  - elementId: test-icon\n    elementType: icon\n    iconName: '${icon}'\n    bounds: [100, 100, 120, 120]\n    fill: {color: '#12AB34'}\n`);
  return dir;
}
function run(dir,report=true) {
  return spawnSync(process.execPath,[resolve('skills/open-pptd/scripts/export_pptx.mjs'),dir,'--no-embed-fonts','--json',...(report?['--report',join(dir,'report.json')]:[])],{encoding:'utf8',timeout:30000});
}
test('PPTX: Font Awesome path and color survive instead of bullet substitution',async t=>{
  const dir=fixture(t,'fas:bolt');
  const r=run(dir,false);
  assert.equal(r.status,0,r.stderr);
  const zip=await JSZip.loadAsync(readFileSync(join(dir,'deck.pptx')));
  const svgs=Object.keys(zip.files).filter(p=>/^ppt\/media\/.*\.svg$/.test(p));
  assert.ok(svgs.length,'SVG icon is embedded');
  const svg=await zip.file(svgs[0]).async('string');
  assert.match(svg,/<path\b/);
  assert.match(svg,/#12AB34/i);
  const slide=await zip.file('ppt/slides/slide1.xml').async('string');
  assert.doesNotMatch(slide,/<a:t>•<\/a:t>/);
  // XML consumers must be able to parse the entire slide, including the
  // a14:useLocalDpi extension in the PNG + SVG fallback branch.
  const xml = spawnSync('python3', ['-c', 'import sys,zipfile,xml.etree.ElementTree as E\nwith zipfile.ZipFile(sys.argv[1]) as z:\n for name in z.namelist():\n  if name.endswith((".xml", ".rels")): E.fromstring(z.read(name))', join(dir, 'deck.pptx')], {encoding:'utf8'});
  assert.equal(xml.status, 0, xml.stderr);
  assert.match(slide, /<a:blip r:embed="rId\d+">/);
  assert.ok(Object.keys(zip.files).some(p=>/^ppt\/media\/.*\.png$/.test(p)), 'PNG fallback is packaged');
});
test('PPTX: smooth line approximation is visible in the full report',t=>{
  const dir=fixture(t,'fas:bolt');
  writeFileSync(join(dir,'pages/01.page'),`pageType: content
    
elements:
  - elementId: curved-path
    elementType: line
    bounds: [100, 100, 200, 100]
    viewBox: [200, 100]
    points: "0,50 50,0 150,100 200,50"
    curve: smooth
    border: {width: 2, color: '#123456'}
`);
  const r=run(dir);
  assert.equal(r.status,0,r.stderr);
  const warning=JSON.parse(readFileSync(join(dir,'report.json'),'utf8')).warnings.find(w=>w.code==='line-curve-flattened');
  assert.ok(warning, 'Smooth-to-straight loss must be reported');
  assert.match(warning.context,/curved-path/);
});

test('PPTX: full engine warnings available through report with clean JSON',t=>{
  const dir=fixture(t,'fas:bolt');
  const r=run(dir);
  assert.equal(r.status,0,r.stderr);
  assert.equal(JSON.parse(r.stdout).ok,true);
  assert.ok(Array.isArray(JSON.parse(readFileSync(join(dir,'report.json'),'utf8')).warnings));
});
test('PPTX: unsupported icon is explicit loss and nonzero, not a successful unrelated glyph',t=>{
  const dir=fixture(t,'fas:this-icon-does-not-exist');
  const r=run(dir);
  assert.notEqual(r.status,0);
  assert.equal(JSON.parse(r.stdout).ok,false);
  assert.ok(JSON.parse(readFileSync(join(dir,'report.json'),'utf8')).warnings.some(w=>w.code==='icon-unsupported'));
});

test('PPTX: unsupported content cannot be silently delivered as an empty placeholder',t=>{
  const dir=fixture(t,'fas:bolt');
  const file=join(dir,'pages/01.page');
  writeFileSync(file,readFileSync(file,'utf8').replace('elementType: icon','elementType: made-up'));
  const r=run(dir);
  assert.notEqual(r.status,0);
  assert.equal(JSON.parse(r.stdout).ok,false);
  assert.ok(JSON.parse(readFileSync(join(dir,'report.json'),'utf8')).warnings.some(w=>w.code==='unsupported-element-type'));
});

const cachedFonts = ['NotoSerifSC-Regular.ttf', 'NotoSansSC-Regular.ttf', 'Oranienbaum-Regular.ttf'];
const hasCachedFonts = cachedFonts.every(name => existsSync(resolve('skills/open-pptd/scripts/fonts', name)));
const fontCases = [
  {
    name: 'plain manifest scalar',
    theme: 'theme:\n  textStyles:\n    title:\n      fontFamily: Noto Serif SC\n',
    content: '      style: $title\n      text: 中文教学\n',
    families: ['Noto Serif SC'],
  },
  {
    name: 'plain scalar in a referenced page outside pages/',
    content: '      fontFamily: Noto Serif SC\n      text: 中文教学\n',
    families: ['Noto Serif SC'],
  },
  {
    name: 'multiline latin/ea object',
    content: '      fontFamily:\n        latin: Oranienbaum\n        ea: Noto Sans SC\n      text: 中文 Lesson\n',
    families: ['Oranienbaum', 'Noto Sans SC'],
  },
  {
    name: 'HTML font-family declarations',
    content: `      text: |\n        <p style="font-family: Noto Serif SC">中文</p>\n        <span style='font-family: "Oranienbaum"'>Lesson</span>\n`,
    families: ['Noto Serif SC', 'Oranienbaum'],
  },
];

for (const sample of fontCases) {
  test(`PPTX: font embedding reads ${sample.name} and ignores orphan pages`, {
    skip: hasCachedFonts ? false : 'Font regression requires cached Noto Sans/Serif SC and Oranienbaum; never download during tests',
  }, async t => {
    const dir = fixture(t, 'fas:bolt');
    mkdirSync(join(dir, 'chapters'));
    writeFileSync(join(dir, 'deck.pptd'), `version: v2\nsize: [960, 540]\n${sample.theme ?? ''}pages:\n  - chapters/intro.page\n`);
    writeFileSync(join(dir, 'chapters/intro.page'), `pageType: content\nelements:\n  - elementId: text\n    elementType: text\n    bounds: [48, 48, 864, 200]\n    content:\n${sample.content}`);
    // The manifest does not reference this page. Even malformed YAML and a
    // different cached font here must have no effect on this export.
    writeFileSync(join(dir, 'pages/orphan.page'), 'fontFamily: "Noto Sans SC"\nelements: [unfinished\n');
    const r = spawnSync(process.execPath, [resolve('skills/open-pptd/scripts/export_pptx.mjs'), dir, '--json', '--report', join(dir, 'report.json')], {encoding:'utf8', timeout:30000});
    assert.equal(r.status, 0, r.stderr);
    const summary = JSON.parse(r.stdout);
    assert.equal(summary.ok, true);
    assert.equal(summary.fonts, sample.families.length);
    assert.ok(Array.isArray(JSON.parse(readFileSync(join(dir, 'report.json'), 'utf8')).warnings));
    const zip = await JSZip.loadAsync(readFileSync(join(dir, 'deck.pptx')));
    const parts = Object.keys(zip.files).filter(name => /^ppt\/fonts\/.*\.fntdata$/.test(name));
    assert.equal(parts.length, sample.families.length);
    for (const part of parts) assert.ok((await zip.file(part).async('nodebuffer')).length > 0);
    const presentation = await zip.file('ppt/presentation.xml').async('string');
    const families = [...presentation.matchAll(/<p:font typeface="([^"]+)"/g)].map(match => match[1]);
    assert.deepEqual(families.sort(), [...sample.families].sort());
    assert.match(presentation, /embedTrueTypeFonts="1"/);
  });
}

for (const invalidPage of [null, 'elements: [unfinished\n']) {
  test(`PPTX: ${invalidPage === null ? 'missing' : 'invalid YAML'} referenced page fails before font resolution`, t => {
    const dir = fixture(t, 'fas:bolt');
    writeFileSync(join(dir, 'deck.pptd'), 'version: v2\nsize: [960, 540]\ntheme:\n  textStyles:\n    title: {fontFamily: "Noto Serif SC"}\npages:\n  - pages/broken.page\n');
    if (invalidPage !== null) writeFileSync(join(dir, 'pages/broken.page'), invalidPage);
    const r = spawnSync(process.execPath, [resolve('skills/open-pptd/scripts/export_pptx.mjs'), dir, '--json'], {encoding:'utf8', timeout:30000});
    assert.notEqual(r.status, 0);
    assert.equal(JSON.parse(r.stdout).ok, false);
    assert.doesNotMatch(r.stderr, /\[fonts\]/);
    assert.equal(existsSync(join(dir, 'deck.pptx')), false);
  });
}

function convertedLine(overrides={}) {
  const line={elementId:'direction',elementType:'line',bounds:[100,200,200,100],viewBox:[100,100],points:'0,100 100,0',curve:'sharp',arrow:[null,'arrow'],border:{width:4,color:'#12AB34'},...overrides};
  const deck=pptdToDeck({manifest:{version:'v2',size:[960,540],pages:['pages/1.page']},pages:[{elements:[line]}]}, {scale:1});
  return deck.slides[0].elements[0];
}

test('PPTX: line direction, viewBox scaling and declared flips compose without overwriting each other',()=>{
  const rising=convertedLine();
  assert.deepEqual(rising.position,{left:100,top:200,width:200,height:100});
  assert.equal(rising.flipV,true);
  assert.equal(rising.style.line.endArrowType,'triangle');
  const reversed=convertedLine({points:'100,0 0,100'});
  assert.equal(reversed.flipH,true);
  assert.equal(Boolean(reversed.flipV),false);
  const flipped=convertedLine({flip:[false,true]});
  assert.equal(Boolean(flipped.flipV),false);
  const rotated=convertedLine({points:'25,25 100,100',flip:[true,false],rotation:90});
  assert.ok(Math.abs(rotated.position.left-150)<1e-8);
  assert.ok(Math.abs(rotated.position.top-150)<1e-8);
  assert.ok(Math.abs(rotated.position.width-75)<1e-8);
  assert.ok(Math.abs(rotated.position.height-150)<1e-8);
  assert.equal(rotated.flipH,true);
  assert.equal(rotated.flipV,true);
});

test('PPTX: polyline heads stay on first/last segments and horizontal paths remain horizontal',()=>{
  const poly=convertedLine({points:'0,100 50,0 100,100',arrow:undefined,border:{width:4,color:'#12AB34',arrow:['stealth','arrow']}});
  assert.equal(poly.children.length,2);
  assert.equal(poly.children[0].flipV,true);
  assert.equal(poly.children[0].style.line.beginArrowType,'stealth');
  assert.equal(poly.children[0].style.line.endArrowType,undefined);
  assert.equal(poly.children[1].style.line.beginArrowType,undefined);
  assert.equal(poly.children[1].style.line.endArrowType,'triangle');
  assert.equal(convertedLine({points:'0,50 100,50'}).position.height,0);
});

const soffice = '/Applications/LibreOffice.app/Contents/MacOS/soffice';
const hasNativeRenderer = existsSync(soffice) && spawnSync('python3',['-c','import pymupdf'],{encoding:'utf8'}).status===0;
test('PPTX: native LibreOffice render shows the icon, upward line and filled arrowhead', {skip: hasNativeRenderer ? false : 'Optional native regression requires LibreOffice and PyMuPDF'}, t=>{
  const dir=fixture(t,'fas:lightbulb');
  const page=join(dir,'pages/01.page');
  writeFileSync(page,readFileSync(page,'utf8')+`  - elementId: upward-arrow\n    elementType: line\n    bounds: [400, 100, 200, 100]\n    viewBox: [200, 100]\n    points: "0,100 200,0"\n    curve: sharp\n    arrow: [null, arrow]\n    border: {width: 4, color: '#12AB34'}\n`);
  const exported=run(dir,false);
  assert.equal(exported.status,0,exported.stderr);
  const native=join(dir,'native'); mkdirSync(native);
  const converted=spawnSync(soffice,[`-env:UserInstallation=${pathToFileURL(join(dir,'lo-profile')).href}`,'--headless','--convert-to','pdf','--outdir',native,join(dir,'deck.pptx')],{encoding:'utf8',timeout:45000});
  assert.equal(converted.status,0,converted.stdout+converted.stderr);
  assert.ok(existsSync(join(native,'deck.pdf')),'LibreOffice produced the PDF');
  const pixels=spawnSync('python3',['-c',`import json,sys,pymupdf\nfrom PIL import Image\ndoc=pymupdf.open(sys.argv[1]); pix=doc[0].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),alpha=False); im=Image.frombytes('RGB',[pix.width,pix.height],pix.samples)\nsx=im.width/960; sy=im.height/540\ndef green(x,y):\n r,g,b=im.getpixel((x,y)); return r<70 and g>100 and b<130\ndef region(x0,y0,x1,y1):\n return sum(green(x,y) for x in range(round(x0*sx),round(x1*sx)) for y in range(round(y0*sy),round(y1*sy)))\nhead=sum(green(x,y) for x in range(round(583*sx),round(606*sx)) for y in range(round(93*sy),round(115*sy)) if abs(y/sy-(400-.5*x/sx))>3)\nprint(json.dumps({'icon':region(100,100,220,220),'rising':region(446,171,454,179),'wrongDirection':region(446,121,454,129),'headOutsideShaft':head}))`,join(native,'deck.pdf')],{encoding:'utf8',timeout:15000});
  assert.equal(pixels.status,0,pixels.stderr);
  const actual=JSON.parse(pixels.stdout);
  assert.ok(actual.icon>1000,`Icon pixels: ${JSON.stringify(actual)}`);
  assert.ok(actual.rising>20,`Rising line pixels: ${JSON.stringify(actual)}`);
  assert.equal(actual.wrongDirection,0,`Old incorrect slope pixels: ${JSON.stringify(actual)}`);
  assert.ok(actual.headOutsideShaft>10,`Arrowhead pixels beyond shaft: ${JSON.stringify(actual)}`);
});

test('PPTX: align variants (nested pair, numeric, bare string) map onto the canonical h/v pair',()=>{
  const cases=[
    [[['center','middle']], 'center','middle'],   // nested — used to fall back to left/top
    [[0.5,0.5],             'center','middle'],   // numeric 0/0.5/1
    [[1,0],                 'right','top'],
    [[0,1],                 'left','bottom'],
    ['right',               'right','top'],       // bare string
    [['center','middle'],   'center','middle'],   // canonical still works
    [undefined,             'left','top'],
  ];
  for(const [align,h,v] of cases){
    const el={elementId:'t',elementType:'text',bounds:[0,0,200,50],content:{text:'x',...(align===undefined?{}:{align})}};
    const deck=pptdToDeck({manifest:{version:'v2',size:[960,540],pages:['pages/1.page']},pages:[{elements:[el]}]},{scale:1});
    const style=deck.slides[0].elements[0].style;
    assert.equal(style.align,h,`h for ${JSON.stringify(align)}`);
    assert.equal(style.valign,v,`v for ${JSON.stringify(align)}`);
  }
});

test('PPTX: a text value parsed as a number exports instead of crashing the writer', () => {
  // The renderer parses YAML 1.2, where a bare 08 is the integer 8, while the authoring tools read
  // it as the string "08". A deck that renders fine must not take the PPTX writer down.
  const element = {elementId:'pageno', elementType:'text', bounds:[844,504,60,20], content:{text:8}};
  const deck = pptdToDeck({manifest:{version:'v2',size:[960,540],pages:['pages/1.page']},pages:[{elements:[element]}]},{scale:1});
  assert.equal(deck.slides[0].elements[0].text, '8');
});
