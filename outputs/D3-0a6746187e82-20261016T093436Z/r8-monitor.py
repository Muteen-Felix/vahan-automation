import harness as h
import json,time,subprocess,hashlib,ctypes
from pathlib import Path
ids=json.loads((h.ROOT/'r8-ids.json').read_text());schedule_id=ids['scheduleId']
web=h.SOURCE/'apps/web-ui'
ts=(Path(r'C:\Users\huyvv12\Desktop\vahan-automation\apps\web-ui\node_modules\typescript\lib\typescript.js')).as_uri()
js="""import ts from TSURL;
import {readFileSync} from 'node:fs';import {createInterface} from 'node:readline';
function mod(file,dep={}){let s=readFileSync(file,'utf8');for(const [n,u] of Object.entries(dep))s=s.replace(`'${n}'`,`'${u}'`);return 'data:text/javascript;base64,'+Buffer.from(ts.transpileModule(s,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString('base64')}
const {observeScheduleTiming,estimateScheduleTiming}=await import(mod(SCHEDULE,{'./batch-timing':mod(BATCH)}));let obs=null;
for await(const line of createInterface({input:process.stdin})){const {schedule,now}=JSON.parse(line);obs=observeScheduleTiming(obs,schedule,now);console.log(JSON.stringify(estimateScheduleTiming(schedule,obs,now)))}
""".replace('TSURL',json.dumps(ts)).replace('SCHEDULE',json.dumps(str(web/'src/schedule-timing.ts'))).replace('BATCH',json.dumps(str(web/'src/batch-timing.ts')))
(h.ROOT/'eta-engine.mjs').write_text(js,encoding='utf-8')
h.save('eta-engine-provenance.json',{'sha':h.SHA,'files':{str(p.relative_to(h.SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [web/'src/schedule-timing.ts',web/'src/batch-timing.ts']},'method':'Exact final source UI estimator; checkpoint every 5s, sample every 60s. No synthetic runner or report.'})
engine=subprocess.Popen(['node',str(h.ROOT/'eta-engine.mjs')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
h.login();login_at=time.monotonic();start=time.monotonic();next_sample=0;previous=None;completed=False
try:
    while True:
        tick=time.monotonic();stamp=h.now()
        if tick-login_at>45*60:h.login();login_at=tick
        r=h.api('GET','/api/run-schedules');assert r['status']==200,h.clean(r)
        schedule=next(s for s in r['body'] if s['id']==schedule_id)
        nowms=time.time()*1000
        engine.stdin.write(json.dumps({'schedule':schedule,'now':nowms})+'\n');engine.stdin.flush()
        line=engine.stdout.readline()
        if not line:raise RuntimeError('UI estimator process exited: '+engine.stderr.read())
        eta=json.loads(line)
        network=h.api('GET','/api/network/status')['body']
        state=(schedule['status'],network.get('online'))
        record={'at':stamp,'unixMs':nowms,'schedule':schedule,'eta':eta,'network':network,'wallElapsedSeconds':tick-start}
        with (h.ROOT/'r8-observations.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(h.clean(record),ensure_ascii=False)+'\n')
        if tick-start>=next_sample:
            with (h.ROOT/'r8-eta-60s.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(h.clean(record),ensure_ascii=False)+'\n')
            next_sample+=60
            print(json.dumps({'at':stamp,'status':schedule['status'],'done':schedule['done'],'total':schedule['total'],'etaMinutes':round(eta['remainingMs']/60000,1) if eta['remainingMs'] else None,'online':network.get('online')}),flush=True)
        if state!=previous:
            with (h.ROOT/'r8-state-events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(h.clean(record),ensure_ascii=False)+'\n')
            previous=state
        h.save('r8-current.json',record)
        if schedule['status'] in ['COMPLETED','COMPLETED_WITH_ERRORS','STOPPED'] and schedule.get('lastRunAt'):
            completed=True;h.save('r8-terminal.json',record);break
        time.sleep(max(0,5-(time.monotonic()-tick)))
finally:
    engine.terminate();ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    h.save('r8-monitor-finished.json',{'at':h.now(),'terminalObserved':completed,'operatorFaultInjection':False})
