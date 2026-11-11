"""Independent expected intervals and the binary emitted by the engine fixture."""
from pathlib import Path
import sys

here = Path(__file__).resolve().parent
sys.path[:0] = [str(here / "capture"), str(here.parent / "spawn-path/capture")]
from analyze_binder import capture_data, interval_union, verify_episodes

assert interval_union([(90, 120), (115, 125), (180, 220), (101, 104)], 100, 200) == 45

ep = dict(begin=1000, end=1100, binders=2, dispatches=1, binder_dropped=0, dispatch_dropped=0, copy_ticks=0)
dispatch = dict(begin=1010, end=1090, scope=1, parent_scope=0, tid=7, stalker=1, parent_object=65535, result=1)
base = dict(tid=7, dispatch=1, flags=0)
binder = [
    dict(base, begin=1020, end=1060, scope=2, parent_scope=1, phase_ticks=[4, 6, 10, 10]),
    dict(base, begin=1030, end=1040, scope=3, parent_scope=2, phase_ticks=[0, 0, 3, 7]),
]
presents = {1000: (1000, 1000, 3, 1, 7, 0), 1100: (1100, 1100, 3, 2, 7, 0)}
cpu = {7: ([1000, 1050, 1060], [(1000, 1050, "running", None), (1050, 1060, "ready", None),
                                 (1060, 1100, "blocked", 8)])}
joined = {1000: (1000, {}), 1100: (1100, {})}
etl = dict(qpc_first=999, qpc_last=1101)
row, = verify_episodes([ep], binder, [dispatch], presents, [], joined, cpu, etl, 1000)
assert row["present_gap_ms"] == 100 and row["dispatch_ms"] == 80 and row["binder_ms"] == 40
assert row["remaining_if_all_binder_removed_ms"] == 60
assert row["binder_categories_ms"] == {"host": 4, "vm_and_internal": 6, "external_c": 13, "gc": 17}
assert row["cpu_ms"] == {"running": 50, "ready": 10, "blocked": 40, "unknown_offcpu": 0, "uncovered_ms": 0}
assert row["strong"] and not row["invalid"] and not row["unresolved"]
row, = verify_episodes([dict(ep, binder_dropped=1)], binder, [dispatch], presents, [], {}, cpu, etl, 1000)
assert len(row["invalid"]) == 2
if len(sys.argv) > 1:
    header, episodes, binders, dispatches = capture_data(Path(sys.argv[1]))
    assert header["strong"] == 8 and header["large"] == 8 and header["dispatch_dropped"] == 1
    assert len(episodes) >= 6 and len(binders) >= 18 and len(dispatches) >= 18
print("Binder binary and independent QPC interval fixtures passed")
