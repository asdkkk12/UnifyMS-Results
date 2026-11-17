#!/usr/bin/env python3
"""Official Chinese Whispers on Java AST fields and entity-level co-access."""
import json,sys
from pathlib import Path
import run_piggy_metrics_comparison as r
b=r.DEFAULT;d=b/'servicecutter';x=r.read(b/'input/extraction.json')
model={'name':'PIGGY_METRICS_AST','entities':[{'name':e['entity'],'nanoentities':[f['name'] for f in e['fields']]} for e in x['entities']],'relations':[{'origin':e['entity'],'destination':ref,'type':'AGGREGATION'} for e in x['entities'] for ref in sorted({r for f in e['fields'] for r in f.get('entity_references',[])})]}
fields={e['name']:[e['name']+'.'+n for n in e['nanoentities']] for e in model['entities']};uses=[]
for uc in x['services'].values():
 refs=sorted({e for o in x['operations'] if o['service']==uc for e in o['entities']})
 if refs:uses.append({'name':uc,'nanoentitiesRead':[n for e in refs for n in fields[e]],'nanoentitiesWritten':[]})
reps={'useCases':uses,'compatibilities':{},'sharedOwnerGroups':[]};cfg={'algorithm':'Chinese Whispers','algorithmParams':{'cwNodeWeighting':0},'priorities':{'Identity & Lifecycle Commonality':1.0,'Semantic Proximity':1.0,'Shared Owner':1.0}}
r.write(d/'input/servicecutter_model.json',model);r.write(d/'input/servicecutter_user_representations.json',reps);r.write(d/'input/solver_config.json',cfg)
r.write(d/'input/servicecutter_conversion_manifest.json',{'source':'../../input/extraction.json','adapter':'piggy_metrics_servicecutter.py','model':'servicecutter_model.json','user_representations':'servicecutter_user_representations.json','counts':{'entities':len(model['entities']),'actual_fields':sum(len(e['nanoentities']) for e in model['entities']),'nonempty_usecases':len(uses)},'policy':'Actual Java AST fields and conservative entity-level co-access; no sentinel, inferred owner or guessed foreign key.','supersedes_generic_manifest':True})
r.write(d/'input/java_mapping_manifest.json',{'source':'input/extraction.json','native_algorithm':'Chinese Whispers','cwNodeWeighting':0,'actual_java_fields':sum(len(e['nanoentities']) for e in model['entities']),'nonempty_usecases':len(uses),'omitted_stateless_usecases':x['zero_entity_services'],'policy':'Actual Java field names only; entity-level AST reachability expanded to all fields as conservative co-access. No invented type-token attributes, sentinel references, guessed foreign keys or owner groups. Chinese Whispers selected for non-K disconnected graph handling; one native run, no quality-based selection. Native Chinese Whispers is fixed before this case; no clustering-quality-based algorithm selection.'})
complete=d/'java_engine_cw_completed.json'
if not complete.exists():
 s=r.post(b,'servicecutter_cw_import','http://127.0.0.1:18081/engine/import',model);sid=s['id'];r.post(b,'servicecutter_cw_representations',f'http://127.0.0.1:18081/engine/import/{sid}/userrepresentations/',reps);result=r.post(b,'servicecutter_cw_solver',f'http://127.0.0.1:18081/engine/solver/{sid}',cfg);r.write(d/'solver_result.json',result);r.write(complete,{'complete':True,'algorithm':'Chinese Whispers','actual_clusters':len(result['services'])})
r.command(b,'servicecutter_cw_java_bridge',[sys.executable,r.ROOT/'tools/piggy_metrics_servicecutter_bridge.py','--base',b])
r.command(b,'servicecutter_cw_java_metrics',[sys.executable,r.MONO/'tools/compute_airms_metrics.py','--app','PiggyMetrics','--model',b/'input/PiggyMetrics.remodel','--decomposition',d/'decomposition.json','--output',d/'metrics.json'])
print('native CW actual Java-field clusters',r.read(d/'metrics.json')['MS_Num'])
