"""Read x64 PE import/export tables without third-party packages."""
import struct,json,sys
from pathlib import Path
class PE:
 def __init__(self,path):
  self.data=Path(path).read_bytes();d=self.data;pe=self.u32(0x3c)
  assert d[:2]==b'MZ' and d[pe:pe+4]==b'PE\0\0'
  assert self.u16(pe+4)==0x8664
  opt=pe+24;assert self.u16(opt)==0x20b
  self.sections=[]
  for i in range(self.u16(pe+6)):
   sec=opt+self.u16(pe+20)+i*40
   self.sections.append((self.u32(sec+12),max(self.u32(sec+8),self.u32(sec+16)),self.u32(sec+20)))
  self.dirs=[(self.u32(opt+112+i*8),self.u32(opt+116+i*8)) for i in range(min(16,self.u32(opt+108)))]
  self.exports={};self.ordinals=set();self.imports={}
  er,es=self.dirs[0]
  if er:
   e=self.offset(er);base=self.u32(e+16);nf=self.u32(e+20);nn=self.u32(e+24)
   funcs=self.offset(self.u32(e+28));names=self.offset(self.u32(e+32));ords=self.offset(self.u32(e+36))
   self.ordinals={base+i for i in range(nf) if self.u32(funcs+i*4)}
   for i in range(nn):
    name=self.string(self.u32(names+i*4));ordinal=base+self.u16(ords+i*2)
    self.exports[name]=ordinal
  ir,isize=self.dirs[1]
  if ir:
   p=self.offset(ir)
   while any(self.data[p:p+20]):
    name=self.string(self.u32(p+12)).lower();thunks=self.offset(self.u32(p) or self.u32(p+16));imports=[]
    while self.u64(thunks):
     v=self.u64(thunks);imports.append(int(v&0xffff) if v>>63 else self.string(v+2));thunks+=8
    self.imports[name]=imports;p+=20
  # Delay-load descriptors are separate from the normal import table.
  self.delay_imports={}
  if len(self.dirs)>13 and self.dirs[13][0]:
   p=self.offset(self.dirs[13][0]);image_base=self.u64(opt+24)
   while any(self.data[p:p+32]):
    fields=struct.unpack_from('<8I',self.data,p);attrs,name,handle,iat,intable,bound,unload,stamp=fields
    def rva(value):return value if attrs&1 else value-image_base
    dep=self.string(rva(name)).lower();t=self.offset(rva(intable or iat));symbols=[]
    while self.u64(t):
     value=self.u64(t);symbols.append(int(value&0xffff) if value>>63 else self.string(rva(value)+2));t+=8
    self.delay_imports[dep]=symbols;self.imports.setdefault(dep,[]).extend(symbols);p+=32
 def u16(self,o):return struct.unpack_from('<H',self.data,o)[0]
 def u32(self,o):return struct.unpack_from('<I',self.data,o)[0]
 def u64(self,o):return struct.unpack_from('<Q',self.data,o)[0]
 def offset(self,rva):
  for va,size,raw in self.sections:
   if va<=rva<va+size:return raw+rva-va
  return rva
 def string(self,rva):
  o=self.offset(rva);e=self.data.index(0,o);return self.data[o:e].decode('ascii')
def verify(directory,baseline=None):
 modules={p.name.lower():PE(p) for p in Path(directory).iterdir() if p.suffix.lower() in ['.dll','.exe']}
 result={'modules':{},'missing_internal_imports':[],'external_import_modules':[],'baseline_missing_exports':{}}
 external=set()
 for name,pe in modules.items():
  result['modules'][name]={'export_names':len(pe.exports),'export_ordinals':len(pe.ordinals),'imports':{k:len(v) for k,v in pe.imports.items()},'delay_imports':{k:len(v) for k,v in pe.delay_imports.items()}}
  for dep,imports in pe.imports.items():
   if dep not in modules:external.add(dep);continue
   for symbol in imports:
    if (symbol not in modules[dep].ordinals if isinstance(symbol,int) else symbol not in modules[dep].exports):result['missing_internal_imports'].append([name,dep,symbol])
 if baseline:
  for path in Path(baseline).iterdir():
   if path.name.lower() in modules:
    before=PE(path);after=modules[path.name.lower()]
    missing=sorted(set(before.exports)-set(after.exports));result['baseline_missing_exports'][path.name]=missing
 result['external_import_modules']=sorted(external)
 assert not result['missing_internal_imports'],result['missing_internal_imports']
 assert not any(result['baseline_missing_exports'].values()),result['baseline_missing_exports']
 return result
if __name__=='__main__':print(json.dumps(verify(*sys.argv[1:]),indent=2))
