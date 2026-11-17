"""Preserve auxiliary Mapper XML and README; does not alter extraction/model/API input."""
from pathlib import Path
import json,hashlib,shutil
import xml.etree.ElementTree as ET
b=Path(__file__).resolve().parents[1]/'runs/spring_20261104_01'
p=b/'input/source-manifest.json';manifest=json.loads(p.read_text());src=Path(manifest['source_directory']);xmls=[]
for f in sorted(src.rglob('*.xml')):
 if '/src/main/resources/' not in str(f) or '/target/' in str(f):continue
 try:root=ET.fromstring(f.read_text())
 except ET.ParseError:continue
 if root.tag!='mapper':continue
 rel=f.relative_to(src);target=b/'input/source-java'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
 xmls.append({'path':str(rel),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'used_for_method_graph':False})
manifest['mapper_xml_files']=xmls;p.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
for f in src.glob('README*'):
 if f.is_file():shutil.copy2(f,b/'input/source-java'/f.name)
print('Auxiliary Mapper XML snapshots:',len(xmls))
