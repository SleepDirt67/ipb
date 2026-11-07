"""Offline QPC correlation. Inputs are kept even when a source is incomplete."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
from statistics import median
import subprocess
import zipfile

STAGES = {
    1: "OnIdle", 2: "Render", 3: "Present", 4: "WaitWorkers",
    5: "PreRender", 6: "Discord", 7: "SceneRender", 8: "Gamma", 11: "Reset", 14: "BeginRender",
    16: "FrameMove", 17: "LevelFrame", 18: "ClientReceive", 19: "GameEvents", 20: "SpawnEvent",
    21: "ObjectsUpdate", 22: "GameTask", 23: "Scheduler", 24: "ParallelTasks", 25: "FrameMT",
    26: "ParticleUpdates", 27: "TaskEnqueue", 29: "PixelProbeWork", 30: "TimedCallbacks", 31: "HudUpdate",
}
PIXEL_SAMPLE = 28
GPU_METRICS = ("MsGPULatency", "MsGPUTime", "MsGPUBusy", "MsGPUWait",
               "MsRenderPresentLatency", "MsUntilDisplayed")
BANDS = ((.6, 1.6), (7, 15))
CPU_STATES = ("running", "ready", "blocked", "unknown_offcpu")


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def engine(path, pid):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        meta = dict(field.split("=", 1) for field in next(stream).strip()[1:].split(","))
        if int(meta["version"]) != 1 or int(meta["pid"]) != pid:
            raise ValueError("Engine CSV version or process ID differs from capture.json")
        spans = []
        for row in csv.DictReader(stream):
            kind, frame, tid, start, end, payload = (
                int(row[key]) for key in ("kind", "frame", "thread_id", "qpc_start", "qpc_end", "payload"))
            if not 0 < start <= end:
                raise ValueError("Invalid engine QPC interval")
            spans.append((start, end, kind, frame, tid, payload))
    return {key: int(meta[key]) for key in ("qpc_frequency", "qpc_origin", "dropped")}, sorted(spans)


def segment_presents(spans, frequency):
    states = [span for span in spans if span[2] == 13]
    epochs = []
    segment, active, active_since = 0, False, 0
    for start, _, _, _, _, payload in states:
        playing = (payload >> 32) & 31 == 17
        if playing and not active:
            segment += 1
            active_since = start
        active = playing
        epochs.append(segment if active and start - active_since >= 2 * frequency else None)
    state_times = [state[0] for state in states]
    result = []
    for row in (span for span in spans if span[2] == 3):
        index = bisect_right(state_times, row[0]) - 1
        epoch = epochs[index] if index >= 0 else None
        if epoch is not None and states[index][3] == row[3]:
            result.append((row, epoch))
    return result, len(states)


def join_presents(path, pid, presents, frequency):
    """Use TimeInQPC (the actual Present event), with one-to-one and swap-chain checks."""
    times = [span[0] for span in presents]
    candidates = defaultdict(lambda: defaultdict(list))
    invalid = 0
    for row in read_rows(path):
        if row["ProcessID"] != str(pid):
            continue
        try:
            timestamp = int(row["TimeInQPC"])
        except (KeyError, ValueError):
            invalid += 1
            continue
        index = bisect_left(times, timestamp)
        nearby = [i for i in (index - 1, index) if 0 <= i < len(times)
                  and abs(times[i] - timestamp) <= .0005 * frequency]
        if len(nearby) != 1:
            invalid += 1
            continue
        candidates[row["SwapChainAddress"]][nearby[0]].append((timestamp, row))
    if not candidates:
        raise ValueError("No raw Present QPC matches. Check PresentMon and clock coverage.")
    # The game swap chain has the largest one-to-one correspondence with instrumented Presents.
    chain = max(candidates, key=lambda key: len(candidates[key]))
    if sum(len(values) == len(candidates[chain]) for values in candidates.values()) != 1:
        raise ValueError("Game swap chain is ambiguous")
    matched = {}
    duplicate_rows = 0
    for index, rows in candidates[chain].items():
        if len(rows) != 1:
            duplicate_rows += len(rows)
        else:
            matched[presents[index][0]] = rows[0]
    if not matched:
        raise ValueError("All raw Present QPC matches are ambiguous")
    errors = [abs(qpc - q) * 1000 / frequency for q, (qpc, _) in matched.items()]
    return matched, {
        "swap_chain": chain, "matched": len(matched), "gameplay_engine_presents": len(presents),
        "coverage": len(matched) / len(presents),
        "rows_outside_gameplay_match_or_ambiguous": invalid + duplicate_rows,
        "max_residual_ms": max(errors), "median_residual_ms": median(errors),
    }


def cpu_schedule(directory, helper, threads, frequency):
    source = directory / "cpu_scheduling.etl"
    if not source.is_file():
        raise ValueError("CPU ETL unavailable")
    path = directory / "cpu_schedule.csv"
    result = subprocess.run([str(helper), "--extract", str(source), str(path),
                             ",".join(map(str, sorted(threads)))],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"ETL decoder: {result.stderr.strip()}")
    meta = json.loads(result.stdout)
    if meta["qpc_frequency"] != frequency:
        raise ValueError("ETL QPC frequency differs from the engine")
    events = defaultdict(list)
    for row in read_rows(path):
        qpc, tid, other, state, flags = (int(row[key]) for key in
            ("qpc", "tid", "other_tid", "old_state", "wait_reason_or_ready_flags"))
        if row["kind"] == "ready":
            if not flags & 6:  # Swapped stack/process is not yet dispatchable.
                events[tid].append((qpc, 1, 0 if flags & 1 or other == 0xffffffff else other))
        else:
            if other in threads:
                events[other].append((qpc, 0, state))
            if tid in threads:
                events[tid].append((qpc, 2, other))
    return {tid: thread_intervals(items) for tid, items in events.items()}, meta


def thread_intervals(events):
    """Build witnessed states only. A wait without ReadyThread remains unknown."""
    intervals = []
    switch_in, switch_out, wake = None, None, None
    for qpc, kind, data in sorted(events):
        if kind == 0:  # switch out
            if switch_in is not None and switch_in < qpc:
                intervals.append((switch_in, qpc, "running", None))
            switch_in, switch_out, wake = None, (qpc, data), None
        elif kind == 1:  # ReadyThread
            if switch_out is not None and switch_out[0] <= qpc and wake is None:
                wake = qpc, data
        else:  # switch in
            if switch_out is not None:
                begin, old_state = switch_out
                if begin < qpc:
                    if old_state == 1:
                        intervals.append((begin, qpc, "ready", None))
                    elif old_state == 5 and wake is not None and wake[0] <= qpc:
                        intervals.append((begin, wake[0], "blocked", wake[1]))
                        intervals.append((wake[0], qpc, "ready", wake[1]))
                    else:
                        intervals.append((begin, qpc, "unknown_offcpu", None))
            switch_in, switch_out, wake = qpc, None, None
    return [row[0] for row in intervals], intervals


def cpu_overlap(index, begin, end, scale):
    times, rows = index
    pos = max(0, bisect_right(times, begin) - 1)
    sums = Counter()
    readiers = Counter()
    while pos < len(rows) and rows[pos][0] < end:
        lo, hi, state, actor = rows[pos]
        ticks = min(hi, end) - max(lo, begin)
        if ticks > 0:
            sums[state] += ticks
            if actor and state == "blocked":
                readiers[actor] += ticks
        pos += 1
    return {state: round(sums[state] * scale, 4) for state in CPU_STATES}, readiers


def cpu_window_available(etw, begin, end):
    return (bool(etw) and etw["qpc_first"] <= begin < end <= etw["qpc_last"] and
            not any(etw.get(key, 0) for key in ("events_lost", "buffers_lost", "unsupported_events", "switch_chain_breaks")))


def context_gaps(presents, joined, spans, schedules, etw, frequency):
    scale = 1000 / frequency
    last_by_segment = {}
    stages = defaultdict(list)
    for lo, hi, kind, frame, tid, payload in spans:
        if kind in STAGES:
            stages[frame].append((lo, hi, kind, tid, payload))
    frames = []
    for present, segment in presents:
        qpc, end, _, frame, main, hr = present
        previous = last_by_segment.get(segment)
        last_by_segment[segment] = present
        if previous is None:
            continue
        start = previous[0]
        record = {"qpc_start": start, "qpc_end": qpc, "segment": segment, "frame": frame, "main_tid": main,
                  "present_gap_ms": (qpc - start) * scale, "previous_present_ms": (previous[1] - start) * scale,
                  "present_api_ms": (end - qpc) * scale, "present_hresult": hr, "WaitWorkers_overlap_ms": 0}
        workers = set()
        for index in {frame, previous[3]}:
            for lo, hi, kind, tid, _ in stages.get(index, ()):
                if lo >= qpc or hi <= start or kind == 3:
                    continue
                name = STAGES[kind] + "_overlap_ms"
                overlap = (min(hi, qpc) - max(lo, start)) * scale
                record[name] = record.get(name, 0) + overlap
                if kind == 22:
                    task = "GameTask_main_overlap_ms" if tid == main else "GameTask_worker_overlap_ms"
                    record[task] = record.get(task, 0) + overlap
                if kind in (5, 22) and tid != main:
                    workers.add(tid)
        pm = joined.get(qpc)
        if pm:
            pm_qpc, row = pm
            record["pm_present_qpc"] = pm_qpc
            record["display_mode"] = row.get("PresentMode")
            record["display_lane"] = (row.get("VidPnSourceId"), row.get("LayerIndex"))
            for metric in GPU_METRICS:
                record[metric] = number(row.get(metric))
            gpu_latency = record["MsGPULatency"]
            gpu_complete = record["MsRenderPresentLatency"]
            if gpu_latency is not None and (row.get("CPUStartQPC") or "").isdigit():
                record["gpu_start_qpc"] = int(row["CPUStartQPC"]) + round(gpu_latency / scale)
            if gpu_complete is not None and gpu_complete > 0:
                record["gpu_complete_qpc"] = pm_qpc + round(gpu_complete / scale)
            if record["MsUntilDisplayed"] is not None:
                record["display_qpc"] = pm_qpc + round(record["MsUntilDisplayed"] / scale)
                if gpu_complete is not None and 0 < gpu_complete <= record["MsUntilDisplayed"]:
                    record["gpu_complete_to_display_ms"] = record["MsUntilDisplayed"] - gpu_complete
        if main in schedules and cpu_window_available(etw, start, qpc):
            sums, ready_by = cpu_overlap(schedules[main], start, qpc, scale)
            for state, ms in sums.items():
                record["main_" + state + "_ms"] = ms
            record["main_etw_covered_ms"] = sum(sums.values())
            record["main_etw_unobserved_ms"] = max(0, record["present_gap_ms"] - sum(sums.values()))
            if ready_by:
                record["top_readying_tid"] = ready_by.most_common(1)[0][0]
            if workers:
                record["worker_running_ms"] = sum(
                    cpu_overlap(schedules[tid], start, qpc, scale)[0]["running"]
                    for tid in workers if tid in schedules)
        frames.append(record)
    return frames


def display_series(frames, frequency):
    shown = [row for row in frames if row.get("display_qpc") is not None]
    lanes = Counter(row["display_lane"] for row in shown)
    # Keep separate output/layer streams. Report the largest lane; no cross-lane gaps.
    if not lanes:
        return {"shown": 0, "note": "No display outcome; do not infer dropped frames or panel behavior"}
    lane = lanes.most_common(1)[0][0]
    shown = [row for row in shown if row["display_lane"] == lane]
    previous = None
    for row in sorted(shown, key=lambda r: r["display_qpc"]):
        if previous and row["segment"] == previous["segment"]:
            delta = row["display_qpc"] - previous["display_qpc"]
            if delta > 0:
                row["display_gap_ms"] = delta * 1000 / frequency
                row["display_gap_start_qpc"] = previous["display_qpc"]
                if previous.get("display_mode") != row.get("display_mode"):
                    row["display_mode_change"] = True
        previous = row
    return {"shown": len(shown), "lane": lane, "lanes": len(lanes),
            "present_rows_without_display_outcome": sum("pm_present_qpc" in r and "display_qpc" not in r for r in frames)}


def local_outliers(frames, metric, frequency, minimum, relative, absolute=0):
    """Robust local reference, independent of assumed recurrence period."""
    bins = defaultdict(list)
    for row in frames:
        value = row.get(metric)
        if value is not None:
            qpc = row.get("display_qpc", row["qpc_end"]) if metric == "display_gap_ms" else row["qpc_end"]
            bins[row["segment"], qpc // (frequency * 5)].append((qpc, value, row))
    outliers = []
    for (segment, bucket), values in bins.items():
        context = [v for k in range(bucket - 1, bucket + 2) for _, v, _ in bins.get((segment, k), ())]
        if len(context) < 20:
            continue
        base = median(context)
        mad = median(abs(v - base) for v in context)
        threshold = max(absolute, base + max(minimum, relative * base, 4 * 1.4826 * mad))
        for qpc, value, row in values:
            if value >= threshold:
                outliers.append((qpc, value, base, row))
    return sorted(outliers, key=lambda event: event[0])


def collapse(events, frequency):
    """Consecutive spikes close in time are one episode for recurrence tests."""
    result = []
    start = previous = None
    for event in events:
        qpc = event[0]
        if previous is None or qpc - previous > frequency * .08 or result[-1][3]["segment"] != event[3]["segment"]:
            result.append(event)
            start = qpc
        elif qpc - start > frequency * .25:
            result.append(event)
            start = qpc
        elif event[1] - event[2] > result[-1][1] - result[-1][2]:
            result[-1] = event
        previous = qpc
    return result


def frequency_grid(low, high, duration):
    steps = max(32, min(1500, math.ceil((1 / low - 1 / high) * duration * 5)))
    return (1 / high + (1 / low - 1 / high) * i / steps for i in range(steps + 1))


def phase(times, hz):
    angles = [math.tau * hz * t for t in times]
    x = sum(math.cos(a) for a in angles) / len(angles)
    y = sum(math.sin(a) for a in angles) / len(angles)
    return math.hypot(x, y), math.atan2(y, x)


def event_periods(events, frequency):
    if len(events) < 5:
        return []
    t = [(qpc - events[0][0]) / frequency for qpc, *_ in events]
    middle = t[-1] / 2
    halves = ([x for x in t if x <= middle], [x for x in t if x > middle])
    intervals = [b - a for a, b, previous, current in zip(t, t[1:], events, events[1:])
                 if previous[3]["segment"] == current[3]["segment"]]
    result = []
    for low, high in BANDS:
        if t[-1] < 3 * high:
            continue
        strength, hz = max((phase(t, hz)[0], hz) for hz in frequency_grid(low, high, t[-1]))
        period = 1 / hz
        split = [phase(part, hz) if len(part) >= 2 else None for part in halves]
        delta = abs(math.remainder(split[0][1] - split[1][1], math.tau)) if all(split) else None
        near = sum(abs(d / period - 1) <= .20 for d in intervals) / len(intervals) if intervals else None
        stable = strength >= .65 and delta is not None and delta < .7 and min(x[0] for x in split) >= .60
        recurrence = "weak_or_inconsistent"
        if stable:
            recurrence = "repeated_interval_candidate" if near is not None and near >= .5 else "phase_only_check_harmonics_and_missing_cycles"
        elif len(events) >= 40 and strength >= .35 and delta is not None and delta < .8 and min(x[0] for x in split) >= .30:
            recurrence = "cluster_phase_candidate"
        result.append({"band_s": [low, high], "period_s": round(period, 4), "phase_R": round(strength, 3),
                       "half_R": [round(x[0], 3) if x else None for x in split],
                       "half_phase_difference_rad": delta, "events": len(t), "recurrence": recurrence,
                       "median_interval_s": median(intervals) if intervals else None,
                       "adjacent_intervals_near_period_fraction": near})
    return result


def continuous_periods(frames, metric, frequency):
    # Median within 100-ms time bins: inspect weak modulation separately from rare spikes.
    buckets = defaultdict(list)
    for row in frames:
        value = row.get(metric)
        if value is not None:
            buckets[row["qpc_end"] * 10 // frequency].append(value)
    if len(buckets) < 150:
        return []
    first = min(buckets)
    samples = [((q - first) / 10, median(v)) for q, v in sorted(buckets.items())]
    duration = samples[-1][0]
    mean = sum(v for _, v in samples) / len(samples)
    variance = sum((v - mean) ** 2 for _, v in samples)
    if not variance:
        return []

    def fit(hz):
        n = len(samples)
        cosines = [math.cos(math.tau * hz * t) for t, _ in samples]
        sines = [math.sin(math.tau * hz * t) for t, _ in samples]
        c, s = sum(cosines) / n, sum(sines) / n
        cc = sum((x - c) ** 2 for x in cosines)
        ss = sum((y - s) ** 2 for y in sines)
        cs = sum((x - c) * (y - s) for x, y in zip(cosines, sines))
        xc = sum((v - mean) * x for (_, v), x in zip(samples, cosines))
        xs = sum((v - mean) * y for (_, v), y in zip(samples, sines))
        det = cc * ss - cs * cs
        if det <= 0:
            return 0, 0
        a, b = (xc * ss - xs * cs) / det, (xs * cc - xc * cs) / det
        return (a * xc + b * xs) / variance, math.hypot(a, b)

    peaks = []
    for low, high in BANDS:
        if duration < 3 * high:
            continue
        score, amplitude, hz = max((*fit(hz), hz) for hz in frequency_grid(low, high, duration))
        peaks.append({"band_s": [low, high], "period_s": round(1 / hz, 4),
                      "amplitude_ms": round(amplitude, 5), "variance_fraction": round(score, 5)})
    return peaks


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        if fields:
            writer = csv.DictWriter(stream, fields)
            writer.writeheader()
            writer.writerows(rows)


def correlate_windows(windows, schedules, etw, frequency):
    submission = sorted((row for row in windows if row["detector"].endswith("_submission")),
                        key=lambda row: row["window_start_qpc"])
    starts = [row["window_start_qpc"] for row in submission]
    scale = 1000 / frequency
    for row in windows:
        begin, end = row["window_start_qpc"], row["window_end_qpc"]
        first = max(0, bisect_right(starts, begin) - 1)
        last = bisect_left(starts, end)
        if row["detector"].endswith("_display"):
            row["overlapping_submission_anomaly_frames"] = ",".join(
                str(other["frame"]) for other in submission[first:last] if other["window_end_qpc"] > begin)
        if row["main_tid"] in schedules and cpu_window_available(etw, begin, end):
            sums, ready_by = cpu_overlap(schedules[row["main_tid"]], begin, end, scale)
            for state, ms in sums.items():
                row["window_main_" + state + "_ms"] = ms
            row["window_main_unobserved_ms"] = max(0, (end - begin) * scale - sum(sums.values()))
            if ready_by:
                row["window_top_readying_tid"] = ready_by.most_common(1)[0][0]


def pixel_observations(frames, spans, frequency):
    # One sample per presented game frame. A missing readback stays unknown.
    samples = defaultdict(list)
    statuses = Counter()
    for start, _, kind, frame, _, payload in spans:
        if kind == PIXEL_SAMPLE:
            samples[frame].append((start, payload))
        elif kind == 29 and payload:
            statuses[payload] += 1
    resolved = []
    for row in frames:
        matches = [sample for sample in samples.get(row["frame"], ())
                   if row["qpc_start"] < sample[0] <= row["qpc_end"]]
        if len(matches) == 1:
            qpc, packed = matches[0]
            row["pixel_sample_qpc"] = qpc
            row["pixel_levels"] = " ".join(str((packed >> (i * 8)) & 255) for i in range(8))
            resolved.append((row, tuple((packed >> (i * 8)) & 255 for i in range(8))))
    events = []
    adjacent_triplets = 0
    for (left, a), (row, b), (right, c) in zip(resolved, resolved[1:], resolved[2:]):
        if left["segment"] != row["segment"] or row["segment"] != right["segment"]:
            continue
        if left["frame"] + 1 != row["frame"] or row["frame"] + 1 != right["frame"]:
            continue
        adjacent_triplets += 1
        bright = sum(y - x >= 24 and y - z >= 24 and abs(x - z) <= 12 for x, y, z in zip(a, b, c))
        dark = sum(x - y >= 24 and z - y >= 24 and abs(x - z) <= 12 for x, y, z in zip(a, b, c))
        if max(bright, dark) >= 6:
            event = dict(row, detector="pixel_single_frame_pulse", event_qpc=row["pixel_sample_qpc"],
                         window_start_qpc=row["pixel_sample_qpc"], window_end_qpc=right["pixel_sample_qpc"],
                         pixel_polarity="bright" if bright > dark else "dark", pixel_points_changed=max(bright, dark))
            events.append(event)
    return {
        "sampled_gameplay_frames": len(resolved), "eligible_gameplay_frames": len(frames),
        "coverage": len(resolved) / len(frames) if frames else 0,
        "adjacent_sample_triplets": adjacent_triplets,
        "probe_busy_unsupported_failed": {"busy": statuses[1], "unsupported": statuses[2], "failed": statuses[3]},
        "single_frame_pulse_candidates": len(events),
        "period_candidates": event_periods([(r["event_qpc"], 1, 0, r) for r in events], frequency),
        "limits": "Eight encoded luma points of the swap-chain texture. No full-image, HDR panel or emitted light inference.",
    }, events


def assess(directory, helper):
    capture = json.loads((directory / "capture.json").read_text(encoding="utf-8-sig"))
    pid = capture["pid"]
    meta, spans = engine(directory / f"ixray_pacing_{pid}.csv", pid)
    frequency = meta["qpc_frequency"]
    if frequency <= 0 or frequency != capture["qpc_frequency"]:
        raise ValueError("Launcher and engine QPC frequency disagree")
    if not capture["launch_qpc"] <= meta["qpc_origin"] <= capture["exit_qpc"]:
        raise ValueError("Engine QPC origin outside observed process lifetime")
    presents, state_count = segment_presents(spans, frequency)
    if len(presents) < 2:
        raise ValueError("No analyzable active gameplay Present sequence")
    problems = list(capture.get("capture_errors", ()))
    if meta["dropped"]:
        problems.append("Engine buffer overflow. End of session may be missing.")
    try:
        joined, join = join_presents(directory / "presentmon.csv", pid, [p for p, _ in presents], frequency)
        if join["coverage"] < .95:
            problems.append("Low game Present join coverage. Inspect unmatched outcomes.")
    except (OSError, KeyError, ValueError) as error:
        problems.append(str(error))
        joined, join = {}, {}
    try:
        schedules, etw = cpu_schedule(directory, helper, {span[4] for span in spans}, frequency)
        if etw["qpc_first"] > presents[0][0][0] or etw["qpc_last"] < presents[-1][0][0]:
            problems.append("ETW covers only part of gameplay, likely circular buffer rollover.")
        if etw["events_lost"] or etw["buffers_lost"] or etw["unsupported_events"]:
            problems.append("ETW losses or unsupported events. CPU attribution withheld.")
        if etw.get("switch_chain_breaks", 0):
            problems.append("ETW context-switch chains have gaps. CPU attribution withheld.")
        if not etw["ready_events"]:
            problems.append("ETW has no ReadyThread. Wake-to-run cannot be established.")
    except (OSError, ValueError) as error:
        problems.append(str(error))
        schedules, etw = {}, {}
    frames = context_gaps(presents, joined, spans, schedules, etw, frequency)
    display = display_series(frames, frequency)
    for row in frames:
        row["elapsed_s"] = (row["qpc_end"] - meta["qpc_origin"]) / frequency
    pixels, pixel_events = pixel_observations(frames, spans, frequency)
    if capture.get("pixel_probe_requested") and pixels["coverage"] < .90:
        problems.append("Pixel probe coverage below 90%; do not infer stable frame contents.")
    if not display["shown"]:
        problems.append("No usable displayed outcomes. Cannot assess displayed cadence.")
    if not any(row.get("MsGPUBusy") is not None for row in frames):
        problems.append("No PresentMon GPU execution metrics.")
    definitions = {
        "short_submission": ("present_gap_ms", 2, .20, 0, 25),
        "long_submission": ("present_gap_ms", 8, .35, 25, None),
        "short_display": ("display_gap_ms", 2, .20, 0, 25),
        "long_display": ("display_gap_ms", 8, .35, 25, None),
        "present_api": ("present_api_ms", 1, .25, 0, None),
        "on_idle": ("OnIdle_overlap_ms", 2, .25, 0, None),
        "scene_render": ("SceneRender_overlap_ms", 1.5, .25, 0, None),
        "worker_wait": ("WaitWorkers_overlap_ms", 1, .30, 0, None),
        "main_ready": ("main_ready_ms", .8, .30, 0, None),
        "main_blocked": ("main_blocked_ms", 1, .30, 0, None),
        "gpu_start_latency": ("MsGPULatency", 1.5, .25, 0, None),
        "gpu_busy": ("MsGPUBusy", 1.5, .25, 0, None),
        "gpu_wait": ("MsGPUWait", 1, .25, 0, None),
        "gpu_complete_after_present": ("MsRenderPresentLatency", 1, .25, 0, None),
        "gpu_complete_to_display": ("gpu_complete_to_display_ms", 2, .25, 0, None),
        "submit_to_display": ("MsUntilDisplayed", 2, .25, 0, None),
    }
    findings = {}
    windows = pixel_events
    for label, (metric, minimum, relative, absolute, upper) in definitions.items():
        spikes = local_outliers(frames, metric, frequency, minimum, relative, absolute)
        episodes = collapse([item for item in spikes if upper is None or item[1] < upper], frequency)
        findings[label] = {"metric": metric, "episode_count": len(episodes),
                           "period_candidates": event_periods(episodes, frequency)}
        for qpc, value, base, row in episodes:
            start = row["qpc_start"]
            end = row["qpc_end"]
            if metric == "present_api_ms":
                start, end = qpc, qpc + round(value * frequency / 1000)
            elif metric == "display_gap_ms":
                start, end = row["display_gap_start_qpc"], qpc
            windows.append(dict(row, detector=label, event_qpc=qpc, window_start_qpc=start, window_end_qpc=end,
                                metric_ms=value, local_median_ms=base, excess_ms=value - base))
    for row in frames:
        if row["present_hresult"] or row.get("display_mode_change") or row.get("Reset_overlap_ms", 0):
            windows.append(dict(row, detector="status_or_mode_change", event_qpc=row["qpc_end"],
                                window_start_qpc=row["qpc_start"], window_end_qpc=row["qpc_end"]))
    continuous_metrics = ("present_gap_ms", "display_gap_ms", "Render_overlap_ms", "WaitWorkers_overlap_ms",
                          "present_api_ms", "main_ready_ms", "MsGPULatency", "MsGPUBusy", "MsGPUWait",
                          "gpu_complete_to_display_ms")
    continuous = {metric: continuous_periods(frames, metric, frequency) for metric in continuous_metrics}
    correlate_windows(windows, schedules, etw, frequency)
    write_csv(directory / "windows.csv", sorted(windows, key=lambda row: (row["event_qpc"], row["detector"])))
    write_csv(directory / "frame_timeline.csv", frames)
    gameplay_seconds = sum(row["present_gap_ms"] for row in frames) / 1000
    if gameplay_seconds < 110:
        problems.append("Less than 110 s of analyzed gameplay. Long-period results may be limited.")
    return {
        "status": "partial" if problems else "captured",
        "quality_notes": problems,
        "pid": pid, "qpc_frequency": frequency, "qpc_origin": meta["qpc_origin"],
        "gameplay_seconds": gameplay_seconds, "frame_states": state_count,
        "presents": len(presents), "engine_dropped_rows": meta["dropped"],
        "presentmon_join": join, "cpu_etw": etw, "display": display, "pixel_probe": pixels,
        "event_series": findings, "continuous_candidates": continuous,
        "period_method": "Exploratory band search; check halves, recurrence intervals and harmonics. No exact timer or cause inferred.",
        "cpu_method": "Observed switch-in/out and ReadyThread intervals clipped to submission windows. Nested engine stages overlap.",
        "visual_observation": "The pixel probe observes encoded back-buffer values. Physical panel light is not measured.",
        "physical_symptom_acceptance": "pending",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--helper", type=Path)
    parser.add_argument("--pack", action="store_true")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.pack:
        path = directory.with_suffix(".zip")
        temporary = path.with_suffix(".zip.partial")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for file in sorted(directory.iterdir()):
                if file.is_file():
                    archive.write(file, file.name)
        temporary.replace(path)
        print(path)
        return
    if not args.helper:
        parser.error("--helper is required for analysis")
    try:
        report = assess(directory, args.helper.resolve())
    except (OSError, ValueError, KeyError, StopIteration) as error:
        report = {"status": "incomplete", "quality_notes": [str(error)]}
    (directory / "analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(report["status"])


if __name__ == "__main__":
    main()
