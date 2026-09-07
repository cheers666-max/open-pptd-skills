#!/usr/bin/env python3
"""Automated two-judge review of finished PPTD decks (content judge on page text, visual judge on a
page contact sheet), plus a report builder. Judges are called through an OpenAI-compatible endpoint.

  python3 eval/auto_judge.py judge  --presentations DIR --cases-file eval/cases.json --out DIR/_auto_eval \
      --models google/gemini-3.5-flash,anthropic/claude-sonnet-4-6 --key-env QIHOO_API_KEY --workers 3
  python3 eval/auto_judge.py report --presentations DIR --out DIR/_auto_eval

Each deck directory must hold deck.pptd, pages/*.page and .qa-images/pages/*.png (export_images.py).
Scores are judge means on 1-5; disagreement is kept per dimension. Time-sensitive cases need the
verified source pack passed with --context-dir so judges do not mark post-cutoff events as fabricated.
Not a quality pass: judges read text and a contact sheet, never the native PPTX.
"""
import argparse, base64, collections, concurrent.futures as cf, glob, html, io, json, os, re, statistics as st, sys, time, urllib.request
from PIL import Image
P=OUT=KEY=BASE=CTX=None; MODELS=[]; cases={}
DIMS=['intent','fact_source','structure','boundary','layout','image_fit','density']
DIM_CN={'intent':'意图契合','fact_source':'事实与来源','structure':'结构与叙事','boundary':'内容边界(不编造/待填)','layout':'版式可读性','image_fit':'配图贴题','density':'文字密度合理'}
def call(model,content,max_tokens=6000,retries=3):
    body={'model':model,'max_tokens':max_tokens,'temperature':0.2,'messages':[{'role':'user','content':content}]}
    for i in range(retries):
        try:
            req=urllib.request.Request(BASE.rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'})
            r=json.load(urllib.request.urlopen(req,timeout=300)); return r['choices'][0]['message'].get('content') or ''
        except Exception as e:
            err=e; time.sleep(5*(i+1))
    raise RuntimeError(f'{model}: {err}')
def parse_json(s):
    m=re.search(r'\{.*\}',s,re.S)
    if not m: raise ValueError('no json')
    return json.loads(m.group(0))
def call_json(model,content,max_tokens=6000):
    txt=call(model,content,max_tokens)
    try: return parse_json(txt)
    except Exception:
        fix=call(model,f'把下面内容修正为严格合法的 JSON（detail 字符串内不得出现未转义的双引号，改用单引号），只输出 JSON：\n{txt}',max_tokens)
        return parse_json(fix)
def deck_text(d):
    out=[]
    for i,pg in enumerate(sorted(glob.glob(d+'pages/*.page')),1):
        t=open(pg).read(); tx=[re.sub(r'<[^>]+>',' ',x) for x in re.findall(r'^\s+text:\s*(.+)$',t,re.M)]
        notes=re.search(r'^notes:\s*(.+?)(?=^\S)',t,re.M|re.S)
        out.append(f'--- 第{i}页 ---\n'+'\n'.join(x.strip().strip("'\"") for x in tx if x.strip())+(f'\n[讲者备注] {notes.group(1).strip()[:400]}' if notes else ''))
    return '\n'.join(out)[:14000]
def sheet_b64(d):
    files=sorted(glob.glob(d+'.qa-images/pages/*.png')); ims=[Image.open(f).convert('RGB') for f in files]
    w=640;h=int(w*ims[0].height/ims[0].width);cols=3;rows=(len(ims)+cols-1)//cols
    sh=Image.new('RGB',(cols*w,rows*h),'#999')
    for i,im in enumerate(ims): sh.paste(im.resize((w,h)),((i%cols)*w,(i//cols)*h))
    b=io.BytesIO(); sh.save(b,'JPEG',quality=82); return base64.b64encode(b.getvalue()).decode(), len(ims)
RUBRIC='''评分 1–5（5 最好），只输出 JSON，不要多余文字。JSON 结构：
{"scores":{"intent":n,"fact_source":n,"structure":n,"boundary":n,"layout":n,"image_fit":n,"density":n},
 "issues":[{"page":页码或0,"severity":"high|medium|low","type":"事实|编造|结构|边界|排版|配图|文案|其他","detail":"具体问题，≤60字"}],
 "strengths":["≤3条"],"top_fixes":["最值得改的 3 条，具体到页"],"overall":n}
评分口径：intent=是否回答了原题的真实需求与受众；fact_source=事实是否可核、来源是否标注、有无年代/人物/数字错误；structure=页间逻辑与叙事完整；boundary=未提供的资料是否明确待填而非编造、敏感/虚构是否标注；layout=文字溢出/重叠/对比度/留白；image_fit=配图是否贴题、是否像凑数、图注是否有技术占位文本；density=每页文字量是否适合演示。对无法从材料判断的维度给 3 并在 issues 说明。'''
def context_pack(cid):
    if not CTX: return ''
    for f in glob.glob(os.path.join(CTX,cid+'*')):
        if f.endswith(('.md','.txt')): return open(f).read()[:6000]
    return ''
def judge_content(model,cid,d):
    c=cases[cid]; pack=context_pack(cid); prompt=(f'今天是 {time.strftime("%Y-%m-%d")}。以下资料包是人工核对过官方来源的事实基准，请以它为准，不要因训练截止日期把其中事件判为未来/编造：\n{pack}\n\n' if pack else '')+f'''你是 PPT 内容评审。原始需求：{c.get("originalPrompt") or c["prompt"].split(chr(10))[0]}
评阅要点：{"；".join(c.get("expected_behavior",[]))}
以下是 PPT 逐页文字（含图注、脚注、讲者备注）：
{deck_text(d)}

请只依据文字评 intent/fact_source/structure/boundary/density（layout、image_fit 给 3 并注明"文本判官不评"）。{RUBRIC}'''
    return call_json(model,prompt)
def judge_visual(model,cid,d):
    c=cases[cid]; b64,n=sheet_b64(d)
    prompt=f'''你是 PPT 视觉评审。原始需求：{c.get("originalPrompt") or c["prompt"].split(chr(10))[0]}
下图是整套 {n} 页幻灯片的拼图（从左到右、从上到下为第 1..{n} 页，每页 16:9）。逐页检查：文字溢出/重叠/被裁切、对比度不足、空洞留白、配图是否贴题或明显凑数、图注是否残留技术占位文本（如 images_report.json）、封面与结尾是否重复用图、整体风格是否统一。
请只评 layout/image_fit/density（intent/fact_source/structure/boundary 给 3 并注明"视觉判官不评"）。{RUBRIC}'''
    return call_json(model,[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+b64}}])
def run(cid):
    d=f'{P}/{cid}/'; out=f'{OUT}/{cid}.json'
    if os.path.exists(out): return cid,'cached'
    res={'id':cid,'content':{},'visual':{}}
    for m in MODELS:
        for kind,fn in (('content',judge_content),('visual',judge_visual)):
            try: res[kind][m]=fn(m,cid,d)
            except Exception as e: res[kind][m]={'error':str(e)[:300]}
    json.dump(res,open(out,'w'),ensure_ascii=False,indent=1); return cid,'done'
def cmd_judge(a):
    global P,OUT,KEY,BASE,CTX,MODELS,cases
    P=str(a.presentations); OUT=os.path.join(a.out,'results'); os.makedirs(OUT,exist_ok=True)
    KEY=os.environ.get(a.key_env or '','') ; BASE=a.base_url; CTX=a.context_dir; MODELS=[m for m in a.models.split(',') if m]
    if not KEY: sys.exit(f'{a.key_env} is unset')
    cases={c['id']:c for c in json.load(open(a.cases_file))['cases']}
    ids=[os.path.basename(x.rstrip('/')) for x in sorted(glob.glob(f'{P}/[0-9][0-9]-*/'))]
    if a.case: ids=[i for i in ids if any(i.startswith(x) for x in a.case.split(','))]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for cid,state in ex.map(run,ids): print(cid,state,flush=True)
def mechanical_metrics(P):
    rows={}
    for d in sorted(glob.glob(f'{P}/[0-9][0-9]-*/')):
        cid=os.path.basename(d.rstrip('/')); pages=sorted(glob.glob(d+'pages/*.page')); imgs=[]; chars=[]; src=0; tbd=0
        for pg in pages:
            t=open(pg).read(); tx=' '.join(re.findall(r'^\s+text:\s*(.+)$',t,re.M)); chars.append(len(re.sub(r'<[^>]+>','',tx)))
            tbd+=t.count('待填'); imgs+=re.findall(r'src:\s*"?(media/[^"\n]+)',t)
            if re.search(r'来源|资料图|Commons|S\d',tx): src+=1
        rows[cid]=dict(pages=len(pages),avg_chars=int(sum(chars)/max(1,len(chars))),max_chars=max(chars or [0]),uniq_imgs=len(set(imgs)),dup_imgs=sum(1 for k,v in collections.Counter(imgs).items() if v>1),placeholders=tbd,src_pages=src)
    return rows
def cmd_report(a):
    global P,OUT
    P=str(a.presentations); OUT=str(a.out)
    DIMS=['intent','fact_source','structure','boundary','layout','image_fit','density']
    CN={'intent':'意图契合','fact_source':'事实来源','structure':'结构叙事','boundary':'内容边界','layout':'版式','image_fit':'配图','density':'密度'}
    TEXT_DIMS=['intent','fact_source','structure','boundary','density']; VIS_DIMS=['layout','image_fit','density']
    mech=mechanical_metrics(P)
    decks=[]; all_issues=[]
    for f in sorted(glob.glob(f'{OUT}/results/*.json')):
        d=json.load(open(f)); cid=d['id']; per={k:[] for k in DIMS}; judges={}; issues=[]
        for kind,dims in (('content',TEXT_DIMS),('visual',VIS_DIMS)):
            for m,v in d[kind].items():
                if 'error' in v or not isinstance(v.get('scores'),dict): judges[f'{kind}/{m.split("/")[-1]}']='ERR'; continue
                judges[f'{kind}/{m.split("/")[-1]}']=v.get('overall')
                for k in dims:
                    try: per[k].append(float(v['scores'][k]))
                    except Exception: pass
                for i in v.get('issues',[]):
                    if isinstance(i,dict) and '不评' not in str(i.get('detail','')):
                        issues.append({**i,'judge':f'{kind}/{m.split("/")[-1]}'})
        avg={k:(round(st.mean(v),2) if v else None) for k,v in per.items()}
        spread={k:(round(max(v)-min(v),1) if len(v)>1 else 0) for k,v in per.items()}
        overall=round(st.mean([x for x in avg.values() if x is not None]),2)
        hi=[i for i in issues if i.get('severity')=='high']
        decks.append(dict(id=cid,avg=avg,spread=spread,overall=overall,judges=judges,issues=issues,high=len(hi),
            top_fixes=[x for kind in ('content','visual') for v in d[kind].values() for x in (v.get('top_fixes') or [])][:6],
            strengths=[x for kind in ('content','visual') for v in d[kind].values() for x in (v.get('strengths') or [])][:4],**{k:mech.get(cid,{}).get(k) for k in ('pages','avg_chars','max_chars','uniq_imgs','dup_imgs','placeholders','src_pages')}))
        all_issues+= [{**i,'deck':cid} for i in issues]
    decks.sort(key=lambda x:x['overall'])
    dim_avg={k:round(st.mean([d['avg'][k] for d in decks if d['avg'][k] is not None]),2) for k in DIMS}
    by_type=collections.Counter(i.get('type','其他') for i in all_issues)
    by_type_high=collections.Counter(i.get('type','其他') for i in all_issues if i.get('severity')=='high')
    json.dump({'decks':decks,'dim_avg':dim_avg,'issue_by_type':by_type,'issue_by_type_high':by_type_high,'n_issues':len(all_issues)},open(f'{OUT}/summary.json','w'),ensure_ascii=False,indent=1)
    # markdown
    L=['# 20 题自动化评测汇总','',f'判官：Gemini 3.5 Flash + Claude Sonnet 4.6，各评内容（文本）与视觉（整套页面拼图）；分数为可评判官均值（1–5）。共 {len(all_issues)} 条问题。','',
       '## 维度均分','','| '+' | '.join(CN[k] for k in DIMS)+' |','|'+'---|'*len(DIMS),'| '+' | '.join(str(dim_avg[k]) for k in DIMS)+' |','',
       '## 问题类型分布（高严重度）','','| 类型 | 总数 | high |','|---|---:|---:|']+[f'| {t} | {n} | {by_type_high.get(t,0)} |' for t,n in by_type.most_common()]+['','## 逐题（按总分升序）','','| 题目 | 总分 | '+' | '.join(CN[k] for k in DIMS)+' | high | 页 | 待填 | 图 |','|---|---:|'+'---:|'*len(DIMS)+'---:|---:|---:|---:|']
    for d in decks: L.append(f"| {d['id']} | {d['overall']} | "+' | '.join(str(d['avg'][k]) for k in DIMS)+f" | {d['high']} | {d['pages']} | {d['placeholders']} | {d['uniq_imgs']} |")
    L+=['','## 每题最值得改的点','']
    for d in decks:
        L.append(f"### {d['id']}（{d['overall']}）")
        for i in sorted(d['issues'],key=lambda x:{'high':0,'medium':1,'low':2}.get(x.get('severity'),3))[:5]: L.append(f"- [{i.get('severity')}] P{i.get('page')} {i.get('type')}：{i.get('detail')}（{i['judge']}）")
        L.append('')
    open(f'{OUT}/summary.md','w').write('\n'.join(L))
    # html
    def bar(v): 
        c='#2e8b57' if v>=4 else '#d99a00' if v>=3 else '#c0392b'; return f'<span class="bar"><i style="width:{v/5*100:.0f}%;background:{c}"></i></span>{v}'
    rows=''.join(f'<tr><td><a href="index.html#{d["id"]}">{d["id"]}</a></td><td><b>{d["overall"]}</b></td>'+''.join(f'<td>{bar(d["avg"][k]) if d["avg"][k] is not None else "-"}</td>' for k in DIMS)+f'<td>{d["high"]}</td><td>{d["pages"]}</td><td>{d["placeholders"]}</td><td>{d["uniq_imgs"]}{"/"+str(d["dup_imgs"])+"重" if d["dup_imgs"] else ""}</td></tr>' for d in decks)
    details=''.join(f'<details id="d-{d["id"]}"><summary><b>{d["id"]}</b> 总分 {d["overall"]} · 高严重 {d["high"]} · 判官总评 {html.escape(json.dumps(d["judges"],ensure_ascii=False))}</summary><div class="two"><div><h4>问题（按严重度）</h4><ul>'+''.join(f'<li class="{i.get("severity")}">P{i.get("page")} <em>{html.escape(str(i.get("type")))}</em> {html.escape(str(i.get("detail")))} <small>{i["judge"]}</small></li>' for i in sorted(d["issues"],key=lambda x:{"high":0,"medium":1,"low":2}.get(x.get("severity"),3)))+'</ul></div><div><h4>建议修改</h4><ul>'+''.join(f'<li>{html.escape(str(x))}</li>' for x in d["top_fixes"])+'</ul><h4>优点</h4><ul>'+''.join(f'<li>{html.escape(str(x))}</li>' for x in d["strengths"])+'</ul></div></div></details>' for d in decks)
    types=''.join(f'<tr><td>{t}</td><td>{n}</td><td>{by_type_high.get(t,0)}</td></tr>' for t,n in by_type.most_common())
    page=f'''<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>自动化评测报告 · 20 题</title>
    <style>body{{font-family:-apple-system,"PingFang SC","Noto Sans SC",sans-serif;margin:0;background:#f5f3ee;color:#1d1d1f;font-size:14px}}main{{max-width:1400px;margin:0 auto;padding:20px 24px 60px}}h1{{font-size:22px;margin:0 0 4px}}.sub{{color:#666;font-size:13px;margin-bottom:16px}}
    table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px}}th,td{{border-bottom:1px solid #e6e2da;padding:6px 8px;text-align:left;white-space:nowrap}}th{{background:#faf8f3;position:sticky;top:0}}.bar{{display:inline-block;width:56px;height:8px;background:#eee;border-radius:4px;margin-right:6px;vertical-align:middle}}.bar i{{display:block;height:100%;border-radius:4px}}
    .kpi{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}}.kpi div{{background:#fff;border:1px solid #e6e2da;border-radius:8px;padding:10px 14px;min-width:120px}}.kpi b{{font-size:20px;display:block}}.kpi span{{font-size:12px;color:#666}}
    details{{background:#fff;border:1px solid #e6e2da;border-radius:8px;padding:8px 14px;margin:8px 0}}summary{{cursor:pointer}}.two{{display:grid;grid-template-columns:1.4fr 1fr;gap:18px}}ul{{padding-left:18px;line-height:1.5}}li.high{{color:#c0392b}}li.medium{{color:#8a5a00}}li small{{color:#999}}h4{{margin:10px 0 4px;font-size:13px}}.wrap{{overflow-x:auto}}@media(max-width:800px){{.two{{grid-template-columns:1fr}}}}</style></head>
    <body><main><h1>自动化评测报告 · 20 题</h1><div class="sub">判官：Gemini 3.5 Flash + Claude Sonnet 4.6 · 内容判官读逐页文字，视觉判官看整套页面拼图 · 分数 1–5 为判官均值 · <a href="index.html">返回评测台</a> · <a href="summary.md">Markdown</a> · <a href="summary.json">JSON</a> · <a href="OPTIMIZATION.md">优化分析</a></div>
    <div class="kpi">'''+''.join(f'<div><b>{dim_avg[k]}</b><span>{CN[k]}</span></div>' for k in DIMS)+f'''<div><b>{len(all_issues)}</b><span>问题总数</span></div><div><b>{sum(by_type_high.values())}</b><span>高严重度</span></div></div>
    <h3>逐题分数（按总分升序）</h3><div class="wrap"><table><tr><th>题目</th><th>总分</th>'''+''.join(f'<th>{CN[k]}</th>' for k in DIMS)+f'''<th>high</th><th>页</th><th>待填</th><th>图(唯一/重复)</th></tr>{rows}</table></div>
    <h3>问题类型分布</h3><table style="width:auto"><tr><th>类型</th><th>总数</th><th>high</th></tr>{types}</table>
    <h3>逐题问题与建议</h3>{details}</main></body></html>'''
    open(f'{OUT}/auto-eval.html','w').write(page)
    print('decks',len(decks),'issues',len(all_issues),'dim_avg',dim_avg); print(by_type.most_common())

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub=ap.add_subparsers(dest='cmd',required=True)
    j=sub.add_parser('judge'); j.add_argument('--presentations',required=True); j.add_argument('--cases-file',default=os.path.join(os.path.dirname(__file__),'cases.json'))
    j.add_argument('--out',required=True); j.add_argument('--models',default='google/gemini-3.5-flash,anthropic/claude-sonnet-4-6'); j.add_argument('--key-env',default='QIHOO_API_KEY')
    j.add_argument('--base-url',default='https://api.360.cn/v1'); j.add_argument('--context-dir',help='Directory of verified source packs named <case-id>*.md, passed to content judges'); j.add_argument('--workers',type=int,default=3); j.add_argument('--case',help='Comma-separated id prefixes')
    r=sub.add_parser('report'); r.add_argument('--presentations',required=True); r.add_argument('--out',required=True)
    a=ap.parse_args(argv); (cmd_judge if a.cmd=='judge' else cmd_report)(a)
if __name__=='__main__':
    main()
