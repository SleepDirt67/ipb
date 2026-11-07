"""Append diagnostics to exact PR17; reject gameplay/layout source changes."""
from pathlib import Path
import hashlib,json,subprocess,shutil,re
engine=Path('ixray');repo=Path(__file__).resolve().parents[1];src=repo/'experiments/periodic-136'
protected=list(json.loads((repo/'experiments/stall-work-136/CONTROL_BASELINE_SHA256.json').read_text()))
protected+=['src/xrEngine/IGame_ObjectPool.h','src/xrEngine/IGame_Persistent.h','src/Layers/xrRender/ModelPool.h','src/xrGame/ui/UICellItem.h','src/xrEngine/FrameStallDiagnostics.h','src/xrEngine/xrSheduler.cpp','src/xrGame/alife_update_manager.cpp','src/xrGame/script_binder.cpp']
def hashes():return {n:hashlib.sha256((engine/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for n in protected}
before=hashes();patch=src/'pacing.patch';data=patch.read_bytes().replace(b'\r\n',b'\n');patch.write_bytes(data)
for name in re.findall(rb'^--- a/(.+)$',data,re.M):
 p=engine/name.decode();p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n'))
subprocess.run(['git','-C',str(engine),'apply','--check',str(patch)],check=True)
subprocess.run(['git','-C',str(engine),'apply',str(patch)],check=True)
for name in ['PacingDiagnostics.h','PacingDiagnostics.cpp']:shutil.copy2(src/name,engine/'src/xrEngine'/name)
assert before==hashes()
Path('checks/PACING_PROTECTED_SOURCE_SHA256.json').write_text(json.dumps(before,indent=2)+'\n')
print('PR17 controls / public layouts / scheduler / ALife / binder protected; independent pacing overlay applied')

# Keep optimized Release code and emit matching PDBs for frame-specific ETW stacks.
with (engine/'CMakeLists.txt').open('a') as f:
 f.write('\nforeach(pacing_target xrEngine xrAbstractions xrGame xrCore xrScripts xrUI xrRender_R1 xrRender_R2 xrRender_R4 xrSound xrNetServer)\n if(TARGET ${pacing_target})\n  target_link_options(${pacing_target} PRIVATE /DEBUG:FULL /OPT:REF /OPT:ICF)\n endif()\nendforeach()\n')
