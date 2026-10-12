import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
const mode=process.env.REVIEW_UI_CASE||'sample';
try {
  const page=await browser.newPage();
  let historyCalls=0;
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>localStorage.setItem('vahanUiAccessToken','fixture-token'));
  await page.route('https://fonts.googleapis.com/**',r=>r.abort());
  await page.route('https://fonts.gstatic.com/**',r=>r.abort());
  await page.routeWebSocket('**/socket.io/**',socket=>{
    socket.send('0'+JSON.stringify({sid:'fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));
    socket.onMessage(m=>{if(String(m).startsWith('40/ui,'))socket.send('40/ui,'+JSON.stringify({sid:'ui'}));});
  });
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    let body=[];
    if(path==='/api/auth/status')body={configured:true};
    else if(path==='/api/auth/me')body={username:'fixture',role:'admin'};
    else if(path==='/api/user-state'||path==='/api/auth/activity')body={};
    else if(path==='/api/network/status')body={online:true};
    else if(path==='/api/ui-health/status')body={blocked:false};
    else if(path==='/api/worker-pool')body={desiredCount:3,phase:'ready',workers:[]};
    else if(path==='/api/annual-reports/run-history'){
      historyCalls++;body={runs:[],total:0};
    } else if(path==='/api/run-schedules')body=[{
      id:'finished-fixture',profileId:'profile',profileName:'Finished fixture',profileRevision:1,
      year:2026,timeZone:'Asia/Ho_Chi_Minh',startsAt:'2026-10-12T01:00:00Z',repeat:'once',enabled:false,
      status:'COMPLETED',sessionId:'finished-session',lastRunAt:'2026-10-12T01:00:00Z',
      finishedAt:'2026-10-12T02:00:00Z',total:100,done:100,withData:100,noData:0,failed:0,
    }];
    await route.fulfill({json:body});
  });
  const origin=(process.env.REVIEW_UI_URL||'http://127.0.0.1:5184/').split('#')[0];
  if(mode==='sample')await page.clock.install();
  await page.goto(origin+(mode==='sample'?'#run-history':'#settings'));
  if(mode==='sample'){
    const sample=page.getByRole('checkbox',{name:'Show sample data'});
    await sample.waitFor();await sample.check();
    await page.locator('[data-source=sample]').first().waitFor();
    const before=historyCalls;
    await page.clock.fastForward(60_000);
    await page.waitForTimeout(300);
    assert.equal(historyCalls,before,'Sample mode must stop history API polling.');
    assert.equal(await page.getByRole('alert').count(),0);
    await page.clock.resume();
    await sample.uncheck();
    await page.waitForTimeout(1200);
    assert.ok(historyCalls>before,'Turning samples off resumes actual history loading.');
  }else{
    await page.getByText('Finished fixture',{exact:true}).waitFor();
    assert.equal(await page.locator('.schedule-progress-eta').count(),0,
      'Completed schedules must not show ETA Finished.');
  }
  assert.deepEqual(errors,[]);
  console.log(`${mode} regression PASS`);
}finally{await browser.close();}
