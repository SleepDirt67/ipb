"""Validate and correlate the retained binder episodes on the engine's QPC clock."""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import file_digest
import csv
import json
from pathlib import Path
from struct import Struct
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_capture import (cpu_overlap, cpu_schedule, cpu_window_available, engine,
                             join_presents, read_rows, segment_presents)

HEADER = Struct("<8s5Q16I")
EPISODE = Struct("<3Q6I")
BINDER = Struct("<12Q14I")
PHASES = Struct("<48Q")
TALLY = Struct("<2Q2I")
NATIVE = Struct("<4Q4I")
METHOD = Struct("<48s64sI")
DISPATCH = Struct("<6Q8I96s")
BINDER_SIZE = BINDER.size + PHASES.size + 16 * TALLY.size + 96 * NATIVE.size + 256
CATEGORIES = ("host", "vm_and_internal", "external_c", "gc")
KINDS = {1: "reinit", 2: "reload", 3: "net_spawn", 4: "load"}
GC = (
    "roots", "propagate", "atomic_other", "sweep_strings", "sweep_objects", "finalize", "step_overhead",
    "open_upvalues", "remark_roots", "grayagain", "separate_userdata", "clear_weak", "shrink",
)
BASELINE = "886337084c8fd851a4fff186b453ae7cc6450821"


def labelled(names, values):
    return dict(zip(names.split(), values, strict=True))


def unique_rows(rows, id_field):
    seen = {}
    for row in rows:
        key = row[id_field]
        if key in seen and row != seen[key]:
            raise ValueError(f"Conflicting copies of record {key}")
        seen[key] = row
    return list(seen.values())


def capture_data(path):
    with path.open("rb") as stream:
        header = labelled("magic frequency active_ticks observation_begin observation_end save_loaded "
                          "pid binders dispatches binder_dropped dispatch_dropped wrapper_installs wrapper_refused "
                          "script_matches script_misses stop_reason strong large binder_size dispatch_size episodes methods",
                          HEADER.unpack(stream.read(HEADER.size)))
        if (header["magic"] != b"IXBIND4\0" or header["binder_size"] != BINDER_SIZE or
                header["dispatch_size"] != DISPATCH.size or not 0 < header["frequency"] or
                not 0 <= header["episodes"] <= 9 or header["binders"] > 4500 or header["dispatches"] > 14400 or header["methods"] > 512):
            raise ValueError("Invalid binder binary header")
        del header["magic"]
        episodes = [
            labelled("begin end copy_ticks binders dispatches binder_dropped dispatch_dropped invalid slot",
                     EPISODE.unpack(stream.read(EPISODE.size)))
            for _ in range(header["episodes"])
        ]
        if (sum(row["binders"] for row in episodes) != header["binders"] or
                sum(row["dispatches"] for row in episodes) != header["dispatches"]):
            raise ValueError("Retained episode record counts do not match header")
        binders = []
        for _ in range(header["binders"]):
            raw = stream.read(BINDER_SIZE)
            row = labelled("begin end scope parent_scope dispatch last global allocated released allocation_calls "
                           "heap_before heap_after frame tid vm_generation object generation kind flags "
                           "phase execution gc_stage gc_cycles marks address_count native_cursor",
                           BINDER.unpack_from(raw))
            if row["address_count"] > 96 or row["kind"] not in KINDS or not 0 < row["begin"] <= row["end"]:
                raise ValueError("Invalid binder record")
            row["phase_ticks"] = PHASES.unpack_from(raw, BINDER.size)
            offset = BINDER.size + PHASES.size
            row["gc"] = list(TALLY.iter_unpack(raw[offset:offset + 16 * TALLY.size]))
            offset += 16 * TALLY.size
            row["native"] = list(NATIVE.iter_unpack(raw[offset:offset + row["address_count"] * NATIVE.size]))
            binders.append(row)
        dispatches = []
        for _ in range(header["dispatches"]):
            row = labelled("begin end scope parent_scope queue class_id frame tid object generation "
                           "parent_object parent_generation stalker result section", DISPATCH.unpack(stream.read(DISPATCH.size)))
            if not 0 < row["begin"] <= row["end"]:
                raise ValueError("Invalid dispatch interval")
            row["section"] = row["section"].split(b"\0", 1)[0].decode("cp1251", errors="replace")
            dispatches.append(row)
        header["native_methods"] = {}
        for index in range(1, header["methods"] + 1):
            owner, name, overload = METHOD.unpack(stream.read(METHOD.size))
            header["native_methods"][index] = (
                owner.split(b"\0", 1)[0].decode("utf-8", errors="replace"),
                name.split(b"\0", 1)[0].decode("utf-8", errors="replace"), overload,
            )
        if stream.read(1):
            raise ValueError("Trailing data in binder trace")
    return header, episodes, unique_rows(binders, "scope"), unique_rows(dispatches, "scope")


