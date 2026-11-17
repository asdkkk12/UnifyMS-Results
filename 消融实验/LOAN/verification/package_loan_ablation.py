# -*- coding: utf-8 -*-
import csv,hashlib,json,math,re,shutil,statistics
from pathlib import Path
ROOT=Path('/Users/yuanyaowu/Desktop/实验室材料/UnifyMs/UnifyMS代码')
SRC=ROOT/'output/loan-ablation-20261114';DEST=Path('/Users/yuanyaowu/Desktop/消融实验');OUT=DEST/'LOAN';MASTER=DEST/'汇总Case.md';FULL=Path('/Users/yuanyaowu/Desktop/输出/Loan/unifyms');ATTACH=Path('/Users/yuanyaowu/Desktop/输出/汇总Case.md.md')
SEEDS=[101,103,107,109,113,127,131,137,139,149];METRICS=['IFN','CHD','Instability','UCM','CMQ'];KEYS=['MS_Num',*METRICS,'HV'];LABELS={'full':'Full：完整方法','without-offline':'−O：无离线选参','without-probability':'−P：无动态概率','without-guidance':'−G：无候选引导'}
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
assert read(SRC/'study-status.json')['status']=='success' and not OUT.exists()
master=MASTER.read_text();master_sha=sha(MASTER);assert '\n## LOAN\n' not in master and '\n## Loan\n' not in master
r=read(SRC/'report/results.json');protocol=read(SRC/'shared/protocol.json');fs=read(FULL/'report/ten-run-summary.json');assert len(r['runs'])==30
assert fs['inputHash']==protocol['inputHash'] and fs['metricVersion']==protocol['metricVersion'] and fs['seeds']==SEEDS and fs['offlineChoice']=='C5'
assert read(FULL/'experiment/Loan/calibration.json')==read(SRC/'shared/calibration.json') and read(FULL/'model-snapshot.json')==read(SRC/'shared/model-snapshot.json')
assert read(FULL/'run-config.json')==read(SRC/'shared/run-config.json') and protocol['historicalParser']=='filtered-comment-reader-v1'
s=ATTACH.read_text();section='## 07. Loan'+s.split('## 07. Loan',1)[1].split('\n## ',1)[0];line=next(x for x in section.splitlines() if x.startswith('| UnifyMS + LLM + JEV'));attachment=dict(zip(KEYS[:-1],map(float,[x.strip() for x in line.split('|')[2:-1]])))
rows=[];fullfiles=[]
for arm in LABELS:
 for seed in SEEDS:
  f=FULL/'experiment/Loan/online-jev/guidance-jev'/f'run-jev-{seed}.json' if arm=='full' else SRC/'arms'/arm/f'seed-{seed}'/'run.json'
  x=read(f);run=x['run'];rep=x['representative'];c=run['config'];assert run['status']=='success' and rep['valid'] and run['inputHash']==protocol['inputHash'] and run['metricVersion']==protocol['metricVersion']
  expected=('C0',200,100,.7,.5) if arm=='without-offline' else ('C5',100,200,.9,.25)
  assert c['seed']==seed and run['completedGenerations']==expected[2] and tuple(c[k] for k in ['id','populationSize','generations','crossoverProbability','crossP'])==expected
  m=rep['metrics'];rows.append(dict(arm=arm,method=LABELS[arm],seed=seed,MS_Num=rep['serviceCount'],IFN=m[0],CHD=m[1],CMQ=m[2],Instability=m[3],UCM=m[4],HV=x['hv'],source=f'LOAN/full-reference/run-full-{seed}.json' if arm=='full' else 'LOAN/'+str(f.relative_to(SRC)),sourceSha256=sha(f)))
  if arm=='full':fullfiles.append(f)
bounds={k:dict(min=min(x[k] for x in rows),max=max(x[k] for x in rows)) for k in METRICS}
for row in rows:
 z={};sq={}
 for k in METRICS:
  b=bounds[k];span=b['max']-b['min'];z[k]=(row[k]-b['min'])/span if span else (0 if k=='IFN' else 1);sq[k]=(z[k] if k=='IFN' else 1-z[k])**2 if span else 0
 row.update(normalized=z,squaredContributions=sq,ED=math.sqrt(math.fsum(sq.values())));assert abs(row['ED']-math.dist(list(z.values()),[0,1,1,1,1]))<1e-12
