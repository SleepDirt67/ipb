"""Read actual PE CodeView and MSF7 PDB identities; compare GUID bytes and age."""
from pathlib import Path
import struct,json,sys,uuid,shutil,subprocess,re
def rsds(path):
 d=path.read_bytes();pe=struct.unpack_from('<I',d,0x3c)[0];opt=pe+24
 sections=[]
 for n in range(struct.unpack_from('<H',d,pe+6)[0]):
  p=opt+struct.unpack_from('<H',d,pe+20)[0]+40*n
  size,rva,rawsize,raw=struct.unpack_from('<4I',d,p+8);sections.append((rva,max(size,rawsize),raw))
 def at(rva):
  for v,s,r in sections:
   if v<=rva<v+s:return r+rva-v
  return rva
 rva,size=struct.unpack_from('<2I',d,opt+112+6*8)
 if not rva:return None
 for offset in range(at(rva),at(rva)+size,28):
  kind,length,location,raw=struct.unpack_from('<4I',d,offset+12)
  if kind==2 and d[raw:raw+4]==b'RSDS':return d[raw+4:raw+20],struct.unpack_from('<I',d,raw+20)[0]
def pdb_info(path):
 d=path.read_bytes();assert d.startswith(b'Microsoft C/C++ MSF 7.00\r\n\x1aDS\x00\x00\x00'),(path,d[:32])
 block,free,num,bytes_,reserved,mapblock=struct.unpack_from('<6I',d,32)
 dirs=struct.unpack_from('<'+'I'*((bytes_+block-1)//block),d,mapblock*block)
 directory=b''.join(d[i*block:(i+1)*block] for i in dirs)[:bytes_];streams=struct.unpack_from('<I',directory)[0]
 sizes=struct.unpack_from('<'+'I'*streams,directory,4);offset=4+4*streams
 for i,size in enumerate(sizes):
  count=0 if size==0xffffffff else (size+block-1)//block
  blocks=struct.unpack_from('<'+'I'*count,directory,offset);offset+=4*count
  if i==1:
   data=b''.join(d[j*block:(j+1)*block] for j in blocks)[:size]
   return data[12:28],struct.unpack_from('<I',data,8)[0]
 raise AssertionError(path)

if __name__=='__main__':
 pe=Path(sys.argv[1]);pdb=Path(sys.argv[2]);identity=rsds(pe);other=pdb_info(pdb)
 assert identity is not None and identity==other,(identity,other)
 result={'module':pe.name,'pdb':pdb.name,'GUID':str(uuid.UUID(bytes_le=identity[0])),'age':identity[1],'MSF7_magic_verified':True}
 tool=shutil.which('llvm-pdbutil')
 if tool:
  output=subprocess.check_output([tool,'dump','-summary',str(pdb)],text=True,errors='replace')
  guid=re.search(r'Guid:\s*\{?([0-9A-Fa-f-]{36})',output,re.I);age=re.search(r'Age:\s*(\d+)',output)
  assert guid and age and guid[1].lower()==result['GUID'].lower() and int(age[1])==identity[1],output
  result['independent_llvm_summary']=True
 else:result['independent_llvm_summary']=False
 print(json.dumps(result))
