#!/usr/bin/env python3
"""Verify and report the corrected-extraction PiggyMetrics round, without running APIs."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import run_piggy_metrics_comparison as runner

KEYS=['IFN','CHD','Instability','UCM','CMQ']
NAMES={'microminer':'MicroMiner Java AST 信号适配版','monoembed':'MonoEmbed 真实 Java 源码 API 变体',
       'servicecutter':'Service Cutter Engine + 结果适配','unifyms':'UnifyMS + JEV（10 次均值，原生口径）'}
SHORT={'microminer':'MicroMiner','monoembed':'MonoEmbed','servicecutter':'Service Cutter','unifyms':'UnifyMS + JEV'}

def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def link(p,label=None):return '['+(label or p.name)+'](<'+str(p)+'>)'
def fmt(x):return '' if x is None else f'{x:.6f}'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,default=runner.ROOT/'runs/piggy_metrics_20261103_01')
    base=parser.parse_args().run_dir.resolve()
    summary=read(base/'unifyms/summary.json')
    assert len(summary['runs'])==10 and summary['jev_requests']==1
    runner.validate(base)
    manifest=read(base/'manifest.json');snapshot=read(base/'unifyms/model-snapshot.json')
    import sys
    sys.path.insert(0,str(runner.MONO/'tools'))
    from compute_airms_metrics import parse_model
    source_services,source_entities,_,source_actors,source_ucs=parse_model(base/'input/PiggyMetrics.remodel')
    assert set(snapshot['entityNames'].values())==set(source_entities)
    assert set(snapshot['useCaseNames'].values())==set(source_ucs)
    declared_ops=sum(map(len,source_services.values()))
    extraction=read(base/'input/extraction.json');sources=read(base/'input/source-manifest.json')
    assert sha(base/'input/PiggyMetrics.remodel')==manifest['input_sha256']==extraction['model_sha256']
    assert sources['source_tree_hash']==manifest['java_source_tree_hash']
    for f in sources['java_files']:
        assert sha(Path(sources['source_directory'])/f['path'])==sha(base/'input/source-java'/f['path'])==f['sha256']
    for f in sources['mapper_xml_files']:
        assert sha(Path(sources['source_directory'])/f['path'])==sha(base/'input/source-java'/f['path'])==f['sha256']
    for f in extraction['routing_config']:
        assert sha(Path(sources['source_directory'])/f['path'])==f['sha256']
    assert sum(map(sum,snapshot['entityRelationMatrix']))==7
    assert all(f['identical'] for f in extraction['duplicate_fqn_sources'])
    assert declared_ops==len(extraction['operations'])==14
    assert all(set(snapshot['operationEntities'][o['id']])==set(o['entities']) for o in extraction['operations'])
    assert sum(not any(row) for row in snapshot['useCaseEntityMatrix'])==len(extraction['zero_entity_services'])==0
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
    selection=read(base/'unifyms/experiment/PiggyMetrics/selection-jev.json')
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
    extraction_seconds=extraction['seconds']
    unify_total=sum(phases)+extraction_seconds if all(t is not None for t in phases) else None
    mono_total=extraction_seconds+sum(timings[k] for k in ['monoembed_java_input','monoembed_decomposition'])
    token=selection.get('totalTokens') if selection.get('usageComplete') else None
    vis=base/'unifyms/report/visualizations'
    visualizations=[p for p in vis.glob('seed-*/*.req') if not p.name.startswith('._')]
    costs={'monoembed':{'total_tokens':astats['total_tokens'],'total_seconds':mono_total,
                       'input_tokens':astats['prompt_tokens'],'text_output_tokens':None,
                       'api_seconds':astats['api_seconds'],'requests':astats['api_requests'],'shared_java_extraction_seconds':extraction_seconds},
           'unifyms':{'total_tokens':token,'total_seconds':unify_total,'jev_requests':len(selection['attempts']),
                      'calibration_seconds':timings.get('unifyms_calibrate'),'selection_seconds':timings.get('unifyms_select'),
                      'formal_sum_seconds':sum(rt),'formal_mean_seconds':sum(rt)/10,'shared_java_extraction_seconds':extraction_seconds}}
    write(base/'costs.json',costs)
    cal=read(base/'unifyms/experiment/PiggyMetrics/calibration.json')
    lines=['# PiggyMetrics 案例运行结果','',
      '生成时间：'+datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')+'。','',
      '## 本轮结论与实验身份','',
      '本轮四个程序均实际运行，UnifyMS 校准后仅调用一次真实 JEV，固定选择 `'+summary['selection']+'` 再执行 10 次独立正式搜索。','',
      '- 源工程：`'+str(sources['source_directory'])+'`；88 个生产 Java 文件全部通过 AST 解析，Java 源文件集合哈希 `'+sources['source_tree_hash']+'`。逐文件原始字节、路径和 SHA-256 见 '+link(base/'input/source-manifest.json')+'。',
      '- 工程原本包含 5 个 Spring Boot 应用（account、statistics、notification、gateway、registry），属于既有微服务工程重新分组实验，不是单体系统恢复实验。',
      '- 中间模型：'+link(base/'input/PiggyMetrics.remodel')+'；SHA-256 `'+manifest['input_sha256']+'`。源码未修改。模型以 6 个 @Service 实现类为用例代理、14 个公开非静态方法为操作，13 个非枚举领域类（MongoDB 文档、嵌入值对象及 DTO）为实体。',
      '- 全局操作名加入类/模块前缀以避免同名冲突；'+link(base/'input/extraction.json','原方法路径、行号、依赖和符号映射')+' 可反查。6 个代理用例和模块角色不是人工业务用例或真实组织角色，不能冒称完整领域建模。',
      '- 4 个 Feign 方法中，2 个内部方法结合配置中的 servlet context-path、HTTP 动词及路径模板匹配成功；路径变量名差异归一化。user-service-client 与 rates-client 指向源码外服务，未伪造本地实现。根据声明类型、this.field、接口到实现、通配符导入、方法名和参数数量传播静态依赖；lambda 内调用静态计入，但不模拟异步运行或第三方内部行为。',
      '- 同名 Account、Item、Saving 按模块分别保留；它们可能表示同一业务概念的传输副本，但不是同一个 Java 类，本轮不自动合并。13 个领域类共有 48 个非静态字段；直接或泛型字段显式引用导出 7 条不同实体关联，保留原 Java 类型。枚举归并标量，标量 ID 不猜外键。全部 6 个代理有领域类依赖。',
      '- MonoEmbed API 获用户明确授权后发送 6 个业务实现类与 13 个领域类的真实 Java 内容，共 19 段，不是生成的 Java 占位实现。实际输入在 monoembed/java-input/。',
      '- 前三种方法共用修复后的公共评价器；UnifyMS 保留自己的目标公式。相同输入和实体集合仍不代表五指标公式已经统一。','',
      '## 各程序的输入转换链','',
      '| 程序 | 转换工具 | 实际输入及口径 |',
      '|---|---|---|',
      '| MicroMiner 信号适配版 | piggy_metrics_extract.py → remodel_to_microminer_input.py | Java AST/MongoDB 领域信号导出中间模型；适配器实际读取 microminer/input/PiggyMetrics.remodel。application.txt、entity.txt、utility.txt、PiggyMetrics_call_graph.csv 和类结构文件为转换辅助产物，不是原论文 KDM/CodeBERT 输入流水线。 |',
      '| MonoEmbed API 变体 | piggy_metrics_extract.py → piggy_metrics_prepare_embeddings.py | monoembed/java-input/typeData.json，包含 6 个业务实现类及 13 个领域类的真实 Java 内容；原始包名、方法实现和注释均保留，不发送通用转换器的占位代码。 |',
      '| Service Cutter 官方引擎 | piggy_metrics_servicecutter.py → piggy_metrics_servicecutter_bridge.py | servicecutter/input/ 下 ERM、用例约束和配置；48 个真实字段、6 个非空实体访问代理用例，内置 Chinese Whispers 只运行一次，原生属性簇再映射回业务类。 |',
      '| UnifyMS + JEV | piggy_metrics_extract.py → tuning.TuningCli | input/PiggyMetrics.remodel；6 个业务类用例代理、14 个全局唯一操作、13 个领域类、模块 actor 代理和 AST 依赖；由原生算法校准与搜索，不是手工业务需求模型。 |','',
      '四种转换的共同源是同一份 Java 工程快照，输入格式各自独立。源码提取、转换脚本及中间结果均保留；共同使用评价模型只为对齐实体与操作身份，并不意味着各指标公式一致。','',
      '## 五指标对比','',
      '| 方法 | MS_Num | IFN | CHD | Instability | UCM | CMQ |',
      '|---|---:|---:|---:|---:|---:|---:|']
    for m,name in NAMES.items():lines.append('| '+name+' | '+' | '.join(fmt(metrics[m][k]) for k in ['MS_Num']+KEYS)+' |')
    if any(row['MS_Num']==1 for row in summary['runs']):
        lines+=['','**本轮 UnifyMS 的代表方案包含单服务结果。原生搜索允许一个服务，IFN=0 表示没有跨服务实体接口，不能把它解释为完成了有意义的多微服务拆分。此次保留真实算法输出，没有临时增加至少两服务的约束。**']
        example=read(base/'unifyms/experiment/PiggyMetrics/run-jev-101.json')
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
    native_example=read(base/'unifyms/experiment/PiggyMetrics/run-jev-101.json')['representative']
    required=sum(len(part['requiredEntityInterfaces']) for part in native_example['services'])
    provided=sum(len(part['providedEntityInterfaces']) for part in native_example['services'])
    lines+=['','## IFN 口径核查','',
      f'前三种适配器 IFN=14 条操作声明/簇数。UnifyMS 只统计跨服务实体接口；例如 seed 101 所需接口合计 {required}、提供接口合计 {provided}，服务数 {native_example["serviceCount"]}，所以 IFN=({required}+{provided})/{native_example["serviceCount"]}={native_example["metrics"][0]:.4f}。',
      '本轮全部 6 个代理用例均有关联领域类；原生 IFN 统计跨服务实体接口，RPC 调用本身并不直接作为该指标的接口计数。接口与声明操作不是同一统计对象，不能比较两种 IFN 的绝对值。','']
    lines+=['外部汇率服务、用户服务以及异步执行没有完整运行时模型，具体静态实体边界和分组见逐次可读划分与 .req。','']
    bridge=read(base/'servicecutter/decomposition.json')
    lines+=['','Service Cutter 无原生用例责任而回退到最大属性簇的 Java 业务类：`'+json.dumps(bridge['fallback_services'],ensure_ascii=False)+'`。本轮没有业务类需要该回退，全部按原生用例责任映射。','']
    pairs=metrics['monoembed']['CMQ_details']['pairs']
    lines+=['','## CMQ 逐项复核','',
      f'按 {len(source_entities)} 个实体计算，共 {len(pairs)} 个不同实体对，其中 {sum(p["similarity"]>0 for p in pairs)} 对相似度非零。前三种适配方法的 Intra、Inter 和 CMQ 已按保存的特征与归属独立重算，误差小于 1e-12。','',
      '| 方法 | 同簇实体对数 | 异簇实体对数 | Intra_Cohesion | Inter_Coupling | CMQ |','|---|---:|---:|---:|---:|---:|']
    for m in ['microminer','monoembed','servicecutter']:
        d=metrics[m];x=d['CMQ_details'];lines.append(f'| {SHORT[m]} | {x["intra_pair_count"]} | {x["inter_pair_count"]} | {d["Intra_Cohesion"]:.9f} | {d["Inter_Coupling"]:.9f} | {d["CMQ"]:.9f} |')
    lines+=['','公共 CMQ 是词特征余弦代理，UnifyMS 是实体关系矩阵的服务内关联密度减服务间接口耦合。本轮原生关联矩阵保留 7 条显式 Java 字段引用；集合、映射值和直接引用均简化为关联，不等价完整 MongoDB 嵌入与基数语义。两套 CMQ 的绝对值不能当作统一指标比较。','',
      '## 唯一 JEV 选参与十次正式搜索','',
      f'JEV 模型：`{selection.get("actualModel")}`；真实 HTTP 请求 **1 次**；选择 **{summary["selection"]}**。',
      '固定参数：`'+json.dumps({k:v for k,v in summary['config'].items() if k!='seed'},ensure_ascii=False)+'`。',
      f'校准种子 `[11]`，正式种子 `{runner.SEEDS}`，每次实际评价上限 {cal["evaluationBudget"]:,}。名义候选 evaluationBudget=0 由上述统一上限替代。','',
      '| seed | MS_Num | IFN | CHD | Instability | UCM | CMQ | 原始输出 |','|---|---:|---:|---:|---:|---:|---:|---|']
    for row in summary['runs']:
        lines.append('| '+str(row['seed'])+' | '+' | '.join(fmt(row[k]) for k in ['MS_Num']+KEYS)+' | '+link(base/f'unifyms/experiment/PiggyMetrics/run-jev-{row["seed"]}.json','JSON')+' |')
    lines+=['','各指标样本标准差（ddof=1）：`'+json.dumps(summary['sample_std'],ensure_ascii=False)+'`。',
      '本轮十个独立种子的代表方案保存指标相同，因此标准差为 0；每次均实际执行搜索，独立命令、日志、种子与原始 JSON 已保留。',
      f'十次代表方案的服务数范围为 {min(row["MS_Num"] for row in summary["runs"])}–{max(row["MS_Num"] for row in summary["runs"])}；标准差仅反映本输入、本参数与代表方案选择规则下的变动。',
      '每次从自己的非支配解集中，按冻结校准归一化空间到理想点最近的规则取代表方案，再对十个代表方案取算术平均。不是挑最好的一次，也不把十个前沿合并另选。',
      '搜索库将目标值保留四位小数，本报告平均的是保存的原生数值，六位小数仅为展示。','',
      '| 校准配置 | N | 名义 G | 交叉概率 | crossP | 校准 HV |','|---|---:|---:|---:|---:|---:|']
    for cid,entry in sorted(cal['candidates'].items()):
        c=entry['config'];lines.append(f'| {cid} | {c["populationSize"]} | {c["generations"]} | {c["crossoverProbability"]} | {c["crossP"]} | {entry["meanHv"]:.12f} |')
    lines+=['','没有额外执行默认配置的十次配对对照，不能据本表宣称 JEV 的因果收益或统计显著改善。','',
      '## Token 与总耗时','',
      '| 方法 | 总 token | 总耗时（秒） | 计量范围 |','|---|---:|---:|---|',
      f'| MonoEmbed API | {astats["total_tokens"]} | {mono_total:.6f} | 源码 AST 提取 + 实际 Java 输入准备 + 向量 API、标准化、聚类及保存；不含五指标评估。 |',
      f'| UnifyMS + JEV | {token if token is not None else ""} | {fmt(unify_total)} | 源码 AST 提取 + 六组校准 + JEV 一次 + 正式拆分十次；不含构建和绘图。 |','',
      f'- MonoEmbed：实际请求 {astats["api_requests"]} 次，无缓存命中；共 {n} 段输入、{chars} 个字符；输入 token {astats["prompt_tokens"]}，没有文本生成输出 token（输出为数值向量）。',
      f'- API 纯请求墙钟耗时（含网络及解析）{astats["api_seconds"]:.6f} 秒；内部总耗时 {astats["total_seconds"]:.6f} 秒。总 token 与保存的原始 usage 已核对。',
      f'- UnifyMS：校准 {timings["unifyms_calibrate"]:.6f} 秒；JEV 选择进程 {timings["unifyms_select"]:.6f} 秒；十次正式拆分合计 {sum(rt):.6f} 秒，均值 {sum(rt)/10:.6f} 秒。',
      '- JEV 没有完整 usage 时总 token 按要求留空，不能用 knownTokens=0 代替。token 仅统计本轮请求。',
      f'- 共享源码 AST 提取耗时 {extraction_seconds:.6f} 秒，在每种方法的独立运行范围各计一次；整组实验墙钟时间不应将共享步骤重复相加。',
      '- 累计耗时是上述程序阶段的实测时间，不含等待授权、适配器开发、诊断轮次和报告整理时间。',
      '- 两者运行次数和工作量不同，累计耗时不是公平的单次效率排名；进程启动、依赖加载和系统缓存状态也影响耗时。','',
      '## 输入输出、图与验证','',
      '| 方法 | 输入 | 划分输出 | 指标 |','|---|---|---|---|']
    for m in ['microminer','monoembed','servicecutter']:
        lines.append('| '+NAMES[m]+' | '+link(base/m/('java-input' if m=='monoembed' else 'input'))+' | '+link(base/m/'decomposition.json')+' | '+link(base/m/'metrics.json')+' |')
    lines.append('| UnifyMS + JEV | '+link(base/'unifyms/model-snapshot.json')+' | '+link(base/'unifyms/experiment/PiggyMetrics','十次 JSON 和 trials')+' | '+link(base/'unifyms/summary.json')+' |')
    lines+=['',f'严格源实体集合校验下，本轮保存的 .req 文件数为 **{len(visualizations)}**。','',
      '- '+link(base/'unifyms/report/analysis.md','UnifyMS 原生报告与十次图'),
      '- '+link(base/'unifyms/partitions','十次可读服务划分'),
      '- '+link(base/'monoembed/api_response','API 请求体、向量与 usage（不含凭据）'),
      '- '+link(base/'servicecutter/solver_result.json','Service Cutter Engine 原始结果'),
      '- '+link(base/'unifyms/experiment/PiggyMetrics/selection-jev.json','唯一 JEV 请求及响应'),
      '- '+link(base/'logs','原始命令、日志与阶段耗时'),
      '- '+link(base/'validation.json','操作完整归属、实体一致性和十次接口复算验证'),
      '- '+link(base/'input/extraction.json','Java AST 提取规则、原方法和实体映射'),
      '- '+link(base/'input/method-graph.json','完整静态方法依赖图'),
      '- '+link(base/'input/source-java','原始 Java 输入副本与 POM'),
      '- '+link(base/'protocol','代码快照与 UnifyMS Java 补丁'),
      '- '+link(base/'manifest.json','输入和协议哈希'),'- '+link(base/'costs.json','机器可读消耗汇总'),'']
    lines+=['## 方法和指标口径限制','',
      '- MicroMiner 为 Java AST 信号通过中间模型驱动的适配器，按业务类建候选簇；不是原始 Java/KDM + CodeBERT/Word2Vec + Louvain 实现。',
      '- MonoEmbed 使用真实 Java 业务类与实体源码的百炼 embedding API，再 StandardScaler 与 Affinity Propagation；不是论文微调编码器。Controller、工具类、未选定为实体的 VO 不作为独立聚类单元，动态运行数据未采集。',
      f'- Service Cutter 使用官方 Engine 内置 Chinese Whispers，cwNodeWeighting=0，不指定全局簇数，实际返回 {metrics["servicecutter"]["MS_Num"]} 簇。原生字段簇完整保留，未手工合并。',
      '- Service Cutter 桥接器按 Java 业务类代理名称匹配原生用例责任，本轮操作分布为 '+str([part['provided_interface'] for part in metrics['servicecutter']['microservices']])+'；无操作簇不能解释为独立功能服务。',
      '- Service Cutter 正式 ERM 使用 48 个实际字段、7 条显式字段关联、6 个非空实体访问代理用例；实体级访问保守展开到全部属性。预先固定 Chinese Whispers，cwNodeWeighting=0，仅执行一次，不指定全局簇数，也不按输出质量择优。未推测团队所有权。',
      '- 三个适配器的 IFN=声明操作数/全部簇数，包含无操作簇；UnifyMS IFN=所需与提供实体接口计数之和/服务数，不能横向比较其绝对值。',
      '- 公共 CHD 包含自身操作对、平均有操作簇；UnifyMS 排除自身且单操作记 1。公共 Instability 为启发式 Required/(Provided+Required)；UnifyMS 为 ProvidedEntityInterfaces/(RequiredEntityInterfaces+ProvidedEntityInterfaces)，无所需接口记 1，并最大化。',
      '- 公共 UCM 不依赖划分且 CorrF=0；完整用例控制流尚未建模。UnifyMS UCM 为服务内用例内聚减跨服务耦合，本轮 actor 由源码模块代理，会引入现有模块边界先验，不能等同真实用户用例内聚。',
      '- 模型标量字段归并为 Integer/Real/Date/String，枚举作为标量；集合和 Map 中的领域类型转为显式 Association，原始字段、泛型类型和模块限定名均保留在 extraction.json。重复的 16 份 cathelper 类与首份内容一致，方法图只保留一份，88 个原始文件副本均保留；这些公共追踪辅助类不作为聚类输入。',
      '- 公共 CMQ 采用 v2 词特征余弦，重叠实体仍按最后簇归属；模块前缀进入实体名词特征，可能带入已有模块边界先验。UnifyMS 是实体关系矩阵模块度。不同评估器的目标方向与计算对象不同，表格仅按数值排序。',
      '- 本轮原生解析器的 14 个操作—实体集合均与 AST 可达集合核对一致。中间 Contract 仅表达静态依赖，result=true 是结构语法占位，不能当作实际业务后置条件。','',
      '## 各簇操作数量','']
    for m in ['microminer','monoembed','servicecutter']:
        nums=[x['provided_interface'] for x in metrics[m]['microservices']]
        lines.append(f'- {SHORT[m]}：`{nums}`，合计 {sum(nums)}；无操作簇 {nums.count(0)} 个。')
    report=base/'PiggyMetrics案例运行结果.md';report.write_text('\n'.join(lines)+'\n')
    manifest.update(status='completed',formal_runs_completed=10,jev_requests=1,strict_req_exports=len(visualizations))
    write(base/'manifest.json',manifest)
    print(json.dumps({'report':str(report),'means':summary['mean'],'costs':costs,'strict_req_exports':len(visualizations)},ensure_ascii=False))

if __name__=='__main__':main()