stats={a:{k:dict(mean=statistics.mean(x[k] for x in rows if x['arm']==a),sampleStd=statistics.stdev(x[k] for x in rows if x['arm']==a)) for k in [*KEYS,'ED']} for a in LABELS}
for k in KEYS:
 v=fs['serviceCount' if k=='MS_Num' else 'hv'] if k in ['MS_Num','HV'] else fs['metrics'][k]
 assert abs(v['mean']-stats['full'][k]['mean'])<1e-12
for k,v in attachment.items():assert abs(v-stats['full'][k]['mean'])<.00000051
for a in list(LABELS)[1:]:
 for k in KEYS:assert abs(r['aggregates'][a][k]['mean']-stats[a][k]['mean'])<1e-12
ranks={}
def rank(k):
 order=sorted(LABELS,key=lambda a:stats[a][k]['mean'],reverse=k not in ['IFN','ED']);groups=[]
 for a in order:
  if groups and abs(stats[a][k]['mean']-stats[groups[-1][0]][k]['mean'])<1e-12:groups[-1].append(a)
  else:groups.append([a])
 ranks[k]=groups
 return ' → '.join(' = '.join(f"{LABELS[a]}（{stats[a][k]['mean']:.6f}）" for a in g) for g in groups),' = '.join(LABELS[a] for a in groups[0])
