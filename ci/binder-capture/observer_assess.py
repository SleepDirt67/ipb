"""Separate collection cost from scheduler noise in paired real voice replays."""
from collections import defaultdict
from pathlib import Path
from statistics import median
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spawn-path/capture"))
from analyze_capture import cpu_overlap, cpu_schedule, cpu_window_available


def p95(items):
    items = sorted(items)
    return items[(95 * len(items) + 99) // 100 - 1]


def assess(output, trace, decoder, frequency, limit=0.5):
    rows = defaultdict(list)
    threads = set()
    for line in output.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"OBSERVER_SAMPLE (binder_(?:545|569)) (\d+) ([0-4]) ([0-3]) (\d+) (\d+) (\d+)", line)
        if match:
            workload, *values = match.groups()
            trial, repeat, mode, tid, start, end = map(int, values)
            if trial:
                rows[workload, trial, repeat, mode].append((tid, start, end))
                threads.add(tid)
    if len(rows) != 800 or any(len(windows) != 10 for windows in rows.values()) or len(threads) != 1:
        raise ValueError("Incomplete or inconsistent observer replay windows")
    schedules, etw = cpu_schedule(trace, decoder, threads, frequency)
    hz = etw["qpc_frequency"]
    results = {}
    for workload in ("binder_545", "binder_569"):
        wall, running = {}, {}
        for trial in range(1, 21):
            for mode in range(4):
                wall_repeats, running_repeats = [], []
                for repeat in range(5):
                    total, elapsed = 0, 0
                    for tid, begin, end in rows[workload, trial, repeat, mode]:
                        if not cpu_window_available(etw, begin, end):
                            raise ValueError("Scheduler trace does not cover an observer interval")
                        timing, _ = cpu_overlap(schedules[tid], begin, end, 1000 / hz)
                        elapsed += (end - begin) * 1000 / hz
                        total += timing["running"]
                    wall_repeats.append(elapsed)
                    running_repeats.append(total)
                wall[trial, mode] = median(wall_repeats)
                running[trial, mode] = median(running_repeats)

        def deltas(values, mode, absolute=False):
            gaps = [values[trial, mode] - values[trial, 0] for trial in range(1, 21)]
            return list(map(abs, gaps)) if absolute else gaps

        full, noise = deltas(running, 2), deltas(running, 3, True)
        cpu_p95, noise_p95 = p95(full), p95(noise)
        results[workload] = {
            "pairs": len(full), "replicates_per_mode": 5, "cpu_full_median_ms": median(full), "cpu_full_p95_ms": cpu_p95,
            "cpu_boundaries_p95_ms": p95(deltas(running, 1)), "cpu_off_off_noise_p95_ms": noise_p95,
            "wall_full_p95_ms": p95(deltas(wall, 2)), "wall_off_off_noise_p95_ms": p95(deltas(wall, 3, True)),
            "status": "PASS" if cpu_p95 <= limit and noise_p95 <= limit else "OBSERVER_EFFECT_UNRESOLVED",
        }
    return {"limit_ms": limit, "basis": "P95 of paired five-replay medians, with running time from scheduling ETW",
            "etw": etw, "workloads": results}


if __name__ == "__main__":
    source, trace, decoder, report = map(Path, sys.argv[1:5])
    summary = assess(source, trace, decoder, int(sys.argv[5]))
    report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if any(row["status"] != "PASS" for row in summary["workloads"].values()):
        sys.exit(1)
