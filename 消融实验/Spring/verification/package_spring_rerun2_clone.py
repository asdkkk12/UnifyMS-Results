# -*- coding: utf-8 -*-
import csv,hashlib,json,math,re,shutil,statistics,ctypes,os
from pathlib import Path
ROOT=Path('/Users/yuanyaowu/Desktop/实验室材料/UnifyMs/UnifyMS代码')
SRC=ROOT/'output/spring-ablation-20261114-rerun2';DEST=Path('/Users/yuanyaowu/Desktop/消融实验');OUT=DEST/'Spring';MASTER=DEST/'汇总Case.md';FULL=Path('/Users/yuanyaowu/Desktop/输出/Spring/unifyms');ATTACH=Path('/Users/yuanyaowu/Desktop/输出/汇总Case.md.md')
SEEDS=[101,103,107,109,113,127,131,137,139,149];METRICS=['IFN','CHD','Instability','UCM','CMQ'];KEYS=['MS_Num',*METRICS,'HV'];LABELS={'full':'Full：完整方法','without-offline':'−O：无离线选参','without-probability':'−P：无动态概率','without-guidance':'−G：无候选引导'}
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
# Preserve any interrupted copy, then create independent APFS copy-on-write clones.
libc=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
libc.clonefile.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint32]
libc.clonefile.restype=ctypes.c_int

def clone_tree(src,dst):
 src=Path(src);dst=Path(dst);dst.mkdir()
 for old in src.rglob('*'):
  new=dst/old.relative_to(src)
  if old.is_dir():new.mkdir(exist_ok=True)
  elif old.is_file():
   new.parent.mkdir(parents=True,exist_ok=True)
   if libc.clonefile(os.fsencode(old),os.fsencode(new),0)!=0:raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()),str(new))
 return dst
