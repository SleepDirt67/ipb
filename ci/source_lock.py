"""Check the exact public build inputs before the first source transformation."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
lock_path = root / 'ci/source-lock.json'
upstream = '612b165c97d5e6a50ac0a6d1384ac8c95a63dda5'
luabind = '128ba59572e508f0c550f4ff8a5235c07c77de3d'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == '__main__':
    if sys.argv[1:] == ['--seal']:
        paths = sorted(p for p in root.rglob('*') if p.is_file()
                       and p != lock_path and '__pycache__' not in p.parts)
        manifest = {p.relative_to(root).as_posix(): digest(p) for p in paths}
        lock_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii', newline='\n')
    else:
        expected = json.loads(lock_path.read_text())
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
        assert set(filter(None, tracked)) == set(expected) | {'ci/source-lock.json'}
        for name, sha in expected.items():
            assert digest(root / name) == sha, name
        actual = subprocess.check_output(['git', '-C', 'ixray', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        assert actual == upstream
        print(f'Verified {len(expected)} exact build inputs and upstream {actual}')
