# coding: utf-8
from pathlib import Path
import re,json,hashlib,collections
from datetime import datetime
from zoneinfo import ZoneInfo
source=Path('/Users/yuanyaowu/Desktop/输出/汇总Case.md');original=source.read_text();audit=json.loads(Path('/tmp/summary_ranking_audit.json').read_text());assert hashlib.sha256(source.read_bytes()).hexdigest()==audit['source_sha256']
items=audit['items'];modified=original
for item in reversed(items):
 block=modified[item['start']:item['end']]
 def update(m):
  cells=[v.strip() for v in m[0].strip('|').split('|')]
  if len(cells)!=7:return m[0]
  method=next(mid for prefix,mid in [('MicroMiner','microminer'),('MonoEmbed','monoembed'),('Service Cutter','servicecutter'),('UnifyMS','unifyms')] if cells[0].startswith(prefix))
  for j,k in enumerate(['IFN','CHD','Instability','UCM','CMQ'],2):cells[j]=item['ranks'][k][method]
  return '| '+' | '.join(cells)+' |'
 block=re.sub(r'^\| (?:MicroMiner|MonoEmbed|Service Cutter|UnifyMS)[^\n]+$',update,block,flags=re.M)
 modified=modified[:item['start']]+block+modified[item['end']:]
# Keep user-selected eight sections and their numbering; fix stale source index entries.
active={v['id'] for v in items}
modified=re.sub(r'^\| (\d{2}) \|[^\n]+\n',lambda m:m[0] if m[1] in active else '',modified,flags=re.M)
modified=modified.replace('共汇总 **8 个案例、12 份报告**','当前正文保留 **8 个案例、8 份报告**')
modified=modified.replace('以下分别保留各报告的五指标对比、五指标排序和 Token 与总耗时，未重新运行程序或重算指标。','本次按正文各案例“五指标排序”的数值同步“五指标对比”，不重新运行拆分。排序表不是原始测量凭据；同步后的数值仍需按论文公式与原始工件核查。')
modified=modified.replace('COCOME 的当前入口和 `重算_20261103_01` 是同一批次的两份报告，指标和排序相同，分别列出以覆盖全部文件，不应重复算作两次实验。Spring 首轮与重跑批次分别列出；COCOME 历史报告保留旧方法版本和旧计量范围。','正文采用 COCOME 当前入口和 Spring 的 spring_20261104_02 批次；历史文件保留在原目录，不在本正文重复列入。来源索引及来源哈希仅对应原报告，不能证明人工修改后的排序值正确。')
modified=modified.replace('以下 SHA-256 对应本次读取的完整来源文件，可用于确认汇总取自哪个版本。','以下 SHA-256 是既有来源报告的版本标识。它们不是本次同步后数值的真实性校验；本次修改清单和原始工件核查见下方分析链接。')
output_dir=Path('/Users/yuanyaowu/Desktop/输出/指标核查_20261104')
warning='## 本次同步与论文核查\n\n本次只按排序表同步了 **15 处对比表单元格**，MS_Num、排序表原值及 token/耗时保持不变。**该操作解决表内不一致，不代表数值已按论文计算或已得到原始输出支持。**\n\n已发现四处非 UCM 数值不符合原始输出，UCM 则混合了论文重算值、旧评价值和缺少来源支持的值。详见 [指标公式与数据问题分析](<'+str(output_dir/'指标公式与数据问题分析.md')+'>) 和 [逐项数据核查](<'+str(output_dir/'逐项数据核查.json')+'>)。\n\n'
modified=modified.replace('## 来源索引\n',warning+'## 来源索引\n')
changes=[v for item in items for v in item['changes']];comparisons=[v for item in items for v in item['comparisons']]
counts=collections.Counter(v['status'] for v in comparisons if v['metric']=='UCM')
analysis=['# 五指标公式与实验数据核查','', '核查时间：'+datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')+'。','',
'结论：当前汇总不具备统一论文指标口径，不能直接据此声称某方法在五指标上全面领先。此次按要求只使对比表与排序表数值一致；没有把错误的排序值认证为实验测量，也没有更改原始 JSON、各案例报告、论文或运行结果。','',
'## 本次完成的表内同步','',f'- 正文实际为 {len(items)} 个案例、8 个结果章节，修正索引和概述中残留的12份报告信息，保留用户当前选定的案例与批次。',f'- 按排序表同步 {len(changes)} 处单元格；仅涉及 UCM。已有排序与对比表同时写错的值不会因为这次同步而自动正确。','- MS_Num、排序表原有数值、token 和耗时没有改变；未调用API、未重新搜索。','',
'| 案例 | 方法 | 指标 | 同步前 | 按排序表同步后 |','|---|---|---|---:|---:|']
for v in changes:analysis.append('| '+' | '.join(v[k] for k in ['case','method','metric','before','after'])+' |')
analysis+=['','## 一、与原始拆分输出不符的数值','',
'已重新读取80份 UnifyMS 代表方案，逐指标复算各案例十次算术均值，并核对 summary.json；以下原始均值与逐次结果一致。排名表中的这些值缺少当前原始输出支持。若它们来自另一个批次或一次独立重算，需要另行提供该批次输入、公式和结果依据，不能沿用当前来源链接。','',
'| 案例 / 方法 | 指标 | 当前排序与同步后对比表 | 原始十次均值 | 判断 |','|---|---|---:|---:|---|']
for v in comparisons:
 if v['metric']!='UCM' and v['status']=='unsupported_by_raw_output':analysis.append(f'| {v["case"]} / {v["method"]} | {v["metric"]} | {v["ranking_value"]} | {v["raw_output"]} | 与所引批次不符 |')
