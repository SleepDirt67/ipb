"""Verify the rebuilt DLL against the pinned import library's original runtime."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from verify_ixray_pe import PE

stock, candidate = map(PE, sys.argv[1:3])
allowed = set()
if sys.argv[3:] == ["--binder-capture"]:
    allowed = {
        "xrBinderCaptureContext", "xrBinderCaptureInstall", "xrBinderCaptureRegister",
        "xrBinderCaptureStatus", "xrBinderCaptureTagNative", "xrBinderCaptureMethods",
    }
assert stock.exports == {name: ordinal for name, ordinal in candidate.exports.items() if name not in allowed}
assert set(candidate.exports) - set(stock.exports) == allowed
assert stock.ordinals | {candidate.exports[name] for name in allowed} == candidate.ordinals
print(f"Matched {len(stock.exports)} existing LuaJIT exports and ordinals; {len(allowed)} diagnostic exports")
