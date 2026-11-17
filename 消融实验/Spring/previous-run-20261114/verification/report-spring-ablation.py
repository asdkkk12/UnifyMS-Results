#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate and publish only the three legacy Spring ablation arms."""
import collections,csv,hashlib,json,statistics,sys
from pathlib import Path
from merm_model import export_req,parse_req,write_json
from merm_view import render_svg,render_html
SEEDS=[101,103,107,109,113,127,131,137,139,149]
ARMS={'without-offline':'−O：无离线选参','without-probability':'−P：无动态概率','without-guidance':'−G：无候选引导'}
METRICS=['MS_Num','IFN','CHD','Instability','UCM','CMQ','HV']
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tokens(call):
    u=(call.get('response') or {}).get('usage') or {}
    return u.get('prompt_tokens',u.get('input_tokens'))
def stats(calls):
    attempted=[c for c in calls if c.get('attempted',True)]
    known=[tokens(c) for c in attempted if tokens(c) is not None]
    return dict(requests=len(attempted),failures=sum(c.get('status')!='success' for c in calls),keep=sum(c.get('status')=='success' and c.get('choice')=='KEEP' for c in calls),inputTokens=sum(known) if len(known)==len(attempted) else None,knownInputTokens=sum(known),unknownUsageCalls=len(attempted)-len(known),responseMillis=sum(c.get('responseMillis',0) for c in calls))
def audit_index(summary,index_name):
    p=Path(summary['auditDirectory']); index=p/index_name
    assert sha(index)==summary['auditIndexSha256'],'Audit index modified'
    for name,digest in read(index).items():
        target=(p/name).resolve();assert target.is_relative_to(p.resolve());assert sha(target)==digest,'Audit file modified: '+name

