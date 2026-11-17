# coding: utf-8
"""Package ATM rerun under the requested ATN directory and refresh summary."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json,hashlib,re,shutil,subprocess
import run_atm_rerun as r
source=r.DEFAULT;target=Path('/Users/yuanyaowu/Desktop/输出/ATN');summary=target.parent/'汇总Case.md'
assert r.read(source/'manifest.json')['status']=='completed'
assert not target.exists(),'Refusing to overwrite ATN output'
assert len([p for p in (source/'unifyms/report/visualizations').glob('seed-*/*.req') if not p.name.startswith('._')])==10
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
previous_summary=summary.read_bytes();target.mkdir(parents=True)
for p in sorted(source.rglob('*')):
 rel=p.relative_to(source)
 if any(v.startswith('._') or v in ['.git','.local','.env','__pycache__'] for v in rel.parts):continue
 if rel.parts[:2]==('unifyms','runtime'):continue
 out=target/rel
 if p.is_dir():out.mkdir(parents=True,exist_ok=True);continue
 if not p.is_file():continue
 out.parent.mkdir(parents=True,exist_ok=True)
 if p.suffix=='.md':out.write_text(p.read_text().replace(str(source),str(target)))
 else:shutil.copy2(p,out)
 if p.suffix!='.md':assert sha(p)==sha(out),str(rel)
(target/'README.md').write_text('# ATM 重跑结果（ATN 目录）\n\n[案例运行结果](ATM案例运行结果.md)包含四方法五指标对比、排序及 token 与耗时。\n\n本轮输入为原始 atm.remodel，案例身份为 ATM；ATN 是用户指定的归档目录名称。重新运行四个程序；UnifyMS 重新校准，真实 JEV 只调用一次，固定所选配置后十次正式搜索取平均。每次输出、.req 和图示均保留。\n\n原始 JSON/日志保持字节一致，Markdown 工件链接已映射到本目录。凭据文件与运行时依赖不归档。输入转换范围及指标公式差异见报告。\n\n旧 ATM 批次未覆盖。汇总Case_更新前.md 为本次修改汇总文档前的完整备份。\n')
(target/'汇总Case_更新前.md').write_bytes(previous_summary)
subprocess.run(['python3',str(source/'protocol/summarize_case_reports_with_atn.py')],check=True)
draft=Path('/tmp/汇总Case.md');content=draft.read_text();assert 'ATN/ATM案例运行结果.md' in content
assert content.count('### 五指标对比')==12 and content.count('### 五指标排序')==12 and content.count('### Token 与总耗时')==12
# Ensure the preexisting summary did not change during preparation.
assert summary.read_bytes()==previous_summary
summary.write_bytes(draft.read_bytes());assert sha(summary)==sha(draft)
checks=[]
for p in sorted(target.rglob('*')):
 if not p.is_file() or p.name.startswith('._'):continue
 checks.append({'path':str(p.relative_to(target)),'bytes':p.stat().st_size,'sha256':sha(p)})
for p in [target/'ATM案例运行结果.md',summary]:
 for t in re.findall(r'\]\(<([^>]+)>\)',p.read_text()):assert Path(t).exists(),t
for f in checks:assert sha(target/f['path'])==f['sha256']
(target/'文件校验清单.json').write_text(json.dumps({'created_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'source_directory':str(source),'summary_path':str(summary),'summary_sha256':sha(summary),'files':checks},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'destination':str(target),'verified_files':len(checks),'formal_runs':10,'jev_requests':1,'strict_req_exports':10,'summary_updated':str(summary)},ensure_ascii=False))
