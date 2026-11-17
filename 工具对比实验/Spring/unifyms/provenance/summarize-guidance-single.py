#!/usr/bin/env python3
"""Summarize exactly ten measured LLM+JEV runs; no search, evaluation or API calls."""
import argparse
from collections import Counter
import csv
import datetime
import hashlib
import json
from pathlib import Path
import statistics

METRICS = ['IFN', 'CHD', 'CMQ', 'Instability', 'UCM']
DISPLAY = ['IFN', 'CHD', 'Instability', 'UCM', 'CMQ']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def describe(values):
    if len(values) != 10:
        raise ValueError('Exactly ten measured values are required')
    return dict(mean=statistics.mean(values), sampleStandardDeviation=statistics.stdev(values),
                minimum=min(values), maximum=max(values))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def link(path, label=None):
    return '['+(label or Path(path).name)+'](<'+str(Path(path).resolve())+'>)'


def audit_complete(summary, index_name):
    root = Path(summary['auditDirectory']).resolve()
    index = root/index_name
    if sha(index) != summary['auditIndexSha256']:
        raise ValueError('Audit index hash mismatch: '+str(index))
    for name, expected in read(index).items():
        path = (root/name).resolve()
        if root not in path.parents or sha(path) != expected:
            raise ValueError('Audit file hash mismatch: '+str(path))


def usage_total(groups):
    values = [g.get('totalTokens') for g in groups]
    return None if any(v is None for v in values) else sum(values)


