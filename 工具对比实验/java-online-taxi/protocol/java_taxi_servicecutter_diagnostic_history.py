#!/usr/bin/env python3
"""Feed AST-resolved use cases to the unmodified official Service Cutter Engine."""
import json,shutil,sys
from pathlib import Path
import run_java_taxi_comparison as r
b=r.DEFAULT;d=b/'servicecutter';backup=b/'servicecutter_initial_generic'
if not backup.exists():shutil.copytree(d,backup,ignore=shutil.ignore_patterns('._*'))
x=r.read(b/'input/extraction.json');model=r.read(d/'input/servicecutter_model.json');fields={e['name']:[e['name']+'.'+n for n in e['nanoentities']] for e in model['entities']};uses=[]
for uc in x['services'].values():
 refs=sorted({e for o in x['operations'] if o['service']==uc for e in o['entities']})
 if refs:uses.append({'name':uc,'nanoentitiesRead':[n for e in refs for n in fields[e]],'nanoentitiesWritten':[]})
reps={'useCases':uses,'compatibilities':{},'sharedOwnerGroups':[]}
r.write(d/'input/servicecutter_user_representations.json',reps)
r.write(d/'input/java_mapping_manifest.json',{'source':'input/extraction.json','nonempty_usecases':len(uses),'omitted_stateless_usecases':x['zero_entity_services'],'policy':'AST class-to-entity reachability; entity-level access expanded conservatively to all its fields. No fabricated sentinel entity, guessed foreign keys or ownership constraints.'})
record=d/'java_engine_completed.json'
if not record.exists():
 s=r.post(b,'servicecutter_java_import','http://127.0.0.1:18081/engine/import',model);sid=s['id'];r.post(b,'servicecutter_java_representations',f'http://127.0.0.1:18081/engine/import/{sid}/userrepresentations/',reps);result=r.post(b,'servicecutter_java_solver',f'http://127.0.0.1:18081/engine/solver/{sid}',r.read(d/'input/solver_config.json'));r.write(d/'solver_result.json',result);r.write(record,{'complete':True,'actual_clusters':len(result['services'])})
r.command(b,'servicecutter_java_bridge',[sys.executable,r.CUTTER/'tools/servicecutter_result_to_metrics_input.py','--model',b/'input/java-online-taxi.remodel','--solver-result',d/'solver_result.json','--output',d/'decomposition.json'])
r.command(b,'servicecutter_java_metrics',[sys.executable,r.MONO/'tools/compute_airms_metrics.py','--app','JavaOnlineTaxi','--model',b/'input/java-online-taxi.remodel','--decomposition',d/'decomposition.json','--output',d/'metrics.json'])
print('AST usecases',len(uses),'actual clusters',r.read(d/'metrics.json')['MS_Num'])
# A divisive algorithm cannot attain fewer clusters than its positive-score components.
alln=[n for ns in fields.values() for n in ns];parents={n:n for n in alln}
def find(n):
 while parents[n]!=n:n=parents[n]
 return n
for group in list(fields.values())+[uc['nanoentitiesRead'] for uc in uses]:
 for n in group[1:]:parents[find(n)]=find(group[0])
components={}
for n in alln:components.setdefault(find(n),[]).append(n)
target=max(5,len(components));r.write(d/'input/positive_score_components.json',{'components':list(components.values()),'component_count':len(components),'requested_default':5,'effective_target':target,'policy':'max(default 5, positive-score connected components); no quality-based selection','source_of_edges':'Identity & Lifecycle per imported entity; Semantic Proximity for entity-level AST use-case co-access; no guessed foreign keys or owners.'})
if target>5:
 diagnostic=b/'servicecutter_unreachable_target5'
 if not diagnostic.exists():shutil.copytree(d,diagnostic,ignore=shutil.ignore_patterns('._*'))
 cfg=r.read(d/'input/solver_config.json');cfg['algorithmParams']['numberOfClusters']=target;r.write(d/'input/solver_config.json',cfg)
 complete=d/'java_engine_feasible_completed.json'
 if not complete.exists():
  s=r.post(b,'servicecutter_feasible_import','http://127.0.0.1:18081/engine/import',model);sid=s['id'];r.post(b,'servicecutter_feasible_representations',f'http://127.0.0.1:18081/engine/import/{sid}/userrepresentations/',reps);result=r.post(b,'servicecutter_feasible_solver',f'http://127.0.0.1:18081/engine/solver/{sid}',cfg);r.write(d/'solver_result.json',result);r.write(complete,{'complete':True,'requested_clusters':target,'actual_clusters':len(result['services'])})
 r.command(b,'servicecutter_feasible_bridge',[sys.executable,r.CUTTER/'tools/servicecutter_result_to_metrics_input.py','--model',b/'input/java-online-taxi.remodel','--solver-result',d/'solver_result.json','--output',d/'decomposition.json'])
 r.command(b,'servicecutter_feasible_metrics',[sys.executable,r.MONO/'tools/compute_airms_metrics.py','--app','JavaOnlineTaxi','--model',b/'input/java-online-taxi.remodel','--decomposition',d/'decomposition.json','--output',d/'metrics.json'])
 print('feasible target',target,'actual clusters',r.read(d/'metrics.json')['MS_Num'])