interrupted=DEST/'Spring-copy-interrupted-20261114'
assert not interrupted.exists()
if OUT.exists():OUT.rename(interrupted)
assert read(SRC/'study-status.json')['status']=='success' and not OUT.exists()
master=MASTER.read_text();master_sha=sha(MASTER);assert master.count('\n## Spring\n')==1;old_section='## Spring\n'+master.split('\n## Spring\n',1)[1];assert '\n## ' not in old_section[3:]
r=read(SRC/'report/results.json');protocol=read(SRC/'shared/protocol.json');fs=read(FULL/'report/ten-run-summary.json');assert len(r['runs'])==30
assert fs['inputHash']==protocol['inputHash'] and fs['metricVersion']==protocol['metricVersion'] and fs['seeds']==SEEDS and fs['offlineChoice']=='C3'
assert read(FULL/'experiment/Spring/calibration.json')==read(SRC/'shared/calibration.json') and read(FULL/'model-snapshot.json')==read(SRC/'shared/model-snapshot.json')
assert read(FULL/'run-config.json')==read(SRC/'shared/run-config.json') and protocol['historicalParser']=='filtered-comment-reader-v1'
s=ATTACH.read_text();section='## 10. Spring'+s.split('## 10. Spring',1)[1].split('\n## ',1)[0];line=next(x for x in section.splitlines() if x.startswith('| UnifyMS + LLM + JEV'));attachment=dict(zip(KEYS[:-1],map(float,[x.strip() for x in line.split('|')[2:-1]])))
rows=[];fullfiles=[]
for arm in LABELS:
 for seed in SEEDS:
  f=FULL/'experiment/Spring/online-jev/guidance-jev'/f'run-jev-{seed}.json' if arm=='full' else SRC/'arms'/arm/f'seed-{seed}'/'run.json'
  x=read(f);run=x['run'];rep=x['representative'];c=run['config'];assert run['status']=='success' and rep['valid'] and run['inputHash']==protocol['inputHash'] and run['metricVersion']==protocol['metricVersion']
  expected=('C0',200,100,.7,.5) if arm=='without-offline' else ('C3',200,100,.5,.25)
  assert c['seed']==seed and run['completedGenerations']==expected[2] and tuple(c[k] for k in ['id','populationSize','generations','crossoverProbability','crossP'])==expected
  m=rep['metrics'];rows.append(dict(arm=arm,method=LABELS[arm],seed=seed,MS_Num=rep['serviceCount'],IFN=m[0],CHD=m[1],CMQ=m[2],Instability=m[3],UCM=m[4],HV=x['hv'],source=f'Spring/full-reference/run-full-{seed}.json' if arm=='full' else 'Spring/'+str(f.relative_to(SRC)),sourceSha256=sha(f)))
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
(SRC/'summary-before-spring.md').write_bytes(MASTER.read_bytes());clone_tree(SRC,OUT);clone_tree(ROOT/'output/spring-ablation-20261114',OUT/'previous-run-20261114');ref=OUT/'full-reference';ref.mkdir()
for p,name in [(ATTACH,'汇总Case来源.md.md'),(FULL/'report/ten-run-summary.json','ten-run-summary.json'),(FULL/'run-config.json','run-config.json'),(FULL/'experiment/Spring/calibration.json','calibration.json'),(FULL/'experiment/Spring/selection-jev.json','selection-jev.json')]:shutil.copy2(p,ref/name)
(ref/'Spring附件节选.md').write_text(section+'\n')
for f,seed in zip(fullfiles,SEEDS):shutil.copy2(f,ref/f'run-full-{seed}.json')
write(ref/'verified-full-results.json',dict(source=str(FULL),sourceAttachment=str(ATTACH),attachmentMeans=attachment,verifiedStatistics=stats['full'],runs=[x for x in rows if x['arm']=='full'],compatibility=dict(input=True,metricVersion=True,calibration=True,normalization=True,parserSnapshot=True,seeds=True,initialConfig='C3'),discrepancies=[]))
ed=dict(case='Spring',metric='ED',better='lower',normalization='shared min-max across all 40 per-run representatives in this case',metricOrder=METRICS,ideal=[0,1,1,1,1],weights=[1]*5,zeroSpanPolicy='zero distance contribution',metricVersion=protocol['metricVersion'],inputHash=protocol['inputHash'],sampleCount=40,seeds=SEEDS,bounds=bounds,groups={a:dict(method=LABELS[a],n=10,**stats[a]['ED']) for a in LABELS},runs=[dict(case='Spring',arm=x['arm'],method=x['method'],seed=x['seed'],metrics={k:x[k] for k in METRICS},normalized=x['normalized'],squaredContributions=x['squaredContributions'],ED=x['ED'],source=x['source'],sourceSha256=x['sourceSha256']) for x in rows])
lines=['## Spring','','### 分组与冻结协议','','输入为 `/Users/yuanyaowu/Desktop/输出/Spring/input/Spring.remodel`，与历史 Full 哈希相同；767份 Java 源码、1份Mapper XML与54份POM已逐项匹配并保存于 provenance/source-java。指标版本 `paper-ieee-eq5-21-v2-isolated-zero`，IFN ↓，其余四项 ↑；无接口服务 Instability=0。每 10 代观察，末代不调用，候选损失门槛 0.5。','','|组别|离线选参|动态概率|LLM 生成＋JEV 优选|起始配置|次数|','|---|---|---|---|---|---:|','|Full|历史 JEV 选择 C3|开启|开启|C3：N200/G100/p_var0.5/crossP0.25|10（历史）|','|−O|关闭|开启|开启|C0：N200/G100/p_var0.7/crossP0.5|10（本轮）|','|−P|复用历史 C3|关闭，固定0.5|开启|C3|10（本轮）|','|−G|复用历史 C3|开启|关闭|C3|10（本轮）|','','本轮只新跑三组共30次；Full 从既有输出汇总的 Spring 节导入，并用十次原始 JSON 和机器汇总核验，不重新运行 Full 或离线 JEV。种子：'+', '.join(map(str,SEEDS))+'。各组均N200/G100，实际评价与额外候选开销分别记录；不声称严格等评价预算，不将C0与C3之差解释为单变量超参数效应。','','历史950条校准方案、六组校准搜索、冻结归一化及HV、360个生成任务、35个候选Choice请求、90个概率请求均通过兼容核查。采用历史 candidate-consistency-choice-v2-compact 紧凑请求与24000字节上限，模型、提示词和实现身份见协议及兼容检查。','','### 完整方法来源','','[既有汇总来源](Spring/full-reference/汇总Case来源.md.md) · [Spring 节选](Spring/full-reference/Spring附件节选.md) · [十次机器汇总](Spring/full-reference/ten-run-summary.json) · [逐次核验](Spring/full-reference/verified-full-results.json)','','本节为重新执行的30次消融，替换上一批Spring数值。上一批工作区完整结果保存在Spring/previous-run-20261114，更新前汇总另有备份。本案例复用Java AST中间模型：66个服务实现类用例代理、359个操作、58个实体、14个模块actor；原项目是既有微服务重分组，不当作单体恢复或人工需求实验。[源码身份核验](Spring/provenance/verification.json)。本节采用既有 `/Users/yuanyaowu/Desktop/输出/汇总Case.md.md` 中完整方法结果；五指标与原始十次 JSON 一致。','','### 五指标对比（十次均值，含 ED）','','|方法|MS_Num|IFN ↓|CHD ↑|Instability ↑|UCM ↑|CMQ ↑|ED ↓|','|---|---:|---:|---:|---:|---:|---:|---:|']
for arm in LABELS:lines.append('|'+LABELS[arm]+'|'+'|'.join(f'{stats[arm][k]["mean"]:.6f}' for k in [*KEYS[:-1],'ED'])+'|')
lines+=['','ED 使用四组40次代表方案共同Min–Max区间，逐次计算到理想点 `(0,1,1,1,1)` 的等权欧式距离，再取十次均值；不是对五指标均值求距离。零跨度维度不参与。本轮使用新三组与历史Full重新建立共同区间；Full原始五指标不变，其ED可能不同于上一批。','','归一化范围：'+'；'.join(f"{k} [{bounds[k]['min']:.6f}, {bounds[k]['max']:.6f}]" for k in METRICS)+'。','','[逐次 ED JSON](Spring/report/ed-results.json) · [逐次 ED CSV](Spring/report/ed-per-run.csv)','','### 五指标排序（含 ED）','','|指标|方向|由好到差（十次均值）|均值最优组|','|---|---|---|---|']
for k in [*METRICS,'ED']:
 desc,best=rank(k);lines.append('|'+k+'|'+('越小越好 ↓' if k in ['IFN','ED'] else '越大越好 ↑')+'|'+desc+'|'+best+'|')
