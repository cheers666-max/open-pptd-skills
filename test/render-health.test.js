import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync, renameSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const scripts = resolve('skills/open-pptd/scripts');
import { readPptdProject } from '../skills/open-pptd/scripts/vendor/open-ppt-engine/adapters/pptd.mjs';
const run = (script, args) => spawnSync('python3', [join(scripts, script), ...args, '--timeout', '20'], {encoding:'utf8', timeout:60000});
function fixture(t, element, count=1) {
  const dir = mkdtempSync(join(tmpdir(),'pptd-render-'));
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  mkdirSync(join(dir,'pages'));
  writeFileSync(join(dir,'deck.pptd'), `version: v2\ntitle: Render fixture\nsize: [960, 540]\npages:\n${Array.from({length:count},(_,i)=>`  - pages/${i+1}.page`).join('\n')}\n`);
  for(let i=1;i<=count;i++) writeFileSync(join(dir,`pages/${i}.page`),`pageType: content\nbackground: {type: solid, color: '#FFFFFF'}\nelements:\n  - elementId: title\n    elementType: text\n    bounds: [40, 30, 800, 50]\n    content: {fontSize: 32, text: 'Page ${i}'}\n${element}`);
  return dir;
}

test('authoring: numeric-looking string labels survive Python to JS YAML parsing',async t=>{
  const dir=mkdtempSync(join(tmpdir(),'pptd-labels-'));
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  const labels=['08','09','0','1e3','+012','001.50','0o17','0x20','ordinary'];
  const code=`import sys,json\nsys.path.insert(0,sys.argv[1])\nfrom authoring_helpers import text,page,write_project\nlabels=json.loads(sys.argv[3])\nwrite_project(sys.argv[2],'Labels',[page([text(str(i),0,0,100,30,v) for i,v in enumerate(labels)])])`;
  const r=spawnSync('python3',['-c',code,scripts,dir,JSON.stringify(labels)],{encoding:'utf8'});
  assert.equal(r.status,0,r.stderr);
  const project=await readPptdProject(dir);
  assert.deepEqual(project.pages[0].content.elements.map(el=>el.content.text),labels);
});

test('render: numeric text and zero table cells render without dropping zero',t=>{
  const dir=fixture(t,`  - elementId: number\n    elementType: text\n    bounds: [100, 120, 100, 80]\n    content: {fontSize: 48, text: 8}\n  - elementId: zero\n    elementType: table\n    bounds: [300, 120, 100, 80]\n    columnWidths: [1]\n    rowHeights: [1]\n    rows: [[{text: 0, fontSize: 48}]]\n`);
  const r=run('export_images.py',[dir,'--workers','1','--scale','1','--json']);
  assert.equal(r.status,0,r.stderr);
  const png=join(JSON.parse(r.stdout).output,'pages/page_01.png');
  const pixels=spawnSync('python3',['-c',`from PIL import Image\nimport sys,json\nim=Image.open(sys.argv[1]).convert('RGB')\nprint(json.dumps([sum(1 for x in range(left+10,left+80) for y in range(130,190) if max(im.getpixel((x,y)))<80) for left in (100,300)]))`,png],{encoding:'utf8'});
  assert.equal(pixels.status,0,pixels.stderr);
  assert.ok(JSON.parse(pixels.stdout).every(count=>count>50),pixels.stdout);
});

for (const specialPaths of [false,true]) test(`render: local percent filenames preserve actual bytes${specialPaths ? ' with special manifest/page paths' : ''}`,t=>{
  const dir=fixture(t,`  - elementId: photo\n    elementType: image\n    bounds: [100, 120, 200, 100]\n    src: 'media/cover%23.png'\n`);
  mkdirSync(join(dir,'media'));
  const files=spawnSync('python3',['-c',`from PIL import Image\nfrom pathlib import Path\nimport sys\np=Path(sys.argv[1]);Image.new('RGB',(200,100),'red').save(p/'cover%23.png');Image.new('RGB',(200,100),'blue').save(p/'cover#.png')`,join(dir,'media')],{encoding:'utf8'});
  assert.equal(files.status,0,files.stderr);
  if(specialPaths) {
    const name='pages/中文%23 #?.page';
    renameSync(join(dir,'pages/1.page'),join(dir,name));
    writeFileSync(join(dir,'deck.pptd'),readFileSync(join(dir,'deck.pptd'),'utf8').replace('pages/1.page',JSON.stringify(name)));
    renameSync(join(dir,'deck.pptd'),join(dir,'deck%23 #?.pptd'));
  }
  const r=run('export_images.py',[dir,'--workers','1','--scale','1','--json']);
  assert.equal(r.status,0,r.stderr);
  const pixels=spawnSync('python3',['-c',`from PIL import Image\nimport sys,json\nprint(json.dumps(Image.open(sys.argv[1]).convert('RGB').getpixel((150,150))))`,join(JSON.parse(r.stdout).output,'pages/page_01.png')],{encoding:'utf8'});
  assert.equal(pixels.status,0,pixels.stderr);
  assert.deepEqual(JSON.parse(pixels.stdout),[255,0,0],'Must use literal %23 file, not the blue # sibling');
  if(specialPaths) {
    const html=run('export_html.py',[dir,'--json']);
    assert.equal(html.status,0,html.stderr);
  }
});

