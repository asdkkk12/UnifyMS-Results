#!/usr/bin/env python3
"""Verify and report the corrected-extraction Library round, without running APIs."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import run_library_comparison as runner

KEYS=['IFN','CHD','Instability','UCM','CMQ']
NAMES={'microminer':'MicroMiner Remodel 适配版','monoembed':'MonoEmbed 百炼 API 变体',
       'servicecutter':'Service Cutter Engine + 结果适配','unifyms':'UnifyMS + JEV（10 次均值，原生口径）'}
SHORT={'microminer':'MicroMiner','monoembed':'MonoEmbed','servicecutter':'Service Cutter','unifyms':'UnifyMS + JEV'}

def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def link(p,label=None):return '['+(label or p.name)+'](<'+str(p)+'>)'
def fmt(x):return '' if x is None else f'{x:.6f}'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,default=runner.ROOT/'runs/library_20261103_01')
    base=parser.parse_args().run_dir.resolve()
    summary=read(base/'unifyms/summary.json')
    assert len(summary['runs'])==10 and summary['jev_requests']==1
    runner.validate(base)
    manifest=read(base/'manifest.json');snapshot=read(base/'unifyms/model-snapshot.json')
    import sys
    sys.path.insert(0,str(runner.MONO/'tools'))
    from compute_airms_metrics import parse_model
    source_services,source_entities,_,source_actors,source_ucs=parse_model(base/'input/library.remodel')
    assert set(snapshot['entityNames'].values())==set(source_entities)
    assert set(snapshot['useCaseNames'].values())==set(source_ucs)
    declared_ops=sum(map(len,source_services.values()))
    assert sha(Path(manifest['input_original']))==sha(base/'input/library.remodel')==manifest['input_sha256']
    metrics={m:read(base/m/'metrics.json') for m in ['microminer','monoembed','servicecutter']}
    from itertools import combinations
    for m,d in metrics.items():
        detail=d['CMQ_details'];assert detail['version']=='entity-features-v2-annotated-fields-own-name'
        f={name:set(v) for name,v in detail['features'].items()};assert set(f)==set(source_entities)
        own=detail['effective_entity_clusters'];intra=[];inter=[]
        for x,y in combinations(f,2):
            similarity=len(f[x]&f[y])/(len(f[x])*len(f[y]))**.5
            target=intra if x in own and own.get(x)==own.get(y) else inter
            target.append(similarity)
        x=sum(intra)/len(intra) if intra else 0.;y=sum(inter)/len(inter) if inter else 0.
        assert abs(x-d['Intra_Cohesion'])<1e-12 and abs(y-d['Inter_Coupling'])<1e-12
        assert abs(x-y-d['CMQ'])<1e-12
        assert d['provided_interface_total']==declared_ops
    metrics['unifyms']=summary['mean']
    selection=read(base/'unifyms/experiment/Library/selection-jev.json')
    assert selection['status']=='success' and len(selection['attempts'])==1 and selection['mock'] is False
    astats=read(base/'monoembed/decomposition.stats.json')
    assert astats['status']=='completed' and astats['usage_complete'] and astats['cache_hits']==0
    responses=[p for p in (base/'monoembed/api_response').glob('*.json') if p.name not in {'request.json','requests.json'} and not p.name.startswith('._')]
    assert sum(read(p)['usage']['total_tokens'] for p in responses)==astats['total_tokens']
    req=read(base/'monoembed/api_response/request.json')
    n=len(req['payload']['input']);chars=sum(map(len,req['payload']['input']))
    timings={p.stem:read(p).get('seconds') for p in (base/'logs').glob('*.json') if not p.name.startswith('._')}
    rt=[timings.get('unifyms_run_'+str(seed)) for seed in runner.SEEDS]
    phases=[timings.get('unifyms_calibrate'),timings.get('unifyms_select')]+rt
    unify_total=sum(phases) if all(t is not None for t in phases) else None
    mono_total=sum(timings[k] for k in ['monoembed_conversion','monoembed_decomposition'])
    token=selection.get('totalTokens') if selection.get('usageComplete') else None
    vis=base/'unifyms/report/visualizations'
    visualizations=[p for p in vis.glob('seed-*/*.req') if not p.name.startswith('._')]
    costs={'monoembed':{'total_tokens':astats['total_tokens'],'total_seconds':mono_total,
                       'input_tokens':astats['prompt_tokens'],'text_output_tokens':None,
                       'api_seconds':astats['api_seconds'],'requests':astats['api_requests']},
           'unifyms':{'total_tokens':token,'total_seconds':unify_total,'jev_requests':len(selection['attempts']),
                      'calibration_seconds':timings.get('unifyms_calibrate'),'selection_seconds':timings.get('unifyms_select'),
                      'formal_sum_seconds':sum(rt),'formal_mean_seconds':sum(rt)/10}}
    write(base/'costs.json',costs)
    cal=read(base/'unifyms/experiment/Library/calibration.json')
    lines=['# Library 案例运行结果','',
      '生成时间：'+datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')+'。','',
      '## 本轮结论与实验身份','',
      '本轮四个程序均实际运行，UnifyMS 校准后仅调用一次真实 JEV，固定选择 `'+summary['selection']+'` 再执行 10 次独立正式搜索。','',
      '- 源输入：'+link(base/'input/library.remodel')+'；与原始文件字节一致，SHA-256：`'+manifest['input_sha256']+'`。',
      f'- 四种方法使用同一源文件、{len(source_entities)} 个有效实体、{len(source_ucs)} 个用例。公共评估器按 Service+操作名计 {declared_ops} 条声明；UnifyMS 按不同操作名记录 {snapshot["structure"]["operations"]} 项。',
      '- 同行注解字段完整保留；实体/参与者 extends 头部已解析，父实体保留为引用而不展开继承字段，子参与者继承父参与者用例集合；CMQ 包含实体自身名称，refs 仅保留真实实体。',
      '- 前三种方法共用修复后的公共评价器；UnifyMS 保留自己的目标公式。相同输入和实体集合仍不代表五指标公式已经统一。','',
      '## 五指标对比','',
      '| 方法 | MS_Num | IFN | CHD | Instability | UCM | CMQ |',
      '|---|---:|---:|---:|---:|---:|---:|']
    for m,name in NAMES.items():lines.append('| '+name+' | '+' | '.join(fmt(metrics[m][k]) for k in ['MS_Num']+KEYS)+' |')
    if any(row['MS_Num']==1 for row in summary['runs']):
        lines+=['','**本轮 UnifyMS 的代表方案包含单服务结果。原生搜索允许一个服务，IFN=0 表示没有跨服务实体接口，不能把它解释为完成了有意义的多微服务拆分。此次保留真实算法输出，没有临时增加至少两服务的约束。**']
        example=read(base/'unifyms/experiment/Library/run-jev-101.json')
        counts=dict(sorted(Counter(row['serviceCount'] for row in example['run']['front']).items()))
        lines+=['','例如 seed 101 的完整非支配前沿按服务数分布为 `'+json.dumps(counts)+'`（服务数: 方案数）；该种子按冻结归一化后的理想点距离规则选出的代表方案为 '+str(example['representative']['serviceCount'])+' 个服务。不能把代表方案等同于整个搜索空间。']
    lines+=['','## 五指标排序','',
      '按六位小数判定并列；IFN、Instability 升序，CHD、UCM、CMQ 降序。这是数值排序，不能作为跨公式的方法优劣排名。','',
      '| 指标 | 排序口径 | 表内数值顺序 |','|---|---|---|']
    for k in KEYS:
        groups={};desc=k in ['CHD','UCM','CMQ']
        for m,d in metrics.items():
            if d[k] is not None:groups.setdefault(round(d[k],6),[]).append(SHORT[m])
        order=' → '.join(' = '.join(groups[v])+f'（{v:.6f}）' for v in sorted(groups,reverse=desc))
        lines.append(f'| {k} | 数值'+('降序' if desc else '升序')+' | '+order+' |')
    pairs=metrics['monoembed']['CMQ_details']['pairs']
    lines+=['','## CMQ 逐项复核','',
      f'按 {len(source_entities)} 个实体计算，共 {len(pairs)} 个不同实体对，其中 {sum(p["similarity"]>0 for p in pairs)} 对相似度非零。前三种适配方法的 Intra、Inter 和 CMQ 已按保存的特征与归属独立重算，误差小于 1e-12。','',
      '| 方法 | 同簇实体对数 | 异簇实体对数 | Intra_Cohesion | Inter_Coupling | CMQ |','|---|---:|---:|---:|---:|---:|']
    for m in ['microminer','monoembed','servicecutter']:
        d=metrics[m];x=d['CMQ_details'];lines.append(f'| {SHORT[m]} | {x["intra_pair_count"]} | {x["inter_pair_count"]} | {d["Intra_Cohesion"]:.9f} | {d["Inter_Coupling"]:.9f} | {d["CMQ"]:.9f} |')
    lines+=['','实体继承关系 Student→User、Faculty→User、RecommendBook→Book 已保留为父引用；真实属性不按继承展开，以免重复生成 nanoentity。公共 CMQ 仍是词特征余弦代理，UnifyMS 是实体关系矩阵模块度，绝对值不能当作统一指标比较。','',
      '## 唯一 JEV 选参与十次正式搜索','',
      f'JEV 模型：`{selection.get("actualModel")}`；真实 HTTP 请求 **1 次**；选择 **{summary["selection"]}**。',
      '固定参数：`'+json.dumps({k:v for k,v in summary['config'].items() if k!='seed'},ensure_ascii=False)+'`。',
      f'校准种子 `[11]`，正式种子 `{runner.SEEDS}`，每次实际评价上限 {cal["evaluationBudget"]:,}。名义候选 evaluationBudget=0 由上述统一上限替代。','',
      '| seed | MS_Num | IFN | CHD | Instability | UCM | CMQ | 原始输出 |','|---|---:|---:|---:|---:|---:|---:|---|']
    for row in summary['runs']:
        lines.append('| '+str(row['seed'])+' | '+' | '.join(fmt(row[k]) for k in ['MS_Num']+KEYS)+' | '+link(base/f'unifyms/experiment/Library/run-jev-{row["seed"]}.json','JSON')+' |')
    lines+=['','各指标样本标准差（ddof=1）：`'+json.dumps(summary['sample_std'],ensure_ascii=False)+'`。',
      '若十次代表方案指标相同，样本标准差为 0；这仅是本输入、本参数与代表方案选择规则下的观察，不能推断其他输入或整个非支配前沿都无差异。',
      '每次从自己的非支配解集中，按冻结校准归一化空间到理想点最近的规则取代表方案，再对十个代表方案取算术平均。不是挑最好的一次，也不把十个前沿合并另选。',
      '搜索库将目标值保留四位小数，本报告平均的是保存的原生数值，六位小数仅为展示。','',
      '| 校准配置 | N | 名义 G | 交叉概率 | crossP | 校准 HV |','|---|---:|---:|---:|---:|---:|']
    for cid,entry in sorted(cal['candidates'].items()):
        c=entry['config'];lines.append(f'| {cid} | {c["populationSize"]} | {c["generations"]} | {c["crossoverProbability"]} | {c["crossP"]} | {entry["meanHv"]:.12f} |')
    lines+=['','没有额外执行默认配置的十次配对对照，不能据本表宣称 JEV 的因果收益或统计显著改善。','',
      '## Token 与总耗时','',
      '| 方法 | 总 token | 总耗时（秒） | 计量范围 |','|---|---:|---:|---|',
      f'| MonoEmbed API | {astats["total_tokens"]} | {mono_total:.6f} | 转换输入 + 向量 API、标准化、聚类及保存；不含五指标评估。 |',
      f'| UnifyMS + JEV | {token if token is not None else ""} | {fmt(unify_total)} | 六组校准 + JEV 一次 + 正式拆分十次；不含构建和绘图。 |','',
      f'- MonoEmbed：实际请求 {astats["api_requests"]} 次，无缓存命中；共 {n} 段输入、{chars} 个字符；输入 token {astats["prompt_tokens"]}，没有文本生成输出 token（输出为数值向量）。',
      f'- API 纯请求墙钟耗时（含网络及解析）{astats["api_seconds"]:.6f} 秒；内部总耗时 {astats["total_seconds"]:.6f} 秒。总 token 与保存的原始 usage 已核对。',
      f'- UnifyMS：校准 {timings["unifyms_calibrate"]:.6f} 秒；JEV 选择进程 {timings["unifyms_select"]:.6f} 秒；十次正式拆分合计 {sum(rt):.6f} 秒，均值 {sum(rt)/10:.6f} 秒。',
      '- JEV 没有完整 usage 时总 token 按要求留空，不能用 knownTokens=0 代替。token 仅统计本轮请求。',
      '- 两者运行次数和工作量不同，累计耗时不是公平的单次效率排名；进程启动、依赖加载和系统缓存状态也影响耗时。','',
      '## 输入输出、图与验证','',
      '| 方法 | 输入 | 划分输出 | 指标 |','|---|---|---|---|']
    for m in ['microminer','monoembed','servicecutter']:
        lines.append('| '+NAMES[m]+' | '+link(base/m/'input')+' | '+link(base/m/'decomposition.json')+' | '+link(base/m/'metrics.json')+' |')
    lines.append('| UnifyMS + JEV | '+link(base/'unifyms/model-snapshot.json')+' | '+link(base/'unifyms/experiment/Library','十次 JSON 和 trials')+' | '+link(base/'unifyms/summary.json')+' |')
    lines+=['',f'严格源实体集合校验下，本轮保存的 .req 文件数为 **{len(visualizations)}**。','',
      '- '+link(base/'unifyms/report/analysis.md','UnifyMS 原生报告与十次图'),
      '- '+link(base/'unifyms/partitions','十次可读服务划分'),
      '- '+link(base/'monoembed/api_response','API 请求体、向量与 usage（不含凭据）'),
      '- '+link(base/'servicecutter/solver_result.json','Service Cutter Engine 原始结果'),
      '- '+link(base/'unifyms/experiment/Library/selection-jev.json','唯一 JEV 请求及响应'),
      '- '+link(base/'logs','原始命令、日志与阶段耗时'),
      '- '+link(base/'validation.json','操作完整归属、实体一致性和十次接口复算验证'),
      '- '+link(base/'protocol','修复后的 Python 代码快照与 UnifyMS Java 补丁'),
      '- '+link(base/'manifest.json','输入和协议哈希'),'- '+link(base/'costs.json','机器可读消耗汇总'),'']
    lines+=['## 方法和指标口径限制','',
      '- MicroMiner 为 Remodel 信号适配器，不是原始 Java/KDM + CodeBERT/Word2Vec + Louvain 实现。',
      '- MonoEmbed 是百炼 embedding 编码器变体；输入仍为 Remodel 生成的源码结构片段，不含完整 Contract 业务逻辑，不等同于论文微调模型。',
      f'- Service Cutter 使用官方 Engine，Girvan–Newman 请求 5 簇，实际返回 {metrics["servicecutter"]["MS_Num"]} 簇。保留原始结果，不为了接近目标而人工合并。',
      '- Service Cutter 桥接器将完整 Service 映射回属性簇，本轮操作分布为 [47, 0, 1, 0, 0]，三个簇无操作，不能理解为五个均匀分工的功能服务。继承关系作为父实体引用保留，未展开为 Engine 原生继承结构。',
      '- 三个适配器的 IFN=声明操作数/全部簇数，包含无操作的实体簇；UnifyMS IFN=所需与提供实体接口计数之和/服务数，不能横向比较其绝对值。',
      '- 公共 CHD 包含自身操作对、平均有操作簇；UnifyMS 排除自身且单操作记 1。公共 Instability 为启发式 Required/(Provided+Required)；UnifyMS 为 ProvidedEntityInterfaces/(RequiredEntityInterfaces+ProvidedEntityInterfaces)，无所需接口记 1，并最大化。',
      '- 公共 UCM 不依赖划分且 CorrF=0；参与者继承已保留，但完整用例控制流尚未建模。UnifyMS UCM 为服务内用例内聚减跨服务耦合。',
      '- 公共 CMQ 采用 v2 词特征余弦，重叠实体仍按最后簇归属；UnifyMS 是实体关系矩阵模块度。不同评估器的目标方向与计算对象不同，表格仅按数值排序。',
      '- queryBookCopy、addBookCopy、deleteBookCopy 各在两个 Service 中声明，公共评估器保留三对声明；UnifyMS 用简单操作名索引，合并为 45 个名字，未将其冒称 48 个独立操作。','',
      '## 各簇操作数量','']
    for m in ['microminer','monoembed','servicecutter']:
        nums=[x['provided_interface'] for x in metrics[m]['microservices']]
        lines.append(f'- {SHORT[m]}：`{nums}`，合计 {sum(nums)}；无操作簇 {nums.count(0)} 个。')
    report=base/'Library案例运行结果.md';report.write_text('\n'.join(lines)+'\n')
    manifest.update(status='completed',formal_runs_completed=10,jev_requests=1,strict_req_exports=len(visualizations))
    write(base/'manifest.json',manifest)
    print(json.dumps({'report':str(report),'means':summary['mean'],'costs':costs,'strict_req_exports':len(visualizations)},ensure_ascii=False))

if __name__=='__main__':main()
