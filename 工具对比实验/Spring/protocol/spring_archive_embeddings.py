"""Archive this run's cached provider vectors/usage without making any API calls."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MONO=ROOT.parent/'MonoEmbed-EMSE25-RP'
b=ROOT/'runs/spring_20261104_01'
settings=json.loads((MONO/'.local/embedding_api.json').read_text())
stats=json.loads((b/'monoembed/decomposition.stats.json').read_text())
records=json.loads((b/'monoembed/java-input/typeData.json').read_text())
texts=[r['content'] for r in records]
out=b/'monoembed/api_response';out.mkdir(exist_ok=True)
requests=[];total=0
assert stats['usage_complete'] and stats['cache_hits']==0 and stats['input_records']==len(records)==124
for start in range(0,len(texts),10):
 payload={'model':stats['model'],'input':texts[start:start+10],'dimensions':stats['dimensions'],'encoding_format':'float'}
 identity={'base_url':settings['base_url'].rstrip('/'),'payload':payload}
 digest=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 original=MONO/'data/api_embeddings'/(digest+'.json')
 response=json.loads(original.read_text())
 assert len(response['data'])==len(payload['input'])
 total+=response['usage']['total_tokens']
 shutil.copy2(original,out/original.name);requests.append(identity)
assert total==stats['total_tokens'] and len(requests)==stats['api_requests']==13
(out/'requests.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2)+'\n')
(out/'request.json').write_text(json.dumps({'note':'Combined accounting metadata, not a single HTTP request. requests.json reconstructs the thirteen exact batch identities from retained inputs and CLI settings; each identity is checked against the provider response cache SHA256 filename. Cached files preserve provider data and usage; response headers and other envelope metadata were not retained. Explicit user consent received for these 124 Spring Java sources.','payload':{'model':stats['model'],'input':texts,'dimensions':stats['dimensions'],'encoding_format':'float'}},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'archived_responses':len(requests),'total_tokens':total,'records':len(records)}))
