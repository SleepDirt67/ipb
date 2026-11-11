"""Add the checked capture tools and matching symbol indices to the existing Release."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_lock import digest

bundle = Path(__file__).resolve().parent
package = Path("package")
checks = Path("checks")
capture = package / "capture-tools"
capture.mkdir()
tools = checks / "spawn-path/Release"
for name in ("ixray_etw_decode", "ixray_stack_extract", "ixray_display_path"):
    shutil.copy2(tools / (name + ".exe"), capture)
for name in ("PresentMon-2.6.0-x64.exe", "PresentMon-LICENSE.txt"):
    shutil.copy2(checks / name, capture)

runtime = checks / "python-embed.zip"
expected = "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38"
assert digest(runtime) == expected, "Python embedded runtime checksum mismatch"
with ZipFile(runtime) as archive:
    archive.extractall(capture / "python")
for file in (bundle / "capture").iterdir():
    if file.suffix != ".cpp":
        shutil.copy2(file, package)
shutil.copy2(bundle / "analyze_spawn_path.py", package)

indices = capture / "stack-symbols"
indices.mkdir()
symbols = Path("symbols").resolve()
binary_manifest_path = package / "BUILD_MANIFEST.json"
binary_manifest = json.loads(binary_manifest_path.read_text())
symbol_manifest = json.loads((symbols / "SYMBOLS_MANIFEST.json").read_text())
assert symbol_manifest["source_commit"] == binary_manifest["commit"]
for record in symbol_manifest["files"]:
    module = package / "bin" / record["module"]
    pdb = symbols / record["pdb"]
    assert digest(module) == record["module_sha256"] and digest(pdb) == record["pdb_sha256"]
    index = indices / (module.name + ".tsv")
    subprocess.run([str((capture / "ixray_stack_extract.exe").resolve()), "--index",
                    str(module.resolve()), str(symbols), str(index.resolve())], check=True)
    assert index.stat().st_size > 0
    record["index_sha256"] = digest(index)
(indices / "INDEX_MANIFEST.json").write_text(json.dumps(symbol_manifest, indent=2) + "\n")
binary_manifest["capture_kind"] = "spawn-path-v1"
binder = bundle.parent / "binder-capture"
for file in (binder / "capture").iterdir():
    if file.is_file():
        shutil.copy2(file, package)
shutil.copy2(checks / "binder/instrumentation_map.json", package)
shutil.copy2(checks / "BINDER_OBSERVER.json", package / "binder_observer.json")
shutil.copy2(Path("binder-checks/Release/binder_capture_runtime_test.exe"), capture)
shutil.copy2(package / "bin/lua51.dll", capture)
binary_manifest["binder_capture"] = {
    "schema": 5,
    "base": "886337084c8fd851a4fff186b453ae7cc6450821",
    "acceptance": "matched native replay and scheduler observer bound",
    "observer_sha256": digest(package / "binder_observer.json"),
}
binary_manifest_path.write_text(json.dumps(binary_manifest, indent=2) + "\n")
files = sorted(path for path in package.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
(package / "SHA256SUMS.txt").write_text(
    "".join(f"{digest(path)}  {path.relative_to(package).as_posix()}\n" for path in files), newline="\n")
