"""Package the tested Release directory and bind it to source, runtime and PDBs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from pdb_identity import pdb_info, rsds
from verify_ixray_pe import verify
from source_lock import digest, upstream, luabind

out = Path('ixray/build/x64/Engine-Windows/bin/Release')
package = Path('package')
symbol_root = Path('symbols')
bin_path = package / 'bin'
bin_path.mkdir(parents=True)
symbol_root.mkdir()
checks = package / 'checks'
checks.mkdir()
source = package / 'source'
source.mkdir()
modules, pdbs = [], []
for path in sorted(out.iterdir()):
    if path.suffix.lower() != '.dll' and path.name != 'xrEngine.exe':
        continue
    data = path.read_bytes()
    pe = int.from_bytes(data[0x3c:0x40], 'little')
    assert data[pe:pe + 6] == b'PE\0\0\x64\x86', path
    assert data[pe + 24:pe + 26] == b'\x0b\x02', path
    shutil.copy2(path, bin_path / path.name)
    entry = {'name': path.name, 'bytes': len(data), 'sha256': digest(path)}
    modules.append(entry)
    pdb = path.with_suffix('.pdb')
    if pdb.is_file():
        guid, age = rsds(path)
        assert (guid, age) == pdb_info(pdb), path.name
        shutil.copy2(pdb, symbol_root / pdb.name)
        pdbs.append({'module': path.name, 'pdb': pdb.name, 'module_sha256': entry['sha256'],
                     'pdb_sha256': digest(pdb), 'guid': guid.hex(), 'age': age})
assert len(modules) == 36 and len(pdbs) == 11, (len(modules), len(pdbs))
assert digest(bin_path / 'lua51.dll') == '09fd13282c381f5b9afae3debb986474656d466006c80591e9da251f0ddcc47c'
shutil.copy2('LICENSE.md', package / 'LICENSE.md')
for name in ('INSTALL.cmd', 'RESTORE.cmd', 'RUN_PERFORMANCE.cmd', 'install.ps1', 'restore.ps1',
             'installation_common.ps1', 'run.ps1'):
    shutil.copy2(Path('experiments/stall-work-136') / name, package / name)
for path in Path('checks').iterdir():
    if path.is_file() and path.suffix in ('.txt', '.json'):
        shutil.copy2(path, checks / path.name)
for name in ('ci/source-lock.json',):
    shutil.copy2(name, source / Path(name).name)
# Archive the exact engine delta plus newly generated files before packaging.
(source / 'engine.patch').write_bytes(subprocess.check_output(
    ['git', '-C', 'ixray', 'diff', '--binary', '--ignore-space-at-eol']))
for name in subprocess.check_output(['git', '-C', 'ixray', 'ls-files', '--others',
                                       '--exclude-standard', '-z', 'src',
                                       'audit_core_integration.cpp', 'ixray_spawn_ini_fixture.cpp', 'ixray_spawn_plan_fixture.cpp',
                                       'ixray_spawn_goap_fixture.cpp']
                                      ).decode().split('\0'):
    if name:
        dest = source / 'added' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path('ixray') / name, dest)
dependency_pins = {'luabind-src': luabind, 'sdl3-src': 'a96677bdf6b4acb84af4ec294e5f60a4e8cbbe03'}
for dependency, pin in dependency_pins.items():
    actual = subprocess.check_output(['git', '-C', str(out.parents[1] / '_deps' / dependency),
                                      'rev-parse', 'HEAD'], text=True).strip()
    assert actual == pin, (dependency, actual)
manifest = {
    'commit': os.environ['GITHUB_SHA'], 'build_repository': os.environ['GITHUB_REPOSITORY'],
    'run_id': os.environ['GITHUB_RUN_ID'], 'upstream_commit': upstream,
    'source_lock_sha256': digest(root / 'ci/source-lock.json'),
    'engine_inputs_sha256': digest(Path('checks/PUBLIC_ENGINE_INPUTS.json')),
    'dependency_commits': dependency_pins,
    'configuration': 'Release', 'architecture': 'x64',
    'ingame_tested': False, 'modules': modules, 'pe_validation': verify(bin_path),
}
(package / 'BUILD_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
(symbol_root / 'SYMBOLS_MANIFEST.json').write_text(
    json.dumps({'source_commit': manifest['commit'], 'files': pdbs}, indent=2) + '\n', encoding='utf-8')
shutil.copy2(symbol_root / 'SYMBOLS_MANIFEST.json', checks / 'SYMBOLS_MANIFEST.json')
files = sorted(p for p in package.rglob('*') if p.is_file())
(package / 'SHA256SUMS.txt').write_text(''.join(f'{digest(p)}  {p.relative_to(package).as_posix()}\n' for p in files),
                                       encoding='ascii', newline='\n')
print(f'Windows x64 Release, 36 modules, 11 exact PDB matches and {len(files)} SHA-256 entries')
