"""Compare the rebuilt runtime against the package used by the stock engine."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from verify_ixray_pe import PE

stock, candidate = map(PE, sys.argv[1:])
assert stock.exports == candidate.exports, (
    sorted(stock.exports.keys() - candidate.exports.keys()),
    sorted(candidate.exports.keys() - stock.exports.keys()),
    [(name, number, candidate.exports[name]) for name, number in stock.exports.items()
     if name in candidate.exports and candidate.exports[name] != number])
assert stock.ordinals == candidate.ordinals
print(json.dumps({'named_exports': len(stock.exports),
                  'ordinals': len(stock.ordinals), 'imports': sorted(candidate.imports)}))