def interval_union(intervals, begin, end):
    result = 0
    current = begin
    for lo, hi in sorted(intervals):
        lo, hi = max(lo, begin), min(hi, end)
        if hi > max(current, lo):
            result += hi - max(current, lo)
            current = hi
    return result


def intersects(row, begin, end):
    return row["begin"] < end and begin < row["end"]


def nested_row(row, parent):
    return parent and row["tid"] == parent["tid"] and parent["begin"] <= row["begin"] <= row["end"] <= parent["end"]


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def hash_file(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def export_scopes(directory, capture_id, header, binders, dispatches, tools):
    identity = {"capture_id": capture_id, "pid": header["pid"]}
    keep = ("begin", "end", "scope", "parent_scope", "dispatch", "frame", "tid", "vm_generation",
            "object", "generation", "kind", "flags", "marks")
    write_csv(directory / "binder_scopes.csv", [
        {**identity, **{key: row[key] for key in keep}} for row in binders
    ])
    write_json(directory / "workload.json", [
        {**identity, **row} for row in sorted(dispatches, key=lambda row: row["scope"])
    ])
    sites = []
    modules = []
    if (directory / "module_snapshot.csv").is_file():
        from analyze_stacks import Modules
        mapper = Modules(directory, tools / "stack-symbols")
        modules = [(int(row["base_hex"], 16), int(row["size"]), row["name"])
                   for row in read_rows(directory / "module_snapshot.csv")]
    for row in binders:
        for address, inclusive, ticks, longest, count, interrupted, phase, method in row["native"]:
            class_name, method_name, overload = header["native_methods"].get(method, ("", "", ""))
            mapping = next(((name, address - base) for base, size, name in modules if base <= address < base + size), None)
            sites.append({
                **identity, "scope": row["scope"], "phase": phase, "address": f"0x{address:x}",
                "module": mapping[0] if mapping else "", "rva": f"0x{mapping[1]:x}" if mapping else "",
                "symbol": mapper.address(address, False)[0] if mapping else "",
                "class_name": class_name, "method_name": method_name, "overload": overload,
                "inclusive_c_wrapper_ticks": inclusive, "exclusive_ticks": ticks,
                "max_exclusive_ticks": longest, "count": count, "nested_calls": interrupted,
            })
    write_csv(directory / "native_summary.csv", sites)
    write_csv(directory / "gc_phases.csv", [
        {**identity, "scope": row["scope"], "vm_generation": row["vm_generation"], "stage": stage,
         "ticks": ticks, "count": count, "interrupted": interrupted, "cycles_in_scope": row["gc_cycles"]}
        for row in binders for stage, (ticks, _, count, interrupted) in zip(GC, row["gc"]) if ticks or count
    ])
    write_csv(directory / "binder_phases.csv", [
        {**identity, "scope": row["scope"], "phase": i // 4, "category": CATEGORIES[i % 4], "ticks": value}
        for row in binders for i, value in enumerate(row["phase_ticks"]) if value
    ])
    write_csv(directory / "allocation_summary.csv", [
        {**identity, "scope": row["scope"], "heap_before": row["heap_before"], "heap_after": row["heap_after"],
         "allocated_delta_bytes": row["allocated"], "released_delta_bytes": row["released"],
         "allocations_and_resizes": row["allocation_calls"], "flags": row["flags"]}
        for row in binders
    ])


def verify_episodes(episodes, binders, dispatches, by_present, spans, joined, schedules, etw, hz):
    episode_keys = {(row["begin"], row["end"]): row for row in episodes}
    by_binder = {row["scope"]: row for row in binders}
    by_dispatch = {row["scope"]: row for row in dispatches}
    children = defaultdict(list)
    for row in binders:
        children[row["parent_scope"]].append((row["begin"], row["end"]))
    for key, ep in sorted(episode_keys.items(), key=lambda item: -item[1]["end"] + item[1]["begin"]):
        begin, end = key
        present = by_present.get(end)
        previous = by_present.get(begin)
        if not previous or not present:
            raise ValueError("Retained episode does not align to two consecutive engine Presents")
        tid = present[4]
        dispatch = [row for row in dispatches if intersects(row, begin, end)]
        binder = [row for row in binders if intersects(row, begin, end)]
        errors, gaps = [], []
        if (len(dispatch), len(binder)) != (ep["dispatches"], ep["binders"]):
            errors.append("Retained scope count does not match QPC interval")
        if ep["binder_dropped"] or ep["dispatch_dropped"]:
            errors.append("Retained episode exceeded the scope buffer")
        for row in binder:
            parent = by_binder.get(row["parent_scope"], by_dispatch.get(row["parent_scope"]))
            if not nested_row(row, parent) or row["dispatch"] not in by_dispatch:
                errors.append(f"Invalid binder hierarchy {row['scope']}")
            if row["flags"] & (1 | 8 | 16 | 32):
                errors.append(f"Invalid binder scope {row['scope']} flags={row['flags']}")
            if row["flags"] & (2 | 4):
                gaps.append(f"Native site or Lua phase coverage incomplete in scope {row['scope']}")
            if not begin <= row["begin"] <= row["end"] <= end:
                gaps.append(f"Aggregate scope {row['scope']} crosses a Present")
            child_ticks = interval_union(children[row["scope"]], row["begin"], row["end"])
            remainder = row["end"] - row["begin"] - child_ticks - sum(row["phase_ticks"])
            if remainder < 0 or remainder > max(4, hz // 2000):
                gaps.append(f"Unreconciled binder time in scope {row['scope']}")
        for row in dispatch:
            if row["parent_scope"] and not nested_row(row, by_dispatch.get(row["parent_scope"])):
                errors.append(f"Invalid dispatch hierarchy {row['scope']}")
            if not row["result"]:
                errors.append(f"Dispatch {row['scope']} has no result")

        spawn_ticks = interval_union([(row["begin"], row["end"]) for row in dispatch], begin, end)
        binder_ticks = interval_union([(row["begin"], row["end"]) for row in binder], begin, end)
        event_ticks = interval_union([(a, b) for a, b, kind, _, thread, _ in spans
                                      if kind == 20 and thread == tid and a < end and begin < b], begin, end)
        roots = sum(row["stalker"] and row["parent_object"] == 65535 for row in dispatch)
        strong = (end - begin) * 1000 >= 40 * hz and (spawn_ticks * 1000 >= 20 * hz or binder_ticks * 1000 >= 12 * hz)
        cpu = {}
        if previous[0] not in joined or present[0] not in joined:
            errors.append("PresentMon endpoints are missing or ambiguous")
        if tid not in schedules or not cpu_window_available(etw, begin, end):
            errors.append("Scheduling ETW does not cover this Present interval")
        else:
            cpu, _ = cpu_overlap(schedules[tid], begin, end, 1000 / hz)
            cpu["uncovered_ms"] = max(0, (end - begin) * 1000 / hz - sum(cpu.values()))
            if cpu["uncovered_ms"] + cpu["unknown_offcpu"] > .5:
                gaps.append("CPU scheduling has an unresolved interval")

        categories = Counter()
        phase_categories = defaultdict(Counter)
        gc_stages = Counter()
        for row in binder:
            for i, value in enumerate(row["phase_ticks"]):
                category = CATEGORIES[i % 4]
                categories[category] += value
                if value:
                    phase_categories[i // 4][category] += value
            for name, (ticks, _, _, _) in zip(GC, row.get("gc", ())):
                if ticks:
                    gc_stages[name] += ticks
        scale = 1000 / hz
        before = 0
        after = 0
        between = 0
        no_binder = 0
        for row in dispatch:
            if row["parent_scope"]:
                continue
            related = [scope for scope in binder if scope["dispatch"] == row["scope"]]
            if related:
                low, high = min(item["begin"] for item in related), max(item["end"] for item in related)
                before += max(0, min(end, low) - max(begin, row["begin"]))
                after += max(0, min(end, row["end"]) - max(begin, high))
                between += max(0, min(end, high) - max(begin, low)) - interval_union(
                    [(item["begin"], item["end"]) for item in related], begin, end)
            else:
                no_binder += max(0, min(end, row["end"]) - max(begin, row["begin"]))
        yield {
            "qpc_begin": begin, "qpc_end": end, "engine_frame": present[3], "tid": tid,
            "present_gap_ms": (end - begin) * scale, "spawn_events_ms": event_ticks * scale,
            "dispatch_ms": spawn_ticks * scale, "binder_ms": binder_ticks * scale,
            "dispatch_before_binder_ms": before * scale, "dispatch_between_binders_ms": between * scale,
            "dispatch_after_binder_ms": after * scale, "dispatch_without_binder_ms": no_binder * scale,
            "nonbinder_dispatch_ms": max(0, spawn_ticks - binder_ticks) * scale,
            "frame_outside_dispatch_ms": max(0, end - begin - spawn_ticks) * scale,
            "remaining_if_all_binder_removed_ms": (end - begin - binder_ticks) * scale,
            "remaining_if_all_dispatch_removed_ms": (end - begin - spawn_ticks) * scale,
            "capture_copy_ms": ep["copy_ticks"] * scale, "root_stalkers": roots,
            "dispatches": len(dispatch), "strong": strong, "structural": roots >= 6,
            "binder_categories_ms": {name: value * scale for name, value in categories.items()},
            "binder_phases_ms": {phase: {name: value * scale for name, value in values.items()}
                                 for phase, values in phase_categories.items()},
            "gc_stages_ms": {name: value * scale for name, value in gc_stages.items()},
            "cpu_ms": cpu, "invalid": list(dict.fromkeys(errors)), "unresolved": list(dict.fromkeys(gaps)),
        }


def write_timeline(directory, presents, joined, hz):
    rows = []
    for (previous, prev_epoch), (current, epoch) in zip(presents, presents[1:]):
        if prev_epoch != epoch:
            continue
        a, b = previous[0], current[0]
        rows.append({"qpc_begin": a, "qpc_end": b, "engine_frame": current[3], "tid": current[4],
                     "present_gap_ms": (b - a) * 1000 / hz, "presentmon_begin": joined.get(a, (None,))[0],
                     "presentmon_end": joined.get(b, (None,))[0]})
    write_csv(directory / "frame_timeline.csv", rows)


def assess(directory, tools, capture, quality):
    header, episodes, binders, dispatches = capture_data(directory / "binder_scopes.bin")
    hz, pid = header["frequency"], header["pid"]
    quality["engine_binder"] = header
    if hz != capture["qpc_frequency"] or pid != capture["pid"]:
        raise ValueError("Game and launcher QPC frequency or process ID differs")
    if not (capture["launch_qpc"] <= header["save_loaded"] <= header["observation_begin"] <=
            header["observation_end"] <= capture["exit_qpc"]):
        raise ValueError("The game did not confirm the expected save and observation window")
    if not header["wrapper_installs"] or header["wrapper_refused"]:
        raise ValueError("Diagnostic LuaJIT wrapper is unavailable or was refused")
    if not header["script_matches"] or header["script_misses"]:
        quality["unresolved"].append("Stock xr_motivator source could not be established for every load")
    export_scopes(directory, capture["capture_id"], header, binders, dispatches, tools)
    meta, spans = engine(directory / f"ixray_pacing_{pid}.csv", pid)
    if meta["qpc_frequency"] != hz or not capture["launch_qpc"] <= meta["qpc_origin"] <= header["observation_end"]:
        raise ValueError("Engine pacing clock does not match capture")
    quality["engine_pacing"] = meta
    if meta["dropped"]:
        quality["invalid"].append(f"Engine pacing buffer dropped {meta['dropped']} intervals")
    if header["binder_dropped"] or header["dispatch_dropped"]:
        quality["unresolved"].append("Some frames exceeded binder or dispatch limits")
    presents, _ = segment_presents(spans, hz)
    presents = [(row, epoch) for row, epoch in presents if
                header["observation_begin"] <= row[0] <= header["observation_end"]]
    joined, quality["presentmon"] = join_presents(directory / "presentmon.csv", pid, [p for p, _ in presents], hz)
    write_timeline(directory, presents, joined, hz)
    # These two jobs share the task_group joined by the frame barrier.
    jobs = defaultdict(dict)
    for a, b, k, frame, tid, payload in spans:
        if (k, payload) in ((5, 1), (22, 2), (27, 1), (27, 2), (4, 3)):
            jobs[frame][k, payload] = a, b, tid
    links = []
    for frame, rows in sorted(jobs.items()):
        for job_id, worker_kind in ((1, 5), (2, 22)):
            submitted, worker, wait = rows.get((27, job_id)), rows.get((worker_kind, job_id)), rows.get((4, 3))
            if submitted and worker and wait and submitted[0] <= worker[0] <= worker[1] <= wait[1]:
                links.append({"frame": frame, "task": f"{frame}:{job_id}", "barrier": f"{frame}:3",
                              "submit_qpc": submitted[0], "worker_begin": worker[0], "worker_end": worker[1],
                              "worker_tid": worker[2], "wait_begin": wait[0], "wait_end": wait[1],
                              "barrier_overlap_ticks": max(0, worker[1] - max(wait[0], worker[0]))})
    write_csv(directory / "task_dependencies.csv", links)
    write_csv(directory / "task_timeline.csv", [
        {"qpc_begin": a, "qpc_end": b, "kind": k, "frame": frame, "tid": tid, "payload": payload}
        for a, b, k, frame, tid, payload in spans if k in (4, 22, 24, 25, 27, 41, 42, 43, 44)
    ])
    schedules, quality["etw"] = cpu_schedule(directory, tools / "ixray_etw_decode.exe",
                                            {span[4] for span in spans}, hz)
    stack = subprocess.run([str(tools / "ixray_stack_extract.exe"), "--extract",
                            str(directory / "cpu_scheduling.etl"), str(directory / "cpu_stack_samples.csv"),
                            str(pid), ",".join(map(str, sorted({span[4] for span in spans})))],
                           capture_output=True, text=True, check=False)
    if stack.returncode:
        quality["unresolved"].append(f"CPU sample stacks unavailable ({stack.returncode})")
    else:
        quality["sample_stacks"] = json.loads(stack.stdout)
        if any(quality["sample_stacks"].get(key) for key in ("events_lost", "buffers_lost", "unsupported")):
            quality["unresolved"].append("Some sampled CPU stacks were lost or unsupported")
    return list(verify_episodes(episodes, binders, dispatches, {row[0]: row for row, _ in presents},
                                spans, joined, schedules, quality["etw"], hz))


def run(directory, tools):
    quality = {"invalid": [], "unresolved": [], "episodes": []}
    capture = json.loads((directory / "capture.json").read_text(encoding="utf-8-sig"))
    quality["observer"] = capture.get("observer", "UNVERIFIED_ON_TARGET")
    quality["invalid"].extend(capture.get("issues", ()))
    for flag in ("startup_verified", "modules_verified", "restored"):
        if not capture.get(flag):
            quality["invalid"].append(f"Missing required verification: {flag}")
    try:
        manifest = json.loads((directory / "BUILD_MANIFEST.json").read_text(encoding="utf-8-sig"))
        if manifest["commit"] != capture["commit"] or manifest["binder_capture"]["base"] != BASELINE:
            raise ValueError("Unexpected build identity")
        quality["episodes"] = assess(directory, tools, capture, quality)
        instrument = json.loads((directory / "instrumentation_map.json").read_text(encoding="utf-8-sig"))
        quality["phase_names"] = instrument["phases"]
    except (OSError, KeyError, ValueError, TypeError, ArithmeticError, RuntimeError) as exc:
        quality["invalid"].append(str(exc))
    except Exception as exc:
        quality["invalid"].append(f"Decoder failure {type(exc).__name__}: {exc}")

    targets = [row for row in quality["episodes"] if row["strong"] or row["structural"]]
    complete = [row for row in targets if not row["invalid"] and not row["unresolved"]]
    if quality["invalid"] or targets and all(row["invalid"] for row in targets):
        state = "CAPTURE_INVALID"
    elif not targets:
        state = "NO_TARGET_EVENT"
    elif not complete or quality["unresolved"]:
        state = "FRAME_MODEL_INCOMPLETE"
    elif quality["observer"] != "VERIFIED_ON_TARGET":
        state = "OBSERVER_EFFECT_UNRESOLVED"
    elif any(row["strong"] for row in complete):
        state = "READY_FOR_PRIORITY"
    else:
        state = "FRAME_MODEL_INCOMPLETE"
    quality["status"] = state
    write_json(directory / "quality.json", quality)
    lines = [
        "# IX-Ray binder capture", "", f"**{state}**", "",
        f"Build {capture.get('commit', 'unknown')}, capture {capture.get('capture_id', 'unknown')}.", "",
        "| Engine frame | Present gap | Dispatch | Binder | Frame if binder cost vanished | Root stalkers |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in targets:
        lines.append("| {engine_frame} | {present_gap_ms:.3f} ms | {dispatch_ms:.3f} ms | {binder_ms:.3f} ms | "
                     "{remaining_if_all_binder_removed_ms:.3f} ms | {root_stalkers} |".format(**row))
    lines.extend(["", "The subtraction is an optimistic bound at the measured workload.", ""])
    if targets:
        first = targets[0]
        lines.extend([
            f"## Frame {first['engine_frame']}", "",
            "| Script phase | Host | VM and other | External C | GC |",
            "|---|---:|---:|---:|---:|",
        ])
        for number, values in sorted(first["binder_phases_ms"].items(), key=lambda x: -sum(x[1].values())):
            names = quality.get("phase_names", ())
            label = names[number] if number < len(names) else str(number)
            times = " | ".join(f"{values.get(key, 0):.3f} ms" for key in CATEGORIES)
            lines.append(f"| {label} | {times} |")
        lines.append("")
        cpu = first["cpu_ms"]
        if cpu:
            lines.append("Game thread scheduler time. " + ", ".join(f"{name} {value:.3f} ms" for name, value in cpu.items()) + ".")
            lines.append("")
        if first["remaining_if_all_binder_removed_ms"] >= 40:
            lines.append("At the recorded workload, reaching a 40 ms frame requires time savings outside the binder as well.")
            lines.append("")
    lines.extend(f"- {reason}" for reason in dict.fromkeys(quality["invalid"] + quality["unresolved"]))
    for row in targets:
        lines.extend(f"- Frame {row['engine_frame']}: {reason}" for reason in row["invalid"] + row["unresolved"])
    if state == "OBSERVER_EFFECT_UNRESOLVED":
        lines.append("- Capture overhead on the target workload remains unverified.")
    (directory / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(state)


def pack(directory):
    files = sorted(path for path in directory.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt")
    (directory / "SHA256SUMS.txt").write_text(
        "".join(f"{hash_file(path)}  {path.name}\n" for path in files), encoding="utf-8")
    archive_path = directory.with_suffix(".zip")
    temporary = directory.with_suffix(".zip.tmp")
    with ZipFile(temporary, "w", ZIP_DEFLATED, compresslevel=3) as archive:
        for path in files + [directory / "SHA256SUMS.txt"]:
            archive.write(path, path.name)
    temporary.replace(archive_path)
    print(archive_path)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("tools", type=Path)
    parser.add_argument("--pack", action="store_true")
    args = parser.parse_args()
    run(args.directory, args.tools)
    if args.pack:
        pack(args.directory)