analysis+=['','## 二、UCM 混用了三个来源口径','',
'论文第9–10页公式(15)–(21)：CorrA取是否具有共同actor，CorrF取是否具有include/extend关系，CorrE取二进制用例—实体访问向量的余弦相似度；rU=0.2CorrA+0.3CorrF+0.5CorrE。UCM是同服务不同用例对相关值的全局均值减去跨服务用例对全局均值，空集合记0。服务数并不作为这两个均值的分母，单用例服务不额外奖励0.5。','',
'此前已按同一批次的保存划分重算UCM；本次排序表32个UCM中，'+str(counts['paper_recalculation'])+'个与严格论文重算一致，'+str(counts['legacy_raw_output'])+'个仍等于旧实现输出，'+str(counts['unsupported_by_raw_or_strict_paper_recalculation'])+'个既不等于旧值也没有严格论文重算支持。不能把这三类数混到一张论文指标表中比较。','',
'| 案例 | 方法 | 当前排序值 | 旧程序输出 | 严格论文重算 | 状态 |','|---|---|---:|---:|---:|---|']
labels={'paper_recalculation':'与严格论文重算一致','legacy_raw_output':'仍为旧实现值','unsupported_by_raw_or_strict_paper_recalculation':'缺少所引数据支持'}
for v in comparisons:
 if v['metric']=='UCM':analysis.append(f'| {v["case"]} | {v["method"]} | {v["ranking_value"]} | {v["raw_output"]} | {v["paper_UCM"] or ""} | {labels[v["status"]]} |')
