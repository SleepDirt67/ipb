"""Bind the transformed engine source used by the build to the artifact."""
import json
from pathlib import Path
import subprocess
import sys
from source_lock import digest, upstream

engine = Path('ixray')
seal = Path('checks/PUBLIC_ENGINE_INPUTS.json')


def git_paths(*args):
    data = subprocess.check_output(['git', '-C', str(engine), *args])
    return set(filter(None, data.decode().split('\0')))


def engine_inputs():
    paths = git_paths('diff', '--name-only', '-z', upstream)
    paths |= git_paths('ls-files', '--others', '--exclude-standard', '-z', 'src',
                       'audit_core_integration.cpp', 'ixray_spawn_ini_fixture.cpp', 'ixray_spawn_plan_fixture.cpp', 'ixray_spawn_voice_catalog.cpp', 'ixray_spawn_contact_fixture.cpp', 'ixray_spawn_admission_fixture.cpp', 'ixray_spawn_mainline_replay.cpp')
    return {p: digest(engine / p) if (engine / p).is_file() else None for p in sorted(paths)}


if __name__ == '__main__':
    files = engine_inputs()
    if sys.argv[1:] == ['--seal']:
        seal.write_text(json.dumps(files, indent=2) + '\n', encoding='ascii', newline='\n')
    else:
        assert files == json.loads(seal.read_text()), 'engine inputs changed after the build seal'
    print(f'{len(files)} transformed/new engine input paths verified')
