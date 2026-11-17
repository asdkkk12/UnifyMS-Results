"""Finish an existing four-worker wave in two pairs without restarting any search."""
import json,os,signal,subprocess,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
b=Path(__file__).resolve().parents[1]/'runs/spring_20261104_01'
state_path=b/'logs/unifyms_active_limit.json'
def processes():
 return {int(p):{'parent':int(parent),'command':cmd} for row in subprocess.check_output(['ps','-axo','pid=,ppid=,command='],text=True).splitlines() for p,parent,cmd in [row.strip().split(None,2)]}
def stamp():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
def save():state_path.write_text(json.dumps(state,indent=2)+'\n')
def resume(pid):
 try:os.kill(pid,signal.SIGCONT)
 except ProcessLookupError:pass
def interrupted(*args):raise InterruptedError('Resource scheduler interrupted')
signal.signal(signal.SIGTERM,interrupted)
ps=processes();workers=[]
for pid,row in ps.items():
 cmd=row['command']
 if str(b) in cmd and ' tuning.Worker ' in cmd:
  argv=cmd.split();request=Path(argv[argv.index('tuning.Worker')+1]);seed=json.loads(request.read_text())['config']['seed']
  if seed in [101,103,107,109,113,127,131,137,139,149]:workers.append({'pid':pid,'seed':seed,'controller':row['parent']})
if len(workers)!=4:
 print('No complete four-worker wave remains; no process state changed');raise SystemExit(0)
parents={ps[w['controller']]['parent'] for w in workers};assert len(parents)==1;parent=parents.pop()
assert ps[parent]['command'].endswith('tools/run_spring_comparison.py unify')
workers.sort(key=lambda w:w['seed']);active=workers[:2];paused=workers[2:]
state={'started_at':stamp(),'policy':'Existing wave in two pairs, then allow the two remaining queued seeds; no restart or budget changes.','runner_pid':parent,'workers':workers,'paused_worker_pids':[],'runner_paused':False,'runner_resumed':False,'events':[]}
def wait_for_outputs(group):
 deadline=time.monotonic()+7200
 while True:
  if all((b/f'unifyms/experiment/Spring/run-jev-{w["seed"]}.json').exists() for w in group):return
  for w in group:
   log=b/f'logs/unifyms_run_{w["seed"]}.log'
   if log.exists() and any(s in log.read_text() for s in ['OutOfMemoryError','Some systems failed','Exception in thread "main"']):raise RuntimeError('Native controller failed; restoring all process states')
  if time.monotonic()>deadline:raise TimeoutError('Pair did not finish within scheduler observation bound')
  time.sleep(5)
try:
 os.kill(parent,signal.SIGSTOP);state['runner_paused']=True;save()
 for w in paused:
  os.kill(w['pid'],signal.SIGSTOP);state['paused_worker_pids'].append(w['pid']);save()
 state['events'].append({'at':stamp(),'stage':'two_workers_active','seeds':[w['seed'] for w in active]});save();print('Two active seeds:',[w['seed'] for w in active],flush=True)
 wait_for_outputs(active)
 for w in paused:resume(w['pid'])
 state['events'].append({'at':stamp(),'stage':'second_pair_resumed','seeds':[w['seed'] for w in paused]});save();print('Second pair resumed:',[w['seed'] for w in paused],flush=True)
 wait_for_outputs(paused)
 state['events'].append({'at':stamp(),'stage':'wave_complete'});save()
finally:
 for pid in state['paused_worker_pids']:resume(pid)
 if state['runner_paused']:resume(parent);state['runner_resumed']=True
 state['ended_at']=stamp();save()
print('Existing wave complete; runner resumed for final queued seeds')