(SRC/'summary-before-loan.md').write_bytes(MASTER.read_bytes());shutil.copytree(SRC,OUT);ref=OUT/'full-reference';ref.mkdir()
for p,name in [(ATTACH,'汇总Case来源.md.md'),(FULL/'report/ten-run-summary.json','ten-run-summary.json'),(FULL/'run-config.json','run-config.json'),(FULL/'experiment/Loan/calibration.json','calibration.json'),(FULL/'experiment/Loan/selection-jev.json','selection-jev.json')]:shutil.copy2(p,ref/name)
(ref/'Loan附件节选.md').write_text(section+'\n')
for f,seed in zip(fullfiles,SEEDS):shutil.copy2(f,ref/f'run-full-{seed}.json')
write(ref/'verified-full-results.json',dict(source=str(FULL),sourceAttachment=str(ATTACH),attachmentMeans=attachment,verifiedStatistics=stats['full'],runs=[x for x in rows if x['arm']=='full'],compatibility=dict(input=True,metricVersion=True,calibration=True,normalization=True,parserSnapshot=True,seeds=True,initialConfig='C5'),discrepancies=[]))
ed=dict(case='LOAN',metric='ED',better='lower',normalization='shared min-max across all 40 per-run representatives in this case',metricOrder=METRICS,ideal=[0,1,1,1,1],weights=[1]*5,zeroSpanPolicy='zero distance contribution',metricVersion=protocol['metricVersion'],inputHash=protocol['inputHash'],sampleCount=40,seeds=SEEDS,bounds=bounds,groups={a:dict(method=LABELS[a],n=10,**stats[a]['ED']) for a in LABELS},runs=[dict(case='LOAN',arm=x['arm'],method=x['method'],seed=x['seed'],metrics={k:x[k] for k in METRICS},normalized=x['normalized'],squaredContributions=x['squaredContributions'],ED=x['ED'],source=x['source'],sourceSha256=x['sourceSha256']) for x in rows])
lines=['## LOAN','','### 分组与冻结协议','','输入为 `/Users/yuanyaowu/Desktop/输出/Loan/input/loan.remodel`，与历史 Full 哈希相同；仓库根目录另一个 loan.remodel 未使用。指标版本 `paper-ieee-eq5-21-v2-isolated-zero`，IFN ↓，其余四项 ↑；无接口服务 Instability=0。每 10 代观察，末代不调用，候选损失门槛 0.5。','','|组别|离线选参|动态概率|LLM 生成＋JEV 优选|起始配置|次数|','|---|---|---|---|---|---:|','|Full|历史 JEV 选择 C5|开启|开启|C5：N100/G200/p_var0.9/crossP0.25|10（历史）|','|−O|关闭|开启|开启|C0：N200/G100/p_var0.7/crossP0.5|10（本轮）|','|−P|复用历史 C5|关闭，固定0.9|开启|C5|10（本轮）|','|−G|复用历史 C5|开启|关闭|C5|10（本轮）|','','本轮只新跑三组共30次；Full 从既有输出汇总的 Loan 节导入，并用十次原始 JSON 和机器汇总核验，不重新运行 Full 或离线 JEV。种子：'+', '.join(map(str,SEEDS))+'。名义代数不同，实际评价与额外候选开销分别记录，不声称等预算或单变量实验。','','历史950条校准方案、六组校准搜索、冻结归一化及HV、760个生成任务、20个候选Choice请求、190个概率请求均通过兼容核查。模型、提示词和实现身份见协议及兼容检查。','','### 完整方法来源','','[既有汇总来源](LOAN/full-reference/汇总Case来源.md.md) · [Loan 节选](LOAN/full-reference/Loan附件节选.md) · [十次机器汇总](LOAN/full-reference/ten-run-summary.json) · [逐次核验](LOAN/full-reference/verified-full-results.json)','','本消融汇总此前未收录 Loan，本节采用既有 `/Users/yuanyaowu/Desktop/输出/汇总Case.md.md` 中完整方法结果；五指标与原始十次 JSON 一致。','','### 五指标对比（十次均值，含 ED）','','|方法|MS_Num|IFN ↓|CHD ↑|Instability ↑|UCM ↑|CMQ ↑|ED ↓|','|---|---:|---:|---:|---:|---:|---:|---:|']
for arm in LABELS:lines.append('|'+LABELS[arm]+'|'+'|'.join(f'{stats[arm][k]["mean"]:.6f}' for k in [*KEYS[:-1],'ED'])+'|')
lines+=['','ED 使用四组40次代表方案共同Min–Max区间，逐次计算到理想点 `(0,1,1,1,1)` 的等权欧式距离，再取十次均值；不是对五指标均值求距离。零跨度维度不参与。','','归一化范围：'+'；'.join(f"{k} [{bounds[k]['min']:.6f}, {bounds[k]['max']:.6f}]" for k in METRICS)+'。','','[逐次 ED JSON](LOAN/report/ed-results.json) · [逐次 ED CSV](LOAN/report/ed-per-run.csv)','','### 五指标排序（含 ED）','','|指标|方向|由好到差（十次均值）|均值最优组|','|---|---|---|---|']
for k in [*METRICS,'ED']:
 desc,best=rank(k);lines.append('|'+k+'|'+('越小越好 ↓' if k in ['IFN','ED'] else '越大越好 ↑')+'|'+desc+'|'+best+'|')
