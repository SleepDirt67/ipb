"""Join CPU stacks to measured game stages using the raw QPC sample timestamp."""
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import subprocess
import sys

# The embedded Windows Python keeps the script directory out of sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_capture import (collapse, context_gaps, continuous_periods, display_series,
                             engine, event_periods, join_presents, local_outliers,
                             pixel_observations, read_rows, segment_presents, write_csv)

STAGES = {
    4: "WaitWorkers", 5: "PreRender", 7: "SceneRender", 14: "BeginRender",
    16: "FrameMove", 17: "LevelFrame", 18: "ClientReceive", 19: "GameEvents",
    20: "SpawnEvent", 21: "ObjectsUpdate", 22: "GameTask", 23: "Scheduler",
    24: "ParallelTasks", 25: "FrameMT", 26: "ParticleUpdates", 27: "TaskEnqueue",
    30: "TimedCallbacks", 31: "HudUpdate",
}


class FunctionIndex:
    def __init__(self, source):
        rows = []
        for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
            address, size, name = line.split("\t", 2)
            base = int(address, 16)
            rows.append((base, base + int(size, 16), name))
        self.rows = sorted(set(rows), key=lambda row: (row[0], -row[1], row[2]))
        self.starts = [row[0] for row in self.rows]
        self.max_end = []
        for row in self.rows:
            self.max_end.append(max(row[1], self.max_end[-1] if self.max_end else 0))

    def lookup(self, address):
        pos = bisect_right(self.starts, address) - 1
        while pos >= 0 and self.max_end[pos] > address:
            _, end, name = self.rows[pos]
            if address < end:
                return name
            pos -= 1
        return None


class Modules:
    def __init__(self, directory, index_dir):
        self.modules = sorted((int(row["base_hex"], 16), int(row["size"]), row["name"])
                              for row in read_rows(directory / "module_snapshot.csv"))
        self.starts = [row[0] for row in self.modules]
        self.symbols = {file.name.removesuffix(".tsv").lower(): FunctionIndex(file)
                        for file in index_dir.glob("*.tsv")}
        self.cache = {}

    def address(self, ip, return_pc):
        key = ip, return_pc
        if key not in self.cache:
            # Non-leaf frames contain a return address, so use the caller instruction.
            pc = ip - int(return_pc)
            pos = bisect_right(self.starts, pc) - 1
            label, named = f"0x{ip:x}", False
            if pos >= 0:
                base, size, name = self.modules[pos]
                if pc < base + size:
                    offset = pc - base
                    index = self.symbols.get(name.lower())
                    function = index.lookup(offset) if index else None
                    label = f"{name}!{function}" if function else f"{name}+0x{offset:x}"
                    named = function is not None
            self.cache[key] = label, named
        return self.cache[key]


def stage_at(spans, frame, tid, qpc):
    containing = [span for frame_number in (frame - 1, frame) for span in spans.get((frame_number, tid), ())
                  if span[0] <= qpc < span[1]]
    # Distinguish stages on the sampled thread, including the previous frame's task wait.
    containing.sort(key=lambda span: (span[1] - span[0], -span[0]))
    return "/".join(STAGES[span[2]] for span in reversed(containing)) or "unscoped"


def pacing_periods(frames, hz):
    definitions = {
        "submission": ("present_gap_ms", 2, .20),
        "display": ("display_gap_ms", 2, .20),
        "present_api": ("present_api_ms", 1, .25),
        "gpu_start_latency": ("MsGPULatency", 1.5, .25),
        "gpu_busy": ("MsGPUBusy", 1.5, .25),
        "gpu_wait": ("MsGPUWait", 1, .25),
    }
    groups = {}
    for label, (metric, minimum, relative) in definitions.items():
        events = local_outliers(frames, metric, hz, minimum, relative)
        if label in ("submission", "display"):
            groups[f"short_{label}"] = [e for e in events if e[1] < 25]
            groups[f"long_{label}"] = [e for e in events if e[1] >= 25]
        else:
            groups[label] = events
    groups["short_wait_dominated"] = [(r["qpc_end"], r["present_gap_ms"], 0, r) for r in frames
                                      if 8 <= r["present_gap_ms"] < 25
                                      and r.get("WaitWorkers_overlap_ms", 0) > r["present_gap_ms"] / 2]
    event_summary = {}
    for label, events in groups.items():
        episodes = collapse(events, hz)
        event_summary[label] = {"episodes": len(episodes), "candidates": event_periods(episodes, hz)}
    return {"event_series": event_summary,
            "continuous_candidates": {metric: continuous_periods(frames, metric, hz)
                                      for metric in ("present_gap_ms", "display_gap_ms", "WaitWorkers_overlap_ms")}}


