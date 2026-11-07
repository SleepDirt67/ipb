"""QPC join; ambiguous/unmatched rows remain explicit, never aligned by file name."""
from pathlib import Path
import csv,json,sys,bisect,statistics
root=Path(sys.argv[1]);pacing=list(root.glob('ixray_pacing_*.csv'))
if len(pacing)!=1:raise SystemExit('Expected exactly one pacing CSV; Baseline captures intentionally have none.')
with pacing[0].open(encoding='utf-8-sig') as f:
 meta=dict(v.split('=',1) for v in next(f).strip()[1:].split(','));rows=list(csv.DictReader(f))
frequency=int(meta['qpc_frequency'])
if int(meta['dropped']):raise SystemExit('Pacing buffer overflow; shorten capture. Do not treat missing intervals as smooth frames.')
spans=sorted((r for r in rows if r['kind']=='3'),key=lambda r:int(r['qpc_start']))
times=[int(r['qpc_start']) for r in spans]
with (root/'presentmon.csv').open(encoding='utf-8-sig') as f:pm=list(csv.DictReader(f))
if not pm or not {'CPUStartQPC','MsCPUBusy'}<=pm[0].keys():raise SystemExit('PresentMon raw CPUStartQPC/MsCPUBusy missing; no guessed wall-clock alignment.')
joined=[];unmatched=0;used=set()
for p in pm:
 if p.get('ProcessID')!=meta['pid']:continue
 try:q=int(p['CPUStartQPC'])+round(float(p['MsCPUBusy'])*frequency/1000)
 except (ValueError,TypeError):unmatched+=1;continue
 i=bisect.bisect_left(times,q);candidates=[j for j in (i-1,i) if 0<=j<len(times)]
 if not candidates:unmatched+=1;continue
 j=min(candidates,key=lambda n:abs(times[n]-q));error=(times[j]-q)*1000/frequency
 if abs(error)>.5 or j in used:unmatched+=1;continue
 used.add(j);r=spans[j]
 item=dict(p);item.update(engine_frame=r['frame'],engine_present_qpc=r['qpc_start'],engine_present_api_ms=(int(r['qpc_end'])-int(r['qpc_start']))*1000/frequency,join_residual_ms=error)
 joined.append(item)
if not joined:raise SystemExit('No unambiguous QPC matches within 0.5 ms; inspect raw ETW Present events, do not force alignment.')
with (root/'joined_presentmon.csv').open('w',newline='',encoding='utf-8') as f:
 writer=csv.DictWriter(f,fieldnames=list(joined[0]));writer.writeheader();writer.writerows(joined)
report={'matched':len(joined),'unmatched':unmatched,'engine_presents':len(spans),'match_fraction':len(joined)/len(spans) if spans else 0,'max_absolute_join_residual_ms':max(abs(r['join_residual_ms']) for r in joined),'method':'CPUStartQPC + MsCPUBusy estimates Present entry; reject >0.5ms residual and duplicate matches; inspect ETW if low coverage','visual_onset_known':False,'reaction_marks':'independent helper key-arrival QPC, not onset; sync square + camera needed for exact visible frame'}
(root/'JOIN_SUMMARY.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