lines+=['','相同均值并列，不代表统计显著性；Case 内归一化的 ED 不与其他案例直接比较。','','### 均值、样本标准差与 HV','','每项为均值 ± 样本标准差（n=10，分母 n−1）；五指标/ED对应代表方案，HV对应完整前沿。','','|方法|MS_Num|IFN|CHD|Instability|UCM|CMQ|HV ↑|ED ↓|','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for arm in LABELS:lines.append('|'+LABELS[arm]+'|'+'|'.join(f'{stats[arm][k]["mean"]:.6f} ± {stats[arm][k]["sampleStd"]:.6f}' for k in [*KEYS,'ED'])+'|')
desc,_=rank('HV');lines+=['','HV排序：'+desc+'。','','### 实际执行与输出','','|组别|实际评价合计|额外候选评价|入选|下一代留存|概率 JEV 请求|生成 LLM 请求|候选 JEV 请求|','|---|---:|---:|---:|---:|---:|---:|---:|']
for arm in list(LABELS)[1:]:
 sub=[x for x in r['runs'] if x['arm']==arm];counts={m:sum(x['requests'] for x in r['moduleStatistics'] if x['arm']==arm and x['module']==m) for m in ['probability-JEV','generation-LLM','candidate-JEV']}
 lines.append('|'+LABELS[arm]+'|'+'|'.join(str(v) for v in [sum(x['evaluations'] for x in sub),sum(x['candidateEvaluations'] for x in sub),sum(x['selected'] for x in sub),sum(x['retained'] for x in sub),*counts.values()])+'|')
lines+=['','### 调用失败统计','','按实际响应记录调用失败，具体原因见失败分类文件。保持冻结完整请求协议，未重试或切换紧凑版本；失败不算成功 KEEP，原搜索继续。','','|组别|模块|请求|失败|','|---|---|---:|---:|']
for arm in list(LABELS)[1:]:
 for module in ['probability-JEV','generation-LLM','candidate-JEV']:
  part=[x for x in r['moduleStatistics'] if x['arm']==arm and x['module']==module];lines.append('|'+LABELS[arm]+'|'+module+'|'+str(sum(x['requests'] for x in part))+'|'+str(sum(x['failures'] for x in part))+'|')
lines+=['','评价计数包含重复种群评价；模型请求失败、成功KEEP与实际入选分别记录。tokens未知时不当作0。分模块时间与输入tokens见[调用统计](Spring/report/module-statistics.csv)，失败见[失败分类](Spring/report/call-failures.json)。','','每个种子保存完整种群、前沿、代表方案和审计；`visualization/Spring.req` 为拆分模型，`Spring-merm.html` 可直接在浏览器打开，`Spring-usecases.svg`、`Spring-domain.svg` 为两类拆分图。共30套。','','|种子|−O|−P|−G|','|---:|---|---|---|']
for seed in SEEDS:
 links=[]
 for arm in list(LABELS)[1:]:
  b=f'Spring/arms/{arm}/seed-{seed}';links.append(f'[HTML]({b}/visualization/Spring-merm.html) · [.req]({b}/visualization/Spring.req) · [JSON]({b}/run.json)')
 lines.append('|'+str(seed)+'|'+'|'.join(links)+'|')
lines+=['','[三组详细报告](Spring/report/ablation-analysis.md) · [机器汇总](Spring/report/results.json) · [逐次结果](Spring/report/runs.csv) · [兼容检查](Spring/shared/compatibility.json) · [冻结协议](Spring/shared/protocol.json) · [更新前汇总备份](Spring/summary-before-spring.md)','','三组详细报告仅统计本轮新增运行，本汇总通过独立证据副本补入Full。不改既有CoCoME、Library、ATM、LOAN、java-online-taxi、light-reading、PiggyMetrics及其ED。']
ed['ranking']=ranks['ED'];write(OUT/'report/ed-results.json',ed)
with (OUT/'report/ed-per-run.csv').open('w',newline='') as f:
 fields=['case','arm','method','seed',*METRICS,*['z_'+k for k in METRICS],'ED','source','sourceSha256'];w=csv.DictWriter(f,fields);w.writeheader()
 for x in rows:w.writerow(dict(case='Spring',arm=x['arm'],method=x['method'],seed=x['seed'],**{k:x[k] for k in METRICS},**{'z_'+k:v for k,v in x['normalized'].items()},ED=x['ED'],source=x['source'],sourceSha256=x['sourceSha256']))
write(OUT/'summary-data.json',dict(groups=stats,rankings=ranks,attachmentMeans=attachment,fullSource=str(FULL),sourceSummary=str(ATTACH)))
updated=master.split('\n## Spring\n',1)[0].replace('收录 CoCoME、Library、ATM、LOAN、java-online-taxi、light-reading 和 PiggyMetrics','收录 CoCoME、Library、ATM、LOAN、java-online-taxi、light-reading、PiggyMetrics 和 Spring',1).rstrip()+'\n\n'+'\n'.join(lines)+'\n';assert sha(MASTER)==master_sha;MASTER.write_text(updated)
links=re.findall(r'\]\(([^)]+)\)',updated);assert all((DEST/l).exists() for l in links)
for pat in ['*.req','*.html','*-usecases.svg','*-domain.svg']:assert len(list((OUT/'arms').glob('*/*/visualization/'+pat)))==30
index={str(f.relative_to(DEST)):sha(f) for f in OUT.rglob('*') if f.is_file()}
for f in SRC.rglob('*'):
 if f.is_file():assert sha(f)==sha(OUT/f.relative_to(SRC))
write(OUT/'copy-manifest.json',dict(source=str(SRC),destination=str(OUT),sourceSummaryBeforeSha256=master_sha,summaryAfterSha256=sha(MASTER),copiedFiles=len(index),copyMethod='APFS clonefile copy-on-write independent clones',interruptedCopyPreserved=str(interrupted),sha256=index))
print(json.dumps(dict(status='success',output=str(OUT),summary=str(MASTER),copiedFiles=len(index),linksVerified=len(links),ED={a:stats[a]['ED'] for a in LABELS}),ensure_ascii=False))
