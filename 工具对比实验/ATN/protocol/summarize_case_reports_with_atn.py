from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import re,hashlib,json
root=Path('/Users/yuanyaowu/Desktop/输出')
reports=sorted(p for p in root.rglob('*案例运行结果.md') if not p.name.startswith('._'))
reports.sort(key=lambda p: ('ATM' if p.relative_to(root).parts[0]=='ATN' else p.relative_to(root).parts[0], 0 if p.relative_to(root).parts[0]=='ATN' else 1, str(p)))
link=lambda p,label:'['+label+'](<'+str(p)+'>)'
def sections(s):
 hs=list(re.finditer(r'^#{1,6} +(.+?)\s*$',s,re.M));out={}
 for i,m in enumerate(hs):out[m[1]]=s[m.end():hs[i+1].start() if i+1<len(hs) else len(s)].strip()
 return out

def table_rows(block):
 return [line for line in block.splitlines() if line.startswith('|')]

items=[];anomalies=[]
for i,p in enumerate(reports,1):
 raw=p.read_bytes();s=raw.decode();sec=sections(s);comparison=sec.get('五指标对比',sec.get('指标对比'));ranking=sec['五指标排序'];cost=sec.get('Token 与总耗时')
 assert comparison and len(table_rows(comparison))==6,(p,'comparison')
 assert len(table_rows(ranking))==7,(p,'ranking')
 rel=p.relative_to(root);case='ATM' if rel.parts[0]=='ATN' else rel.parts[0];batch='当前目录报告'
 if len(rel.parts)>2:batch='/'.join(rel.parts[1:-1])
 if rel.parts[0]=='ATM':batch='历史批次 / '+batch
 elif rel.parts[0]=='ATN':batch='最新重跑 atm_20261104_01（ATN 目录）'
 elif case=='Spring' and len(rel.parts)==2:batch='首轮 spring_20261104_01'
 elif case=='COCOME' and len(rel.parts)==2:batch='当前入口（对应 重算_20261103_01）'
 if cost:
  def clean_token(m):
   method,token,seconds,scope=[v.strip() for v in m.groups()]
   if token and not re.fullmatch(r'\d+',token):
    anomalies.append((i,token));return '| '+method+' |  | '+seconds+' | '+scope+' |'
   return m[0]
  cost=re.sub(r'^\|\s*(MonoEmbed API|UnifyMS \+ JEV)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$',clean_token,cost,flags=re.M)
  assert len(table_rows(cost))==4
  for sid,value in anomalies:
   if sid==i:cost+='\n\n原报告“总 token”栏为 `'+value+'`（金额格式）；本汇总不将其视为 token 数量，该单元格留空。原始值仍保留在来源报告中。'
 else:
  cost='| 方法 | 总 token | 总耗时（秒） | 说明 |\n|---|---:|---:|---|\n| MonoEmbed 轻量替代版 | | | 原报告未提供总 token 与总耗时。 |\n| UnifyMS + JEV | | | 原报告未提供完整总量。 |\n\n历史报告只记载正式搜索平均 **88.402364 秒/次**，未将其换算为包含校准与 JEV 的总耗时；十次搜索使用两个进程并行，不能用均值乘十当作总墙钟时间。'
 # Move relative local artifact links to original report's directory.
 def absolute_links(text):
  def repl(m):
   target=m[2];bare=target.strip('<>')
   if bare.startswith(('/', '#','http:', 'https:')):return m[0]
   return '['+m[1]+'](<'+str((p.parent/bare).resolve())+'>)'
  return re.sub(r'\[([^\]]+)\]\(([^)]+)\)',repl,text)
 items.append(dict(id=i,path=p,sha256=hashlib.sha256(raw).hexdigest(),case=case,batch=batch,comparison=absolute_links(comparison),ranking=absolute_links(ranking),cost=absolute_links(cost)))
lines=['# 案例运行结果汇总','', '生成时间：'+datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')+'。','',f'扫描 `{root}`，共汇总 **{len({v["case"] for v in items})} 个案例、{len(items)} 份报告**。以下分别保留各报告的五指标对比、五指标排序和 Token 与总耗时，未重新运行程序或重算指标。','',
'不同案例、方法和批次的输入表示、指标公式、运行次数及计时范围并不一致；排序沿用原报告的数值口径，不是统一的方法优劣排名。MS_Num 为服务数，另外五列为五项指标。缺失 token 或完整总耗时留空；数值向量没有文本生成输出 token。','',
'ATM 的最新重跑报告位于 `ATN/ATM案例运行结果.md`，按 ATM 案例归类；原 `ATM` 目录的报告保留为历史批次。', '',
'COCOME 的当前入口和 `重算_20261103_01` 是同一批次的两份报告，指标和排序相同，分别列出以覆盖全部文件，不应重复算作两次实验。Spring 首轮与重跑批次分别列出；COCOME 历史报告保留旧方法版本和旧计量范围。','',
'部分原报告在总 token 栏写入金额格式的值。本汇总将这些单元格留空，并在对应章节保留原值备注；原文件保持不变。Spring 报告注明的原生 CMQ 历史计数缺陷、ATM 单服务代表方案等限制仍适用。','',
'## 来源索引','', '| 编号 | 案例 | 批次 / 入口 | 原报告 |','|---|---|---|---|']
for v in items:lines.append(f'| {v["id"]:02d} | {v["case"]} | {v["batch"]} | '+link(v['path'],'查看来源')+' |')
for v in items:
 lines+=['',f'## {v["id"]:02d}. {v["case"]} — {v["batch"]}','', '来源：'+link(v['path'],str(v['path'].relative_to(root)))+'。','', '### 五指标对比','',v['comparison'],'','### 五指标排序','',v['ranking'],'','### Token 与总耗时','',v['cost']]
lines+=['','## 来源校验','', '以下 SHA-256 对应本次读取的完整来源文件，可用于确认汇总取自哪个版本。','', '| 编号 | SHA-256 |','|---|---|']
for v in items:lines.append(f'| {v["id"]:02d} | `{v["sha256"]}` |')
out=Path('/tmp/汇总Case.md');out.write_text('\n'.join(lines)+'\n')
s=out.read_text();assert s.count('### 五指标对比')==len(items)==s.count('### 五指标排序')==s.count('### Token 与总耗时')
assert len(re.findall(r'^\| (?:MicroMiner|MonoEmbed|Service Cutter|UnifyMS).*?\|',s,re.M))==len(items)*6
for v in items:assert hashlib.sha256(v['path'].read_bytes()).hexdigest()==v['sha256']
for t in re.findall(r'\]\(<([^>]+)>\)',s):assert Path(t).exists(),t
print(json.dumps({'reports':len(items),'cases':len({v['case'] for v in items}),'metric_rows':len(items)*4,'ranking_rows':len(items)*5,'token_anomalies':[{'report':sid,'original':v} for sid,v in anomalies],'draft':str(out),'bytes':out.stat().st_size},ensure_ascii=False))
