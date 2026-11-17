"""Preserve successful fresh ATM provider response, vectors and token usage."""
from pathlib import Path
import hashlib,json,shutil
import run_atm_rerun as r
b=r.DEFAULT
settings=r.read(r.MONO/'.local/embedding_api.json');stats=r.read(b/'monoembed/decomposition.stats.json');records=r.read(b/'monoembed/input/typeData.json')
assert stats['status']=='completed' and stats['usage_complete'] and stats['cache_hits']==0
assert len(records)==7 and stats['api_requests']==1
payload={'model':stats['model'],'input':[v['content'] for v in records],'dimensions':stats['dimensions'],'encoding_format':'float'}
identity={'base_url':settings['base_url'].rstrip('/'),'payload':payload};digest=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
original=r.MONO/'data/api_embeddings'/(digest+'.json');response=r.read(original)
assert len(response['data'])==len(records) and response['usage']['total_tokens']==stats['total_tokens']
out=b/'monoembed/api_response';out.mkdir(exist_ok=True);shutil.copy2(original,out/original.name);r.write(out/'request.json',identity)
print(json.dumps({'requests':1,'records':len(records),'total_tokens':stats['total_tokens']}))
