"""Module-scoped Java/MyBatis extraction. No network or application execution."""
import argparse,collections,hashlib,json,re,shutil,time
from pathlib import Path
import xml.etree.ElementTree as ET
import javalang as jl

def write(p,d):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def letters(s):return ''.join(x[:1].upper()+x[1:] for x in re.findall('[A-Za-z]+',s))
def anns(n):return {a.name:a for a in n.annotations}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
 start=time.perf_counter();src=args.source.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
 modules={};artifacts={};ns={'m':'http://maven.apache.org/POM/4.0.0'};pom_records=[]
 for p in sorted(src.rglob('pom.xml')):
  if '/target/' in str(p):continue
  root=ET.fromstring(p.read_text());module=str(p.parent.relative_to(src));artifact=root.findtext('m:artifactId',namespaces=ns)
  deps=[e.findtext('m:artifactId',namespaces=ns) for e in root.findall('m:dependencies/m:dependency',ns)]
  modules[module]={'artifact':artifact,'dependencies':deps,'parent':root.findtext('m:parent/m:artifactId',namespaces=ns)};artifacts[artifact]=module
  rel=p.relative_to(src);target=out/'source-java'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  pom_records.append({'path':str(rel),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 def dependencies(mod):
  result={mod};todo=[mod]
  while todo:
   m=todo.pop()
   for a in modules.get(m,{}).get('dependencies',[])+[modules.get(m,{}).get('parent')]:
    dep=artifacts.get(a)
    if dep is not None and dep not in result:result.add(dep);todo.append(dep)
  return result
 scopes={m:dependencies(m) for m in modules};classes={};fq_index=collections.defaultdict(list);files=[]
 for p in sorted(src.rglob('*.java')):
  if '/src/main/java/' not in str(p) or '/target/' in str(p):continue
  text=p.read_text();tree=jl.parse.parse(text);rel=p.relative_to(src);mod=str(rel).split('/src/main/java/')[0]
  target=out/'source-java'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  files.append({'path':str(rel),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
  for c in tree.types:
   if not hasattr(c,'methods'):continue
   fq=tree.package.name+'.'+c.name;key=mod+'|'+fq
   assert key not in classes
   classes[key]={'ast':c,'fqn':fq,'module':mod,'group':rel.parts[0],'path':str(rel),'package':tree.package.name,'imports':{i.path.rsplit('.',1)[-1]:i.path for i in tree.imports if not i.wildcard and not i.static},'wildcards':[i.path for i in tree.imports if i.wildcard and not i.static],'text':text}
   fq_index[fq].append(key)
 unresolved_types=set()
 def pick(c,fq):
  options=fq_index.get(fq,[]);local=c['module']+'|'+fq
  if local in options:return local
  allowed=[k for k in options if classes[k]['module'] in scopes.get(c['module'],{c['module']})]
  if len(allowed)==1:return allowed[0]
  # Same business group is a secondary source-layout cue when POM inheritance is incomplete.
  same=[k for k in allowed or options if classes[k]['group']==c['group']]
  if len(same)==1:return same[0]
  if len(options)==1:return options[0]
  if options:unresolved_types.add((c['module'],fq,tuple(options)))
  return fq
 def resolve(c,name,bind=None):
  if bind and name in bind:return bind[name]
  if name in classes:return name
  if name in fq_index:return pick(c,name)
  if name in c['imports']:return pick(c,c['imports'][name])
  local=c['package']+'.'+name
  if local in fq_index:return pick(c,local)
  matches=[pick(c,w+'.'+name) for w in c['wildcards'] if w+'.'+name in fq_index]
  if len(matches)==1:return matches[0]
  return name
 def types(c,node,bind=None):return {resolve(c,t.name,bind) for _,t in node.filter(jl.tree.ReferenceType)} if isinstance(node,jl.ast.Node) else set()
 def parents(q):
  c=classes[q];a=c['ast'];result=[];ext=getattr(a,'extends',None)
  for t in (ext if isinstance(ext,list) else [ext])+(getattr(a,'implements',None) or []):
   if not t:continue
   parent=resolve(c,t.name)
   if parent in classes:
    params=getattr(classes[parent]['ast'],'type_parameters',None) or [];argv=t.arguments or []
    bind={v.name:resolve(c,arg.type.name) for v,arg in zip(params,argv) if arg.type}
    result.append((parent,bind))
  return result
 inheritance={q:parents(q) for q in classes}
 entity_set=set()
 for q,c in classes.items():
  for _,t in c['ast'].filter(jl.tree.ReferenceType):
   if t.name in ['BaseMapper','ElasticsearchRepository','CrudRepository','MongoRepository'] and t.arguments and t.arguments[0].type:
    e=resolve(c,t.arguments[0].type.name)
    if e in classes:entity_set.add(e)
  if {'TableName','Document'}&anns(c['ast']).keys():entity_set.add(q)
 assert entity_set
 entity_names={q:letters(classes[q]['module'])+classes[q]['ast'].name for q in sorted(entity_set)}
 assert len(set(entity_names.values()))==len(entity_names)
 class_entities={q:types(c,c['ast'])&entity_set for q,c in classes.items()}
 selected={q:c for q,c in classes.items() if isinstance(c['ast'],jl.tree.ClassDeclaration) and 'Service' in anns(c['ast'])}
 symbols={q:letters(c['module'])+c['ast'].name for q,c in selected.items()}
 assert len(set(symbols.values()))==len(symbols)
 # Materialize effective fields and source-backed inherited concrete/default methods.
 def effective(q,seen=None,bind=None):
  seen=set(seen or []);bind=bind or {}
  if q in seen:return {},{}
  seen.add(q);c=classes[q];fields={};methods={}
  for parent,pb in inheritance[q]:
   pb={n:bind.get(v,v) for n,v in pb.items()};pf,pm=effective(parent,seen,pb);fields.update(pf);methods.update(pm)
  for f in c['ast'].fields:
   for d in f.declarators:fields[d.name]=(q,f,d,bind)
  for m in c['ast'].methods:
   if m.body is not None:methods[(m.name,tuple(resolve(c,p.type.name,bind)+'[]'*len(p.type.dimensions or []) for p in m.parameters))]=(q,m,bind)
  return fields,methods
 effective_cache={q:effective(q) for q in classes}
 methods={};index=collections.defaultdict(list)
 for q,c in classes.items():
  entries=effective_cache[q][1] if q in selected else {(m.name,len(m.parameters),m.position.line):(q,m,{}) for m in c['ast'].methods}
  for origin,m,bind in entries.values():
   key=q+'#'+m.name+'/'+str(len(m.parameters))+'@'+str(m.position.line)
   methods[key]={'owner':q,'origin':origin,'ast':m,'bindings':bind,'direct':types(classes[origin],m,bind)&entity_set,'edges':set()};index[q,m.name,len(m.parameters)].append(key)
 impls=collections.defaultdict(list)
 for q in selected:
  todo=[q];seen=set()
  while todo:
   child=todo.pop()
   if child in seen:continue
   seen.add(child)
   for parent,_ in inheritance[child]:impls[parent].append(q);todo.append(parent)
 for (q,n,arity),keys in list(index.items()):
  for child in set(impls[q]):
   for k in keys:methods[k]['edges'].update(index.get((child,n,arity),[]))
 def constant(c,node):
  if isinstance(node,jl.tree.Literal):
   try:return json.loads(node.value)
   except Exception:return node.value
  if isinstance(node,jl.tree.MemberReference):
   target=resolve(c,node.qualifier) if node.qualifier else None
   if target in classes:
    for f in classes[target]['ast'].fields:
     for d in f.declarators:
      if d.name==node.member and isinstance(d.initializer,jl.tree.Literal):return constant(classes[target],d.initializer)
   return node.member
  if isinstance(node,jl.tree.ElementArrayValue):return [constant(c,x) for x in node.values]
  return None
 def attrs(c,a):
  if not a:return {}
  return {v.name:constant(c,v.value) for v in a.element} if isinstance(a.element,list) else {'value':constant(c,a.element)}
 def route(c,node):
  for a in node.annotations:
   if a.name in ['RequestMapping','GetMapping','PostMapping','PutMapping','DeleteMapping','PatchMapping']:
    d=attrs(c,a);p=d.get('value',d.get('path',''));p=p[0] if isinstance(p,list) else p
    verb=d.get('method',a.name.replace('Mapping','').upper() if a.name!='RequestMapping' else 'ANY');verb=verb[0] if isinstance(verb,list) else verb
    return verb,p or ''
 def canon(p):return re.sub(r'\{[^}]+\}','{}',p.rstrip('/') or '/')
 routes=collections.defaultdict(list)
 for q,c in classes.items():
  if not {'RestController','Controller'}&anns(c['ast']).keys():continue
  prefix=(route(c,c['ast']) or ('ANY',''))[1]
  for m in c['ast'].methods:
   rr=route(c,m)
   if rr:
    v,p=rr;p='/'+('/'.join([prefix.strip('/'),p.strip('/')])).strip('/');routes[c['group'],v,canon(p)].extend(index[q,m.name,len(m.parameters)])
 feign=[];unresolved_calls=[]
 for k,info in methods.items():
  q=info['owner'];origin=classes[info['origin']];c=classes[q];m=info['ast'];bind=info['bindings']
  env={n:resolve(classes[o],f.type.name,bb) for n,(o,f,_,bb) in effective_cache[q][0].items()}
  env.update({v.name:resolve(origin,v.type.name,bind) for v in m.parameters})
  for _,v in m.filter(jl.tree.LocalVariableDeclaration):env.update({d.name:resolve(origin,v.type.name,bind) for d in v.declarators})
  explicit={}
  for _,this in m.filter(jl.tree.This):
   receiver=q
   for sel in this.selectors or []:
    if isinstance(sel,jl.tree.MemberReference):receiver=env.get(sel.member)
    elif isinstance(sel,jl.tree.MethodInvocation):explicit[id(sel)]=receiver;break
  for _,call in m.filter(jl.tree.MethodInvocation):
   qualifier=call.qualifier or '';first=qualifier.split('.')[0]
   receiver=explicit.get(id(call),env.get(first) if qualifier else q)
   if receiver is None:receiver=resolve(origin,first,bind)
   if receiver in entity_set:info['direct'].add(receiver)
   if receiver in classes:
    if classes[receiver]['ast'].name.endswith(('Mapper','Repository')):info['direct'].update(class_entities[receiver])
    targets=index.get((receiver,call.member,len(call.arguments)),[]);info['edges'].update(targets)
    if not targets:unresolved_calls.append({'caller':k,'receiver':receiver,'member':call.member})
  # Same-class method references are resolved by all source arities; overload dispatch remains conservative.
  for _,ref in m.filter(jl.tree.MethodReference):
   expr=ref.expression;receiver=q if isinstance(expr,jl.tree.This) else env.get(getattr(expr,'member',''),resolve(origin,getattr(expr,'member',''),bind))
   member=getattr(ref.method,'member',None)
   for (owner,name,_),keys in index.items():
    if owner==receiver and name==member:info['edges'].update(keys)
  fa=anns(c['ast']).get('FeignClient')
  if fa:
   d=attrs(c,fa);group=d.get('name',d.get('value'));rr=route(c,m);prefix=d.get('path','')
   if rr:
    v,p=rr;p='/'+('/'.join([prefix.strip('/'),p.strip('/')])).strip('/');targets=routes.get((group,v,canon(p)),[])+routes.get((group,'ANY',canon(p)),[])
    if v=='ANY':targets+=sum([ts for (g,_,rp),ts in routes.items() if g==group and rp==canon(p)],[])
    info['edges'].update(targets);feign.append({'method':k,'target_module':group,'verb':v,'path':p,'controller_targets':sorted(set(targets))})
 reached={k:set(v['direct']) for k,v in methods.items()}
 for _ in range(len(methods)):
  changed=False
  for k,v in methods.items():
   new=reached[k]|set().union(*(reached[t] for t in v['edges']))
   if new!=reached[k]:reached[k]=new;changed=True
  if not changed:break
 ops=[];seen=collections.Counter()
 for q,c in selected.items():
  for (owner,name,arity),keys in index.items():
   if owner!=q:continue
   for k in keys:
    info=methods[k];m=info['ast'];oa=classes[info['origin']]['ast']
    if 'static' in m.modifiers or ('public' not in m.modifiers and not isinstance(oa,jl.tree.InterfaceDeclaration)):continue
    if m.body is None:continue
    base=symbols[q]+name[:1].upper()+name[1:];seen[base]+=1;symbol=base+('Overload'+chr(64+seen[base]) if seen[base]>1 else '')
    assert re.fullmatch('[A-Za-z]+',symbol),symbol
    ops.append({'id':symbol,'service':symbols[q],'java_method':k,'declaring_class':info['origin'],'path':classes[info['origin']]['path'],'line':m.position.line,'inherited':info['origin']!=q,'generic_bindings':info['bindings'],'direct_entities':sorted(entity_names[e] for e in info['direct']),'entities':sorted(entity_names[e] for e in reached[k]),'calls':sorted(info['edges'])})
 op_by_method={o['java_method']:o for o in ops}
 for o in ops:
  todo=list(methods[o['java_method']]['edges']);visited=set();targets=set()
  while todo:
   k=todo.pop()
   if k in visited:continue
   visited.add(k)
   if k in op_by_method and op_by_method[k]['service']!=o['service']:targets.add(k);continue
   todo.extend(methods[k]['edges'])
  o['resolved_service_calls']=[{'service':op_by_method[k]['service'],'operation':op_by_method[k]['id'],'java_method':k} for k in sorted(targets)]
 lines=['UseCaseModel Spring {']+[' UC::'+s+'()' for s in symbols.values()]
 for group in sorted({c['group'] for c in selected.values()}):lines+=[' Actor '+letters(group)+'Role {']+['  '+symbols[q] for q,c in selected.items() if c['group']==group]+[' }']
 for q,s in symbols.items():lines+=[' Service '+s+' {','  [Operation]']+['  '+o['id']+'()' for o in ops if o['service']==s]+[' }']
 entities=[]
 for q,name in entity_names.items():
  fs=[];lines+=[' Entity '+name+' {']
  for fname,(origin,f,d,bind) in effective_cache[q][0].items():
   if 'static' in f.modifiers:continue
   c=classes[origin];typ=f.type.name;refs=sorted(types(c,f.type,bind)&entity_set)
   assert len(refs)<=1,(q,fname,refs)
   render=entity_names[refs[0]] if refs else 'Integer' if typ in ['int','long','Long','Integer','short','Short','byte','Byte'] else 'Real' if typ in ['Double','double','Float','float','BigDecimal'] else 'Date' if 'Date' in typ else 'String'
   lines.append('  '+fname+' : '+render+(' Association' if refs else ''))
   fs.append({'name':fname,'java_type':typ,'model_type':render,'entity_references':[entity_names[e] for e in refs],'source_class':origin,'inherited':origin!=q})
  lines+=[' }'];entities.append({'entity':name,'java_class':classes[q]['fqn'],'module':classes[q]['module'],'path':classes[q]['path'],'fields':fs})
 for o in ops:lines+=[' Contract '+o['service']+'::'+o['id']+'() : Boolean {','  definition:']+['   ref'+e+' : '+e for e in o['entities']]+['  postcondition:']+['   '+call['service']+'::'+call['operation']+'() and' for call in o['resolved_service_calls']]+['   result = true',' }']
 lines+=['}'];model=out/'Spring.remodel';model.write_text('\n'.join(lines)+'\n')
 records=[]
 for q in list(selected)+sorted(entity_set):
  c=classes[q];kind='service' if q in selected else 'domain';name=symbols[q] if q in selected else entity_names[q]
  text,n=re.subn(r'(?i)(\b(?:\w*(?:password|secret|apiKey|accessToken)\w*)\s*=\s*)"[^"\n]+"',r'\1"REDACTED"',c['text'])
  records.append({'fullName':'Spring.'+kind+'.'+name,'simpleName':name,'serviceName':name if kind=='service' else 'domain-model','content':text,'source_path':c['path'],'java_class':c['fqn'],'module':c['module'],'literal_assignments_redacted':n})
 write(out/'java-embedding/typeData.json',records)
 write(out/'source-manifest.json',{'source_directory':str(src),'java_files':files,'java_files_count':len(files),'mapper_xml_files':[],'pom_files':pom_records,'source_tree_hash':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()})
 write(out/'method-graph.json',{k:{'direct_entities':sorted(entity_names[e] for e in v['direct']),'reachable_entities':sorted(entity_names[e] for e in reached[k]),'calls':sorted(v['edges'])} for k,v in methods.items()})
 d={'parser':'javalang 0.13.0','parsed_classes':len(classes),'modules':modules,'module_scopes':{m:sorted(v) for m,v in scopes.items()},'duplicate_fqns':{q:v for q,v in fq_index.items() if len(v)>1},'ambiguous_types':[list(v) for v in sorted(unresolved_types)],'services':symbols,'operations':ops,'entities':entities,'feign_routes':feign,'unresolved_project_calls':unresolved_calls,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'zero_entity_services':[s for s in symbols.values() if not any(o['entities'] for o in ops if o['service']==s)],'zero_entity_operations':[o['id'] for o in ops if not o['entities']],'zero_operation_services':[s for s in symbols.values() if not any(o['service']==s for o in ops)],'inheritance_policy':'Public source-backed class and default interface methods instantiated with generic substitutions, excluding overrides by name/arity. Effective inherited entity fields flattened with per-field source origin. External library methods and Lombok-generated bodies are not synthesized.','entity_relationship_policy':'BaseMapper/repository first generic type or TableName/Document annotation. Actual explicit entity fields form associations; scalar IDs are not guessed as foreign keys.','method_graph_policy':'Maven module local/import/dependency/group resolution; declaration types, inherited generic fields, this.field, interface implementations and conservative same-class method references. Feign constants/verb/path matched. No full overload, chained return type, reflection or dynamic execution modeling.','usecase_policy':'One Service-annotated class is one usecase proxy; group module is actor proxy, not hand-authored requirements.','seconds':time.perf_counter()-start}
 write(out/'extraction.json',d)
 print(json.dumps({'source_files':len(files),'services':len(selected),'operations':len(ops),'inherited_operations':sum(o['inherited'] for o in ops),'entities':len(entities),'fields':sum(len(e['fields']) for e in entities),'feign_routes':len(feign),'feign_matched':sum(bool(f['controller_targets']) for f in feign),'zero_entity_services':d['zero_entity_services'],'zero_operation_services':d['zero_operation_services'],'ambiguous_type_count':len(unresolved_types),'embedding_records':len(records),'max_record_chars':max(len(r['content']) for r in records)},ensure_ascii=False))
if __name__=='__main__':main()
