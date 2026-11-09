"""Verify the rebuilt DLL against the pinned import library's original runtime."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from verify_ixray_pe import PE

stock, candidate = map(PE, sys.argv[1:])
assert stock.exports == candidate.exports, (
    sorted(stock.exports.keys() - candidate.exports.keys()),
    sorted(candidate.exports.keys() - stock.exports.keys()),
    sorted(name for name in stock.exports.keys() & candidate.exports.keys()
           if stock.exports[name] != candidate.exports[name]),
)
assert stock.ordinals == candidate.ordinals
print(f"Matched {len(stock.exports)} named LuaJIT exports and {len(stock.ordinals)} ordinals")
