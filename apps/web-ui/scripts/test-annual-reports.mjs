import assert from 'node:assert/strict';
import {testArtifactPath} from './test-artifact-path.mjs';
import { chromium } from '../../browser-runner/node_modules/playwright/index.mjs';

const browser = await chromium.launch({headless: true});
const corsOrigin=new URL(process.env.ANNUAL_UI_URL || 'http://127.0.0.1:5174/#reports').origin;
try {
  const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
  const errors = [];
  const exportRequests = [];
  let historyRequests = 0;
  let reportSocket;
  let lastSaved = null;
  let nextReadDelayMs = 0, watchReads = false, failedReads = 0, activeReads = 0, peakReads = 0;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('https://fonts.googleapis.com/**',route=>route.abort());
  await page.route('https://fonts.gstatic.com/**',route=>route.abort());
  page.on('requestfailed', request => {
    if (watchReads && new URL(request.url()).pathname === '/api/annual-reports') failedReads++;
  });
  await page.routeWebSocket('**/socket.io/**', socket => {
    socket.send('0'+JSON.stringify({sid:'fixture-engine',upgrades:[],pingInterval:60_000,pingTimeout:60_000,maxPayload:1_000_000}));
    socket.onMessage(message => {
      if (String(message).startsWith('40/ui,')) {
        reportSocket=socket; socket.send('40/ui,'+JSON.stringify({sid:'fixture-ui'}));
      }
    });
  });
  await page.addInitScript(() => localStorage.setItem('vahanUiAccessToken', 'fixture-token'));
  const rows = Array.from({length: 105}, (_, i) => ({id: String(i), state: i < 100 ? 'ASSAM' : 'Andaman & Nicobar Island',
    rto: i < 100 ? 'UDALGURI' : 'Port Blair DTO', rto_code: i < 100 ? 'AS27' : 'AN1',
    maker: i === 0 ? 'OLA ELECTRIC TECHNOLOGIES PVT LTD' : `MANUFACTURER ${String(i).padStart(3, '0')} LTD`,
    months: [0,1,2,3,4,5,6,7,8,9,null,null]}));
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let body = {};
    if (url.pathname === '/api/annual-reports/export') {
      exportRequests.push(Object.fromEntries(url.searchParams));
      const filename = url.searchParams.get('rto') ?
        'Maker Month Wise Data of Port Blair DTO - AN1, Andaman & Nicobar Island (2026).xlsx' :
        'Maker Month Wise Data of All RTOs, All States (2026).xlsx';
      return route.fulfill({status:200, contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        body:Buffer.from('workbook-download-fixture'),headers:{'Content-Disposition':`attachment; filename*=UTF-8''${encodeURIComponent(filename)}`,
          'access-control-allow-origin':corsOrigin,'access-control-allow-credentials':'true','access-control-expose-headers':'Content-Disposition'}});
    }
    if (url.pathname === '/api/annual-reports/history') historyRequests++;
    if (url.pathname === '/api/auth/status') body = {configured: true};
    else if (url.pathname === '/api/auth/me') body = {username:'shared-reader', role:'admin'};
    else if (url.pathname === '/api/auth/activity') body = {accessToken:'fixture-token'};
    else if (url.pathname === '/api/user-state') body={vahanRunSettingsV1:{year:2024,workerCount:5}};
    else if (['/api/runners','/api/filter-profiles','/api/run-schedules'].includes(url.pathname)) body = [];
    else if (url.pathname === '/api/health') body = {status:'ok'};
    else if (url.pathname === '/api/jobs/reports/sessions' || url.pathname === '/api/files') body = [];
    else if (url.pathname === '/api/annual-reports') {
      const year = Number(url.searchParams.get('year'));
      const filtered = (year === 2027 ? [{...rows[0], maker:'ATHER ENERGY LTD', months:[12,11,10,9,8,7,6,5,4,3,2,1]}] : rows)
        .filter(row => row.state.toLowerCase().includes((url.searchParams.get('state') || '').toLowerCase()) &&
          `${row.rto} ${row.rto_code}`.toLowerCase().includes((url.searchParams.get('rto') || '').toLowerCase()));
      const offset = Number(url.searchParams.get('offset'));
      body = {year, datasetId:'fixture', datasets:[{id:'fixture',label:'Two Wheeler · Electric'},
          {id:'petrol',label:'Two Wheeler · Petrol'}],
        years:[2026,2027], states:['ASSAM','Andaman & Nicobar Island'], rtos:['UDALGURI AS27','Port Blair DTO AN1'],
        rows:filtered.slice(offset,offset + 100), lastSaved, coverage:year === 2026 ? [1,2,3,4,5,6,7,8,9,10] : [1,2,3,4,5,6,7,8,9,10,11,12],
        summary:{rows:filtered.length,makers:filtered.length,offices:2,updatedAt:'2026-10-02T09:12:13Z'}};
    } else if (url.pathname === '/api/annual-reports/history') body = {total:1, rows:[{
      source_key:'file:fixture',file_id:'fixture',name:'manufacturer.xlsx',status:'added',states:['ASSAM'],rtos:['UDALGURI - AS27'],
      imported_at:'2026-10-02T09:12:13Z',observed_at:'2026-10-02T08:12:13Z',details:{newRows:3,newCells:30,duplicates:0,conflicts:0}}]};
    const responseBody = JSON.stringify(body);
    const watched = watchReads && url.pathname === '/api/annual-reports';
    if (watched) {activeReads++; peakReads = Math.max(peakReads, activeReads);}
    try {
      if (url.pathname === '/api/annual-reports' && nextReadDelayMs) {
        const wait = nextReadDelayMs; nextReadDelayMs = 0;
        await new Promise(resolve => setTimeout(resolve, wait));
      }
      await route.fulfill({status:200, contentType:'application/json', body:responseBody, headers:{'access-control-allow-origin':corsOrigin,'access-control-allow-credentials':'true'}});
    } finally {if (watched) activeReads--;}
  });
  await page.goto(process.env.ANNUAL_UI_URL || 'http://127.0.0.1:5174/#reports');
  await page.getByLabel('Year',{exact:true}).waitFor();
  await page.getByRole('rowheader', {name:'OLA ELECTRIC TECHNOLOGIES PVT LTD', exact:true}).waitFor();
  assert.equal(await page.getByLabel('Year',{exact:true}).inputValue(),String(new Date().getFullYear()),'reports default to the current year even when crawl settings use a historical year');
  await page.getByRole('rowheader', {name:'OLA ELECTRIC TECHNOLOGIES PVT LTD', exact:true}).waitFor();
  assert.deepEqual(await page.getByLabel('Report filters',{exact:true}).locator('option').allTextContents(),
    ['Two Wheeler · Electric','Two Wheeler · Petrol']);
  assert.ok(await page.getByRole('heading',{name:'Exported Reports',exact:true}).isVisible());
  assert.equal(await page.locator('.annual-table thead th').count(),17);
  assert.equal(await page.locator('.annual-table thead th.annual-month').count(),12);
  assert.equal(await page.locator('.annual-table tbody tr').count(),100);
  assert.equal(await page.locator('.annual-table tbody tr').first().locator('td').nth(4).innerText(),'0');
  assert.equal(await page.locator('.annual-table tbody tr').first().locator('td').last().innerText(),'—');
  assert.ok(reportSocket,'authenticated fixture socket connected');
  rows[0].months[10]=7;
  lastSaved={status:'added',states:['ASSAM'],rtos:['UDALGURI - AS27'],savedAt:'2026-10-02T09:12:14Z',
    manufacturerRows:1,newRows:0,newMonthValues:1,alreadySavedMonthValues:10,conflicts:0};
  reportSocket.send('42/ui,'+JSON.stringify(['reports:updated',lastSaved]));
  await page.waitForFunction(()=>document.querySelector('.annual-table tbody tr')?.querySelectorAll('td')[14]?.textContent==='7',{},{timeout:2_000});
  await page.getByRole('status').filter({hasText:'Saved to main table'}).waitFor();
  assert.match(await page.locator('.annual-save-confirmation').innerText(),/1 new month values/);
  lastSaved={...lastSaved,status:'unchanged',newMonthValues:0,alreadySavedMonthValues:11,savedAt:'2026-10-02T09:12:15Z'};
  reportSocket.send('42/ui,'+JSON.stringify(['reports:updated',lastSaved]));
  await page.getByRole('status').filter({hasText:'Already saved in main table'}).waitFor({timeout:2_000});
  assert.equal(await page.locator('.annual-table tbody tr').count(),100,'repeat filter does not duplicate rows');
  // A slow table read must finish even while ten workers keep committing data.
  // The next read must then include changes received during that slow read.
  watchReads = true; nextReadDelayMs = 5_600;
  rows[0].months[10] = 8;
  reportSocket.send('42/ui,'+JSON.stringify(['reports:updated',lastSaved]));
  const burst = setInterval(() => {
    rows[0].months[10] = 9;
    reportSocket.send('42/ui,'+JSON.stringify(['reports:updated',lastSaved]));
  }, 100);
  try {
    await page.waitForFunction(()=>document.querySelector('.annual-table tbody tr')?.querySelectorAll('td')[14]?.textContent==='9',{},{timeout:8_500});
  } finally {clearInterval(burst); watchReads = false;}
  assert.equal(failedReads,0,'worker updates must not cancel an in-flight table read');
  assert.equal(peakReads,1,'worker updates must use one table read at a time');
  reportSocket.send('42/ui,'+JSON.stringify(['captcha:required',{
    jobId:'captcha-fixture',captchaId:'challenge-fixture',imageDataUrl:'data:image/png;base64,iVBORw0KGgo=',
  }]));
  await page.waitForTimeout(100);
  assert.equal(await page.locator('#captcha-assistance').count(),0,'Exported Reports never shows CAPTCHA');
  assert.equal(await page.getByRole('link',{name:'Create Report',exact:true}).count(),0);
  const tableBounds = await page.locator('.annual-table-scroll').boundingBox();
  assert.ok(tableBounds.x >= 0 && tableBounds.x + tableBounds.width <= 1920,
    'the report table stays within the page gutters');
  const desktop = await page.locator('.annual-table-scroll').evaluate(el => ({width:el.clientWidth, scroll:el.scrollWidth}));
  assert.ok(desktop.scroll <= desktop.width + 1, 'all 12 months fit on the 1920px desktop viewport');
  await page.screenshot({path:testArtifactPath('vahan-annual-desktop.png'), fullPage:true});
  await page.getByRole('button',{name:'Next →',exact:true}).click();
  await page.getByRole('rowheader',{name:'MANUFACTURER 100 LTD',exact:true}).waitFor();
  assert.equal(await page.locator('.annual-table tbody tr').count(),5);
  assert.equal(await page.locator('.annual-table tbody tr td').first().innerText(),'101');
  await page.getByLabel('Search State').fill('andaman');
  assert.equal(await page.locator('.annual-export-button').count(),0,'State input immediately hides Excel export');
  await page.waitForFunction(() => document.querySelector('.annual-table tbody td')?.textContent === '1');
  assert.equal(await page.locator('.annual-table tbody tr').count(),5);
  assert.equal(await page.locator('.annual-export-button').count(),0,'State-only filtering hides Excel export');
  await page.getByLabel('Search RTO / code').fill('AN1');
  await page.waitForTimeout(350);
  assert.equal(await page.locator('.annual-table tbody tr').count(),5);
  assert.equal(await page.locator('.annual-export-button').count(),0,'State and RTO filtering hides Excel export');
  await page.getByLabel('Search State').fill('');
  await page.waitForTimeout(350);
  assert.equal(await page.locator('.annual-table tbody tr').count(),5);
  assert.equal(await page.locator('.annual-export-button').count(),0,'RTO-only filtering hides Excel export');
  assert.equal(exportRequests.length,0,'filtering sends no Excel download requests');
  await page.getByRole('button',{name:'Clear',exact:true}).click();
  await page.getByRole('rowheader',{name:'OLA ELECTRIC TECHNOLOGIES PVT LTD',exact:true}).waitFor();
  page.once('dialog',async dialog=>{assert.match(dialog.message(),/Export all 105 manufacturer rows for 2026/);await dialog.dismiss();});
  await page.getByRole('button',{name:'Export all to Excel',exact:true}).click();
  assert.equal(exportRequests.length,0,'cancelled full export sends no download request');
  page.once('dialog',dialog=>dialog.accept());
  const allDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export all to Excel',exact:true}).click();
  const full=await allDownload;
  assert.equal(full.suggestedFilename(),'Maker Month Wise Data of All RTOs, All States (2026).xlsx');
  assert.equal(exportRequests[0].state,'');
  assert.equal(exportRequests[0].rto,'');
  assert.equal(exportRequests[0].year,'2026');
  assert.equal(exportRequests[0].dataset,'fixture');
  assert.equal(exportRequests[0].confirmAll,'true');
  assert.ok(!('offset' in exportRequests[0]) && !('limit' in exportRequests[0]));
  await full.delete();
  await page.getByLabel('Year',{exact:true}).selectOption('2027');
  await page.getByRole('rowheader',{name:'ATHER ENERGY LTD',exact:true}).waitFor();
  assert.equal(await page.locator('.annual-table .annual-month').last().innerText(),'DEC’27');
  assert.equal(await page.locator('.annual-table tbody tr').count(),1);
  assert.equal(await page.locator('.annual-table tbody tr td').last().innerText(),'1');
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'page does not overflow on mobile');
  await page.locator('.annual-table-scroll').evaluate(el => {el.scrollLeft = el.scrollWidth;});
  assert.ok(await page.locator('.annual-table-scroll').evaluate(el => el.scrollLeft > 0));
  await page.screenshot({path:testArtifactPath('vahan-annual-mobile.png'),fullPage:true});
  assert.equal(await page.getByRole('button',{name:'Run history',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Files',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Download',exact:true}).count(),0);
  assert.equal(await page.getByRole('heading',{name:'Update history',exact:true}).count(),0);
  assert.equal(historyRequests,0,'the removed history panel makes no SQL history requests');
  assert.deepEqual(errors,[]);
  console.log('Annual reports UI: live committed updates, slow reads under continuous worker updates, removed workspace absent, search, pagination, exports and responsive layout passed.');
} finally { await browser.close(); }
