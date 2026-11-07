"""Locate output-only gaps from aligned QPC frames and export their graphics ETW events."""
from bisect import bisect_right
import csv
import json
from pathlib import Path
import subprocess
import sys


def selected_windows(rows, frequency):
    by_segment = {}
    for row in rows:
        by_segment.setdefault(row["segment"], []).append(row)
    gaps = []
    windows = []
    padding = frequency // 10
    for frames in by_segment.values():
        submitted = [int(f["qpc_end"]) for f in frames]
        for i, frame in enumerate(frames):
            end = submitted[i]
            if frame.get("display_mode_change", "").lower() == "true":
                windows.append((end - padding, end + padding))
            if not frame["display_gap_ms"] or float(frame["display_gap_ms"]) < 25:
                continue
            first_display = int(float(frame["display_gap_start_qpc"]))
            last_display = int(float(frame["display_qpc"]))
            begin = bisect_right(submitted, first_display)
            observed = frames[begin:i+1]
            largest_submission = max((float(f["present_gap_ms"]) for f in observed), default=0)
            missing = sum(not f["display_qpc"] for f in observed)
            if len(observed) < 2 or largest_submission >= 10 or not missing:
                continue
            gaps.append({"frame": int(frame["frame"]), "first_display_qpc": first_display,
                         "last_display_qpc": last_display, "display_gap_ms": float(frame["display_gap_ms"]),
                         "max_submission_gap_ms": largest_submission, "no_display_outcome": missing,
                         "mode": frame["display_mode"]})
            windows.append((first_display - padding, last_display + padding))
    merged = []
    for begin, end in sorted(windows):
        if merged and begin <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([max(0, begin), end])
    return gaps, merged


def main():
    directory, decoder = map(Path, sys.argv[1:])
    capture = json.loads((directory / "capture.json").read_text(encoding="utf-8-sig"))
    frequency = capture["qpc_frequency"]
    with (directory / "frame_timeline.csv").open(encoding="utf-8-sig", newline="") as stream:
        gaps, windows = selected_windows(csv.DictReader(stream), frequency)
    ranges = directory / "display_path_windows_qpc.txt"
    ranges.write_text("".join(f"{a} {b}\n" for a, b in windows), encoding="ascii")
    result = {"display_only_candidates": gaps, "exported_windows_qpc": windows}
    try:
        process = subprocess.run([str(decoder), str(directory / "cpu_samples.etl"), str(ranges),
                                  str(directory / "display_path_events.csv")], capture_output=True, text=True, check=True)
        stats = json.loads(process.stdout)
        result["etw"] = stats
        result["coverage_complete"] = stats["qpc_frequency"] == frequency and not (
            stats["events_lost"] or stats["buffers_lost"]) and all(
            stats["first_qpc"] <= a <= b <= stats["last_qpc"] for a, b in windows)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        result["error"] = str(error)
    (directory / "display_path_summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
