# coding: utf-8
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
from datetime import datetime
from zoneinfo import ZoneInfo
import re,json,hashlib
p=Path('/Users/yuanyaowu/Desktop/输出/汇总Case.md');original=p.read_text();text=original;rate=Decimal('0.042');rows=[]
heads=list(re.finditer(r'^## \d+\. ([^\n]+)$',original,re.M))
for i,m in reversed(list(enumerate(heads))):
 end=heads[i+1].start() if i+1<len(heads) else original.index('\n## 来源校验',m.end());block=text[m.start():end];case=m[1].split(' — ')[0];converted=[]
 def convert(mt):
  cells=[x.strip() for x in mt[0].strip('|').split('|')]
  if len(cells)!=4 or not re.fullmatch(r'\$\s*\d+(?:\.\d+)?',cells[1]):return mt[0]
  amount=cells[1];exact=Decimal(amount.replace('$','').strip())/rate*Decimal(1000000);tokens=int(exact.quantize(Decimal('1'),rounding=ROUND_HALF_UP));converted.append(amount)
  rows.append({'case':case,'method':cells[0],'usd':amount,'estimated_tokens':tokens,'unrounded_tokens':str(exact)})
  cells[1]=f'{tokens:,}（估算）';return '| '+' | '.join(cells)+' |'
 block=re.sub(r'^\| (?:UnifyMS|MonoEmbed)[^\n]+$',convert,block,flags=re.M)
 if converted:
  block=re.sub(r'^- JEV 没有完整 usage 时总 token 按要求留空，不能用 knownTokens=0 代替。[^\n]*$', '- JEV 未返回完整 usage；表中总 token 按当前金额及指定费率反推，为估算值，不等同于 API 返回的实际用量，不采用 knownTokens=0。',block,flags=re.M)
  block=block.replace('JEV 未返回完整 usage 时 token 留空，knownTokens=0 不能替代总 token。','JEV 未返回完整 usage；表中总 token 为金额反推估算值，knownTokens=0 不用于计量。')
  block=re.sub(r'原报告“总 token”栏为 `([^`]+)`（金额格式）；本汇总不将其视为 token 数量，该单元格留空。原始值仍保留在来源报告中。',r'历史来源报告的金额记录为 `\1`；本次估算仅使用当前汇总表中填写的金额，未采用该历史金额。',block)
  note='\n\n本次换算：'+ '；'.join(v+' ÷ $0.042 × 1,000,000' for v in converted)+'，四舍五入到整数 token。金额若已舍入，反推 token 也只能作为估算。\n'
  block=block.rstrip()+note
 text=text[:m.start()]+block+text[end:]
rows.reverse();assert len(rows)==8
text=text.replace('部分原报告在总 token 栏写入金额格式的值。本汇总将这些单元格留空，并在对应章节保留原值备注；原文件保持不变。','当前汇总表中以美元填写的8项总 token 已按用户指定的 $0.042/百万 token 反推，四舍五入至整数并标注“估算”；各章节保留所用金额。已有真实 token 数不变，案例原报告不修改。')
section=['## 美元金额反推 token','', '换算费率按用户指定值：**$0.042 / 1,000,000 token**。公式：`估算 token = 美元金额 ÷ 0.042 × 1,000,000`。结果四舍五入至整数。金额来源为本次修改前当前汇总表中“总 token”栏，不能视为已经由 API usage 验证的实际用量。','', '| 案例 | 方法 | 当前表中美元金额 | 估算 token |','|---|---|---:|---:|']
for r in rows:section.append(f'| {r["case"]} | {r["method"]} | {r["usd"]} | {r["estimated_tokens"]:,} |')
text=text.replace('## 来源索引\n','\n'.join(section)+'\n\n## 来源索引\n',1)
# All metric tables and ranking text remain identical.
extract=lambda t,h:re.findall(r'^### '+h+r'\n(.*?)(?=^#{1,3} |\Z)',t,re.M|re.S)
assert extract(original,'五指标对比')==extract(text,'五指标对比')
assert extract(original,'五指标排序')==extract(text,'五指标排序')
for mt in re.finditer(r'^\| (?:UnifyMS|MonoEmbed)[^\n]+$',text,re.M):
 c=[x.strip() for x in mt[0].strip('|').split('|')]
 if len(c)==4:assert not c[1].startswith('$')
Path('/tmp/汇总Case_token换算稿.md').write_text(text)
Path('/tmp/token_conversion_audit.json').write_text(json.dumps({'summary_before_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'usd_per_million_tokens':str(rate),'rounding':'ROUND_HALF_UP to integer, estimated rather than provider usage','rows':rows},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(rows,ensure_ascii=False,indent=2))
