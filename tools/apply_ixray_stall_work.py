#!/usr/bin/env python3
"""Apply audited behavior-preserving hotpaths and optional frame correlation after PR15."""
from pathlib import Path
import argparse, re, subprocess, json, hashlib
parser=argparse.ArgumentParser();parser.add_argument('--performance-only',action='store_true');parser.add_argument('--engine',default='ixray');args=parser.parse_args()
repo=Path(__file__).resolve().parents[1]; engine=Path(args.engine)
headers=['src/xrEngine/IGame_ObjectPool.h','src/xrEngine/IGame_Persistent.h']
for name in headers:
 expected=subprocess.check_output(['git','-C',str(engine),'show','612b165c97d5e6a50ac0a6d1384ac8c95a63dda5:'+name]).replace(b'\r\n',b'\n')
 actual=(engine/name).read_bytes().replace(b'\r\n',b'\n')
 assert expected==actual, f'ABI baseline mismatch: {name}'
for name in ['performance.patch']+([] if args.performance_only else ['trace.patch']):
 patch=repo/'experiments/stall-work-136'/name
 patch.write_bytes(patch.read_bytes().replace(b'\r\n',b'\n'))
 for path in re.findall(rb'^--- a/(.+)$',patch.read_bytes(),re.M):
  file=engine/path.decode();file.write_bytes(file.read_bytes().replace(b'\r\n',b'\n').rstrip(b'\n')+b'\n')
 subprocess.run(['git','-C',str(engine),'apply','--check',str(patch)],check=True)
 subprocess.run(['git','-C',str(engine),'apply',str(patch)],check=True)
for name in headers:
 expected=subprocess.check_output(['git','-C',str(engine),'show','612b165c97d5e6a50ac0a6d1384ac8c95a63dda5:'+name]).replace(b'\r\n',b'\n')
 assert (engine/name).read_bytes().replace(b'\r\n',b'\n')==expected, f'ABI changed: {name}'
lock=json.loads((repo/'experiments/stall-work-136/DEPENDENCY_LOCK.json').read_text())
for name, entry in lock.items():
    file=engine/name
    data=file.read_bytes().replace(b'\r\n',b'\n')
    before=entry['before'].encode();after=entry['after'].encode()
    assert data.count(before)==1, f'Dependency anchor mismatch: {name}'
    file.write_bytes(data.replace(before,after))
guard=engine/'src/xrEngine/StallWorkAbiGuard.cpp'
guard.write_text('''#include "stdafx.h"
#include "IGame_Persistent.h"
#include <cstddef>
static_assert(sizeof(void*) == 8, "This artifact must be x64");
static_assert(sizeof(IGame_ObjectPool) == sizeof(void*) + sizeof(xr_vector<CObject*>), "Object pool ABI expanded");
static_assert(alignof(IGame_ObjectPool) == alignof(void*), "Object pool alignment changed");
static_assert(offsetof(IGame_Persistent, pEnvironment) == offsetof(IGame_Persistent, ObjectPool) + sizeof(IGame_ObjectPool), "Persistent ABI offset changed");
static_assert(offsetof(IGame_Persistent, m_pMainMenu) == offsetof(IGame_Persistent, pEnvironment) + sizeof(void*), "Main menu offset changed");
''',encoding='utf-8')
# Canonical gameplay controls must still be present; source hashes retained in artifact.
expected_controls=json.loads((repo/'experiments/stall-work-136/CONTROL_BASELINE_SHA256.json').read_text())
for path, expected in expected_controls.items():
    data=(engine/path).read_bytes().replace(b'\r\n',b'\n')
    if path=='src/xrEngine/Xr_input.cpp' and not args.performance_only:
        data=data.replace(b'#include "FrameStallDiagnostics.h"\n',b'').replace(b'    FrameStallDiag::DetailScope detail(FrameStallDiag::Stage::InputFrame);\n',b'')
    assert hashlib.sha256(data).hexdigest()==expected, f'Control source changed: {path}'
if not args.performance_only:
 text=(engine/'src/xrEngine/FrameStallDiagnostics.h').read_text()
 enum=text.split('enum class Stage : unsigned {',1)[1].split('Count',1)[0]
 stages=re.findall(r'\b[A-Za-z]\w*\b',enum)
 (repo/'experiments/stall-work-136/TRACE_STAGES.json').write_text(json.dumps(dict(enumerate(stages)),indent=2)+'\n')
print('PR15 ABI headers match upstream; HOLD/crouch/wheel source hashes match PR15; compile guards installed')
