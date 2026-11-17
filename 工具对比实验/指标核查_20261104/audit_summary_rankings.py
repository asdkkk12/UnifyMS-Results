# coding: utf-8
from pathlib import Path
import re,json,hashlib
p=Path('/Users/yuanyaowu/Desktop/输出/汇总Case.md');text=p.read_text();recalc=json.loads(Path('/Users/yuanyaowu/Desktop/输出/UCM_论文定义重算_20261104/UCM_计算明细.json').read_text())
canon=lambda name:next(m for prefix,m in [('MicroMiner','microminer'),('MonoEmbed','monoembed'),('Service Cutter','servicecutter'),('UnifyMS','unifyms')] if name.strip().startswith(prefix))
sections=list(re.finditer(r'^## (\d+)\. ([^\n]+)$',text,re.M));items=[]
for i,m in enumerate(sections):
 end=sections[i+1].start() if i+1<len(sections) else text.index('\n## 来源校验',m.end());block=text[m.start():end];case=m[2].split(' — ')[0];ranks={}
 for row in re.findall(r'^\| (IFN|CHD|Instability|UCM|CMQ) \| ([^|]+) \| ([^|]+) \|$',block,re.M):
  metric,direction,expr=row;values={}
  for names,value in re.findall(r'([^（）→]+)（(-?\d+\.\d+)）',expr):
   for name in names.split('='):
    method=canon(name);assert method not in values;values[method]=value
  assert len(values)==4,(case,metric,values);ranks[metric]=values
 assert len(ranks)==5
 old={};changes=[]
 for line in block.splitlines():
  if not re.match(r'^\| (MicroMiner|MonoEmbed|Service Cutter|UnifyMS)',line):continue
  cells=[v.strip() for v in line.strip('|').split('|')]
  if len(cells)!=7:continue
  method=canon(cells[0]);old[method]=dict(zip(['MS_Num','IFN','CHD','Instability','UCM','CMQ'],cells[1:]))
  for metric in ranks:
   if old[method][metric]!=ranks[metric][method]:changes.append({'case':case,'method':method,'metric':metric,'before':old[method][metric],'after':ranks[metric][method]})
 b=Path(recalc['cases'][case]['batch_directory']);raw={method:(json.loads((b/'unifyms/summary.json').read_text())['mean'] if method=='unifyms' else json.loads((b/method/'metrics.json').read_text())) for method in ['microminer','monoembed','servicecutter','unifyms']}
 comparisons=[]
 for metric,vs in ranks.items():
  for method,value in vs.items():
   rv=f'{raw[method][metric]:.6f}';pv=next((r['UCM'] for r in recalc['summary'] if r['case']==case and r['method']==method),None) if metric=='UCM' else None
   if metric=='UCM':
    status='paper_recalculation' if pv is not None and f'{pv:.6f}'==value else ('legacy_raw_output' if rv==value else 'unsupported_by_raw_or_strict_paper_recalculation')
   else:status='recorded_raw_output' if rv==value else 'unsupported_by_raw_output'
   comparisons.append({'case':case,'method':method,'metric':metric,'ranking_value':value,'raw_output':rv,'paper_UCM':None if pv is None else f'{pv:.6f}','status':status})
 items.append({'case':case,'id':m[1],'title':m[2],'start':m.start(),'end':end,'ranks':ranks,'old':old,'changes':changes,'comparisons':comparisons})
print('CHANGES',json.dumps([x for item in items for x in item['changes']],ensure_ascii=False,indent=2))
print('UNSUPPORTED',json.dumps([x for item in items for x in item['comparisons'] if x['status'].startswith('unsupported')],ensure_ascii=False,indent=2))
Path('/tmp/summary_ranking_audit.json').write_text(json.dumps({'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'items':items},ensure_ascii=False,indent=2)+'\n')
