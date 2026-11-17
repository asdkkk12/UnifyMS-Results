#!/usr/bin/env python3
"""ATM experiment phases with retained outputs, frozen JEV selection and 10 seeds."""
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
DEFAULT = ROOT / 'runs/atm_20261104_01'
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


def cli(base,phase,*flags):
    command(base,'unifyms_'+phase+('_'+flags[-1] if flags else ''),java(base)+
            ['tuning.TuningCli',phase,str(base/'unifyms/run-config.json'),'--system','ATM',*flags],base/'unifyms/runtime')


def evaluate(base,method):
    command(base,method+'_metrics',[sys.executable,MONO/'tools/compute_airms_metrics.py','--app','ATM',
            '--model',base/'input/atm.remodel','--decomposition',base/method/'decomposition.json',
            '--output',base/method/'metrics.json'])


def baselines(base):
    model=base/'input/atm.remodel'
    command(base,'microminer_conversion',[sys.executable,ROOT/'tools/remodel_to_microminer_input.py',
            '--model',model,'--output',base/'microminer/input','--app','ATM'])
    command(base,'microminer_decomposition',[sys.executable,MONO/'tools/microminer_remodel_decompose.py',
            '--app','ATM','--model',base/'microminer/input/atm.remodel','--output',base/'microminer/decomposition.json',
            '--membership-threshold','0.70'])
    evaluate(base,'microminer')
    command(base,'monoembed_conversion',[sys.executable,MONO/'tools/remodel_to_monoembed.py',model,base/'monoembed/input','--app','ATM'])
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
            '--model',base/'input/atm.remodel','--solver-result',result_path,'--output',base/'servicecutter/decomposition.json'])
    evaluate(base,'servicecutter')


def mono(base):
    command(base,'monoembed_decomposition',[MONO/'.venv-api/bin/python',MONO/'tools/api_decompose.py','--app','ATM',
            '--input-dir',base/'monoembed/input','--output',base/'monoembed/decomposition.json','--refresh'])
    evaluate(base,'monoembed')


def unify(base):
    selection=read(base/'unifyms/experiment/ATM/selection-jev.json')
    assert selection['status']=='success' and selection['mock'] is False
    assert len(selection['attempts'])==1,'Expected exactly one actual JEV request'
    cfg=selection['config']
    input_hash=selection['inputHash']
    rows=[]
    for seed in SEEDS:
        cli(base,'run','--seed',str(seed))
        path=base/f'unifyms/experiment/ATM/run-jev-{seed}.json';d=read(path)
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
        result=read(base/f'unifyms/experiment/ATM/run-jev-{row["seed"]}.json')
        text=[f'# ATM / seed {row["seed"]}', '', 'Metrics: `'+json.dumps(row)+'`', '',
              '| Service | Use cases | Entities | Required entity interfaces | Provided entity interfaces |',
              '|---|---|---|---|---|']
        for item in result['representative']['services']:
            text.append('| '+str(item['id'])+' | '+' | '.join(', '.join(item.get(k,[]))
                        for k in ['useCases','entities','requiredEntityInterfaces','providedEntityInterfaces'])+' |')
        target=base/f'unifyms/partitions/seed-{row["seed"]}.md';target.parent.mkdir(exist_ok=True)
        target.write_text('\n'.join(text)+'\n')
    try:
        command(base,'unifyms_visualizations',[sys.executable,base/'unifyms/runtime/scripts/run-case.py','report',
                '--input',base/'input/atm.remodel','--case','ATM','--experiment',base/'unifyms/experiment',
                '--snapshot',base/'unifyms/model-snapshot.json','--test-seeds',','.join(map(str,SEEDS)),
                '--output',base/'unifyms/report'])
    except RuntimeError:
        # Do not bypass source/snapshot validation to fabricate a .req diagram.
        (base/'unifyms/report/analysis.md').write_text(
            '# ATM 原生结果导出说明\n\n正式 10 次搜索及原生指标已完成；逐次 JSON 和可读划分见 ../experiment/ATM 与 ../partitions。\n\n'
            '严格 .req 导出失败，详见 ../../logs/unifyms_visualizations.log。原生解析器将注释掉的 Transcation 当作实体，'
            '与严格源文件解析的两个有效实体不一致，因此未绕过校验生成图，也未修改输入或原生指标。\n')


