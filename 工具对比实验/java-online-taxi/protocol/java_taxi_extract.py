#!/usr/bin/env python3
"""Extract traceable Spring service-class proxies and Mapper entities from Java AST."""
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
 classes={};files=[]
 for p in sorted(src.glob('*/src/main/java/**/*.java')):
  text=p.read_text();tree=jl.parse.parse(text);rel=p.relative_to(src);files.append({'path':str(rel),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size});target=out/'source-java'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  imports={i.path.rsplit('.',1)[-1]:i.path for i in tree.imports if not i.wildcard and not i.static}
  for c in tree.types:
   fqn=tree.package.name+'.'+c.name;classes[fqn]={'ast':c,'path':str(rel),'module':rel.parts[0],'imports':imports,'package':tree.package.name,'text':text}
 def resolve(c,name):
  if name in classes:return name
  name=name.rsplit('.',1)[-1]
  if name in c['imports']:return c['imports'][name]
  if c['package']+'.'+name in classes:return c['package']+'.'+name
  return name
 def types(c,node):return {resolve(c,t.name) for _,t in node.filter(jl.tree.ReferenceType)} if isinstance(node,jl.ast.Node) else set()
 entity_fqns=set()
 for fq,c in classes.items():
  for _,t in c['ast'].filter(jl.tree.ReferenceType):
   if t.name=='BaseMapper':
    for arg in t.arguments or []:
     if arg.type:entity_fqns.add(resolve(c,arg.type.name))
 assert len(entity_fqns)==8 and entity_fqns<=set(classes)
 entity_names={q:q.rsplit('.',1)[-1] for q in sorted(entity_fqns)};assert len(set(entity_names.values()))==len(entity_names)
 class_entities={q:types(c,c['ast'])&entity_fqns for q,c in classes.items()}
 fields={q:{d.name:resolve(c,f.type.name) for f in c['ast'].fields for d in f.declarators} for q,c in classes.items()}
 methods={};index=collections.defaultdict(list)
 for fq,c in classes.items():
  for m in c['ast'].methods:
   key=f'{fq}#{m.name}/{len(m.parameters)}@{m.position.line}';methods[key]={'owner':fq,'ast':m,'direct':types(c,m)&entity_fqns,'edges':set()};index[fq,m.name,len(m.parameters)].append(key)
 routes=collections.defaultdict(list)
 for fq,c in classes.items():
  if not {'RestController','Controller'}&annotations(c['ast']).keys():continue
  prefix=(route(c['ast']) or ('ANY',''))[1]
  for m in c['ast'].methods:
   rr=route(m)
   if rr:
    verb,path=rr;path='/'+('/'.join([prefix.strip('/'),path.strip('/')])).strip('/');routes[c['module'],verb,path].extend(index[fq,m.name,len(m.parameters)])
 feign=[];unresolved=[]
 for key,info in methods.items():
  c=classes[info['owner']];m=info['ast'];env=dict(fields[info['owner']]);env.update({v.name:resolve(c,v.type.name) for v in m.parameters})
  for _,v in m.filter(jl.tree.LocalVariableDeclaration):
   env.update({d.name:resolve(c,v.type.name) for d in v.declarators})
  for _,call in m.filter(jl.tree.MethodInvocation):
   qual=call.qualifier or '';first=qual.split('.')[0]
   receiver=env.get(first) if qual else info['owner']
   if receiver is None:receiver=resolve(c,first)
   if receiver in entity_fqns:info['direct'].add(receiver)
   if receiver in classes:
    info['direct'].update(class_entities[receiver] if receiver.endswith('Mapper') else set())
    targets=index.get((receiver,call.member,len(call.arguments)),[]);info['edges'].update(targets)
    if not targets:unresolved.append({'caller':key,'receiver':receiver,'member':call.member,'reason':'inherited/generated/unsupported overload'})
  fa=annotations(c['ast']).get('FeignClient')
  if fa:
   d=attrs(fa);module=d.get('name',d.get('value'));rr=route(m);prefix=d.get('path','')
   if rr:
    verb,path=rr;path='/'+('/'.join([prefix.strip('/'),path.strip('/')])).strip('/');targets=routes.get((module,verb,path),[])+routes.get((module,'ANY',path),[])
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
 assert len(selected)==31 and len(ops)==49
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
 lines=['UseCaseModel JavaOnlineTaxi {']
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
   typ=f.type.name;render=typ if typ in set(entity_names.values()) else ('Integer' if typ in ['int','long','Integer','Long','byte','Byte','Short','short'] else 'Real' if typ in ['Double','double','Float','float','BigDecimal'] else 'Date' if 'Date' in typ else 'String')
   for d in f.declarators:lines.append('  '+d.name+' : '+render);fs.append({'name':d.name,'java_type':typ,'model_type':render})
  lines+=[' }'];entity_rows.append({'entity':name,'java_class':fq,'path':c['path'],'fields':fs})
 for o in ops:
  lines+=[' Contract '+o['service']+'::'+o['id']+'() : Boolean {','  definition:']+['   ref'+entity+' : '+entity for entity in o['entities']]+['  postcondition:']+['   '+call['service']+'::'+call['operation']+'() and' for call in o['resolved_service_calls']]+['   result = true',' }']
 lines+=['}'];model=out/'java-online-taxi.remodel';model.write_text('\n'.join(lines)+'\n')
 records=[]
 for fq,c in list(selected.items())+[(fq,classes[fq]) for fq in entity_names]:
  name=symbols[fq] if fq in selected else entity_names[fq];kind='service' if fq in selected else 'domain'
  # Redact literal credential assignments if any; property placeholders are preserved.
  text,n=re.subn(r'(?i)(\b(?:\w*(?:password|secret|apiKey|accessToken)\w*)\s*=\s*)"[^"\n]+"',r'\1"REDACTED"',c['text'])
  records.append({'fullName':'JavaOnlineTaxi.'+kind+'.'+name,'simpleName':name,'serviceName':name if kind=='service' else 'domain-model','content':text,'source_path':c['path'],'java_class':fq,'literal_assignments_redacted':n})
 write(out/'java-embedding/typeData.json',records)
 write(out/'source-manifest.json',{'source_directory':str(src),'java_files':files,'java_files_count':len(files),'source_tree_hash':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()})
 write(out/'method-graph.json',{k:{'direct_entities':sorted(entity_names[e] for e in v['direct']),'reachable_entities':sorted(entity_names[e] for e in reached[k]),'calls':sorted(v['edges'])} for k,v in methods.items()})
 write(out/'extraction.json',{'parser':'javalang 0.13.0','parsed_classes':len(classes),'services':symbols,'operations':ops,'entities':entity_rows,'feign_routes':feign,'unresolved_project_calls':unresolved,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'zero_entity_services':[s for s in symbols.values() if not any(o['entities'] for o in ops if o['service']==s)],'zero_entity_operations':[o['id'] for o in ops if not o['entities']],'entity_relationship_policy':'Only declared entity-typed fields. Scalar *Id fields are retained as scalar attributes; no guessed foreign keys.','usecase_policy':'One Spring @Service class is one use-case proxy; all its public non-static methods are operations. Existing module boundary is not a clustering constraint. Module roles are actor proxies.','method_graph_policy':'Declared receiver types + method name/arity; Feign module/HTTP method/path to Controller route; monotonic union of reachable Mapper/entity types. No reflection/runtime dispatch/library implementation modeling.','seconds':time.perf_counter()-start})
 print(json.dumps({'source_files':len(files),'service_usecase_proxies':len(selected),'operations':len(ops),'entities':len(entity_names),'feign_routes':len(feign),'feign_matched':sum(bool(r['controller_targets']) for r in feign),'zero_entity_services':[s for s in symbols.values() if not any(o['entities'] for o in ops if o['service']==s)],'seconds':time.perf_counter()-start},ensure_ascii=False))
if __name__=='__main__':main()
