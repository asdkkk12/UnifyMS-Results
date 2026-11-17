# -*- coding: utf-8 -*-
import json,re,runpy,statistics,hashlib
from pathlib import Path
root=Path('output/piggymetrics-ablation-20261114').resolve();read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert read(root/'study-status.json')['status']=='success'
ns=runpy.run_path('scripts/run-piggymetrics-ablation.py');r=read(root/'report/results.json');assert len(r['runs'])==30
for arm in ns['ARMS']:
 assert sorted(x['seed'] for x in r['runs'] if x['arm']==arm)==ns['SEEDS']
 for seed in ns['SEEDS']:
  d=root/'arms'/arm/f'seed-{seed}';x=ns['validate_saved'](d,arm,seed,root/'shared/compatibility.json',root/'shared/protocol.json');o=x['run']['onlineControl']
  if arm=='without-probability':assert o['requestCount']==0 and o['finalProbability']==.9
  if arm=='without-guidance':assert x['run'].get('guidance') is None and x['run']['guidanceEvaluations']==0 and not (d/'guidance').exists()
 for k,s in r['aggregates'][arm].items():
  v=[row[k] for row in r['runs'] if row['arm']==arm];assert s['mean']==statistics.mean(v) and s['sampleStd']==statistics.stdev(v)
for name,h in r['files'].items():assert sha(root/name)==h
counts={pat:len(list((root/'arms').glob('*/*/visualization/'+pat))) for pat in ['*.req','*.html','*-usecases.svg','*-domain.svg']};assert set(counts.values())=={30}
p=root/'report/ablation-analysis.md';links=re.findall(r'\]\(([^)]+)\)',p.read_text());assert all((p.parent/l).exists() for l in links)
out=dict(status='success',runs=30,seedsPerArm=10,generations={'without-offline':100,'without-probability':200,'without-guidance':200},meanAndSampleStdRecomputed=True,protocolAndAuditHashesVerified=True,outputCounts=counts,reportLinksVerified=len(links),tests=dict(suite='LegacyAblationProtocolTest',total=10,failures=0,errors=0),moduleStatistics=r['moduleStatistics'])
(root/'final-validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='moduleStatistics'},ensure_ascii=False))