def build(study):
    study = Path(study).resolve()
    cfg = read(study/'run-config.json')
    seeds = cfg['validationSeeds']
    if len(seeds) != 10 or len(set(seeds)) != 10:
        raise ValueError('Exactly ten distinct configured formal seeds are required')
    if cfg['guidance']['mode'] != 'jev' or cfg['onlineControl']['mode'] != 'jev':
        raise ValueError('Only probability control + LLM generation + JEV selection is supported')
    case = cfg['systems'][0]['id']
    directory = study/'experiment'/case
    calibration = read(directory/'calibration.json')
    selection = read(directory/'selection-jev.json')
    if selection['status'] != 'success' or selection.get('mock') is not False:
        raise ValueError('Real successful offline JEV choice required')
    chosen = selection['choice']
    table = {c['id']:c for c in cfg['candidates']}
    initial = table[chosen]
    report = study/'report'
    if not (report/'analysis.md').exists():
        raise ValueError('Export all ten results before summarizing')
    source_hash = read(study/'experiment/manifest.json')['implementationHash']
    records, llm, jev, probability = [], [], [], []
    rejections, stop_reasons, probability_actions, shortfalls = Counter(), Counter(), Counter(), Counter()
    windows = selected = retained = extra_evaluations = proposals = eligible = 0
    for seed in seeds:
        source = directory/'online-jev/guidance-jev'/f'run-jev-{seed}.json'
        r = read(source)
        run = r['run']
        if run['status'] != 'success' or run['config']['seed'] != seed or run['config']['id'] != chosen:
            raise ValueError('Mismatched or failed run: '+str(source))
        if run['inputHash'] != calibration['inputHash'] or run['metricVersion'] != calibration['metricVersion']:
            raise ValueError('Input/metric version mismatch')
        for field in ('populationSize','generations','crossoverProbability','crossP'):
            if run['config'][field] != initial[field]:
                raise ValueError('Initial configuration differs: '+field)
        if run['completedGenerations'] != initial['generations'] or run['config']['evaluationBudget'] != 0:
            raise ValueError('Nominal generations were not completed')
        g, p = run['guidance'], run['onlineControl']
        if g['mode'] != 'jev' or p['mode'] != 'jev':
            raise ValueError('Unexpected formal arm')
        audit_complete(g, 'guidance-files.json')
        audit_complete(p, 'audit-files.json')
        manifest = read(Path(g['auditDirectory'])/'guidance-manifest.json')
        binding = manifest['binding']
        if binding['policy']['lossTolerance'] != cfg['guidance']['lossTolerance'] or binding['context']['implementationHash'] != source_hash:
            raise ValueError('Tolerance or implementation hash mismatch')
        if binding['context']['inputHash'] != calibration['inputHash']:
            raise ValueError('Audit input mismatch')
        if g['windowCount'] != (initial['generations']-1)//10:
            raise ValueError('Incomplete observation windows')
        llm.append(g['llm']); jev.append(g['jev']); probability.append(p)
        windows += g['windowCount']; selected += g['selectedCount']; retained += g['retainedCount']; extra_evaluations += g['candidateEvaluations']
        per_windows = sorted(Path(g['auditDirectory']).glob('window-*.json'))
        if len(per_windows) != g['windowCount']:
            raise ValueError('Missing window audit files')
        for window in map(read, per_windows):
            shortfalls[window.get('selectedMetric') or 'unrankable'] += 1
            if window.get('skipReason'): stop_reasons[window['skipReason']] += 1
            for candidate in window['candidates']:
                proposals += 1
                if candidate['status'] == 'eligible': eligible += 1
                elif candidate['status'] == 'rejected': rejections[candidate['rejection']] += 1
        for line in (Path(p['auditDirectory'])/'control-decisions.jsonl').read_text().splitlines():
            if line.strip(): probability_actions[json.loads(line)['action']] += 1
        vis = report/'visualizations'/f'seed-{seed}'
        stem = Path(cfg['systems'][0]['input']).stem
        required = {suffix:vis/(stem+suffix) for suffix in ('.req','-merm.html','-domain.svg','-usecases.svg','-diagnostics.json')}
        if any(not path.is_file() for path in required.values()):
            raise ValueError('Missing per-run visualization output')
        diagnostics = read(required['-diagnostics.json'])
        if any(d['severity'] == 'error' for d in diagnostics['diagnostics']):
            raise ValueError('Export diagnostics have errors')
        values = r['representative']['metrics']
        records.append(dict(seed=seed, configuration=chosen, serviceCount=r['representative']['serviceCount'],
                            **dict(zip(METRICS, values)), hv=r['hv'], evaluations=run['evaluations'],
                            completedGenerations=run['completedGenerations'], candidateEvaluations=g['candidateEvaluations'],
                            selectedCount=g['selectedCount'], retainedCount=g['retainedCount'],
                            llmRequests=g['llm']['requestCount'], llmFailures=g['llm']['failureCount'],
                            selectionRequests=g['jev']['requestCount'], selectionFailures=g['jev']['failureCount'],
                            selectionLocalBudgetRejections=g['jev'].get('localBudgetRejectedCount',0),
                            probabilityRequests=p['requestCount'], probabilityFallbacks=p['fallbackCount'],
                            sourceFile=str(source), req=str(required['.req']), html=str(required['-merm.html']),
                            domainSvg=str(required['-domain.svg']), useCasesSvg=str(required['-usecases.svg'])))
    metric_stats = {m:describe([r[m] for r in records]) for m in METRICS}
    stats = dict(sampleCount=10, seeds=seeds, arm='jev', lossTolerance=cfg['guidance']['lossTolerance'],
                 inputHash=calibration['inputHash'], implementationHash=source_hash, offlineChoice=chosen,
                 initialConfiguration=initial, metricVersion=calibration['metricVersion'],
                 metrics=metric_stats, serviceCount=describe([r['serviceCount'] for r in records]),
                 hv=describe([r['hv'] for r in records]), evaluations=describe([r['evaluations'] for r in records]),
                 totalEvaluations=sum(r['evaluations'] for r in records), extraCandidateEvaluations=extra_evaluations,
                 windows=windows, proposals=proposals, eligibleCandidates=eligible, selectedCount=selected,
                 retainedCount=retained, retentionRate=None if selected == 0 else retained/selected,
                 rejections=dict(rejections), skippedWindows=dict(stop_reasons), shortfalls=dict(shortfalls),
                 probabilityActions=dict(probability_actions),
                 llm=dict(requestCount=sum(g['requestCount'] for g in llm), failureCount=sum(g['failureCount'] for g in llm),totalTokens=usage_total(llm)),
                 selectionJev=dict(requestCount=sum(g['requestCount'] for g in jev),failureCount=sum(g['failureCount'] for g in jev),localBudgetRejectedCount=sum(g.get('localBudgetRejectedCount',0) for g in jev),totalTokens=usage_total(jev)),
                 probabilityJev=dict(requestCount=sum(g['requestCount'] for g in probability),fallbackCount=sum(g['fallbackCount'] for g in probability),totalTokens=usage_total(probability)),
                 runs=records)
    (report/'ten-run-summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n')
    with (report/'ten-run-details.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        w = csv.DictWriter(stream,fieldnames=list(records[0])); w.writeheader(); w.writerows(records)
    cells = [stats['serviceCount']['mean']]+[metric_stats[m]['mean'] for m in DISPLAY]+[stats['hv']['mean']]
    timestamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
    lines = [f'# {case}：LLM 生成＋JEV 优选组，{cfg["guidance"]["lossTolerance"]} 门槛，10 次正式结果','',
             f'生成时间：{timestamp}。仅汇总本组，未混入已有概率基线组或数值筛选组。','',
             f'固定离线初始配置：**{chosen}**；N={initial["populationSize"]}、G={initial["generations"]}、初始 p_var={initial["crossoverProbability"]}、crossP={initial["crossP"]}。复用同版本已完成的一次真实离线 JEV 选择，十次正式运行不重复离线选参。',
             f'正式种子：`{seeds}`。每次保留在线概率控制，小模型定向生成候选，JEV 综合两项一致性证据和真实指标代价无放回优选。','',
             f'其他四指标允许的归一化损失增量上限：**{stats["lossTolerance"]}**，相对每次运行首个引导窗口冻结参考；不是原始指标的 50%。目标指标仍须严格改善，固定服务数与合法性校验保留。','',
             '## 1. 十次算术平均','',
             '|方法|平均 MS_Num|IFN ↓|CHD ↑|Instability ↑|UCM ↑|CMQ ↑|HV ↑|',
             '|---|---:|---:|---:|---:|---:|---:|---:|',
             '|LLM 生成＋JEV 优选（保留概率控制）|'+'|'.join(f'{v:.10f}' for v in cells)+'|','',
             '五指标分别对十个运行的代表方案取平均；HV 对十次完整非支配解集的 HV 取平均。没有对染色体取平均，也不存在一张代表这些均值的平均拆分图。','',
             '## 2. 样本标准差与范围','',
             '|指标|均值|样本标准差|最小值|最大值|','|---|---:|---:|---:|---:|']
    for name, d in [('MS_Num',stats['serviceCount'])]+[(m,metric_stats[m]) for m in DISPLAY]+[('HV',stats['hv'])]:
        lines.append('|'+name+'|'+'|'.join(f'{d[f]:.10f}' for f in ('mean','sampleStandardDeviation','minimum','maximum'))+'|')
    lines += ['', '## 3. 十次独立结果','',
              '|种子|MS_Num|IFN|CHD|Instability|UCM|CMQ|HV|评价次数|候选入选／留存|','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in records:
        lines.append('|'+str(r['seed'])+'|'+str(r['serviceCount'])+'|'+'|'.join(f'{r[m]:.8f}' for m in DISPLAY+['hv'])+'|'+str(r['evaluations'])+'|'+str(r['selectedCount'])+'/'+str(r['retainedCount'])+'|')
    lines += ['', '## 4. 真实生成、选择和开销','',
              f'总观察窗口 {windows}；生成候选 {proposals}；通过程序门槛 {eligible}；本批入选 {selected}；下一代正常环境选择留存 {retained}。留存率为 '+('不可估计（没有入选候选）' if selected==0 else f'{retained/selected:.2%}')+'。',
              f'实际总评价次数 {stats["totalEvaluations"]}；其中候选额外评价 {extra_evaluations}。均按各自配置的名义代数完成；调用与额外评价开销单独列出。','',
              '|模块|实际请求数|失败／回退数|取得的总 tokens|','|---|---:|---:|---:|']
    for name, key, failure in [('生成小模型','llm','failureCount'),('一致性与代价优选 JEV','selectionJev','failureCount'),('在线概率控制 JEV','probabilityJev','fallbackCount')]:
        g=stats[key];lines.append(f'|{name}|{g["requestCount"]}|{g[failure]}|'+('未知（接口 usage 不完整）' if g['totalTokens'] is None else str(g['totalTokens']))+'|')
    lines += ['', '调用失败后按既定回退继续搜索的运行也如实计入十次结果；不会挑选最好的一次或用失败次数补造样本。概率控制与优选 JEV 分别计数，未知 tokens 不记为零。',
              '', '### 程序拒绝原因','', '|拒绝原因|次数|','|---|---:|']
    for reason,count in sorted(rejections.items()): lines.append('|'+reason+'|'+str(count)+'|')
    if not rejections: lines.append('|无|0|')
    lines += ['', '以上是程序生成的证据说明，不是 JEV 返回的自然语言理由；两项检查是用例—操作、操作—实体一致性。跨服务依赖不自动判为冲突，四层模型未表达的行为不作推断。','',
              '## 5. 每次输出与拆分图','',
              '|种子|原始五指标与解集|REQ|交互拆分图|实体接口 SVG|用例 SVG|','|---|---|---|---|---|---|']
    for r in records:
        lines.append('|'+str(r['seed'])+'|'+'|'.join(link(r[k]) for k in ('sourceFile','req','html','domainSvg','useCasesSvg'))+'|')
    lines += ['', f'浏览器打开各行 `{stem}-merm.html` 即可离线查看；同目录 `.req` 为该次真实代表方案，SVG 可用于排版。',
              '', '## 6. 数据与复用','',
              '- 完整统计：'+link(report/'ten-run-summary.json')+'。',
              '- 十次逐行指标与文件路径：'+link(report/'ten-run-details.csv')+'。',
              '- 六组校准、初始配置选择及运行分析：'+link(report/'analysis.md')+'。',
              '- 运行配置：'+link(study/'run-config.json')+'；批次状态：'+link(study/'study-status.json')+'。',
              '- 每次生成、拒绝、JEV Choice、概率轨迹与留存证据均在该次 run JSON 指向的审计目录内。',
              '', '本报告只有一个方法组，不能单凭十次均值宣称优于其他方法；未混用旧 0.02 单种子结果，未将候选优选解释为全局最优或行为等价证明。']
    destination=report/'ten-run-results.md';destination.write_text('\n'.join(lines)+'\n')
    return destination


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('study',type=Path);args=p.parse_args();print(build(args.study))
