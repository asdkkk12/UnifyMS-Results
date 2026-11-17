#!/usr/bin/env python3
"""Library experiment phases with retained outputs, frozen JEV selection and 10 seeds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MONO = ROOT.parent / 'MonoEmbed-EMSE25-RP'
CUTTER = ROOT.parent / 'service cutter' / 'ServiceCutter'
DEFAULT = ROOT / 'runs/library_20261103_01'
SEEDS = [101,103,107,109,113,127,131,137,139,149]
METRICS = ['IFN','CHD','Instability','UCM','CMQ']


def read(p):
    return json.loads(Path(p).read_text())


def write(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')


def command(base,label,argv,cwd=None):
    log=base/'logs'/label;log.parent.mkdir(parents=True,exist_ok=True)
    status=log.with_suffix('.json')
    if status.exists() and read(status).get('returncode')==0:
        print('reuse stage '+label,flush=True);return
    start=time.perf_counter()
    write(status,dict(status='running',command=list(map(str,argv)),started_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()))
    env=dict(os.environ,PYTHONPATH=str(MONO/'tools'),PYTHONDONTWRITEBYTECODE='1',PYTHONHASHSEED='0')
    with log.with_suffix('.log').open('w') as stream:
        proc=subprocess.run(list(map(str,argv)),cwd=cwd or ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    write(status,dict(status='success' if proc.returncode==0 else 'failed',command=list(map(str,argv)),
                      returncode=proc.returncode,seconds=time.perf_counter()-start))
    print(label,proc.returncode,flush=True)
    if proc.returncode:raise RuntimeError(label+' failed; see '+str(log.with_suffix('.log')))


def java(base):
    runtime=base/'unifyms/runtime'
    return ['java','-cp',str(runtime/'target/classes')+os.pathsep+(runtime/'target/tuning-classpath.txt').read_text().strip()]


def cli_run(base,phase,*flags):
    command(base,'unifyms_'+phase+('_'+flags[-1] if flags else ''),java(base)+
            ['tuning.TuningCli',phase,str(base/'unifyms/run-config.json'),'--system','Library',*flags],base/'unifyms/runtime')


def evaluate(base,method):
    command(base,method+'_metrics',[sys.executable,MONO/'tools/compute_airms_metrics.py','--app','Library',
            '--model',base/'input/library.remodel','--decomposition',base/method/'decomposition.json',
            '--output',base/method/'metrics.json'])


def baselines(base):
    model=base/'input/library.remodel'
    command(base,'microminer_conversion',[sys.executable,ROOT/'tools/remodel_to_microminer_input.py',
            '--model',model,'--output',base/'microminer/input','--app','Library'])
    command(base,'microminer_decomposition',[sys.executable,MONO/'tools/microminer_remodel_decompose.py',
            '--app','Library','--model',base/'microminer/input/library.remodel','--output',base/'microminer/decomposition.json',
            '--membership-threshold','0.70'])
    evaluate(base,'microminer')
    command(base,'monoembed_conversion',[sys.executable,MONO/'tools/remodel_to_monoembed.py',model,base/'monoembed/input','--app','Library'])
    command(base,'servicecutter_conversion',[sys.executable,CUTTER/'tools/remodel_to_servicecutter.py',model,'--out-dir',base/'servicecutter/input'])
    write(base/'servicecutter/input/solver_config.json',{'algorithm':'Girvan-Newman','algorithmParams':{'numberOfClusters':5},
          'priorities':{'Identity & Lifecycle Commonality':1.0,'Semantic Proximity':1.0,'Shared Owner':1.0}})


def post(base,label,url,payload):
    start=time.perf_counter()
    request=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(request,timeout=300) as response:result=json.load(response)
    write(base/'logs'/f'{label}.json',dict(seconds=time.perf_counter()-start,status='success',url=url,response=result))
    return result


def service(base):
    inputs=base/'servicecutter/input';url='http://127.0.0.1:18081'
    result_path=base/'servicecutter/solver_result.json'
    if not result_path.exists():
        system=post(base,'servicecutter_import',url+'/engine/import',read(inputs/'servicecutter_model.json'))
        sid=system['id']
        post(base,'servicecutter_representations',f'{url}/engine/import/{sid}/userrepresentations/',read(inputs/'servicecutter_user_representations.json'))
        result=post(base,'servicecutter_solver',f'{url}/engine/solver/{sid}',read(inputs/'solver_config.json'))
        if not result.get('services'):raise RuntimeError('Engine returned no services')
        write(result_path,result)
    command(base,'servicecutter_bridge',[sys.executable,CUTTER/'tools/servicecutter_result_to_metrics_input.py',
            '--model',base/'input/library.remodel','--solver-result',result_path,'--output',base/'servicecutter/decomposition.json'])
    evaluate(base,'servicecutter')


def mono(base):
    command(base,'monoembed_decomposition',[MONO/'.venv-api/bin/python',MONO/'tools/api_decompose.py','--app','Library',
            '--input-dir',base/'monoembed/input','--output',base/'monoembed/decomposition.json','--refresh'])
    evaluate(base,'monoembed')


def unify(base):
    selection=read(base/'unifyms/experiment/Library/selection-jev.json')
    assert selection['status']=='success' and selection['mock'] is False
    assert len(selection['attempts'])==1,'Expected exactly one actual JEV request'
    cfg=selection['config']
    input_hash=selection['inputHash']
    rows=[]
    for seed in SEEDS:
        cli_run(base,'run','--seed',str(seed))
        path=base/f'unifyms/experiment/Library/run-jev-{seed}.json';d=read(path)
        for field in ['id','populationSize','generations','crossoverProbability','crossP']:
            assert d['run']['config'][field]==cfg[field]
        assert d['run']['config']['seed']==seed and d['run']['inputHash']==input_hash
        metrics=d['representative']['metrics']
        rows.append(dict(seed=seed,MS_Num=d['representative']['serviceCount'],
                    **dict(zip(['IFN','CHD','CMQ','Instability','UCM'],metrics))))
    write(base/'unifyms/summary.json',dict(selection=selection['choice'],config=cfg,runs=rows,
        mean={k:statistics.mean(row[k] for row in rows) for k in ['MS_Num']+METRICS},
        sample_std={k:statistics.stdev(row[k] for row in rows) for k in ['MS_Num']+METRICS},
        jev_requests=len(selection['attempts'])))
    # Keep a readable partition for every seed, independently of strict .req export.
    for row in rows:
        result=read(base/f'unifyms/experiment/Library/run-jev-{row["seed"]}.json')
        text=[f'# Library / seed {row["seed"]}', '', 'Metrics: `'+json.dumps(row)+'`', '',
              '| Service | Use cases | Entities | Required entity interfaces | Provided entity interfaces |',
              '|---|---|---|---|---|']
        for item in result['representative']['services']:
            text.append('| '+str(item['id'])+' | '+' | '.join(', '.join(item.get(k,[]))
                        for k in ['useCases','entities','requiredEntityInterfaces','providedEntityInterfaces'])+' |')
        target=base/f'unifyms/partitions/seed-{row["seed"]}.md';target.parent.mkdir(exist_ok=True)
        target.write_text('\n'.join(text)+'\n')
    try:
        command(base,'unifyms_visualizations',[sys.executable,base/'unifyms/runtime/scripts/run-case.py','report',
                '--input',base/'input/library.remodel','--case','Library','--experiment',base/'unifyms/experiment',
                '--snapshot',base/'unifyms/model-snapshot.json','--test-seeds',','.join(map(str,SEEDS)),
                '--output',base/'unifyms/report'])
    except RuntimeError:
        # Do not bypass source/snapshot validation to fabricate a .req diagram.
        (base/'unifyms/report/analysis.md').write_text(
            '# Library 原生结果导出说明\n\n正式 10 次搜索及原生指标已完成；逐次 JSON 和可读划分见 ../experiment/Library 与 ../partitions。\n\n'
            '严格 .req 导出失败，具体原因见 ../../logs/unifyms_visualizations.log；未绕过校验，也未修改原生指标。\n')


def validate(base):
    sys.path.insert(0,str(MONO/'tools'))
    from compute_airms_metrics import parse_model
    services,entities,contracts,actors,ucs=parse_model(base/'input/library.remodel')
    expected={(s,o) for s,ops in services.items() for o in ops}
    checks={'source_sha256':hashlib.sha256((base/'input/library.remodel').read_bytes()).hexdigest(),
            'parsed_services':len(services),'parsed_entities':len(entities),'parsed_usecases':len(ucs),
            'declared_operations':len(expected),'methods':{}}
    for method in ['microminer','monoembed','servicecutter']:
        path=base/method/'decomposition.json'
        if not path.exists():continue
        d=read(path);m=read(base/method/'metrics.json');seen=[]
        for cluster in d['clusters']:
            for member in cluster['members']:
                if '.service.' in member:
                    service=member.rsplit('.',1)[-1]
                    seen.extend((service,op) for op in services.get(service,[]))
        assert set(seen)==expected and len(seen)==len(expected),(method,'operation coverage')
        assert abs(m['IFN']*m['MS_Num']-len(expected))<1e-8
        checks['methods'][method]={'operations_complete_unique':True,'MS_Num':m['MS_Num'],
                'provided_interface_distribution':[c['provided_interface'] for c in m['microservices']]}
        if method=='servicecutter':
            raw=read(base/'servicecutter/solver_result.json')
            model=read(base/'servicecutter/input/servicecutter_model.json')
            expected_nanos={e['name']+'.'+n for e in model['entities'] for n in e['nanoentities']}
            nanos=[n for part in raw['services'] for n in part['nanoentities']]
            assert set(nanos)==expected_nanos and len(nanos)==len(expected_nanos)
            checks['methods'][method].update(native_nanoentities_complete_unique=True,
                native_nanoentities=len(nanos),requested_clusters=5,actual_engine_clusters=len(raw['services']))
    summary=base/'unifyms/summary.json'
    if summary.exists():
        s=read(summary);assert len(s['runs'])==10 and s['jev_requests']==1
        snapshot=read(base/'unifyms/model-snapshot.json')
        uc_names=set(snapshot['useCaseNames'].values());en_names=set(snapshot['entityNames'].values())
        trial_checks=[]
        for row in s['runs']:
            result=read(base/f'unifyms/experiment/Library/run-jev-{row["seed"]}.json')
            run=result['run'];rep=result['representative'];parts=rep['services']
            assert run['status']=='success' and run['inputHash']==checks['source_sha256']
            assert run['config']['seed']==row['seed']
            for key in ['id','populationSize','generations','crossoverProbability','crossP']:
                assert run['config'][key]==s['config'][key]
            ucs=[uc for part in parts for uc in part['useCases']]
            ens=[en for part in parts for en in part['entities']]
            assert set(ucs)==uc_names and len(ucs)==len(uc_names)
            assert set(ens)==en_names and len(ens)==len(en_names)
            assert len(parts)==rep['serviceCount']
            required=[len(part['requiredEntityInterfaces']) for part in parts]
            provided=[len(part['providedEntityInterfaces']) for part in parts]
            ifn=sum(required+provided)/len(parts)
            instability=sum(1 if r==0 else p/(r+p) for r,p in zip(required,provided))/len(parts)
            assert abs(ifn-rep['metrics'][0])<=0.000051
            assert abs(instability-rep['metrics'][3])<=0.000051
            trial_checks.append(dict(seed=row['seed'],native_membership_complete_unique=True,
                IFN_recomputed=ifn,Instability_recomputed=instability,
                effective_budget=run['config']['evaluationBudget'],evaluations=run['evaluations'],
                completed_generations=run['completedGenerations']))
        checks['methods']['unifyms']={'runs':10,'unique_seeds':len({r['seed'] for r in s['runs']}),'jev_requests':1,
            'fixed_config':s['config'],'native_entities':sorted(en_names),'per_run':trial_checks}
    write(base/'validation.json',checks)


def link(p,label=None):return '['+(label or Path(p).name)+'](<'+str(p)+'>)'



def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['baselines','snapshot','calibrate','select','unify','mono','service']);p.add_argument('--run-dir',type=Path,default=DEFAULT);a=p.parse_args();b=a.run_dir.resolve()
    if a.phase=='baselines':baselines(b)
    elif a.phase=='snapshot':command(b,'unifyms_snapshot',java(b)+['tuning.MermSnapshot',b/'input/library.remodel',b/'unifyms/model-snapshot.json'],b/'unifyms/runtime')
    elif a.phase=='calibrate':cli_run(b,'calibrate')
    elif a.phase=='select':
        existing=b/'unifyms/experiment/Library/selection-jev.json'
        if existing.exists() and read(existing).get('attempts'):raise RuntimeError('JEV attempt already recorded; refusing another request')
        cli_run(b,'select')
    elif a.phase=='unify':unify(b)
    elif a.phase=='mono':mono(b)
    else:service(b)

if __name__=='__main__':main()