lines+=['','相同均值并列，不代表统计显著性；Case 内归一化的 ED 不与其他案例直接比较。','','### 均值、样本标准差与 HV','','每项为均值 ± 样本标准差（n=10，分母 n−1）；五指标/ED对应代表方案，HV对应完整前沿。','','|方法|MS_Num|IFN|CHD|Instability|UCM|CMQ|HV ↑|ED ↓|','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for arm in LABELS:lines.append('|'+LABELS[arm]+'|'+'|'.join(f'{stats[arm][k]["mean"]:.6f} ± {stats[arm][k]["sampleStd"]:.6f}' for k in [*KEYS,'ED'])+'|')
desc,_=rank('HV');lines+=['','HV排序：'+desc+'。','','### 实际执行与输出','','|组别|实际评价合计|额外候选评价|入选|下一代留存|概率 JEV 请求|生成 LLM 请求|候选 JEV 请求|','|---|---:|---:|---:|---:|---:|---:|---:|']
for arm in list(LABELS)[1:]:
 sub=[x for x in r['runs'] if x['arm']==arm];counts={m:sum(x['requests'] for x in r['moduleStatistics'] if x['arm']==arm and x['module']==m) for m in ['probability-JEV','generation-LLM','candidate-JEV']}
 lines.append('|'+LABELS[arm]+'|'+'|'.join(str(v) for v in [sum(x['evaluations'] for x in sub),sum(x['candidateEvaluations'] for x in sub),sum(x['selected'] for x in sub),sum(x['retained'] for x in sub),*counts.values()])+'|')
lines+=['','评价计数包含重复种群评价；模型请求失败、成功KEEP与实际入选分别记录。tokens未知时不当作0。分模块时间与输入tokens见[调用统计](LOAN/report/module-statistics.csv)，失败见[失败分类](LOAN/report/call-failures.json)。','','每个种子保存完整种群、前沿、代表方案和审计；`visualization/loan.req` 为拆分模型，`loan-merm.html` 可直接在浏览器打开，`loan-usecases.svg`、`loan-domain.svg` 为两类拆分图。共30套。','','|种子|−O|−P|−G|','|---:|---|---|---|']
for seed in SEEDS:
 links=[]
 for arm in list(LABELS)[1:]:
  b=f'LOAN/arms/{arm}/seed-{seed}';links.append(f'[HTML]({b}/visualization/loan-merm.html) · [.req]({b}/visualization/loan.req) · [JSON]({b}/run.json)')
 lines.append('|'+str(seed)+'|'+'|'.join(links)+'|')
lines+=['','[三组详细报告](LOAN/report/ablation-analysis.md) · [机器汇总](LOAN/report/results.json) · [逐次结果](LOAN/report/runs.csv) · [兼容检查](LOAN/shared/compatibility.json) · [冻结协议](LOAN/shared/protocol.json) · [更新前汇总备份](LOAN/summary-before-loan.md)','','三组详细报告仅统计本轮新增运行，本汇总通过独立证据副本补入Full。不改既有CoCoME、Library、ATM及其ED。']
ed['ranking']=ranks['ED'];write(OUT/'report/ed-results.json',ed)
with (OUT/'report/ed-per-run.csv').open('w',newline='') as f:
 fields=['case','arm','method','seed',*METRICS,*['z_'+k for k in METRICS],'ED','source','sourceSha256'];w=csv.DictWriter(f,fields);w.writeheader()
 for x in rows:w.writerow(dict(case='LOAN',arm=x['arm'],method=x['method'],seed=x['seed'],**{k:x[k] for k in METRICS},**{'z_'+k:v for k,v in x['normalized'].items()},ED=x['ED'],source=x['source'],sourceSha256=x['sourceSha256']))
write(OUT/'summary-data.json',dict(groups=stats,rankings=ranks,attachmentMeans=attachment,fullSource=str(FULL),sourceSummary=str(ATTACH)))
updated=master.replace('更新日期：2026-11-13。收录 CoCoME、Library 和 ATM','更新日期：2026-11-14。收录 CoCoME、Library、ATM 和 LOAN',1).replace('不能混用两个案例的归一化或指标版本','不能混用不同案例的归一化或指标版本',1).rstrip()+'\n\n'+'\n'.join(lines)+'\n';assert sha(MASTER)==master_sha;MASTER.write_text(updated)
links=re.findall(r'\]\(([^)]+)\)',updated);assert all((DEST/l).exists() for l in links)
for pat in ['*.req','*.html','*-usecases.svg','*-domain.svg']:assert len(list((OUT/'arms').glob('*/*/visualization/'+pat)))==30
index={str(f.relative_to(DEST)):sha(f) for f in OUT.rglob('*') if f.is_file()}
for f in SRC.rglob('*'):
 if f.is_file():assert sha(f)==sha(OUT/f.relative_to(SRC))
write(OUT/'copy-manifest.json',dict(source=str(SRC),destination=str(OUT),sourceSummaryBeforeSha256=master_sha,summaryAfterSha256=sha(MASTER),copiedFiles=len(index),sha256=index))
print(json.dumps(dict(status='success',output=str(OUT),summary=str(MASTER),copiedFiles=len(index),linksVerified=len(links),ED={a:stats[a]['ED'] for a in LABELS}),ensure_ascii=False))
