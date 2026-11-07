"""Summarize the timed path without treating a Lua stack sample as a duration."""
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_capture import engine, join_presents, segment_presents

KINDS = {
    19: "game_events", 20: "spawn_event", 32: "spawn_dispatch", 33: "stalker_spawn",
    34: "binder_reload", 35: "binder_reinit", 36: "binder_net_spawn", 37: "sound_collection",
    38: "position", 39: "other_event", 40: "spawn_publish", 41: "alife_switch_online",
}


def union(intervals, start, end):
    total, right = 0, start
    for low, high in sorted(intervals):
        low, high = max(start, right, low), min(end, high)
        if low < high:
            total += high - low
            right = high
    return total


def load_samples(directory, pid):
    samples, dropped = defaultdict(list), 0
    for file in sorted(directory.glob(f"ixray_spawn_lua_{pid}_*.tsv")):
        with file.open(encoding="utf-8", errors="replace", newline="") as handle:
            meta = dict(x.split("=") for x in next(handle).strip()[1:].split(","))
            if meta["version"] != "1":
                raise ValueError("Lua sample schema mismatch")
            dropped += int(meta["dropped"])
            for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
                samples[int(row["frame"]), int(row["tid"])].append(row)
    return samples, dropped


def summarize(directory):
    capture = json.loads((directory / "capture.json").read_text(encoding="utf-8-sig"))
    pid = capture["pid"]
    meta, spans = engine(directory / f"ixray_pacing_{pid}.csv", pid)
    hz = meta["qpc_frequency"]
    if hz != capture["qpc_frequency"] or not capture["launch_qpc"] <= meta["qpc_origin"] <= capture["exit_qpc"]:
        raise ValueError("Capture and engine do not share the expected QPC window")
    samples, sample_drops = load_samples(directory, pid)
    presents, _ = segment_presents(spans, hz)
    by_frame = defaultdict(list)
    for start, end, kind, frame, tid, payload in spans:
        if kind in KINDS:
            by_frame[frame].append((start, end, kind, tid, payload))

    def ms(ticks):
        return round(ticks * 1000 / hz, 3)

    def detail(frame, root):
        start, end, kind, tid, payload = root
        nested = defaultdict(list)
        for low, high, part, thread, value in by_frame[frame]:
            if part != kind and thread == tid and start <= low <= high <= end:
                nested[part].append((low, high))
        binder = nested[34] + nested[35] + nested[36]
        stacks = Counter()
        active_states = Counter()
        overhead = 0
        coalesced = 0
        truncated = 0
        for row in samples[frame, tid]:
            tick = int(row["qpc_begin"])
            if not start <= tick < end:
                continue
            stacks[row["phase"], row["stack"]] += 1
            active_states[row["vm_state"]] += 1
            overhead += int(row["qpc_end"]) - tick
            coalesced += int(row["samples"]) > 1
            truncated += row["truncated"] == "1"
        return {
            "kind": KINDS[kind], "tid": tid, "qpc_start": start, "qpc_end": end,
            "payload": payload, "duration_ms": ms(end - start),
            "nested_ms": {KINDS[k]: ms(union(v, start, end)) for k, v in sorted(nested.items()) if v},
            "binder_union_ms": ms(union(binder, start, end)),
            "outside_binder_ms": ms(end - start - union(binder, start, end)),
            "lua_stack_callbacks": sum(stacks.values()), "lua_coalesced_callbacks": coalesced,
            "lua_truncated_stacks": truncated, "lua_callback_self_ms_lower_bound": ms(overhead),
            "timer_vm_states_by_callback": dict(active_states),
            "lua_top_stacks": [{"phase": KINDS[int(phase)], "stack": stack, "callbacks": count}
                               for (phase, stack), count in stacks.most_common(8)],
        }

    frames, previous = [], None
    for event, segment in presents:
        start, _, _, frame, _, _ = event
        if previous and segment == previous[1]:
            gap = ms(start - previous[0])
            roots = [row for row in by_frame[frame] if row[2] in (20, 39)]
            spawns = [row for row in roots if row[2] == 20]
            spawn_ms = ms(sum(end - begin for begin, end, _, _, _ in spawns))
            if gap >= 25 or spawn_ms >= 15:
                frames.append({"frame": frame, "segment": segment, "present_gap_ms": gap,
                               "spawn_event_count": len(spawns), "spawn_event_sum_ms": spawn_ms,
                               "events": [detail(frame, row) for row in roots]})
        previous = start, segment
    aligned = len(presents)
    presentmon = directory / "presentmon.csv"
    if presentmon.is_file():
        _, present_join = join_presents(presentmon, pid, presents, hz)
    else:
        present_join = None
    return {
        "engine_dropped": meta["dropped"], "lua_dropped": sample_drops,
        "lua_callbacks": sum(map(len, samples.values())), "engine_presents": aligned,
        "presentmon_join": present_join,
        "method": "Lua hook stack and timer VM state may differ in time. Coalesced samples have one observed stack. Native spans are inclusive.",
        "frames": sorted(frames, key=lambda frame: frame["present_gap_ms"], reverse=True),
    }


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    try:
        result = summarize(directory)
    except (OSError, KeyError, ValueError, StopIteration) as error:
        result = {"status": "incomplete", "reason": str(error)}
    (directory / "spawn_path_analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