test('render: pie legend survives actual browser rendering',t=>{
  const dir=fixture(t,`  - elementId: shares\n    elementType: chart\n    bounds: [100, 120, 700, 300]\n    data:\n      cols: [category, value]\n      rows: [[A, 40], [B, 60]]\n    series:\n      - type: pie\n        encode: {category: category, value: value}\n    legend: {show: true}\n`);
  const r=run('export_images.py',[dir,'--workers','1','--scale','1','--json']);
  assert.equal(r.status,0,r.stderr);
  const report=JSON.parse(r.stdout);
  assert.equal(report.images.length,1);
  assert.equal(report.renderHealth[0].ok,true);
});

test('render: screenshot retains SVG arrowheads when thumbnails are hidden',t=>{
  const dir=fixture(t,`  - elementId: arrow\n    elementType: line\n    bounds: [100, 120, 200, 40]\n    viewBox: [200, 40]\n    points: "0,20 200,20"\n    curve: sharp\n    arrow: [null, arrow]\n    border: {width: 4, color: '#0F766E'}\n`);
  const r=run('export_images.py',[dir,'--workers','1','--scale','1','--json']);
  assert.equal(r.status,0,r.stderr);
  const png=join(JSON.parse(r.stdout).output,'pages/page_01.png');
  const pixels=spawnSync('python3',['-c',`from PIL import Image\nimport sys\nim=Image.open(sys.argv[1]).convert('RGB')\nprint(sum(1 for x in range(270,306) for y in range(125,156) if abs(y-140)>4 and im.getpixel((x,y))[0]<80 and im.getpixel((x,y))[1]>80))`,png],{encoding:'utf8'});
  assert.equal(pixels.status,0,pixels.stderr);
  assert.ok(Number(pixels.stdout)>100,`Arrowhead pixels outside shaft: ${pixels.stdout}`);
});

test('render: unknown element fails screenshot instead of accepting its placeholder',t=>{
  const dir=fixture(t,`  - elementId: unsupported\n    elementType: made-up\n    bounds: [100, 120, 700, 300]\n`);
  const r=run('export_images.py',[dir,'--workers','1','--scale','1','--json']);
  assert.notEqual(r.status,0);
  assert.match(r.stderr,/unsupported|made-up/);
});

test('render: invalid CSS background bytes fail screenshots and HTML export',t=>{
  const dir=fixture(t,'');
  const file=join(dir,'pages/1.page');
  writeFileSync(file,readFileSync(file,'utf8').replace("{type: solid, color: '#FFFFFF'}",'{type: image, src: "data:image/png;base64,bm90LWFuLWltYWdl"}'));
  for(const script of ['export_images.py','export_html.py']) {
    const r=run(script,[dir,'--json']);
    assert.notEqual(r.status,0,script+' accepted invalid image bytes');
    assert.match(r.stderr+r.stdout,/decode/i);
  }
});

test('render: unresolved search reports its page without breaking an unrelated selected page',t=>{
  const dir=fixture(t,'',2);
  const file=join(dir,'pages/2.page');
  writeFileSync(file,readFileSync(file,'utf8')+`  - elementId: missing-photo
    elementType: image
    bounds: [100, 120, 700, 300]
    src: "search:required authentic photo"
`);
  const selected=run('export_images.py',[dir,'--page','1','--workers','1','--scale','1','--json']);
  assert.equal(selected.status,0,selected.stderr);
  assert.equal(JSON.parse(selected.stdout).renderHealth[0].pageNumber,1);
  const missing=run('export_images.py',[dir,'--page','2','--output',join(dir,'missing'),'--json']);
  assert.notEqual(missing.status,0);
  assert.match(missing.stderr,/missing-photo|search:required/);
});

test('render: invalid page background does not prevent checking a different page',t=>{
  const dir=fixture(t,'',2);
  const file=join(dir,'pages/2.page');
  writeFileSync(file,readFileSync(file,'utf8').replace("{type: solid, color: '#FFFFFF'}",'{type: gradient, gradient: {stops: []}}'));
  const selected=run('export_images.py',[dir,'--page','1','--workers','1','--scale','1','--json']);
  assert.equal(selected.status,0,selected.stderr);
  assert.equal(JSON.parse(selected.stdout).renderHealth[0].pageNumber,1);
  const missing=run('export_images.py',[dir,'--page','2','--output',join(dir,'missing'),'--json']);
  assert.notEqual(missing.status,0);
  assert.match(missing.stderr,/background.*gradient|gradient.*background/i);
});

