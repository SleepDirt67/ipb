"""Apply the post-PR16 audit candidate; preserve exact baseline snapshots for tests."""
from pathlib import Path
import argparse,subprocess,re,json,hashlib,shutil,difflib
p=argparse.ArgumentParser();p.add_argument('--engine',default='ixray');args=p.parse_args()
engine=Path(args.engine).resolve();repo=Path(__file__).resolve().parents[1];checks=repo/'checks';checks.mkdir(exist_ok=True)
source=repo/'experiments/audit-136'
patches=[source/'performance.patch',source/'trace.patch']
for patch in patches: patch.write_bytes(patch.read_bytes().replace(b'\r\n',b'\n'))
paths=sorted(set(path for patch in patches for path in re.findall(rb'^--- a/(.+)$',patch.read_bytes(),re.M)))
for raw in paths:
 name=raw.decode();f=engine/name;b=f.read_bytes().replace(b'\r\n',b'\n');f.write_bytes(b)
 baseline=checks/'pr16-source'/name;baseline.parent.mkdir(parents=True,exist_ok=True);baseline.write_bytes(b)
# Audit-sensitive public layouts and gameplay controls are byte-identical to PR16.
protected=['src/xrEngine/IGame_ObjectPool.h','src/xrEngine/IGame_Persistent.h','src/Layers/xrRender/ModelPool.h']
controls=json.loads((repo/'experiments/stall-work-136/CONTROL_BASELINE_SHA256.json').read_text())
protected+=list(controls)
before={name:hashlib.sha256((engine/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in protected}
for patch in patches:
 subprocess.run(['git','-C',str(engine),'apply','--check',str(patch)],check=True)
 subprocess.run(['git','-C',str(engine),'apply',str(patch)],check=True)
assert before=={name:hashlib.sha256((engine/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in protected}
(checks/'PR16_PROTECTED_SOURCE_SHA256.json').write_text(json.dumps(before,indent=2)+'\n')
# Full class header diff: CUICellItem gains one NONvirtual method, no field or
# virtual slot; all other class headers remain protected above or unchanged.
header='src/xrGame/ui/UICellItem.h'
a=(checks/'pr16-source'/header).read_text();b=(engine/header).read_text()
assert b.replace('                CUICellItem* PopChildForDestroy();\n','')==a
(checks/'CELL_HEADER_DIFF.patch').write_text(''.join(difflib.unified_diff(a.splitlines(True),b.splitlines(True),fromfile='PR16/'+header,tofile='candidate/'+header)))
# Compile the integration executable inside the engine's exact include/define/link environment.
shutil.copy2(source/'tests/core_integration.cpp',engine/'audit_core_integration.cpp')
with (engine/'CMakeLists.txt').open('a') as f:
 f.write('\nadd_executable(ixray_audit_core_test audit_core_integration.cpp)\ntarget_include_directories(ixray_audit_core_test PRIVATE ${CMAKE_SOURCE_DIR}/src/xrCore)\ntarget_link_libraries(ixray_audit_core_test PRIVATE xrCore)\n')
text=(engine/'src/xrEngine/FrameStallDiagnostics.h').read_text();stages=re.findall(r'\b[A-Za-z]\w*\b',text.split('enum class Stage : unsigned {',1)[1].split('Count',1)[0])
(source/'TRACE_STAGES.json').write_text(json.dumps(dict(enumerate(stages)),indent=2)+'\n')
print('Audit patch applied; PR16 controls/Pool/Persistent/ModelPool layouts verified; cell method is nonvirtual only')
