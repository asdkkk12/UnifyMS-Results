"""Parallelize the existing C1-C5 trial method, always resuming the C0 controller."""
import json,os,signal,subprocess,time
from pathlib import Path
import run_spring_comparison as r
b=r.DEFAULT
rt=b/'unifyms/runtime';o=b/'unifyms/orchestration';config=b/'unifyms/run-config.json'
rows=subprocess.check_output(['ps','-axo','pid=,ppid=,command='],text=True).splitlines()
matches=[int(row.split(None,2)[0]) for row in rows if ' tuning.TuningCli calibrate ' in row and str(config) in row]
assert len(matches)==1,('Expected this experiment controller',matches)
pid=matches[0];state={'controller_pid':pid,'paused':False,'resumed':False};state_path=o/'controller.json'
try:
 os.kill(pid,signal.SIGSTOP);state['paused']=True;state_path.write_text(json.dumps(state,indent=2)+'\n')
 cp=str(o)+':'+str(rt/'target/classes')+':'+(rt/'target/tuning-classpath.txt').read_text().strip()
 with (b/'logs/unifyms_parallel_calibration.log').open('w') as log:
  result=subprocess.run(['java','-cp',cp,'SpringCalibrationTrials',str(config),str(b/'logs/unifyms_parallel_calibration.json')],cwd=rt,stdout=log,stderr=subprocess.STDOUT)
 if result.returncode:raise RuntimeError('Parallel calibration failed; see retained log')
finally:
 if state['paused']:
  os.kill(pid,signal.SIGCONT);state['resumed']=True;state_path.write_text(json.dumps(state,indent=2)+'\n')
print('C1-C5 complete and C0 controller resumed')
