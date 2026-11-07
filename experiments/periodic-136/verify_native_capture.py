from pathlib import Path
import csv,sys,json
folder=Path(sys.argv[1]);overflow=len(sys.argv)>2
files=list(folder.glob('ixray_pacing_*.csv'));assert len(files)==1,files
with files[0].open() as f:
 meta=dict(x.split('=',1) for x in next(f).strip()[1:].split(','));rows=list(csv.DictReader(f))
assert int(meta['qpc_frequency'])>0 and int(meta['qpc_origin_uncertainty_ticks'])>=0
assert len(rows)==(1048576 if overflow else 200003),len(rows)
assert (int(meta['dropped'])>0)==overflow
assert len({r['thread_id'] for r in rows if r['kind']=='3'})==4
assert all(int(r['qpc_end'])>=int(r['qpc_start'])>0 for r in rows)
assert all(r['frame']=='124' for r in rows if r['kind']=='3')
assert {r['payload'] for r in rows if r['kind']=='3'}=={'0','1','2','3'}
print(json.dumps({'file':files[0].name,'rows':len(rows),'dropped':meta['dropped'],'concurrent_writers':4,'timestamps_valid':True,'overflow_fixture':overflow}))
