import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = []; let calls=0, newest='Electric two-wheelers', fail=false;
  const artifacts = new URL('../../../outputs/', import.meta.url);
  await mkdir(artifacts, {recursive:true});
  const mockRuns = () => Array.from({length:51}, (_,index) => ({
    sessionId: String(51-index),
    filterName: index === 0 ? newest : ['Electric two-wheelers','Petrol passenger cars','Commercial diesel vehicles'][index%3],
    runNumber: 17-Math.floor(index/3), totalRuns: 17,
    ...[
      {status:'PAUSED',processed:24,totalCases:1676,withData:20,noData:3,failed:1,pending:1652,running:0,finishedAt:null},
      {status:'COMPLETED',processed:240,totalCases:240,withData:218,noData:22,failed:0,pending:0,running:0,finishedAt:'2026-10-12T01:15:00Z'},
      {status:'RUNNING',processed:1069,totalCases:1676,withData:1010,noData:55,failed:4,pending:604,running:3,finishedAt:null},
      {status:'COMPLETED_WITH_ERRORS',processed:100,totalCases:100,withData:80,noData:18,failed:2,pending:0,running:0,finishedAt:'2026-10-11T10:00:00Z'},
      {status:'STOPPED',processed:35,totalCases:600,withData:30,noData:5,failed:0,pending:565,running:0,finishedAt:null},
    ][index%5],
    lastActivityAt:new Date(Date.parse('2026-10-12T02:35:00Z')-index*6*60*60*1000).toISOString(),
    startedAt: new Date(Date.parse('2026-10-12T02:30:00Z')-index*6*60*60*1000).toISOString(),
  }));
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('vahanUiAccessToken','fixture-token'));
  await page.route('https://fonts.googleapis.com/**', r => r.abort());
  await page.route('https://fonts.gstatic.com/**', r => r.abort());
  await page.routeWebSocket('**/socket.io/**', socket => {
    socket.send('0'+JSON.stringify({sid:'fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));
    socket.onMessage(message => {if(String(message).startsWith('40/ui,')) socket.send('40/ui,'+JSON.stringify({sid:'ui'}));});
  });
  await page.route('**/api/**', async route => {
    const url=new URL(route.request().url()), path=url.pathname; let body=[];
    if(path==='/api/auth/status') body={configured:true};
    else if(path==='/api/auth/me') body={username:'fixture',role:'admin'};
    else if(path==='/api/auth/activity'||path==='/api/user-state') body={};
    else if(path==='/api/network/status') body={online:true};
    else if(path==='/api/ui-health/status') body={blocked:false,latestPreflight:null};
    else if(path==='/api/worker-pool') body={enabled:true,desiredCount:3,runningCount:3,phase:'ready',workers:[]};
    else if(path==='/api/annual-reports') body={year:2026,datasetId:'fixture',datasets:[],years:[2026],states:[],rtos:[],rows:[],summary:{rows:0,makers:0,offices:0,updatedAt:null},coverage:[],lastSaved:null};
    else if(path==='/api/annual-reports/run-history') {
      calls++;
      if(fail) return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'History temporarily unavailable'})});
      const offset=Number(url.searchParams.get('offset'));
      body={total:51,runs:mockRuns().slice(offset,offset+50)};
    }
    await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
  });
  const origin=(process.env.HISTORY_UI_URL||'http://127.0.0.1:5184/').split('#')[0];
  await page.goto(origin+'#reports');
  await page.getByRole('heading',{name:'Exported Reports',exact:true}).waitFor();
  assert.equal(calls,0,'History loads when the history page is opened');
  assert.equal(await page.getByRole('button',{name:'Update history',exact:true}).count(),0);
  const nav=page.getByRole('navigation',{name:'Main navigation'});
  assert.deepEqual(await nav.locator('a').allTextContents(),['Exported Reports','Filters','Run History','Settings']);
  await nav.getByRole('link',{name:'Run History',exact:true}).click();
  await page.getByRole('heading',{name:'Run History',exact:true}).waitFor();
  const panel=page.getByRole('region',{name:'Filter run history'});
  await panel.getByRole('rowheader',{name:'Electric two-wheelers',exact:true}).first().waitFor();
  assert.equal(await page.getByRole('dialog').count(),0);
  assert.deepEqual(await panel.locator('thead th').allTextContents(),['Run','Filter','Progress','Status','Results','Run time']);
  assert.equal(await panel.locator('tbody tr').count(),50);
  assert.match(await panel.locator('tbody tr').first().locator('td').first().innerText(),/#17\s+17 runs/);
  const first = panel.locator('tbody tr').first();
  assert.match(await first.locator('[data-label="Progress"]').innerText(),/24 \/ 1,676/);
  assert.match(await first.locator('[data-label="Status"]').innerText(),/Paused\s+1,652 pending · 0 running/);
  assert.match(await first.locator('[data-label="Results"]').innerText(),/With data\s+20\s+No data\s+3\s+Failed\s+1/);
  assert.equal(await first.locator('progress').getAttribute('value'),'24');
  assert.equal(await panel.getByText('History by day',{exact:true}).count(),0);
  assert.match(await panel.locator('time').first().innerText(),/12\/10\/2026,? 09:30:00/);
  assert.equal(await page.getByLabel('Update history from year').count(),0);
  await panel.getByRole('button',{name:'Next',exact:true}).click();
  await panel.getByRole('rowheader',{name:'Commercial diesel vehicles',exact:true}).waitFor();
  assert.equal(await panel.locator('tbody tr').count(),1);
  assert.match(await panel.locator('tbody td').first().innerText(),/#1\s+17 runs/);
  await panel.getByRole('button',{name:'Previous',exact:true}).click();
  await panel.getByRole('rowheader',{name:'Electric two-wheelers',exact:true}).first().waitFor();
  newest='Renamed filter';
  await page.getByRole('button',{name:'Refresh history',exact:true}).click();
  await panel.getByRole('rowheader',{name:'Renamed filter',exact:true}).waitFor();
  fail=true;
  await page.getByRole('button',{name:'Refresh history',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'History temporarily unavailable'}).waitFor();
  assert.equal(await panel.locator('tbody tr').count(),50,'A failed refresh retains the existing rows');
  fail=false;
  await page.getByRole('button',{name:'Refresh history',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'History temporarily unavailable'}).waitFor({state:'hidden'});
  newest='Electric two-wheelers';
  await page.getByRole('button',{name:'Refresh history',exact:true}).click();
  await panel.locator('tbody th').first().filter({hasText:'Electric two-wheelers'}).waitFor();
  for(const width of [1440,768,390,320]) {
    await page.setViewportSize({width,height:1000});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`No horizontal page overflow at ${width}px`);
    if(width===1440||width===390) {
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.screenshot({path:fileURLToPath(new URL(`run-history-${width}.png`,artifacts)),fullPage:false});
    }
  }
  await page.reload();
  await panel.locator('tbody th').first().filter({hasText:'Electric two-wheelers'}).waitFor();
  assert.equal(await nav.getByRole('link',{name:'Run History',exact:true}).getAttribute('aria-current'),'page');
  await page.goto(origin+'#update-history');
  await page.waitForURL('**/#run-history');
  await page.getByRole('heading',{name:'Run History',exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('Run History: navigation, lazy loading, run numbering, Vietnam time, pagination, refresh recovery, direct route and mobile passed.');
} finally {await browser.close();}
