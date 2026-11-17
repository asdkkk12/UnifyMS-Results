"""Validate completed Spring experiments and write a report; makes no API requests."""
import hashlib,json,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import run_spring_comparison as r
KEYS=['IFN','CHD','Instability','UCM','CMQ']
NAMES={'microminer':'MicroMiner Java AST 信号适配版','monoembed':'MonoEmbed 百炼 API 真实源码变体','servicecutter':'Service Cutter Engine + Java 结果适配','unifyms':'UnifyMS + JEV（10 次均值，原生口径）'}
SHORT={'microminer':'MicroMiner','monoembed':'MonoEmbed','servicecutter':'Service Cutter','unifyms':'UnifyMS + JEV'}
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def link(p,label=None):return '['+(label or p.name)+'](<'+str(p)+'>)'
def f(v):return '' if v is None else f'{v:.6f}'

def main():
 b=r.DEFAULT;x=read(b/'input/extraction.json');src=read(b/'input/source-manifest.json');manifest=read(b/'manifest.json');snap=read(b/'unifyms/model-snapshot.json');summary=read(b/'unifyms/summary.json')
 assert len(x['operations'])==359 and len(x['services'])==66 and len(x['entities'])==58
 assert len(summary['runs'])==10 and summary['jev_requests']==1
 assert sha(b/'input/Spring.remodel')==manifest['input_sha256']==x['model_sha256']
 for item in src['java_files']+src['pom_files']+src.get('mapper_xml_files',[]):
  assert sha(Path(src['source_directory'])/item['path'])==sha(b/'input/source-java'/item['path'])==item['sha256']
 assert all(set(snap['operationEntities'][o['id']])==set(o['entities']) for o in x['operations'])
 assert len(snap['useCaseNames'])==66 and len(snap['entityNames'])==58
 assert sum(not any(row) for row in snap['useCaseEntityMatrix'])==len(x['zero_entity_services'])==18
 assert sum(map(sum,snap['entityRelationMatrix']))==0
 r.validate(b)
 validation=read(b/'validation.json')
 metrics={m:read(b/m/'metrics.json') for m in ['microminer','monoembed','servicecutter']}
 from itertools import combinations
 for m,d in metrics.items():
  detail=d['CMQ_details'];features={q:set(v) for q,v in detail['features'].items()};owners=detail['effective_entity_clusters'];inside=[];outside=[]
  assert set(features)==set(snap['entityNames'].values())
  for a,c in combinations(features,2):
   value=len(features[a]&features[c])/(len(features[a])*len(features[c]))**.5
   (inside if a in owners and owners.get(a)==owners.get(c) else outside).append(value)
  intra=sum(inside)/len(inside) if inside else 0;inter=sum(outside)/len(outside) if outside else 0
  assert abs(intra-d['Intra_Cohesion'])<1e-12 and abs(inter-d['Inter_Coupling'])<1e-12 and abs(intra-inter-d['CMQ'])<1e-12
  assert d['provided_interface_total']==359
 metrics['unifyms']=summary['mean'];selection=read(b/'unifyms/experiment/Spring/selection-jev.json')
 assert selection['status']=='success' and selection['mock'] is False and len(selection['attempts'])==1
 stats=read(b/'monoembed/decomposition.stats.json');requests=read(b/'monoembed/api_response/requests.json')
 assert stats['status']=='completed' and stats['usage_complete'] and stats['cache_hits']==0 and stats['api_requests']==len(requests)==13
 responses=[p for p in (b/'monoembed/api_response').glob('*.json') if not p.name.startswith('._') and p.name not in ['request.json','requests.json']]
 assert sum(read(p)['usage']['total_tokens'] for p in responses)==stats['total_tokens']
 for request in requests:
  digest=hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False).encode()).hexdigest();assert (b/'monoembed/api_response'/(digest+'.json')).exists()
 records=read(b/'monoembed/java-input/typeData.json');assert [record['content'] for record in records]==sum([v['payload']['input'] for v in requests],[]) and len(records)==124
 timings={p.stem:read(p).get('seconds') for p in (b/'logs').glob('*.json') if not p.name.startswith('._')}
 formal_times=[timings['unifyms_run_'+str(seed)] for seed in r.SEEDS];formal_wall=timings['unifyms_formal_wall']
 aborted_phases={}
 aborted=sum(aborted_phases.values())
 valid_total=x['seconds']+timings['unifyms_calibrate']+timings['unifyms_select']+formal_wall
 mono_total=x['seconds']+timings['monoembed_java_input']+timings['monoembed_decomposition']
 token=selection.get('totalTokens') if selection.get('usageComplete') else None
 costs={'monoembed':{'total_tokens':stats['total_tokens'],'input_tokens':stats['prompt_tokens'],'text_output_tokens':None,'total_seconds':mono_total,'api_seconds':stats['api_seconds'],'requests':stats['api_requests'],'shared_java_extraction_seconds':x['seconds']},'unifyms':{'total_tokens':token,'total_seconds':valid_total+aborted,'completed_experiment_wall_seconds':valid_total,'aborted_initial_calibration_seconds':aborted,'aborted_phases':aborted_phases,'calibration_wall_seconds':timings['unifyms_calibrate'],'selection_seconds':timings['unifyms_select'],'formal_wall_seconds':formal_wall,'formal_sum_command_seconds':sum(formal_times),'formal_mean_command_seconds':sum(formal_times)/10,'formal_thread_pool_max':2,'calibration_worker_max':2,'calibration_orchestration_record':'unifyms/orchestration/controller.json','jev_requests':1,'shared_java_extraction_seconds':x['seconds']}}
 r.write(b/'costs.json',costs)
 scheduler=read(b/'unifyms/orchestration/controller.json');assert scheduler['resumed']
 equivalence=read(b/'unifyms/optimization-check/equivalence-all.json');assert equivalence['cases']==512 and equivalence['bitwise_equal'] and equivalence['all_five_objectives_and_interfaces']
 reqs=[p for p in (b/'unifyms/report/visualizations').glob('seed-*/*.req') if not p.name.startswith('._')];assert len(reqs)==10
 cal=read(b/'unifyms/experiment/Spring/calibration.json');assert cal['evaluationBudget']==1802000
 inherited=sum(o['inherited'] for o in x['operations']);fields=sum(len(e['fields']) for e in x['entities']);inherited_fields=sum(v['inherited'] for e in x['entities'] for v in e['fields'])
 bridge=read(b/'servicecutter/decomposition.json');assert len(bridge['fallback_services'])==18
 lines=['# Spring-cloud-shop 案例运行结果','', '生成时间：'+datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')+'。','',
 '本轮四种程序均实际执行。UnifyMS 六组正式预算校准后，只请求一次真实 JEV，固定所选参数，再实际运行十个独立正式种子并取均值。','',
 '## 输入与转换范围','',
 '- 原工程：`'+src['source_directory']+'`，原文件未修改；767 个生产 Java 文件全部通过 javalang 解析，54 份 POM 用于模块依赖解析。源码是既有 Spring Cloud 微服务工程，实验是重新分组，不是恢复单体边界。',
 '- 中间模型：'+link(b/'input/Spring.remodel')+'；SHA-256 `'+manifest['input_sha256']+'`。'+link(b/'input/source-manifest.json','逐文件源码与 POM 哈希')+'、'+link(b/'input/extraction.json','原方法、字段与模块映射')+' 均保留。',
 f'- 以 66 个 @Service 类为用例代理，359 个公开源码实现为操作（类内声明 {359-inherited} 个，源码可展开的继承实现 {inherited} 个），58 个 BaseMapper/Repository 泛型或 TableName/Document 标注类为持久化实体。实体有 {fields} 个有效非静态字段，其中 {inherited_fields} 个从项目源码父类展开；来源逐字段可查。',
 '- 同包同名类按 Maven 模块隔离，先匹配本模块，再依赖、同业务组和唯一全局定义；没有按 FQN 覆盖同名业务类。未报告多候选歧义，但这仍是静态解析器，不等同 Java 编译器。类名和操作名加入模块前缀。',
 '- Mapper XML 作为辅助源码快照保留；本轮没有从 SQL JOIN 或表名推断额外实体访问，方法图依据 Java 类型、Mapper 泛型及可解析调用。',
 '- 泛型公共 CRUD 基类和接口 default 方法按实参展开，覆盖按名称与参数类型处理；调用边仍按名称/参数数量保守匹配，并解析 this.field、接口实现与同类方法引用。外部库、Lombok 生成的方法体、完整重载分派与链式返回值没有合成。',
 '- 公开方法统计包含 getBaseMapper 等辅助实现，不等同真实业务 API 数量；本案例的继承展开规则也不能被忽略。',
 '- 92 个 Feign 方法中 51 个按常量服务名、HTTP 动词与路径模板匹配到本地 Controller；其余 41 个保留为未解析。源码中确有注释端点、方法不一致和 return null 的占位实现，不虚构其行为。',
 '- 18 个业务类未关联选定持久化实体，其中 7 个没有可展开的源码公开实现；名单见 extraction.json。这可能来自空实现、外部基类、外部存储或解析覆盖缺口，不能解释成真实系统没有依赖。',
 '- 源码存在大量标量 *Id；没有据名称推断外键。选定实体无显式实体类型字段关联，因此原生实体关联矩阵为零。321 个继承字段会影响公共词特征相似度。',
 '- 用例和 actor 是业务类、模块结构代理，不是手工业务需求或真实组织角色。Contract 中 result=true 仅为结构语法占位，不是实际业务后置条件。','',
 '| 方法 | 输入转换与实际输入 |','|---|---|',
 '| MicroMiner Java AST 信号适配版 | spring_extract.py → remodel_to_microminer_input.py；核心实际读取 microminer/input/Spring.remodel。CSV、txt 与类结构代码是辅助产物，不是论文 KDM/CodeBERT 完整流水线。 |',
 '| MonoEmbed API 变体 | spring_prepare_embeddings.py；monoembed/java-input/typeData.json 包含用户授权的 66 个业务类与 58 个持久化类原文。每类一个向量；源码中父类引用保留，但未额外注入父类源文。然后 StandardScaler → Affinity Propagation。 |',
 '| Service Cutter 官方 Engine | spring_servicecutter.py；真实 645 字段 ERM、48 个非空实体访问代理用例及固定 Chinese Whispers 配置。实体访问保守展开到全部字段；原生字段簇通过用例责任映射到业务类。 |',
 '| UnifyMS + JEV | tuning.TuningCli 读取 input/Spring.remodel；六组候选校准，一次 JEV 选参，十个固定参数种子搜索。与 MonoEmbed 原始类文本相比，派生模型展开了源码继承方法和字段。 |','',
 '## 五指标对比','',
 '| 方法 | MS_Num | IFN | CHD | Instability | UCM | CMQ |','|---|---:|---:|---:|---:|---:|---:|']
 for m,name in NAMES.items():lines.append('| '+name+' | '+' | '.join(f(metrics[m][k]) for k in ['MS_Num']+KEYS)+' |')
 lines+=['','## 五指标排序','', '按展示的六位小数判定并列。IFN、Instability 升序，CHD、UCM、CMQ 降序；这是数值排序，部分公式不同，不能作为统一的方法优劣排名。','', '| 指标 | 排序口径 | 表内数值顺序 |','|---|---|---|']
 for k in KEYS:
  groups={};desc=k in ['CHD','UCM','CMQ']
  for m,d in metrics.items():groups.setdefault(round(d[k],6),[]).append(SHORT[m])
  lines.append('| '+k+' | 数值'+('降序' if desc else '升序')+' | '+' → '.join(' = '.join(groups[v])+f'（{v:.6f}）' for v in sorted(groups,reverse=desc))+' |')
 example=read(b/'unifyms/experiment/Spring/run-jev-101.json')['representative'];needed=sum(len(s['requiredEntityInterfaces']) for s in example['services']);provided=sum(len(s['providedEntityInterfaces']) for s in example['services'])
 lines+=['','## 指标口径与复核','',
 f'- 三个适配器 IFN=359 条声明操作/全部簇数，包含无操作簇；UnifyMS IFN=(所需+提供实体接口)/服务数。seed 101 为 ({needed}+{provided})/{example["serviceCount"]}={example["metrics"][0]:.4f}。原生 IFN 不直接计数全部 RPC 接口。',
 '- 公共 CHD 包含自身操作对并平均有操作簇；原生 CHD 排除自身、单操作记 1。公共 Instability=启发式 Required/(Provided+Required)，原生为 ProvidedEntityInterfaces/(RequiredEntityInterfaces+ProvidedEntityInterfaces)，无所需接口记 1，目标为最大化；表格升序仅为统一展示。',
 '- 公共 UCM 不依赖划分且 CorrF=0，故三工具相同。UnifyMS UCM 为用例内聚减跨服务耦合；本轮模块角色代理带入现有模块边界先验。',
 '- 公共 CMQ 为实体名和字段词特征余弦的同簇均值减异簇均值；模块前缀和继承字段会影响结果，重叠实体按最后簇归属。原生 CMQ 来自实体关联矩阵及接口耦合；本轮矩阵为零，不能当成真实业务无实体关系的证据。',
 '- 原生 QualityCalculate.Modilarity 还有历史计数缺陷：遇到空实体服务对时 continue，临时计数 tempp 未清零，带入后续非空服务对。本轮保留该真实实现；已按 Ob3 的原始分组顺序复算并核对保存值。CMQ 排序包含该行为，不能据此判定算法优劣。',
 '- 58 个实体的 1,653 个不同实体对已逐对独立复算公共 CMQ，误差小于 1e-12；原生 359 个操作—实体集合全部与 AST 核对，十次实体/用例归属以及 IFN、Instability 均独立复算。','',
 '| 方法 | 同簇实体对 | 异簇实体对 | Intra | Inter | CMQ |','|---|---:|---:|---:|---:|---:|']
 for m in ['microminer','monoembed','servicecutter']:
  d=metrics[m];detail=d['CMQ_details'];lines.append(f'| {SHORT[m]} | {detail["intra_pair_count"]} | {detail["inter_pair_count"]} | {d["Intra_Cohesion"]:.9f} | {d["Inter_Coupling"]:.9f} | {d["CMQ"]:.9f} |')
 lines+=['','### 原生 CMQ 历史计数诊断','',
 '下表只用于定位缺陷，主表与排序仍使用原程序保存的 CMQ；局部清零诊断值不是新统一评价器。原实现见 '+link(b/'unifyms/optimization-check/QualityCalculate.original.java')+' 的 Modilarity 方法。','',
 '| seed | 原生保存 CMQ | 原逻辑复算 | 每对独立清零诊断 | 空实体服务数 |','|---|---:|---:|---:|---:|']
 for check in validation['methods']['unifyms']['per_run']:
  row=next(v for v in summary['runs'] if v['seed']==check['seed'])
  lines.append(f'| {check["seed"]} | {row["CMQ"]:.6f} | {check["CMQ_legacy_recomputed"]:.9f} | {check["CMQ_pair_local_diagnostic"]:.9f} | {check["zero_entity_services"]} |')
 lines+=['','Service Cutter 预先固定官方 Chinese Whispers、cwNodeWeighting=0，不指定目标簇数，只运行一次；645 个字段原生归属完整无重复，未手工合并字段簇。18 个没有原生用例责任的业务类回退到最大字段簇，名单见 decomposition.json；这些回退不是引擎从数据访问推导出的边界。','']
 for m in ['microminer','monoembed','servicecutter']:
  nums=[c['provided_interface'] for c in metrics[m]['microservices']];lines.append(f'- {SHORT[m]} 各簇操作数：`{nums}`；合计 {sum(nums)}，无操作簇 {nums.count(0)} 个；无操作簇不能解释为独立功能服务。')
 lines+=['','## 一次 JEV 与十次正式运行','',f'JEV 实际模型 `{selection.get("actualModel")}`，真实请求 **1 次**，选择 **{summary["selection"]}**。固定参数：`'+json.dumps({k:v for k,v in summary['config'].items() if k!='seed'},ensure_ascii=False)+'`。',
 '校准种子为 11；正式种子为 `'+str(r.SEEDS)+'`，各次评价预算 1,802,000；配置中的名义 evaluationBudget=0 由校准统一预算替代。','',
 '| seed | MS_Num | IFN | CHD | Instability | UCM | CMQ | 原始输出 |','|---|---:|---:|---:|---:|---:|---:|---|']
 for row in summary['runs']:lines.append('| '+str(row['seed'])+' | '+' | '.join(f(row[k]) for k in ['MS_Num']+KEYS)+' | '+link(b/f'unifyms/experiment/Spring/run-jev-{row["seed"]}.json','JSON')+' |')
 lines+=['','UnifyMS 十次代表方案的无操作服务数：`'+json.dumps({str(v['seed']):v['zero_operation_services'] for v in validation['methods']['unifyms']['per_run']})+'`；仅含无公开源码实现代理的组不能据此解释为实际功能服务。']
 if any(row['MS_Num']==1 for row in summary['runs']):lines+=['','本轮含单服务代表方案；原生算法允许单服务，这不能被解释为已经完成有意义的多微服务拆分。']
 lines+=['','十次样本标准差（ddof=1）：`'+json.dumps(summary['sample_std'],ensure_ascii=False)+'`。每次在冻结的校准归一化空间中按理想点距离选取自己的代表方案，然后取十次算术平均；不是挑最好一次。原始目标值保存四位小数，六位小数仅用于展示。',
 '本批次重新执行全部六组校准；C0 控制器暂时暂停，C1-C5 经同一原生 trial 方法、最多两个工作进程完成后自动恢复控制器并汇总。正式十次拆分最多两个独立 JVM 并行。各次随机数状态和输出独立，没有重复请求 JEV。校准调度记录见 unifyms/orchestration/controller.json。','',
 '| 配置 | N | 名义 G | 交叉概率 | crossP | 校准 HV |','|---|---:|---:|---:|---:|---:|']
 for cid,d in sorted(cal['candidates'].items()):
  c=d['config'];lines.append(f'| {cid} | {c["populationSize"]} | {c["generations"]} | {c["crossoverProbability"]} | {c["crossP"]} | {d["meanHv"]:.12f} |')
 lines+=['',('本次 JEV 选择 C0（默认参数），未产生调参差异。' if summary['selection']=='C0' else '本次 JEV 所选配置见上表。')+'未运行默认参数的十次配对对照，不能宣称 JEV 因果收益或统计显著改善。','',
 '## Token 与总耗时','', '| 方法 | 总 token | 总耗时（秒） | 范围 |','|---|---:|---:|---|',
 f'| MonoEmbed API | {stats["total_tokens"]} | {mono_total:.6f} | AST 提取、实际源码输入准备、API、标准化、聚类及保存。 |',
 f'| UnifyMS + JEV | {token if token is not None else ""} | {valid_total+aborted:.6f} | 本批次 AST 提取、完整校准、一次 JEV、十次正式运行墙钟时间。 |','',
 f'- MonoEmbed 实际请求 13 次，无缓存命中；输入 {stats["prompt_tokens"]} token。输出是数值向量，没有文本生成输出 token。保存的 13 份 provider data/usage 已逐份核对。纯 API 请求耗时 {stats["api_seconds"]:.6f} 秒，内部程序总耗时 {stats["total_seconds"]:.6f} 秒。',
 f'- UnifyMS 完整实验墙钟合计 {valid_total:.6f} 秒；本批次无中断校准重跑。完整校准墙钟 {timings["unifyms_calibrate"]:.6f} 秒，JEV 进程 {timings["unifyms_select"]:.6f} 秒，十次正式搜索墙钟 {formal_wall:.6f} 秒。',
 f'- 并行运行命令累计墙钟耗时（含进程启动和资源等待） {sum(formal_times):.6f} 秒、单次命令均值 {sum(formal_times)/10:.6f} 秒；该和值包含并行重叠，不加到总墙钟。',
 '- JEV 未返回完整 usage 时 token 留空，knownTokens=0 不能替代总 token。共享 AST 耗时分别纳入两方法的独立范围，整组实验不要重复累加；不计人工等待、构建、等价测试、绘图和报告整理时间。',
 '- 校准控制器暂停的时间计入校准阶段墙钟；正式运行未安排暂停。累计命令时间不是 CPU 时间或纯搜索耗时。',
 '- 该计量包含本轮实际调度及缓存实现，不能与其他案例的串行耗时直接作效率排名。','',
 '## 保持公式的性能改动','',
 '仅在本案例隔离副本缓存固定输入的操作对 Jaccard 值，并将固定列表的 toArray().length 改为 size()，避免循环中临时数组分配；原始 CHD 的循环和浮点累加顺序保持一致，没有改变算子、种群、预算和目标。512 组不同服务划分（含单服务、全分开和随机顺序）的全部五目标和接口矩阵与原实现逐位相同。测试是有限覆盖，保存原始/优化源码和差异以便审查。','',
 '- '+link(b/'unifyms/optimization-check/equivalence-all.json','512 组五目标及接口等价校验结果'),
 '- '+link(b/'protocol/QualityCalculate-similarity-cache.patch','纯缓存改动补丁'),
 '- '+link(b/'unifyms/diagnostics','本批次诊断目录'),
 '- '+link(b/'unifyms/orchestration','并行校准调度源码与结果依据'),'','## 输入输出与复现索引','']
 lines[-2:-2]=['原生汇总超过 Fastjson2 默认大对象写入限制时，通过仅作用于本实验 JVM 的初始化器启用库自带 LargeObject 序列化选项；未修改搜索或指标源码，不截断校准证据。70 MiB 文本在原生 PrettyFormat/WriteNulls 组合下完整往返验证通过。本轮开始前即启用该选项，没有发生该写入失败。初始化器和 512 组等价校验来自上一批次，同一优化实现本批次继续使用；本批次的校准、JEV 和正式搜索均重新执行。','']
 for m in ['microminer','monoembed','servicecutter']:
  lines.append('- '+NAMES[m]+'：'+link(b/m/('java-input' if m=='monoembed' else 'input'),'输入')+'；'+link(b/m/'decomposition.json','划分')+'；'+link(b/m/'metrics.json','指标及明细'))
 for p,label in [(b/'unifyms/summary.json','十次均值与标准差'),(b/'unifyms/partitions','十次可读划分'),(b/'unifyms/report/analysis.md','十份 .req、图与原生报告'),(b/'unifyms/experiment/Spring','六组校准、唯一 JEV、十次原始 JSON 和 trials'),(b/'monoembed/api_response','API 批次身份、向量与 usage（不含凭据）'),(b/'input/README.md','源码转换与覆盖边界'),(b/'protocol','转换及评价代码快照'),(b/'logs','命令、日志和阶段耗时'),(b/'validation.json','独立复算验证'),(b/'manifest.json','输入、源码和协议哈希'),(b/'costs.json','机器可读消耗汇总')]:lines.append('- '+link(p,label))
 lines+=['', '已保留 10 份严格验证的 .req，源 Java 和 POM 哈希全部一致。MicroMiner 使用信号适配器，MonoEmbed 使用百炼 embedding 而非论文微调编码器，UnifyMS 使用源码派生模型；本轮不能冒称四篇原论文的完整复现。','']
 (b/'Spring案例运行结果.md').write_text('\n'.join(lines))
 manifest.update(status='completed',formal_runs_completed=10,jev_requests=1,strict_req_exports=10);r.write(b/'manifest.json',manifest)
 print(json.dumps({'means':summary['mean'],'costs':costs,'report':str(b/'Spring案例运行结果.md')},ensure_ascii=False))
if __name__=='__main__':main()