analysis+=['','### 可由公式直接否定的正 UCM','',
'对于每个用例各占一个服务的方案，同服务不同用例对集合为空，因此 IntraU=0；所有相关项非负，故 UCM=-InterU≤0。保存的 MicroMiner 代码案例恰好是这种用例分组。以下正值不能由该分组及论文公式得到：','',
'| 案例 / MicroMiner | 当前值 | 论文重算 |','|---|---:|---:|',
'| java-online-taxi | 0.121256 | -0.054239 |','| light-reading | 0.163636 | -0.189989 |','| PiggyMetrics | 0.053333 | -0.178408 |','| Spring | 0.224123 | -0.029332 |','',
'Loan / UnifyMS 当前UCM=0.451876，旧程序输出0.392100，严格论文重算0.251876；当前值同时不匹配这两个已知来源。','',
'Library 的 cancelReservation 用例在保存映射中缺少操作，而原始操作拼写为 cannelReservation。严格结果中前三工具无法完整确定用例归属，不能填充一个看似正常的分数。单独采用此别名映射后四方法依次为0.141727、0.233079、0.269412、0.098277；这是一组统一应用别名后的条件性结果，不能与严格版UnifyMS的0.223510混用。','',
'COCOME的MicroMiner与MonoEmbed在论文重算中都为-0.015707，是因为它们的实际用例同簇关系完全一致；实体或其他类的分组数量不同，不必然使UCM不同。这次相等有划分依据。','',
'light-reading排序中0.163636的三者以箭头分两段，但既然展示数值完全相等，应合并并列；更根本的问题是这些数没有按统一论文公式获得。','',
'## 三、IFN：操作数不是跨服务接口数','',
'论文式(5)为各服务跨服务接口数的平均，排除只暴露给外部用户的接口。三个适配器当前使用“声明操作总数/全部簇数”，包含CRUD/外部入口及没有操作的实体簇，并未按实际跨服务边界计算接口。',
'例如ATM的三个结果分别为16/5=3.2、16/4=4、16/17≈0.941176。Service Cutter的17个簇中含无操作簇，分母增大就会降低该旧IFN，不能据此宣称服务耦合更低。Library的UnifyMS十次required和provided实体接口集合均为空，原生IFN确为0，而当前排序与表写成1；Instability=1并不能推出IFN=1。','',
'## 四、Instability：论文要求最大化，分母和方向必须一致','',
'论文式(6)–(7)为 Provided/(Provided+Required) 再对全部服务平均；没有任何服务间接口时按1。原生UnifyMS遵循这一方向。公共评价器使用Required/(Provided+Required)，方向相反，而且其接口来自操作/CRUD启发式。即使直接用1减去旧值，也只能变换旧计数的方向，不能修复接口定义和空服务的加权。',
'当前排序仍按数值升序展示，若仅作数字排列可以保留，但不能解释为论文中的“从好到坏”。Spring的UnifyMS应先解决0.383990与所引原始0.483990不符的问题。ATM单服务得到IFN=0、Instability=1是边界情形；不能把它当成成功划分出高质量微服务的证据。','',
'## 五、CHD：当前实现的对角项、分母和单操作规则不同','',
'论文式(8)–(10)明确：操作实体集Jaccard相似度；在服务内只求k≠m项，服务级分母为n_s²，然后对所有服务平均。因此单操作服务的求和为空，按该式为0，而不是1。三个适配器当前通常包含自身比较，并只平均有操作簇；原生UnifyMS则常按n_s(n_s−1)归一化并给单操作服务记1。这些值不能视为同一论文CHD。',
'由于Jaccard≤1，对于n_s>0有chd_s≤(n_s−1)/n_s。下面三个案例所有MicroMiner簇均有操作，无需假定零操作簇如何处理，就能得到明确上限：','',
'| 案例 / MicroMiner | 当前CHD | 按操作数可达到的论文CHD上限 |','|---|---:|---:|',
'| java-online-taxi | 0.500224 | 0.223118 |','| light-reading | 0.740667 | 0.441667 |','| PiggyMetrics | 0.782704 | 0.486111 |','',
'三者均超出对应操作数允许的论文上限，说明当前数值不是按论文公式计算，并非六位小数舍入误差。对包含零操作服务的结果，论文式(9)分母为0，需要先明确该类空服务的处理规则，不能悄悄删去它们或奖励0.5/1。','',
'## 六、CMQ：论文是属性集合Jaccard，程序使用了不同含义','',
'论文式(11)–(14)为实体属性集合Jaccard，同簇实体对均值减异簇实体对均值；空集合对应均值为0。三个工具现用实体自身名、字段名、类型、引用等词特征的余弦；UnifyMS现用实体关系矩阵和接口耦合。二者都不同于论文的属性Jaccard，不能直接比较绝对值。',
'ATM中BankCard的显式属性名为CardID、CardStatus、Catalog、Password、Balance，User为UserID、Name、Address，交集为空。按这些属性名，唯一实体对Jaccard=0，单服务时论文CMQ也应为0；现有UnifyMS=0.5及公共余弦±0.319801不是这条论文公式的结果。如果作者希望采用属性类型或语义匹配，应另行明确A(e)的构造，不能将类型词余弦混称为集合Jaccard。',
'Spring原生Modilarity还有空实体服务对临时计数未清零、带入后续服务对的历史实现缺陷，已在原报告中复算定位。即使修复该缺陷，也仍需改用论文实体属性公式后才能称为论文CMQ。light-reading的正0.151101则先与保存的原生均值−0.015110直接矛盾，不能只用“公式不同”解释。','',
'## 七、如何使用这些数据','',
'- 本次同步后的表只能作为“排序表数值的转录”，不能作为已验证的论文实验结果。原始拆分结果可以复用，通常不需要重跑搜索或API。',
'- 统一建模跨服务接口后再重算IFN与Instability；采用式(9)的对角项排除和n_s²分母重算CHD；明确属性集合和实体唯一归属后按Jaccard重算CMQ；UCM采用已有统一重算结果并先解决Library别名政策。',
'- 四方法在同一案例内必须使用相同输入语义、计数规则、零分母约定和平均方式；保留UnifyMS十次逐次结果，按同一公式逐次重算再取平均。',
'- 无法从当前保存工件证明的数值应标缺失或待核验。仅因为排序更符合预期而改数值没有实验依据。','',
'## 依据与可复核文件','',
'- 论文：[unifyms_ieee_format.pdf](</Users/yuanyaowu/Desktop/实验室材料/UnifyMs/UnifyMs论文/output/pdf/unifyms_ieee_format.pdf>)，第9–10页式(5)–(21)。',
'- [严格论文UCM对比](</Users/yuanyaowu/Desktop/输出/UCM_论文定义重算_20261104/UCM_八案例对比.csv>)、[80次UnifyMS重算](</Users/yuanyaowu/Desktop/输出/UCM_论文定义重算_20261104/UCM_UnifyMS_逐次.csv>)、[完整输入/配对/归属明细](</Users/yuanyaowu/Desktop/输出/UCM_论文定义重算_20261104/UCM_计算明细.json>)。',
'- 各案例原始metrics.json、UnifyMS summary.json与80份run-jev JSON沿用汇总正文的来源目录；这次只读，不改写。','']
Path('/tmp/汇总Case_修正稿.md').write_text(modified)
Path('/tmp/指标公式与数据问题分析.md').write_text('\n'.join(analysis))
Path('/tmp/逐项数据核查.json').write_text(json.dumps({'source_summary_sha256':audit['source_sha256'],'changes':changes,'comparisons':comparisons,'UCM_status_counts':dict(counts),'scope':'comparison tables transcribed from rankings; raw output and paper-formula validation reported separately'},ensure_ascii=False,indent=2)+'\n')
assert len(changes)==15
# All original ranking sections and token/time sections retain their bytes.
extract=lambda t,heading:re.findall(r'^### '+heading+r'\n(.*?)(?=^#{1,3} |\Z)',t,re.M|re.S)
assert extract(original,'五指标排序')==extract(modified,'五指标排序')
assert extract(original,'Token 与总耗时')==extract(modified,'Token 与总耗时')
assert modified.count('### 五指标对比')==8
print(json.dumps({'changed_cells':len(changes),'cases':len(items),'unsupported_non_UCM':sum(v['metric']!='UCM' and v['status']=='unsupported_by_raw_output' for v in comparisons),'UCM_status_counts':dict(counts),'summary_draft':'/tmp/汇总Case_修正稿.md'},ensure_ascii=False))