def validate(base):
    sys.path.insert(0,str(MONO/'tools'))
    from compute_airms_metrics import parse_model
    services,entities,contracts,actors,ucs=parse_model(base/'input/atm.remodel')
    expected={(s,o) for s,ops in services.items() for o in ops}
    checks={'source_sha256':hashlib.sha256((base/'input/atm.remodel').read_bytes()).hexdigest(),
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
            result=read(base/f'unifyms/experiment/ATM/run-jev-{row["seed"]}.json')
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


def report(base):
    validate(base)
    manifest=read(base/'manifest.json');checks=read(base/'validation.json')
    names={'microminer':'MicroMiner Remodel 适配版','monoembed':'MonoEmbed 百炼 API 变体',
           'servicecutter':'Service Cutter Engine + 结果适配','unifyms':'UnifyMS + JEV（10 次均值，原生口径）'}
    values={}
    for method in names:
        p=base/(method+'/summary.json' if method=='unifyms' else method+'/metrics.json')
        if p.exists():values[method]=read(p)['mean'] if method=='unifyms' else read(p)
    lines=['# ATM 案例运行结果','',
      '报告生成时间：'+datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')+'（Asia/Shanghai）。',
      '', '## 实验输入与执行约束','',
      '- 源输入：'+link(Path(manifest['input_original']))+'。',
      '- 本次唯一输入副本：'+link(base/'input/atm.remodel')+'。',
      '- SHA-256：`'+manifest['input_sha256']+'`。',
      f'- 适配器解析出 {checks["parsed_services"]} 个声明 Service、{checks["parsed_entities"]} 个 Entity、{checks["parsed_usecases"]} 个用例、{checks["declared_operations"]} 个声明操作。',
      '- 前三种方法各运行一次；MonoEmbed 使用 API 向量与标准化/AP 聚类，未使用旧 TF-IDF 分组。',
      '- UnifyMS 先使用校准种子 11 评估正式 C0–C5，再由真实 JEV 选参一次；选定后冻结参数，以 10 个独立种子分别运行拆分，逐指标取算术平均。校准不纳入正式 10 次均值。',
      '- 正式种子：`'+str(SEEDS)+'`。所有运行工件保留。',
      '- 独立 UnifyMS 运行副本仅将 JEV HTTP 尝试上限 2 改为 1，防止失败时自动重试；源项目不修改。','',
      '## 五指标对比','',
      '**前三种方法使用同一个旧评估器；UnifyMS 使用原生五指标公式。下表是截图要求的数值并列，不代表统一口径的方法优劣评判。**','',
      '| 方法 | MS_Num | IFN | CHD | Instability | UCM | CMQ |','|---|---:|---:|---:|---:|---:|---:|']
    def fmt(v):return '' if v is None else f'{v:.6f}'
    for method,name in names.items():
        m=values.get(method,{})
        lines.append('| '+name+' | '+' | '.join(fmt(m.get(k)) for k in ['MS_Num']+METRICS)+' |')
    lines+=['','## 五指标排序','','排序按表中六位小数判定并列。IFN、Instability 升序，CHD、UCM、CMQ 降序；仅为数值排序。UnifyMS 原生 Instability 最大化且公式不同，不能依据此排序评价好坏。','',
            '| 指标 | 排序口径 | 表内数值顺序 |','|---|---|---|']
    short={'microminer':'MicroMiner','monoembed':'MonoEmbed','servicecutter':'Service Cutter','unifyms':'UnifyMS + JEV'}
    for metric in METRICS:
        desc=metric in ['CHD','UCM','CMQ'];groups={}
        for method,m in values.items():
            if m.get(metric) is not None:groups.setdefault(round(m[metric],6),[]).append(short[method])
        ranking=' → '.join(' = '.join(groups[v])+f'（{v:.6f}）' for v in sorted(groups,reverse=desc))
        lines.append(f'| {metric} | 数值'+('降序' if desc else '升序')+' | '+ranking+' |')
    lines+=['','## UnifyMS 的 10 次正式输出','',
            '| seed | MS_Num | IFN | CHD | Instability | UCM | CMQ | 输出 |','|---|---:|---:|---:|---:|---:|---:|---|']
    summary_path=base/'unifyms/summary.json'
    if summary_path.exists():
        s=read(summary_path)
        for row in s['runs']:
            lines.append('| '+str(row['seed'])+' | '+' | '.join(fmt(row[k]) for k in ['MS_Num']+METRICS)+' | '+link(base/f'unifyms/experiment/ATM/run-jev-{row["seed"]}.json','JSON')+' |')
        display_config={k:v for k,v in s['config'].items() if k!='seed'}
        lines+=['','固定选择：`'+s['selection']+'`；候选参数（正式种子见上表）：`'+json.dumps(display_config,ensure_ascii=False)+'`。',
                '样本标准差：`'+json.dumps(s['sample_std'],ensure_ascii=False)+'`。']
        cal=read(base/'unifyms/experiment/ATM/calibration.json')
        lines+=['', f'正式每次统一评价上限为 {cal["evaluationBudget"]:,}；名义参数中的 evaluationBudget=0 是候选配置的原始设置，实际执行使用校准确定的统一上限，逐次实际评价次数和代数见 validation.json。',
                '本次 JEV 选择 C0，与默认参数一致；本实验没有额外执行 JEV/非 JEV 配对对照，不能据此宣称 JEV 提升了拆分质量。' if s['selection']=='C0' else
                '本实验只运行被选配置的 10 次正式拆分，没有额外的同种子默认配置对照，不能仅据此宣称 JEV 改善效果。']
        lines+=['','### 一次性校准与 JEV 选择证据','',
                '| 配置 | N | 名义 G | 交叉概率 | crossP | 校准 HV |',
                '|---|---:|---:|---:|---:|---:|']
        for cid,entry in sorted(cal['candidates'].items()):
            c=entry['config']
            lines.append(f'| {cid} | {c["populationSize"]} | {c["generations"]} | {c["crossoverProbability"]} | {c["crossP"]} | {entry["meanHv"]:.12f} |')
        lines+=['','本次六组配置校准 HV 相同，只有一个校准种子，不能据此推断某组参数稳定更优。','',
                '- '+link(base/'unifyms/experiment/ATM/calibration.json','完整校准数据'),
                '- '+link(base/'unifyms/experiment/ATM/selection-jev.json.evidence.json','传给 JEV 的选参证据'),
                '- '+link(base/'unifyms/experiment/ATM/selection-jev.json.analysis.md','程序生成的选参得失解释（不是模型思维过程）')]
    lines+=['','## Token 与总耗时','',
            '无法取得可靠 token 值时按要求留空，不记为 0。耗时来自本次运行日志；UnifyMS 同时列出前期选参成本和正式运行成本。','',
            '| 方法 | 总 token | 总耗时（秒） | 口径 |','|---|---:|---:|---|']
    mono_stats=base/'monoembed/decomposition.stats.json'
    cost_details=[]
    if mono_stats.exists():
        s=read(mono_stats);tokens=s.get('total_tokens') if s.get('usage_complete') else None
        conversion=read(base/'logs/monoembed_conversion.json')['seconds']
        dec=base/'logs/monoembed_decomposition.json';wall=read(dec)['seconds'] if dec.exists() else None
        total=conversion+wall if wall is not None else None
        lines.append(f'| MonoEmbed API | {tokens if tokens is not None else ""} | {fmt(total)} | Remodel 转换 + embedding/标准化/聚类/保存；不含质量指标评估。 |')
        cost_details+=['',f'MonoEmbed 内部 `total_seconds={s.get("total_seconds")}`；`api_seconds={s.get("api_seconds")}`；缓存历史 token `{s.get("cached_source_tokens")}`；完成状态 `{s.get("status")}`。','']
    selection_path=base/'unifyms/experiment/ATM/selection-jev.json'
    if selection_path.exists():
        sel=read(selection_path);tokens=sel.get('totalTokens')
        stages=['unifyms_calibrate','unifyms_select']+['unifyms_run_'+str(seed) for seed in SEEDS]
        timings=[read(base/f'logs/{label}.json').get('seconds') for label in stages if (base/f'logs/{label}.json').exists()]
        total=sum(timings) if len(timings)==len(stages) and all(t is not None for t in timings) else None
        lines.append(f'| UnifyMS + JEV | {tokens if tokens is not None else ""} | {fmt(total)} | 六组校准一次 + JEV 一次 + 正式拆分 10 次之和；不含构建和可视化。 |')
        cost_details+=['',f'JEV 实际 HTTP 请求数：{len(sel.get("attempts",[]))}；模型 `{sel.get("actualModel","")}`；状态 `{sel.get("status")}`。','']
        for label in ['unifyms_calibrate','unifyms_select']:
            p=base/f'logs/{label}.json'
            if p.exists():cost_details.append(f'- {label}：{read(p).get("seconds",0):.6f} 秒。')
        rt=[read(base/f'logs/unifyms_run_{seed}.json')['seconds'] for seed in SEEDS if (base/f'logs/unifyms_run_{seed}.json').exists()]
        if rt:cost_details.append(f'- 正式拆分 {len(rt)} 次累计：{sum(rt):.6f} 秒；平均：{statistics.mean(rt):.6f} 秒。')
    lines+=cost_details
    lines+=['','两种方法的执行工作量不同：UnifyMS 总耗时含六组校准和 10 次正式拆分，MonoEmbed 为一次向量生成与拆分；不能直接据累计秒数判断单次运行效率。JEV 的未知 token 按要求留空，不用 knownTokens=0 代替。']
    lines+=['','## 五指标公式口径对照','',
      '| 指标 | 前三个方法的公共评估器 | UnifyMS 原生实现 |',
      '|---|---|---|',
      '| IFN | 16 个声明操作 / 全部簇数 | 所需实体接口与提供实体接口的计数之和 / 微服务数；不是操作数 / 服务数 |',
      '| CHD | 组内操作对实体集合 Jaccard，包含自身比较；仅平均有操作簇 | 按同簇用例映射的操作集合计算实体 Jaccard，排除自身；单操作簇记 1，再平均各服务 |',
      '| Instability | Required / (Provided + Required)，Required 为启发式 Contract 调用与 CRUD | ProvidedEntityInterfaces / (RequiredEntityInterfaces + ProvidedEntityInterfaces)，无 required 时记 1；优化方向为最大化 |',
      '| UCM | 输入用例对的关系平均，不依赖划分，CorrF 固定 0 | structureCohesion - structureCoupling，随用例划分变化 |',
      '| CMQ | 实体字段/类型/引用词特征的簇内余弦均值 - 簇间余弦均值 | 基于实体关系矩阵和跨服务实体接口计算的模块度 |','',
      'UnifyMS 搜索库已将目标值保留四位小数；本报告对每次保存的代表方案原生指标取均值，展示六位小数，并未重新计算成另一套指标。',
      '代表方案按冻结的校准归一化空间中距理想点最近的非支配解选择；不是从正式 10 次结果中挑选最好的一次。']
    lines+=['','## 实现和指标边界','',
      '- MicroMiner 是现有 Remodel 信号适配器，阈值 0.70；不是原始 Java/KDM + CodeBERT/Word2Vec + Louvain 的完整实现。',
      '- MonoEmbed 使用 `qwen3.7-text-embedding-flash` API、1024 维向量、StandardScaler 与 damping=0.8 的 Affinity Propagation；不是论文微调权重 ME-llm2vec-340K。',
      '- Service Cutter 使用官方 Engine 的 Girvan–Newman，numberOfClusters=5 沿用已有对比设置；5 为指定值，不是自动选优。保留 nanoentity 原始输出，使用既有桥接器映射回 Service/Entity。',
      '- 本次 Engine 实际返回 14 个单 nanoentity 簇，未达到请求的 5 簇；报告保留真实结果，不手动合并。大量无操作簇会压低 IFN，不能仅按 IFN 将其判为最优。',
      '- Service Cutter 初次导入失败：转换器将注释中的 Transcation 关系误读为有效边；修复转换器注释过滤后运行成功，初次输入和失败原因保留在 servicecutter/initial_failed_import。原始 atm.remodel 未改动。',
      '- UnifyMS 原生快照包含 3 个实体，额外计入了源文件中已注释的 Transcation；前三个适配器解析到 2 个有效实体。故即使源字节完全一致，内部实体集合也不一致。原生指标保持真实程序输出，没有为改善可比性而改写。',
      '- 严格 .req / MERM 图导出因此未通过源实体集合一致性校验，没有绕过校验生成图；10 次原生 JSON、完整种群/前沿、可读划分 MD 均已保留，诊断见 UnifyMS 导出验证说明。',
      '- 前三种方法的 IFN 为声明操作总数 / 簇数，包含没有操作的实体簇；需要结合操作分布解释。CHD 为组内操作对实体集合的 Jaccard 均值，包含自身。',
      '- 前三种方法的 UCM 由输入用例关系计算，固定 CorrF=0，不依赖拆分边界；ATM 实际声明了 include cardIdentification，这部分未被旧评价器建模。同值不能证明三个方法效果相同。',
      '- 前三种方法的 Instability 是启发式外部调用与 CRUD 依赖口径；UnifyMS 使用自身实现并最大化，二者不同。CMQ 的特征表示也不同。',
      '- Remodel 转换产生源码风格片段，不是恢复真实 Java 实现。当前解析器与桥接器有启发式限制；结果不能直接解释为原论文方法排名。','',
      '## 操作覆盖验证与文件索引','']
    for method,check in checks['methods'].items():
        compact={k:v for k,v in check.items() if k not in ['per_run','fixed_config']}
        lines.append('- '+short[method]+'：`'+json.dumps(compact,ensure_ascii=False)+'`。')
    lines+=['','| 方法 | 转换输入 | 原始拆分 | 指标/均值 |','|---|---|---|---|']
    for method,name in names.items():
        if method=='unifyms':
            lines.append('| '+name+' | '+link(base/'unifyms/model-snapshot.json')+' | '+link(base/'unifyms/experiment/ATM','10 次 JSON 与 trials')+' | '+link(summary_path)+' |')
        else:lines.append('| '+name+' | '+link(base/method/'input')+' | '+link(base/method/'decomposition.json')+' | '+link(base/method/'metrics.json')+' |')
    lines+=['', '- '+link(base/'servicecutter/solver_result.json','Service Cutter 原始 Engine 输出'),
            '- '+link(base/'unifyms/experiment/ATM/selection-jev.json','唯一 JEV 选参记录'),
            '- '+link(base/'unifyms/report/analysis.md','UnifyMS 导出验证说明'),
            '- '+link(base/'unifyms/partitions','10 次可读划分'),
            '- '+link(base/'logs','阶段命令、耗时和原始日志'),
            '- '+link(base/'validation.json','验证记录'),'- '+link(base/'manifest.json','实验清单'),'']
    path=base/'ATM案例运行结果.md';path.write_text('\n'.join(lines));print(path,flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['baselines','snapshot','calibrate','select','unify','mono','service','report']);p.add_argument('--run-dir',type=Path,default=DEFAULT);a=p.parse_args();b=a.run_dir.resolve()
    if a.phase=='baselines':baselines(b)
    elif a.phase=='snapshot':command(b,'unifyms_snapshot',java(b)+['tuning.MermSnapshot',b/'input/atm.remodel',b/'unifyms/model-snapshot.json'],b/'unifyms/runtime')
    elif a.phase=='calibrate':cli(b,'calibrate')
    elif a.phase=='select':
        # A failed or successful recorded request is never silently repeated by the coordinator.
        existing=b/'unifyms/experiment/ATM/selection-jev.json'
        if existing.exists() and read(existing).get('attempts'):
            raise RuntimeError('JEV attempt already recorded; refusing a second request')
        cli(b,'select')
    elif a.phase=='unify':unify(b)
    elif a.phase=='mono':mono(b)
    elif a.phase=='service':service(b)
    else:report(b)


if __name__=='__main__':main()
