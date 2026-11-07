from pathlib import Path
import json,csv,sys,subprocess
folder=Path(sys.argv[1]);package=Path(sys.argv[2])
subprocess.run([sys.executable,str(package/'join_capture.py'),str(folder)],check=True)
summary=json.loads((folder/'JOIN_SUMMARY.json').read_text());assert summary['matched']>300 and summary['match_fraction']>.6,summary
with (folder/'markers.csv').open() as f:
 next(f);marks=list(csv.DictReader(f))
assert len(marks)==5 and marks[0]['sync_request_sent']=='1',marks
assert {r['kind'] for r in marks}=={'video_sync_request','blink_observed','long_freeze_observed','segment_boundary','stop'}
print('PASS: CPU-only PresentMon QPC matches controlled DXGI Present entry (headless WARP; physical GPU/display not tested); helper registered Win hotkeys, recorded independent timestamps and delivered sync IPC')