def main(root):
    root=Path(root).resolve();shared=root/'shared';protocol=read(shared/'protocol.json');verified=read(shared/'compatibility.json');assert verified['status']=='success'
    protocol_hash=hashlib.sha256(json.dumps(protocol,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    rows=[];modules=[];aggregates={};files={};manifests=[];errors=collections.Counter()
    for arm,label in ARMS.items():
        for seed in SEEDS:
            d=root/'arms'/arm/('seed-'+str(seed));r=read(d/'run.json');run=r['run'];m=read(d/'manifest.json');c=run['config'];p=r['representative'];values=p['metrics'];assert run['status']=='success' and r['arm']==arm and c['seed']==seed
            assert run['metricVersion']==protocol['metricVersion'] and run['inputHash']==protocol['inputHash']
            assert m['implementationHash']==verified['compatibilityImplementationHash'] and r['protocolHash']==m['protocolHash']
            assert m['protocolHash']==protocol_hash
            expected=('C0',200,100,.7,.5) if arm=='without-offline' else ('C3',200,100,.5,.25)
            assert tuple(c[k] for k in ['id','populationSize','generations','crossoverProbability','crossP'])==expected
            assert run['completedGenerations']==expected[2]
            online=run['onlineControl'];audit_index(online,'audit-files.json')
            requests=[read(f) for f in sorted((d/'audit/requests').glob('*.json'))]
            decisions=[json.loads(s) for s in (d/'audit/control-decisions.jsonl').read_text().splitlines()] if (d/'audit/control-decisions.jsonl').exists() else []
            assert all(x['generation']%10==0 and x['generation']<c['generations'] for x in decisions)
            if arm=='without-probability':
                assert not requests and online['requestCount']==0 and online['finalProbability']==.5
                assert all(x['mode']=='off' and x['action']=='KEEP' and x['probabilityBefore']==.5 and x['probabilityAfter']==.5 and 'requestFile' not in x for x in decisions)
            else:assert len(decisions)==(c['generations']-1)//10
            guidance=run.get('guidance');windows=[];generation=[];choices=[]
            if arm=='without-guidance':assert guidance is None and run['guidanceEvaluations']==0 and not (d/'guidance').exists()
            else:
                audit_index(guidance,'guidance-files.json');windows=[read(f) for f in sorted((d/'guidance').glob('window-*.json'))];assert len(windows)==(c['generations']-1)//10
                for w in windows:
                    assert w['generation']%10==0 and w['generation']<c['generations']
                    generation+=w['generationCalls'];choices += [x['response'] for x in w['selectionCalls']]
            for name,calls in [('probability-JEV',requests),('generation-LLM',generation),('candidate-JEV',choices)]:
                modules.append(dict(arm=arm,seed=seed,module=name,**stats(calls)))
                for call in calls:
                    if call.get('status')!='success':
                        detail=(call.get('response') or {}).get('detail');errors[(arm,name,call.get('error','unknown'),json.dumps(detail,ensure_ascii=False,sort_keys=True))]+=1
            selected=sum(w.get('selectedCount',0) for w in windows);retained=sum(w.get('retainedCount',0) for w in windows)
            row=dict(arm=arm,seed=seed,MS_Num=p['serviceCount'],IFN=values[0],CHD=values[1],CMQ=values[2],Instability=values[3],UCM=values[4],HV=r['hv'],generations=run['completedGenerations'],evaluations=run['evaluations'],candidateEvaluations=run['guidanceEvaluations'],selected=selected,retained=retained,workerSeconds=run['workerMillis']/1000,run=str(d/'run.json'))
            rows.append(row);manifests.append(m)
            vis=d/'visualization';vis.mkdir(exist_ok=True);req=vis/'Spring.req';export_req(d/'run.json',shared/'Spring.remodel',shared/'model-snapshot.json',req);model=parse_req(req)
            assert not any(x.get('severity')=='error' for x in model['diagnostics'])
            uc,ul=render_svg(model,'usecases');dom,dl=render_svg(model,'domain');model['layout']={'usecases':ul,'domain':dl}
            for name,data in [('Spring-usecases.svg',uc),('Spring-domain.svg',dom),('Spring-merm.html',render_html(model,uc,dom))]:(vis/name).write_text(data)
            write_json(vis/'Spring-merm.json',model);write_json(vis/'Spring-diagnostics.json',model['diagnostics'])
            for f in vis.iterdir():files[str(f.relative_to(root))]=sha(f)
        subset=[r for r in rows if r['arm']==arm];aggregates[arm]={k:dict(mean=statistics.mean(r[k] for r in subset),sampleStd=statistics.stdev(r[k] for r in subset)) for k in METRICS}
    out=root/'report';out.mkdir(exist_ok=True)
    write_json(out/'results.json',dict(protocolVersion=protocol['protocolVersion'],metricVersion=protocol['metricVersion'],normalization=read(shared/'calibration.json')['normalization'],seeds=SEEDS,full=None,fullStatus='historical-full-imported-separately-in-master',aggregates=aggregates,runs=rows,moduleStatistics=modules,files=files))
    for name,data in [('runs.csv',rows),('module-statistics.csv',modules)]:
        with (out/name).open('w',newline='') as f:w=csv.DictWriter(f,list(data[0]));w.writeheader();w.writerows(data)
    write_json(out/'call-failures.json',[dict(arm=a,module=m,error=e,providerDetail=json.loads(d),count=n) for (a,m,e,d),n in sorted(errors.items())])
    md=['# Spring 冻结协议三组消融实验','', '本报告仅汇总新增 −O、−P、−G，各十次。完整方法未重跑；历史 Full 由独立证据核验后写入根目录汇总Case.md。','', '## 十次均值与样本标准差','', '各单元为均值 ± 样本标准差（分母 n−1）。MS_Num 是代表方案服务数；HV 是最终前沿的解集 HV。','', '|组别|MS_Num|IFN ↓|CHD ↑|Instability ↑|UCM ↑|CMQ ↑|HV ↑|','|---|---:|---:|---:|---:|---:|---:|---:|']
    for arm in ARMS:md.append('|'+ARMS[arm]+'|'+'|'.join(f"{aggregates[arm][k]['mean']:.6f} ± {aggregates[arm][k]['sampleStd']:.6f}" for k in METRICS)+'|')
    md += ['|Full：完整方法|见主汇总|见主汇总|见主汇总|见主汇总|见主汇总|见主汇总|见主汇总|','','## 运行协议','','−O 固定从 C0（N=200、G=100、p_var=0.7、crossP=0.5）开始，概率控制与候选引导开启。−P 与 −G 复用旧离线选择 C3（N=200、G=100、p_var=0.5、crossP=0.25）；−P 关闭概率控制且概率固定 0.5，−G 关闭生成、候选优选和注入。未重新调用离线 JEV。','','指标版本 `paper-ieee-eq5-21-v2-isolated-zero`：IFN 最小化，其余四项最大化；无接口服务 Instability=0。10 代一窗口，末代不调用；其他指标损失门槛 0.5。沿用名义代数，不能声称等评价预算。','','种子：'+', '.join(map(str,SEEDS))+'。模型：`gpt-4.1-mini-2025-04-14` / `jev-1.14.0`；候选提示词 `candidate-consistency-choice-v2-compact`。','','[冻结归一化、HV 参考点及校准](../shared/calibration.json) · [历史 C3 选择](../shared/selection-jev.json) · [冻结协议兼容检查](../shared/compatibility.json) · [协议与冻结文件哈希](../shared/protocol.json)','','兼容检查复算 950 条校准种群记录并重跑全部六组，核对指标、HV、归一化、生成任务和实际请求结构。历史实现哈希：`'+verified['historicalImplementationHash']+'`；当前兼容实现哈希：`'+verified['compatibilityImplementationHash']+'`。两者分别记录。','','## 每次结果及输出位置','','|组别|种子|代数|实际评价|额外候选评价|优选 / 留存|运行秒数|文件|','|---|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        link='../arms/'+r['arm']+'/seed-'+str(r['seed']);md.append(f"|{ARMS[r['arm']]}|{r['seed']}|{r['generations']}|{r['evaluations']}|{r['candidateEvaluations']}|{r['selected']} / {r['retained']}|{r['workerSeconds']:.3f}|[JSON]({link}/run.json) · [.req]({link}/visualization/Spring.req) · [HTML]({link}/visualization/Spring-merm.html) · [用例 SVG]({link}/visualization/Spring-usecases.svg) · [实体 SVG]({link}/visualization/Spring-domain.svg)|")
    md += ['','### 每组计算量与运行时间','','|组别|实际评价合计|额外候选评价合计|十次进程耗时合计（秒）|平均每次耗时（秒）|','|---|---:|---:|---:|---:|']
    for arm in ARMS:
        subset=[r for r in rows if r['arm']==arm];total=sum(r['workerSeconds'] for r in subset);md.append(f"|{ARMS[arm]}|{sum(r['evaluations'] for r in subset)}|{sum(r['candidateEvaluations'] for r in subset)}|{total:.3f}|{total/10:.3f}|")
    md += ['','进程耗时包含搜索期间的模型调用、监控与审计；并行运行的进程耗时合计不是整批墙钟时间。构建、离线兼容验证、正式运行和报告阶段耗时在 `study-status.json` 分列。']
    md += ['','','## 分模块实际执行','','输入 tokens 仅累计接口返回的 usage，缺失时显示“未知”；已知部分另外列出。失败不计作成功 KEEP。概率请求失败后保持原概率属于降级动作。','','|组别|模块|请求|失败|成功 KEEP|输入 tokens|已知部分|响应耗时秒|','|---|---|---:|---:|---:|---:|---:|---:|']
    for arm in ARMS:
        for module in ['probability-JEV','generation-LLM','candidate-JEV']:
            part=[r for r in modules if r['arm']==arm and r['module']==module];tot=lambda k:sum(r[k] for r in part);t='未知' if any(r['inputTokens'] is None for r in part) else str(tot('inputTokens'));md.append(f"|{ARMS[arm]}|{module}|{tot('requests')}|{tot('failures')}|{tot('keep')}|{t}|{tot('knownInputTokens')}|{tot('responseMillis')/1000:.3f}|")
    md += ['','[调用失败分类与服务方原因](call-failures.json)。沿用历史紧凑请求与24000字节上限；不自动重试或切换模型，本地预算拒绝与真实接口失败分别记录。失败后的候选选择停止，搜索继续。因此需结合实际成功请求、入选与留存解释机制效果。','','各窗口请求、原始响应、候选拒绝原因、选中与留存记录在对应种子的 `audit/`、`guidance/`。原始前沿保存在 `run.json` 的 `run.front`。HTML 直接用浏览器打开，可切换用例图和实体接口图；两类 SVG 可直接查看。','','[原始逐次数据](runs.csv) · [模块逐次统计](module-statistics.csv) · [均值、标准差与文件哈希](results.json) · [构建、验证和并行墙钟阶段统计](../study-status.json)','','## 解释范围','','不计算相对完整组的提升率，不依据三组之间的差异直接推断单个机制贡献。Full 在主汇总独立导入前，须逐项核对输入、指标版本、冻结归一化与参考点、配置、种子、模型、模板和机制协议，兼容才做配对差值；不能仅重算最终指标强行合并。四层依赖证据不证明完整需求行为保持，跨服务访问不自动判错。','','验证和校准重跑为离线兼容检查，不属于 30 次正式搜索或真实离线选参。当前新版默认公式与紧凑协议未改变。']
    md += ['', '## Spring 解释边界', '', 'Full 历史选择 C3，−O 使用默认 C0。两者初始概率和内部 crossP 不同，N、G 相同；保留冻结配置，不能声称逐变量或等评价预算比较。沿用过滤注释解析，并在正式运行前核对历史校准、诊断和实际 Choice 请求。报告以实际候选入选、留存和调用失败情况解释机制效果，不预设完整方法必然最优。']
    (out/'ablation-analysis.md').write_text('\n'.join(md)+'\n');print('REPORT',out/'ablation-analysis.md')
if __name__=='__main__':main(sys.argv[1])
