#!/usr/bin/env python3
"""Spring frozen v2, three ablations only. Verification precedes credentials and network."""
import argparse,concurrent.futures,datetime,getpass,hashlib,json,os,shutil,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SEEDS=[101,103,107,109,113,127,131,137,139,149]
ARMS=['without-offline','without-probability','without-guidance']
def read(p):return json.loads(Path(p).read_text())
def write(p,x):Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def validate_saved(directory,arm,seed,verified,protocol):
    r=read(directory/'run.json');m=read(directory/'manifest.json');p=read(protocol)
    assert r['arm']==arm and r['run']['config']['seed']==seed and r['run']['status']=='success'
    assert r['protocolVersion']==p['protocolVersion'] and r['protocolHash']==m['protocolHash']
    assert m['protocolHash']==hashlib.sha256(json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert m['implementationHash']==read(verified)['compatibilityImplementationHash']
    assert r['run']['inputHash']==p['inputHash'] and r['run']['metricVersion']==p['metricVersion']
    assert m['normalization']==read(p['calibration'])['normalization']
    c=r['run']['config'];expected=('C0',200,100,.7,.5) if arm=='without-offline' else ('C3',200,100,.5,.25)
    assert tuple(c[k] for k in ['id','populationSize','generations','crossoverProbability','crossP'])==expected
    assert r['run']['completedGenerations']==expected[2]
    for key,indexname in [('onlineControl','audit-files.json'),('guidance','guidance-files.json')]:
        summary=r['run'].get(key)
        if summary is None:assert key=='guidance' and arm=='without-guidance';continue
        root=Path(summary['auditDirectory']).resolve();index=root/indexname
        assert root.is_relative_to(directory.resolve()) and sha(index)==summary['auditIndexSha256']
        for name,digest in read(index).items():
            f=(root/name).resolve();assert f.is_relative_to(root) and sha(f)==digest
    return r
def prepare(source,out):
    shared=out/'shared';shared.mkdir(parents=True);exp=source/'experiment/Spring'
    for name,old in [('calibration.json',exp/'calibration.json'),('selection-jev.json',exp/'selection-jev.json'),('run-config.json',source/'run-config.json'),('historical-manifest.json',source/'experiment/manifest.json'),('model-snapshot.json',source/'model-snapshot.json')]:shutil.copy2(old,shared/name)
    candidate=source/'input/Spring.remodel'
    assert sha(candidate)=='11b712b6f27c990ddb86be946ceb57f0e1dd4b4cbc2787089db4df647bacfa02'
    shutil.copy2(candidate,shared/'Spring.remodel')
    windows=[];generation=None;choice=None;definitions=None
    for f in sorted((exp/'online-jev/guidance-jev/trials').glob('*/guidance/window-*.json')):
        w=read(f)
        if w.get('diagnostic') and w.get('tasks') is not None and w.get('selectedMetric'):windows.append(str(f.resolve()))
        for call in w.get('generationCalls',[]):
            if call.get('request'):generation=call['request']['messages'][0]['content']
        for call in w.get('selectionCalls',[]):
            if call.get('response',{}).get('request'):
                choice=call['response']['request']['questions']['configuration']['instructions'];definitions=call['evidence']['metricDefinitions']
    probs=list((exp/'online-jev/guidance-jev/trials').glob('*/audit/requests/*.json'));online=next(read(f) for f in probs if read(f).get('request'))
    assert choice is not None and definitions is not None,'Historical Spring Choice evidence is required'
    manifest=read(shared/'historical-manifest.json');assert manifest['implementationHash']=='101894a87f89384753bd0ff88faa0b943607e875a7de5c7165e0668abccdfb41'
    frozen=[{'path':str(p.resolve()),'sha256':sha(p)} for p in sorted(shared.iterdir()) if p.is_file()]
    p=dict(protocolVersion='spring-frozen-three-ablation-v1',metricVersion='paper-ieee-eq5-21-v2-isolated-zero',selectedConfig='C3',historicalParser='filtered-comment-reader-v1',inputHash=sha(shared/'Spring.remodel'),input=str(shared/'Spring.remodel'),config=str(shared/'run-config.json'),calibration=str(shared/'calibration.json'),selection=str(shared/'selection-jev.json'),historicalExperiment=str(exp.resolve()),historicalManifest=str(shared/'historical-manifest.json'),historicalImplementationHash=manifest['implementationHash'],choicePromptVersion='candidate-consistency-choice-v2-compact',generationInstructions=generation,choiceInstructions=choice,onlineInstructions=online['request']['questions']['configuration']['instructions'],onlinePromptVersion=online['promptVersion'],metricDefinitions=definitions,auditWindows=windows,probabilityRequests=[str(f.resolve()) for f in sorted(probs)],frozenFiles=frozen,verification=str(shared/'compatibility.json'))
    assert 'isolated service=0' in generation and 'isolated=0' in choice
    write(shared/'protocol.json',p);return shared/'protocol.json'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=Path('/Users/yuanyaowu/Desktop/输出/Spring/unifyms'));p.add_argument('--output',type=Path,required=True);p.add_argument('--verify-only',action='store_true');p.add_argument('--report-only',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--workers',type=int,default=4);args=p.parse_args();out=args.output.resolve();assert 1<=args.workers<=4
    out.mkdir(parents=True,exist_ok=True);protocol=out/'shared/protocol.json'
    if protocol.exists():
        assert args.resume,'Use a fresh directory or --resume'
    else:
        assert not any(out.iterdir()),'Output is not empty';protocol=prepare(args.source.resolve(),out)
    logs=out/'logs';logs.mkdir(exist_ok=True);statuspath=out/'study-status.json';status=read(statuspath) if statuspath.exists() else dict(status='preflight',started=datetime.datetime.now().astimezone().isoformat(),arms=ARMS,seeds=SEEDS,full='pending',runs=[],stages=[])
    lock=threading.Lock()
    def publish():
        with lock:
            tmp=statuspath.with_suffix('.partial');write(tmp,status);tmp.replace(statuspath)
    def command(name,cmd,env=None):
        print('START',name,flush=True);t=time.monotonic()
        with (logs/(name+'.log')).open('a') as log:r=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        row=dict(name=name,status='success' if r.returncode==0 else 'failed',seconds=time.monotonic()-t);status['stages'].append(row);publish()
        if r.returncode:raise RuntimeError(name+' failed; see '+str(logs/(name+'.log')))
        print('DONE',name,flush=True)
    publish();command('build',['mvn','-o','-q','-DskipTests','compile','org.apache.maven.plugins:maven-dependency-plugin:3.7.0:build-classpath','-DincludeScope=runtime','-Dmdep.outputFile=target/tuning-classpath.txt'])
    cp=str(ROOT/'target/classes')+':'+(ROOT/'target/tuning-classpath.txt').read_text().strip();java=['java','-cp',cp,'tuning.LegacyAblationCli']
    verified=out/'shared/compatibility.json'
    # Always verify the current implementation, including after code changes on resume.
    command('compatibility',java+['verify',str(protocol),str(verified)])
    assert read(verified)['status']=='success'
    status['status']='verified';publish()
    if args.verify_only:print('VERIFIED',verified);return
    if args.report_only:
        assert {(r['arm'],r['seed']) for r in status['runs'] if r['status']=='success'}=={(a,s) for a in ARMS for s in SEEDS}
        for arm in ARMS:
            for seed in SEEDS:validate_saved(out/'arms'/arm/('seed-'+str(seed)),arm,seed,verified,protocol)
        command('report-recovered',[sys.executable,'scripts/report-spring-ablation.py',str(out)])
        if 'error' in status:status['recoveredError']=status.pop('error')
        status['status']='success';status['finished']=datetime.datetime.now().astimezone().isoformat();publish();return
    env=os.environ.copy()
    for name in ['CHATFIRE_API_KEY','TYPESAFE_API_KEY']:
        if not env.get(name):env[name]=getpass.getpass(name+' (hidden, runtime only): ')
        assert env[name].strip()
    status['status']='running';publish();done={(r['arm'],r['seed']) for r in status['runs'] if r['status']=='success'}
    def run(arm,seed):
        directory=out/'arms'/arm/('seed-'+str(seed));result=directory/'run.json'
        if (arm,seed) in done:
            validate_saved(directory,arm,seed,verified,protocol);return
        command(arm+'-'+str(seed),java+['run',str(protocol),arm,str(seed),str(directory)],env)
        r=read(result);status['runs'].append(dict(arm=arm,seed=seed,status='success',result=str(result),hv=r['hv']));publish()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(run,a,s) for a in ARMS for s in SEEDS]
            for f in concurrent.futures.as_completed(futures):f.result()
        assert len(status['runs'])==30
        command('report',[sys.executable,'scripts/report-spring-ablation.py',str(out)])
        status['status']='success';status['finished']=datetime.datetime.now().astimezone().isoformat();publish();print('REPORT',out/'report/ablation-analysis.md')
    except BaseException as e:
        status['status']='failed' if isinstance(e,Exception) else 'interrupted';status['error']=type(e).__name__+': '+str(e);publish();raise
if __name__=='__main__':main()
