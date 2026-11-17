#!/usr/bin/env python3
import argparse,json,collections
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);a=p.parse_args();b=a.base;x=json.loads((b/'input/extraction.json').read_text());result=json.loads((b/'servicecutter/solver_result.json').read_text());parts=result['services'];responsibility=result.get('useCaseResponsibility',{});fallback=max(range(len(parts)),key=lambda i:len(parts[i]['nanoentities']));assigned=collections.defaultdict(list);fallback_services=[]
for symbol in x['services'].values():
 choices=[i for i,row in enumerate(parts) if symbol in responsibility.get(row['name'],[])]
 if not choices:target=fallback;fallback_services.append(symbol)
 else:target=max(choices,key=lambda i:len(parts[i]['nanoentities']))
 assigned[target].append(symbol)
votes=collections.defaultdict(collections.Counter)
for i,row in enumerate(parts):
 for n in row['nanoentities']:votes[n.split('.',1)[0]][i]+=1
owners={e:max(v,key=v.get) for e,v in votes.items()};clusters=[]
for i,row in enumerate(parts):
 clusters.append({'name':row['name'],'members':['PiggyMetrics.service.'+s for s in sorted(assigned[i])]+['PiggyMetrics.domain.'+e for e in sorted(owners) if owners[e]==i],'servicecutter_nanoentities':row['nanoentities']})
out={'method':'ServiceCutter official Chinese Whispers + Java AST bridge','is_official_servicecutter':True,'source_solver_result':str(b/'servicecutter/solver_result.json'),'mapping_assumptions':['Native use-case responsibilities map directly to Java @Service proxy IDs, then to that class public methods.','A class remains one input unit, matching MicroMiner/MonoEmbed class granularity.','Use-case proxies lacking native responsibility fall back to the largest nanoentity cluster; their list is explicit.','Entity ownership uses the majority of its actual fields; no native field partition is changed.'],'fallback_cluster':fallback,'fallback_services':fallback_services,'clusters':clusters};(b/'servicecutter/decomposition.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'clusters':len(parts),'fallback_services':len(fallback_services),'assigned_classes':[len(assigned[i]) for i in range(len(parts))]},ensure_ascii=False))
