#!/usr/bin/env python3
"""Extract module-qualified Spring service proxies and Mongo/domain Java classes."""
import argparse,collections,hashlib,json,re,shutil,time
from pathlib import Path
import javalang as jl

def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def letters(s):return ''.join(w[:1].upper()+w[1:] for w in re.findall('[A-Za-z]+',s))
def annotations(node):return {a.name:a for a in node.annotations}
def value(node):
 if isinstance(node,jl.tree.Literal):
  try:return json.loads(node.value)
  except Exception:return node.value
 if isinstance(node,jl.tree.MemberReference):return node.member
 if isinstance(node,jl.tree.ElementArrayValue):return [value(v) for v in node.values]
 return None

def attrs(a):
 if not a:return {}
 if isinstance(a.element,list):return {v.name:value(v.value) for v in a.element}
 return {'value':value(a.element)}

def route(node):
 for a in node.annotations:
  if a.name in ['RequestMapping','GetMapping','PostMapping','PutMapping','DeleteMapping','PatchMapping']:
   d=attrs(a);p=d.get('value',d.get('path',''));p=p[0] if isinstance(p,list) else p
   v=d.get('method',a.name.replace('Mapping','').upper() if a.name!='RequestMapping' else 'ANY');v=v[0] if isinstance(v,list) else v
   return v,p or ''
 return None

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();start=time.perf_counter();src=a.source.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
 classes={};files=[];duplicates=[]
 for p in sorted(p for p in src.rglob('*.java') if '/src/main/java/' in str(p) and '/target/' not in str(p)):
  text=p.read_text();tree=jl.parse.parse(text);rel=p.relative_to(src);files.append({'path':str(rel),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size});target=out/'source-java'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  imports={i.path.rsplit('.',1)[-1]:i.path for i in tree.imports if not i.wildcard and not i.static}
  for c in tree.types:
   fqn=tree.package.name+'.'+c.name
   if fqn in classes:duplicates.append({'fqn':fqn,'first_path':classes[fqn]['path'],'duplicate_path':str(rel),'identical':classes[fqn]['text']==text});continue
   classes[fqn]={'ast':c,'path':str(rel),'module':rel.parts[0],'imports':imports,'wildcards':[i.path for i in tree.imports if i.wildcard and not i.static],'package':tree.package.name,'text':text}
 def resolve(c,name):
  if name in classes:return name
  name=name.rsplit('.',1)[-1]
  if name in c['imports']:return c['imports'][name]
  if c['package']+'.'+name in classes:return c['package']+'.'+name
  matches=[q+'.'+name for q in c['wildcards'] if q+'.'+name in classes]
  if len(matches)==1:return matches[0]
  return name
 def types(c,node):return {resolve(c,t.name) for _,t in node.filter(jl.tree.ReferenceType)} if isinstance(node,jl.ast.Node) else set()
 entity_fqns={q for q,c in classes.items() if '.domain.' in q and isinstance(c['ast'],jl.tree.ClassDeclaration)}
 mapper_xml=[];xml_entities=collections.defaultdict(set)
 import xml.etree.ElementTree as ET
 for p in sorted(src.rglob('*Mapper.xml')):
  if '/src/main/resources/' not in str(p):continue
  tree=ET.fromstring(p.read_text());namespace=tree.get('namespace');mapped={n.get(k) for n in tree.iter() for k in ['type','resultType'] if n.get(k) in classes and '.common.pojo.' in n.get(k)}
  entity_fqns.update(mapped);xml_entities[namespace].update(mapped);rel=p.relative_to(src);target=out/'source-java'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  mapper_xml.append({'path':str(rel),'namespace':namespace,'entities':sorted(mapped),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 for fq,c in classes.items():
  if '.dao.' in fq or '.mapper.' in fq:entity_fqns.update(t for t in types(c,c['ast']) if t in classes and '.common.pojo.' in t)
 assert entity_fqns and entity_fqns<=set(classes)
 entity_names={q:letters(classes[q]['module'])+q.rsplit('.',1)[-1] for q in sorted(entity_fqns)};assert len(set(entity_names.values()))==len(entity_names)
 class_entities={q:(types(c,c['ast'])&entity_fqns)|xml_entities.get(q,set()) for q,c in classes.items()}
 fields={q:{d.name:resolve(c,f.type.name) for f in c['ast'].fields for d in f.declarators} for q,c in classes.items()}
 methods={};index=collections.defaultdict(list)
 for fq,c in classes.items():
  for m in c['ast'].methods:
   key=f'{fq}#{m.name}/{len(m.parameters)}@{m.position.line}';methods[key]={'owner':fq,'ast':m,'direct':types(c,m)&entity_fqns,'edges':set()};index[fq,m.name,len(m.parameters)].append(key)
 implementations=collections.defaultdict(list)
 for fq,c in classes.items():
  for i in getattr(c['ast'],'implements',None) or []:implementations[resolve(c,i.name)].append(fq)
 for (fq,name,arity),ks in index.items():
  for impl in implementations.get(fq,[]):
   for k in ks:methods[k]['edges'].update(index.get((impl,name,arity),[]))
 applications={}
 for p in sorted(src.rglob('bootstrap.yml')):
  if '/src/main/resources/' not in str(p):continue
  match=re.search(r'spring:\s*\n\s+application:\s*\n\s+name:\s*([^\s#]+)','\n'.join(line.split('#',1)[0] for line in p.read_text().splitlines()))
  if match:applications[match.group(1)]=p.relative_to(src).parts[0]
 context_paths={};routing_config=[]
 for p in sorted((src/'config').glob('*.properties')):
  props=dict(re.findall(r'^\s*([\w.-]+)\s*=\s*([^\n]*)',p.read_text(),re.M))
  app=props.get('spring.application.name',p.stem);applications[app]=p.stem
  context_paths[p.stem]=props.get('server.servlet.context-path','').strip()
  routing_config.append({'path':str(p.relative_to(src)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'application_name':app,'context_path':context_paths[p.stem]})
 def canonical(path):return re.sub(r'\{[^}]+\}','{}',path.rstrip('/') or '/')
 routes=collections.defaultdict(list)
 for fq,c in classes.items():
  if not {'RestController','Controller'}&annotations(c['ast']).keys():continue
  prefix=context_paths.get(c['module'],'').rstrip('/')+'/'+(route(c['ast']) or ('ANY',''))[1].strip('/')
  for m in c['ast'].methods:
   rr=route(m)
   if rr:
    verb,path=rr;path='/'+('/'.join([prefix.strip('/'),path.strip('/')])).strip('/');routes[c['module'],verb,canonical(path)].extend(index[fq,m.name,len(m.parameters)])
 feign=[];unresolved=[]
 for key,info in methods.items():
  c=classes[info['owner']];m=info['ast'];env=dict(fields[info['owner']]);env.update({v.name:resolve(c,v.type.name) for v in m.parameters})
  for _,v in m.filter(jl.tree.LocalVariableDeclaration):
   env.update({d.name:resolve(c,v.type.name) for d in v.declarators})
  explicit_receivers={}
  for _,this in m.filter(jl.tree.This):
   receiver=info['owner']
   for selector in this.selectors or []:
    if isinstance(selector,jl.tree.MemberReference):receiver=fields.get(receiver,{}).get(selector.member,env.get(selector.member))
    elif isinstance(selector,jl.tree.MethodInvocation):explicit_receivers[id(selector)]=receiver;break
  for _,call in m.filter(jl.tree.MethodInvocation):
   qual=call.qualifier or '';first=qual.split('.')[0]
   receiver=explicit_receivers.get(id(call),env.get(first) if qual else info['owner'])
   if receiver is None:receiver=resolve(c,first)
   if receiver in entity_fqns:info['direct'].add(receiver)
   if receiver in classes:
    info['direct'].update(class_entities[receiver] if receiver.endswith(('Mapper','Repository')) else set())
    targets=index.get((receiver,call.member,len(call.arguments)),[]);info['edges'].update(targets)
    if not targets:unresolved.append({'caller':key,'receiver':receiver,'member':call.member,'reason':'inherited/generated/unsupported overload'})
  fa=annotations(c['ast']).get('FeignClient')
  if fa:
   d=attrs(fa);service_name=d.get('name',d.get('value'));module=applications.get(service_name,service_name);rr=route(m);prefix=d.get('path','')
   if rr:
    verb,path=rr;path='/'+('/'.join([prefix.strip('/'),path.strip('/')])).strip('/');targets=routes.get((module,verb,canonical(path)),[])+routes.get((module,'ANY',canonical(path)),[])
    if verb=='ANY':targets+=sum([ts for (mod,v,p),ts in routes.items() if mod==module and p==canonical(path)],[])
    info['edges'].update(targets);feign.append({'method':key,'target_module':module,'verb':verb,'path':path,'controller_targets':sorted(set(targets))})
 reached={k:set(v['direct']) for k,v in methods.items()}
 for _ in range(len(methods)):
  changed=False
  for k,v in methods.items():
   new=set(reached[k])
   for t in v['edges']:new.update(reached[t])
   if new!=reached[k]:reached[k]=new;changed=True
  if not changed:break
 selected={q:c for q,c in classes.items() if 'Service' in annotations(c['ast']) and isinstance(c['ast'],jl.tree.ClassDeclaration)}
 symbols={q:letters(c['module'])+c['ast'].name for q,c in selected.items()};assert all(re.fullmatch('[A-Za-z]+',s) for s in symbols.values());assert len(set(symbols.values()))==len(symbols)
 ops=[];seen=collections.Counter()
 for fq,c in selected.items():
  for m in c['ast'].methods:
   if 'public' not in m.modifiers or 'static' in m.modifiers:continue
   key=index[fq,m.name,len(m.parameters)];key=[k for k in key if methods[k]['ast'].position.line==m.position.line][0];base=symbols[fq]+m.name[:1].upper()+m.name[1:];seen[base]+=1;symbol=base+('Overload'+chr(64+seen[base]) if seen[base]>1 else '')
   assert re.fullmatch('[A-Za-z]+',symbol)
   ops.append({'id':symbol,'service':symbols[fq],'java_method':key,'path':c['path'],'line':m.position.line,'direct_entities':sorted(entity_names[x] for x in methods[key]['direct']),'entities':sorted(entity_names[x] for x in reached[key]),'calls':sorted(methods[key]['edges'])})
 assert selected and ops
 op_by_method={o['java_method']:o for o in ops}
 for o in ops:
  queue=list(methods[o['java_method']]['edges']);visited=set();targets=set()
  while queue:
   k=queue.pop()
   if k in visited:continue
   visited.add(k)
   if k in op_by_method and op_by_method[k]['service']!=o['service']:
    targets.add(k);continue
   queue.extend(methods[k]['edges'])
  o['resolved_service_calls']=[{'service':op_by_method[k]['service'],'operation':op_by_method[k]['id'],'java_method':k} for k in sorted(targets)]
 lines=['UseCaseModel PiggyMetrics {']
 for s in symbols.values():lines.append(' UC::'+s+'()')
 # Module entry roles are structural proxies, not hand-authored business actors.
 for module in sorted({c['module'] for c in selected.values()}):
  lines+=[' Actor '+letters(module)+'Role {']+['  '+symbols[q] for q,c in selected.items() if c['module']==module]+[' }']
 for fq,s in symbols.items():
  lines+=[' Service '+s+' {','  [Operation]']+['  '+o['id']+'()' for o in ops if o['service']==s]+[' }']
 entity_rows=[]
 for fq,name in entity_names.items():
  c=classes[fq];fs=[];lines+=[' Entity '+name+' {']
  for f in c['ast'].fields:
   if 'static' in f.modifiers:continue
   typ=f.type.name;refs=sorted(types(c,f.type)&entity_fqns)
   render=entity_names[refs[0]] if refs else ('Integer' if typ in ['int','long','Integer','Long','byte','Byte','Short','short'] else 'Real' if typ in ['Double','double','Float','float','BigDecimal'] else 'Date' if 'Date' in typ else 'String')
   assert len(refs)<=1,('multiple entity generic arguments need explicit handling',fq,typ,refs)
   for d in f.declarators:
    lines.append('  '+d.name+' : '+render+(' Association' if refs else ''))
    fs.append({'name':d.name,'java_type':typ,'java_type_arguments':sorted(types(c,f.type)),'model_type':render,'entity_references':[entity_names[t] for t in refs]})
  lines+=[' }'];entity_rows.append({'entity':name,'java_class':fq,'path':c['path'],'fields':fs})
 for o in ops:
  lines+=[' Contract '+o['service']+'::'+o['id']+'() : Boolean {','  definition:']+['   ref'+entity+' : '+entity for entity in o['entities']]+['  postcondition:']+['   '+call['service']+'::'+call['operation']+'() and' for call in o['resolved_service_calls']]+['   result = true',' }']
 lines+=['}'];model=out/'PiggyMetrics.remodel';model.write_text('\n'.join(lines)+'\n')
 records=[]
 for fq,c in list(selected.items())+[(fq,classes[fq]) for fq in entity_names]:
  name=symbols[fq] if fq in selected else entity_names[fq];kind='service' if fq in selected else 'domain'
  # Redact literal credential assignments if any; property placeholders are preserved.
  text,n=re.subn(r'(?i)(\b(?:\w*(?:password|secret|apiKey|accessToken)\w*)\s*=\s*)"[^"\n]+"',r'\1"REDACTED"',c['text'])
  records.append({'fullName':'PiggyMetrics.'+kind+'.'+name,'simpleName':name,'serviceName':name if kind=='service' else 'domain-model','content':text,'source_path':c['path'],'java_class':fq,'literal_assignments_redacted':n})
 write(out/'java-embedding/typeData.json',records)
 write(out/'source-manifest.json',{'source_directory':str(src),'java_files':files,'java_files_count':len(files),'mapper_xml_files':mapper_xml,'source_tree_hash':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()})
 write(out/'method-graph.json',{k:{'direct_entities':sorted(entity_names[e] for e in v['direct']),'reachable_entities':sorted(entity_names[e] for e in reached[k]),'calls':sorted(v['edges'])} for k,v in methods.items()})
 write(out/'extraction.json',{'parser':'javalang 0.13.0','parsed_classes':len(classes),'routing_config':routing_config,'spring_applications':applications,'duplicate_fqn_sources':duplicates,'interface_implementations':dict(implementations),'mapper_xml':mapper_xml,'services':symbols,'operations':ops,'entities':entity_rows,'feign_routes':feign,'unresolved_project_calls':unresolved,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'zero_entity_services':[s for s in symbols.values() if not any(o['entities'] for o in ops if o['service']==s)],'zero_entity_operations':[o['id'] for o in ops if not o['entities']],'entity_relationship_policy':'Module-qualified non-enum domain classes. Direct and generic entity-typed fields are represented as associations; scalar IDs are not inferred as foreign keys. Enums remain scalar attributes. Duplicate document DTOs across modules remain separate Java input units.','usecase_policy':'One Spring @Service class is one use-case proxy; all its public non-static methods are operations. Existing module boundary is not a clustering constraint. Module roles are actor proxies.','method_graph_policy':'Declared receiver types, this.field selectors, interface-to-implementation expansion, method name/arity; Feign app name/HTTP method/path to Controller route; Mongo/domain types, CrudRepository generic types, and monotonic entity reachability. Method calls inside lambdas are included statically; runtime scheduling and chained return type inference are incomplete. No reflection/runtime dispatch/library implementation modeling.','seconds':time.perf_counter()-start})
 print(json.dumps({'source_files':len(files),'service_usecase_proxies':len(selected),'operations':len(ops),'entities':len(entity_names),'feign_routes':len(feign),'feign_matched':sum(bool(r['controller_targets']) for r in feign),'zero_entity_services':[s for s in symbols.values() if not any(o['entities'] for o in ops if o['service']==s)],'seconds':time.perf_counter()-start},ensure_ascii=False))
if __name__=='__main__':main()
