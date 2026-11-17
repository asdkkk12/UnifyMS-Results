"""Archive a completed Spring rerun without overwriting earlier batches."""
from pathlib import Path
import json,hashlib,re,shutil
from datetime import datetime
from zoneinfo import ZoneInfo
import run_spring_comparison as r
source=r.DEFAULT
target=Path('/Users/yuanyaowu/Desktop/输出/Spring')/source.name
assert json.loads((source/'manifest.json').read_text())['status']=='completed'
assert not target.exists(), 'Refusing to overwrite existing batch'
target.mkdir(parents=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
for p in sorted(source.rglob('*')):
 rel=p.relative_to(source)
 if any(x.startswith('._') or x in ['.git','.local','.env','__pycache__'] for x in rel.parts):continue
 if rel.parts[:2]==('unifyms','runtime'):continue
 out=target/rel
 if p.is_dir():out.mkdir(parents=True,exist_ok=True);continue
 if not p.is_file():continue
 out.parent.mkdir(parents=True,exist_ok=True)
 if p.suffix=='.md':out.write_text(p.read_text().replace(str(source),str(target)))
 else:shutil.copy2(p,out)
 checks.append({'path':str(rel),'bytes':out.stat().st_size,'sha256':sha(out)})
readme=target/'README.md'
readme.write_text('# Spring-cloud-shop 重跑结果\n\n[案例运行结果](Spring案例运行结果.md)包含四方法五指标对比、数值排序、token 与总耗时。\n\n本批次重新转换源码、运行三个基线，重新校准并只调用一次 JEV，固定配置完成十次 UnifyMS 拆分。逐次输出及图示完整保留；旧批次未覆盖。\n\n输入范围与指标公式差异、原生 CMQ 历史计数问题见报告。token 缺失时留空。数值向量无文本输出 token。\n\n原始 JSON/日志逐字节保留，Markdown 绝对工件链接更新到本目录。运行时依赖与凭据文件不归档；独立运行副本位置见原始日志。\n')
checks.append({'path':'README.md','bytes':readme.stat().st_size,'sha256':sha(readme)})
for p in [target/'Spring案例运行结果.md']:
 for t in re.findall(r'\]\(<([^>]+)>\)',p.read_text()):assert Path(t).exists(),t
for f in checks:assert sha(target/f['path'])==f['sha256']
assert len(list((target/'unifyms/report/visualizations').glob('seed-*/Spring.req')))==10
(target/'文件校验清单.json').write_text(json.dumps({'created_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'source_directory':str(source),'files':checks},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'destination':str(target),'verified_files':len(checks)},ensure_ascii=False))