def assess(directory, decoder, index_dir):
    capture = json.loads((directory / "capture.json").read_text(encoding="utf-8-sig"))
    pid = capture["pid"]
    meta, spans = engine(directory / f"ixray_pacing_{pid}.csv", pid)
    hz = meta["qpc_frequency"]
    if hz != capture["qpc_frequency"] or not capture["launch_qpc"] <= meta["qpc_origin"] <= capture["exit_qpc"]:
        raise ValueError("Game and launcher do not share the expected QPC window")
    presents, _ = segment_presents(spans, hz)
    if len(presents) < 2:
        raise ValueError("No gameplay intervals")
    issues = list(capture.get("capture_errors", ()))
    if meta["dropped"]:
        issues.append("Engine buffer overflow")
    try:
        joined, join = join_presents(directory / "presentmon.csv", pid, [p for p, _ in presents], hz)
    except (OSError, KeyError, ValueError) as e:
        issues.append(str(e))
        joined, join = {}, {}
    frames = context_gaps(presents, joined, spans, {}, {}, hz)
    display = display_series(frames, hz)
    pixels, _ = pixel_observations(frames, spans, hz)
    for row in frames:
        row["elapsed_s"] = (row["qpc_end"] - meta["qpc_origin"]) / hz
    write_csv(directory / "frame_timeline.csv", frames)

    threads = ",".join(str(tid) for tid in sorted({span[4] for span in spans}))
    output = directory / "cpu_stack_samples.csv"
    proc = subprocess.run([str(decoder), "--extract", str(directory / "cpu_samples.etl"), str(output),
                           str(pid), threads], capture_output=True, text=True, check=False)
    if proc.returncode:
        raise ValueError(proc.stderr.strip() or f"Stack extraction failed ({proc.returncode})")
    etw = json.loads(proc.stdout)
    if etw["qpc_frequency"] != hz:
        raise ValueError("Stack ETL frequency differs from frame QPC")
    if etw["events_lost"] or etw["buffers_lost"] or etw["unsupported"]:
        issues.append("ETW lost events or reported unsupported stack records")
    mapper = Modules(directory, index_dir)
    mapped_after = capture.get("module_snapshot_qpc") or capture["exit_qpc"]
    coverage_start = max(mapped_after, etw["first_cpu_sample_qpc"])
    coverage_end = min(capture["exit_qpc"], etw["last_cpu_sample_qpc"])
    if coverage_start > frames[0]["qpc_start"] or coverage_end < frames[-1]["qpc_end"]:
        issues.append("Only part of gameplay covered by both the sampled ETL and module snapshot")
    paths = defaultdict(list)
    for span in spans:
        if span[2] in STAGES:
            paths[(span[3], span[4])].append(span)
    end_times = [r["qpc_end"] for r in frames]
    hot = []
    counters = defaultdict(Counter)
    candidates = 0
    for sample in read_rows(output):
        qpc, tid = int(sample["qpc"]), int(sample["tid"])
        pos = bisect_right(end_times, qpc)
        if pos == len(frames):
            continue
        row = frames[pos]
        if not row["qpc_start"] <= qpc < row["qpc_end"] or row["present_gap_ms"] < 8:
            continue
        candidates += 1
        if not coverage_start <= qpc < coverage_end:
            continue
        if sample["interrupt_flags"] != "0":
            continue
        stack = [mapper.address(int(ip, 16), i > 0) for i, ip in enumerate(sample["ips"].split())]
        named = [label for label, is_named in stack if is_named]
        thread = "main" if tid == row["main_tid"] else "worker"
        stage = stage_at(paths, row["frame"], tid, qpc)
        if named:
            counters[(thread, stage)][named[0]] += 1
        hot.append({"frame": row["frame"], "sample_qpc": qpc, "elapsed_s": (qpc - meta["qpc_origin"]) / hz,
                    "present_gap_ms": row["present_gap_ms"], "display_gap_ms": row.get("display_gap_ms"),
                    "tid": tid, "thread": thread, "stage": stage, "innermost_game_symbol": named[0] if named else "",
                    "stack": " | ".join(label for label, _ in stack)})
    write_csv(directory / "hot_window_stacks.csv", hot)
    named = sum(bool(row["innermost_game_symbol"]) for row in hot)
    if not named:
        issues.append("No game symbols mapped inside candidate stutters")
    return {"status": "captured" if hot and not issues else "partial", "quality_notes": issues,
            "presentmon_join": join, "display": display, "pixel_probe": pixels, "sampled_etw": etw,
            "pacing_periods": pacing_periods(frames, hz),
            "stack_coverage_qpc": [coverage_start, coverage_end], "candidate_samples": candidates,
            "hot_window_samples": len(hot), "hot_window_samples_with_game_symbols": named,
            "top_game_symbols_by_scope": {f"{thread}/{scope}": names.most_common(8)
                                          for (thread, scope), names in sorted(counters.items())},
            "sampling_limit": "CPU snapshots during the marked scope, not a blocking-call duration or Lua function trace."}


def main():
    directory, decoder, indices = map(Path, sys.argv[1:])
    try:
        result = assess(directory, decoder, indices)
    except (OSError, KeyError, ValueError, StopIteration) as e:
        result = {"status": "incomplete", "quality_notes": [str(e)]}
    (directory / "stack_analysis.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["status"])


if __name__ == "__main__":
    main()
