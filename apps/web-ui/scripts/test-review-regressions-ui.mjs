import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
try {
  const page=await browser.newPage();
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
    else if(path==='/api/run-schedules')body=[{
      id:'finished-fixture',profileId:'profile',profileName:'Finished fixture',profileRevision:1,
      year:2026,timeZone:'Asia/Ho_Chi_Minh',startsAt:'2026-10-12T01:00:00Z',repeat:'once',enabled:false,
      status:'COMPLETED',sessionId:'finished-session',lastRunAt:'2026-10-12T01:00:00Z',
      finishedAt:'2026-10-12T02:00:00Z',total:100,done:100,withData:100,noData:0,failed:0,
    }];
    await route.fulfill({json:body});
  });
  const origin=(process.env.REVIEW_UI_URL||'http://127.0.0.1:5184/').split('#')[0];
  await page.goto(origin+'#settings');
  await page.getByText('Finished fixture',{exact:true}).waitFor();
  assert.equal(await page.locator('.schedule-progress-eta').count(),0,
    'Completed schedules must not show ETA Finished.');
  assert.deepEqual(errors,[]);
  console.log('Finished schedule regression PASS');
}finally{await browser.close();}
