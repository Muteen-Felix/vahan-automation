import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {chromium} from 'playwright';
import {retireReportPage, stableDocumentRead} from './page-recovery.mjs';

// Closing an unresponsive old document must not leave the worker locked.
let closed = 0;
await retireReportPage({isClosed:()=>false,close:()=>{closed++;return new Promise(()=>{});}},20);
assert.equal(closed,1);
let reads=0;
const result=await stableDocumentRead({waitForLoadState:async()=>{}},async()=>{
  if(++reads<3)throw new Error('Execution context was destroyed');return 'ready';
},1000);
assert.equal(result,'ready');assert.equal(reads,3);
await assert.rejects(stableDocumentRead({waitForLoadState:async()=>{}},async()=>{throw new Error('SQL contract is blocked');}),/SQL contract is blocked/);
await assert.rejects(stableDocumentRead({waitForLoadState:async()=>{}},async()=>{throw new Error('Execution context was destroyed');},20),/VAHAN_PAGE_NOT_READY/);

const source=readFileSync(new URL('./runner.mjs',import.meta.url),'utf8');
const slice=(name,end)=>source.slice(source.indexOf(`async function ${name}(`),source.indexOf(`async function ${end}(`));
const browser=await chromium.launch({headless:true});
try {
  const browserContext=await browser.newContext();const damaged=await browserContext.newPage();
  const url='http://readiness.test/analytics/vahanpublicreport';
  await browserContext.route('http://readiness.test/**',route=>route.fulfill({contentType:'text/html',body:'<select id="stateName" hidden><option>Ready State</option></select>'}));
  await damaged.goto(url);await damaged.evaluate(()=>document.querySelector('#stateName').remove());
  const job={jobId:'old-failed-case',cancelled:false};const calls=[];
  const context={isConnectionError:()=>false,page:damaged,pageNeedsReset:false,active:job,stopping:false,
    retireReportPage,stableDocumentRead,globalThis:{URL},URL:url,target:new URL(url),authRequired:false,
    snapshot:async()=>calls.push('snapshot'),status:async()=>calls.push('failed'),saveState:async()=>{},
    console:{error:()=>{}},socket:{disconnect:()=>{},connect:()=>{}},
    http:async()=>({blocked:false,versionId:'verified',revision:1,controls:[]}),
    VAHAN_OPTION_SELECTORS:{states:{selector:'#stateName'}},approvedSelectors:{},contractRevision:0,
    selectorOverrides:()=>({}),launch:async()=>{},newPage:async()=>{context.page=await browserContext.newPage();calls.push('new-page');},
  };
  const worker=runInNewContext(`${slice('ensurePage','saveState')}\n${slice('fail','execute')}\n({ensurePage,fail})`,context);
  await worker.fail(new Error('VAHAN_PAGE_NOT_READY'),job);
  assert.ok(damaged.isClosed());assert.equal(context.pageNeedsReset,true);assert.equal(context.active,null);
  await worker.ensurePage();
  assert.notEqual(context.page,damaged);assert.equal(context.pageNeedsReset,false);
  assert.equal(await context.page.locator('#stateName option').innerText(),'Ready State');
  assert.deepEqual(calls,['snapshot','failed','new-page']);
  // SQL drift protection remains fail-closed even during page recovery.
  context.http=async()=>({blocked:true});await assert.rejects(worker.ensurePage(),/UI_HEALTH_BLOCKED/);
}finally{await browser.close()}

// A new assignment waits for failure cleanup instead of failing as "busy".
let finishSnapshot;const job={jobId:'old',cancelled:false};const calls=[];
const context={isConnectionError:()=>false,active:job,optionsBusy:false,pageNeedsReset:false,page:{evaluate:async()=>({})},stopping:false,
  snapshot:async()=>new Promise(resolve=>{finishSnapshot=resolve;}),retireReportPage:async()=>calls.push('retired'),
  status:async value=>calls.push(value),saveState:async()=>calls.push('saved'),
  ensurePage:async()=>calls.push('ready'),assertCurrent:()=>{},normalizeJobFilters:x=>x,
  ack:async(_event,payload)=>{assert.notEqual(payload.error,'Browser worker is busy.');},challenge:async()=>calls.push('handoff'),
  console:{error:()=>{}},socket:{disconnect:()=>{},connect:()=>{}},
};
const worker=runInNewContext(`${slice('fail','execute')}\n${slice('execute','finalizeResult')}\n({fail,execute})`,context);
const failing=worker.fail(new Error('damaged'),job);const next=worker.execute({jobId:'new',filters:{}});
await new Promise(resolve=>setImmediate(resolve));assert.equal(context.active.jobId,'old');
finishSnapshot();await Promise.all([failing,next]);
assert.equal(context.active.jobId,'new');assert.ok(calls.indexOf('retired')<calls.indexOf('ready'));
assert.deepEqual(calls,['retired','FAILED','saved','OPENING_VAHAN','ready','FILLING_FILTERS','handoff']);
console.log('Page recovery passed: damaged page retired, fresh hidden State loaded, bounded close, navigation reads, SQL gate and assignment race.');