# Native non-K clustering on the actual Java fields, avoiding the GN disconnected-graph degeneration.
rawdiag=b/'servicecutter_gn_target7'
if not rawdiag.exists():shutil.copytree(d,rawdiag,ignore=shutil.ignore_patterns('._*'))
model={'name':'JAVA_ONLINE_TAXI_AST','entities':[{'name':e['entity'],'nanoentities':[f['name'] for f in e['fields']]} for e in x['entities']],'relations':[]}
fields={e['name']:[e['name']+'.'+n for n in e['nanoentities']] for e in model['entities']};uses=[]
for uc in x['services'].values():
 refs=sorted({e for o in x['operations'] if o['service']==uc for e in o['entities']})
 if refs:uses.append({'name':uc,'nanoentitiesRead':[n for e in refs for n in fields[e]],'nanoentitiesWritten':[]})
reps={'useCases':uses,'compatibilities':{},'sharedOwnerGroups':[]};cfg={'algorithm':'Chinese Whispers','algorithmParams':{'cwNodeWeighting':0},'priorities':{'Identity & Lifecycle Commonality':1.0,'Semantic Proximity':1.0,'Shared Owner':1.0}}
r.write(d/'input/servicecutter_model.json',model);r.write(d/'input/servicecutter_user_representations.json',reps);r.write(d/'input/solver_config.json',cfg)
r.write(d/'input/java_mapping_manifest.json',{'source':'input/extraction.json','native_algorithm':'Chinese Whispers','cwNodeWeighting':0,'actual_java_fields':sum(len(e['nanoentities']) for e in model['entities']),'nonempty_usecases':len(uses),'omitted_stateless_usecases':x['zero_entity_services'],'policy':'Actual Java field names only; entity-level AST reachability expanded to all fields as conservative co-access. No invented type-token attributes, sentinel references, guessed foreign keys or owner groups. Chinese Whispers selected for non-K disconnected graph handling; one native run, no quality-based selection. Prior GN diagnostic attempts retained.'})
complete=d/'java_engine_cw_completed.json'
if not complete.exists():
 s=r.post(b,'servicecutter_cw_import','http://127.0.0.1:18081/engine/import',model);sid=s['id'];r.post(b,'servicecutter_cw_representations',f'http://127.0.0.1:18081/engine/import/{sid}/userrepresentations/',reps);result=r.post(b,'servicecutter_cw_solver',f'http://127.0.0.1:18081/engine/solver/{sid}',cfg);r.write(d/'solver_result.json',result);r.write(complete,{'complete':True,'algorithm':'Chinese Whispers','actual_clusters':len(result['services'])})
r.command(b,'servicecutter_cw_bridge',[sys.executable,r.CUTTER/'tools/servicecutter_result_to_metrics_input.py','--model',b/'input/java-online-taxi.remodel','--solver-result',d/'solver_result.json','--output',d/'decomposition.json'])
r.command(b,'servicecutter_cw_metrics',[sys.executable,r.MONO/'tools/compute_airms_metrics.py','--app','JavaOnlineTaxi','--model',b/'input/java-online-taxi.remodel','--decomposition',d/'decomposition.json','--output',d/'metrics.json'])
print('native CW actual Java-field clusters',r.read(d/'metrics.json')['MS_Num'])