test('render: selected pages keep original page identities',t=>{
  const dir=fixture(t,'',5);
  const r=run('export_images.py',[dir,'--page','3,5','--workers','2','--scale','1','--json']);
  assert.equal(r.status,0,r.stderr);
  assert.deepEqual(JSON.parse(r.stdout).images.map(({index,page})=>[index,page]),[[3,'pages/3.page'],[5,'pages/5.page']]);
});

function readinessProbe(t, mode) {
  const dir=mkdtempSync(join(tmpdir(),'pptd-cdp-ready-'));
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  const target=join(dir,'page.png');
  writeFileSync(target,'previous screenshot bytes must not be accepted or lost on failure');
  const code=`import sys,json,time,threading\nfrom pathlib import Path\nfrom http.server import BaseHTTPRequestHandler,ThreadingHTTPServer\nsys.path.insert(0, ${JSON.stringify(scripts)})\nfrom export_images import screenshot_page,ExportError\nfrom export_html import find_chrome\nfrom PIL import Image\nmode=sys.argv[1]; target=Path(sys.argv[2]); before=target.read_bytes()\nbody='''<!doctype html><html><head><style>html,body{margin:0;background:#660000}h1{font:48px sans-serif;color:white}</style></head><body><h1>Async readiness fixture</h1><script>if(ENABLED)setTimeout(()=>{document.body.style.background='#006644';document.documentElement.style.background='#006644';let p=document.createElement('pre');p.id='render-health';p.hidden=true;p.textContent=JSON.stringify({ready:true,ok:true,pageNumber:PAGE_NUMBER,errors:[]});document.body.appendChild(p)},700)</script></body></html>'''.replace('ENABLED','false' if mode=='never' else 'true').replace('PAGE_NUMBER','99' if mode=='wrong' else '3')\nclass Handler(BaseHTTPRequestHandler):\n def do_GET(self):\n  self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body.encode())\n def log_message(self,*args):pass\nserver=ThreadingHTTPServer(('127.0.0.1',0),Handler); threading.Thread(target=server.serve_forever,daemon=True).start()\nstarted=time.monotonic()\ntry:\n health=screenshot_page(find_chrome(None),f'http://127.0.0.1:{server.server_port}/viewer?fixture=1',3,480,270,2,1,target,3 if mode=='never' else 10)\n with Image.open(target) as im: result={'status':'captured','health':health,'size':im.size,'pixel':im.convert('RGB').getpixel((700,400))}\nexcept ExportError as exc:\n result={'status':'failed','error':str(exc),'oldPreserved':target.read_bytes()==before}\nfinally:\n server.shutdown();server.server_close()\nresult['elapsed']=round(time.monotonic()-started,3);print(json.dumps(result))\n`;
  const r=spawnSync('python3',['-c',code,mode,target],{encoding:'utf8',timeout:15000});
  assert.equal(r.status,0,r.stderr);
  return JSON.parse(r.stdout);
}

test('render: CDP waits beyond virtual time for real readiness, then captures that document at requested scale',t=>{
  const result=readinessProbe(t,'late');
  assert.equal(result.status,'captured',JSON.stringify(result));
  assert.equal(result.health.pageNumber,3);
  assert.deepEqual(result.size,[960,540]);
  assert.ok(result.pixel[0]<30 && result.pixel[1]>80,`Captured pre-ready pixels: ${JSON.stringify(result)}`);
  assert.ok(result.elapsed>=.7,'A 1 ms virtual-time value must not bypass the 700 ms real readiness delay');
});

test('render: missing readiness times out and preserves the previous screenshot',t=>{
  const result=readinessProbe(t,'never');
  assert.equal(result.status,'failed');
  assert.match(result.error,/ready|capture/i);
  assert.equal(result.oldPreserved,true);
  assert.ok(result.elapsed<8,JSON.stringify(result));
});

test('render: health for a different page cannot authorize screenshot replacement',t=>{
  const result=readinessProbe(t,'wrong');
  assert.equal(result.status,'failed');
  assert.match(result.error,/identity mismatch/);
  assert.equal(result.oldPreserved,true);
});

test('HTML: JSON exception returns one object and exits nonzero',()=>{
  const code=`import sys\nsys.path.insert(0, ${JSON.stringify(scripts)})\nimport export_html\nexport_html.find_deck=lambda value: (_ for _ in ()).throw(RuntimeError('fixture failure'))\nsys.argv=['export_html.py','unused','--json']\nexport_html.main()\n`;
  const r=spawnSync('python3',['-c',code],{encoding:'utf8'});
  assert.notEqual(r.status,0);
  assert.equal(JSON.parse(r.stdout).ok,false);
});

test('CLI: child killed by signal cannot become exit zero',t=>{
  const dir=mkdtempSync(join(tmpdir(),'pptd-child-'));
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  writeFileSync(join(dir,'python3'),'#!/bin/sh\nkill -TERM $$\n',{mode:0o755});
  const r=spawnSync(process.execPath,[resolve('bin/open-pptd-skills.js'),'validate',dir],{encoding:'utf8',env:{...process.env,PATH:dir}});
  assert.notEqual(r.status,0,r.stderr);
});
