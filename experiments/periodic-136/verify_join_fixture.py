from pathlib import Path
import csv,json,subprocess,tempfile,sys
script=Path(__file__).with_name('join_capture.py').resolve()
with tempfile.TemporaryDirectory() as td:
 root=Path(td);f=10000000;q0=10000000000
 with (root/'ixray_pacing_1.csv').open('w',newline='') as stream:
  stream.write('#pid=1,qpc_frequency=10000000,dropped=0\n');w=csv.writer(stream);w.writerow(['kind','frame','thread_id','qpc_start','qpc_end','payload'])
  for i in range(100):w.writerow([3,i,10,q0+i*100000,q0+i*100000+1000,0])
 with (root/'presentmon.csv').open('w',newline='') as stream:
  w=csv.writer(stream);w.writerow(['ProcessID','CPUStartQPC','MsCPUBusy'])
  for i in range(100):w.writerow([1,q0+i*100000-50000,5])
  w.writerow([1,q0-50000,5]);w.writerow([1,0,5])
 subprocess.run([sys.executable,str(script),td],check=True,stdout=subprocess.DEVNULL)
 result=json.loads((root/'JOIN_SUMMARY.json').read_text());assert result['matched']==100 and result['unmatched']==2,result
 with (root/'presentmon.csv').open('w') as stream:stream.write('ProcessID,CPUStartQPC,MsCPUBusy\n1,42,1\n')
 wrong=subprocess.run([sys.executable,str(script),td],capture_output=True,text=True);assert wrong.returncode and 'No unambiguous QPC matches' in wrong.stderr
print('QPC join: 100 exact frame matches; duplicate/stale timestamps rejected; unrelated epoch fails closed')
