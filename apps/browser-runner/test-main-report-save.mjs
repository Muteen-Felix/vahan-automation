import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source = readFileSync(new URL('./runner.mjs', import.meta.url), 'utf8');
const start = source.indexOf('async function execute(job)');
const end = source.indexOf("socket.on('connect'", start);
assert.ok(start >= 0 && end > start);

function fixture(type = 'DATA_READY', downloadReady = true) {
  const calls = [];
  let resolveCommit, rejectCommit;
  const committed = new Promise((resolve, reject) => {resolveCommit=resolve; rejectCommit=reject;});
  const job = {jobId:'first',status:'WAITING_RESULT',filters:{rtos:['Port Blair DTO - AN1']},retries:0};
  const download = {failure:async()=>null,path:async()=>'/temporary/report.xlsx',suggestedFilename:()=> 'report.xlsx',
    delete:async()=>calls.push('delete-temporary-export')};
  const context = {active:job,optionsBusy:false,authRequired:false,RESULT_TIMEOUT:5000,FormData,Blob,URL,target:new URL('https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en'),
    page:{url:()=> 'https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en',
      waitForEvent:async()=>download,evaluate:async fn=>{
      const code=fn.toString();
      if(code.includes('vahanDriver.result')) return {type,downloadReady,report:{observedAt:'2026-10-02T14:35:42+07:00',pageUrl:'https://fixture/report'}};
      if(code.includes('clickExcel')) calls.push('download');
      if(code.includes('vahanDriver.fill')) calls.push('fill-next-case');
      return {};
    }},
    http:async(path,init)=> {calls.push(path); if(path.endsWith('/main-report')) {
      assert.equal(init.body.get('observedAt'),'2026-10-02T14:35:42+07:00');
      assert.ok(init.body.get('file')); }
      return committed;
    },
    readFile:async()=>new Uint8Array([1,2,3]),saveState:async()=>calls.push('save-browser-state'),
    ensurePage:async()=>{},normalizeJobFilters:value=>value,
    ack:async(event,payload)=>calls.push(`${event}:${payload.status || payload.phase}`),
    status:async()=>{},challenge:async()=>{},fail:async error=>{throw error;},
    snapshot:async()=>{throw new Error('Successful filters must not save report image copies.');},
  };
  context.assertCurrent = candidate => assert.equal(candidate, context.active);
  const code=source.slice(start,end);
  const api=runInNewContext(code+'\n({execute,waitForResult})',context);
  return {api,context,job,calls,resolveCommit,rejectCommit};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const data=fixture();
const first=data.api.waitForResult(data.job);
await tick();
assert.equal(data.context.active,data.job,'current case stays active until SQL acknowledges');
const next=data.api.execute({jobId:'second',filters:{}});
await tick();
assert.ok(!data.calls.includes('fill-next-case'));
assert.ok(!data.calls.includes('job:status:FAILED'));
data.resolveCommit({status:'COMPLETED'});
await Promise.all([first,next]);
assert.equal(data.context.active.jobId,'second');
assert.equal(data.calls.filter(value=>value.includes('/main-report')).length,1);
assert.equal(data.calls.filter(value=>value.includes('/report-result')).length,0);
assert.ok(data.calls.includes('delete-temporary-export'));
assert.ok(data.calls.includes('fill-next-case'));

const empty=fixture('NO_RECORD');
const saving=empty.api.waitForResult(empty.job);
await tick(); empty.resolveCommit({status:'NO_DATA'}); await saving;
assert.equal(empty.context.active,null);
assert.equal(empty.calls.filter(value=>value.includes('/report-result')).length,1);
assert.ok(!empty.calls.includes('download'));

const incomplete=fixture('DATA_READY',false);
await assert.rejects(incomplete.api.waitForResult(incomplete.job),/MAIN_REPORT_EXPORT_MISSING/);
assert.equal(incomplete.context.active,incomplete.job);
assert.ok(!incomplete.calls.some(value=>value.startsWith('/api/')));

const failed=fixture();
const failSave=failed.api.waitForResult(failed.job);
await tick();failed.rejectCommit(new Error('SQL commit failed'));
await assert.rejects(failSave,/SQL commit failed/);
assert.equal(failed.context.active,failed.job);
assert.equal(failed.job.status,'WAITING_RESULT');
assert.ok(failed.calls.includes('delete-temporary-export'));
console.log('Main report worker checks passed: direct save, waiting for SQL before next case, no-data, incomplete export rejection and failed commit cleanup.');
