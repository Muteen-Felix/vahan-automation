import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];let socket,calls=0,complete=false;
 await page.route('https://fonts.googleapis.com/**',r=>r.abort());await page.route('https://fonts.gstatic.com/**',r=>r.abort());
 await page.addInitScript(()=>localStorage.setItem('vahanUiAccessToken','fixture-token'));page.on('pageerror',e=>errors.push(e.message));
 await page.routeWebSocket('**/socket.io/**',s=>{socket=s;s.send('0'+JSON.stringify({sid:'fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));s.onMessage(m=>{if(String(m).startsWith('40/ui,'))s.send('40/ui,'+JSON.stringify({sid:'ui'}));});});
 const daily=(all=false)=>({date:'2026-10-07',updatedCases:all?2:1,totalCases:2,remainingCases:all?0:1,percent:all?100:50,state:all?'complete':'partial',activeCases:0,failedCases:0,reviewCases:0,lastSavedAt:'2026-10-07T08:00:00Z',lastSavedCase:'Office 1',firstNotUpdated:all?null:{name:'Office 2',state:'State A',rto:'Office 2'}});
 await page.route('**/api/**',async r=>{
  const url=new URL(r.request().url()),p=url.pathname;let body={};
  if(p==='/api/auth/status')body={configured:true};else if(p==='/api/auth/me')body={username:'fixture',role:'user'};else if(p==='/api/auth/renew')body={accessToken:'fixture-token'};
  else if(['/api/runners','/api/filter-profiles','/api/jobs','/api/maker-updates'].includes(p))body=[];
  else if(p==='/api/worker-pool')body={enabled:true,desiredCount:5,runningCount:5,phase:'ready',workers:[]};
  else if(p==='/api/annual-reports')body={year:Number(url.searchParams.get('year')),datasetId:'fixture',datasets:[],years:[2026],states:[],rtos:[],rows:[],summary:{rows:0,makers:0,offices:0,updatedAt:null},coverage:[],lastSaved:null};
  else if(p==='/api/annual-reports/update-status'){
   calls++;const from=Number(url.searchParams.get('fromYear'));
   body={coverageBasis:'Recorded case plans',datasets:from<=2023?[{datasetId:'fixture',label:'Two Wheeler · Electric',year:2023,latest:daily(complete),days:[daily(complete),{...daily(true),date:'2026-10-06'}]}]:[]};
  }
  await r.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto(process.env.HISTORY_UI_URL||'http://127.0.0.1:5184/#reports');await page.getByRole('heading',{name:'Exported Reports',exact:true}).waitFor();
 assert.equal(calls,0,'history reads only after opening');
 await page.getByRole('button',{name:'Update history',exact:true}).click();const dialog=page.getByRole('dialog',{name:'Dataset update status'});
 await dialog.getByText('Partially refreshed',{exact:true}).first().waitFor();assert.equal(await dialog.locator('progress').first().getAttribute('value'),'1');
 assert.ok(await dialog.getByText('1 cases not refreshed on this day',{exact:true}).isVisible());assert.ok(await dialog.getByText('State A · Office 2',{exact:true}).isVisible());
 await dialog.getByText('2 days',{exact:true}).click();assert.ok(await dialog.getByText('06/10/2026',{exact:true}).isVisible());
 await page.screenshot({path:'/tmp/vahan-update-history-desktop.png'});
 complete=true;socket.send('42/ui,'+JSON.stringify(['reports:updated',{}]));
 await dialog.getByText('0 cases not refreshed on this day',{exact:true}).waitFor({timeout:18000});
 assert.equal(await dialog.locator('progress').first().getAttribute('value'),'2');assert.equal(await dialog.getByText('First case not refreshed',{exact:true}).count(),0);
 await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Update history',exact:true}).click();await dialog.waitFor();
 const box=await dialog.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=390);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:'/tmp/vahan-update-history-mobile.png'});
 await dialog.getByLabel('Update history from year',{exact:true}).fill('2024');await dialog.getByText('No update records in this year range.',{exact:true}).waitFor();
 await dialog.getByRole('button',{name:'Close update history'}).click();await dialog.waitFor({state:'hidden'});assert.deepEqual(errors,[]);
 console.log('Update history UI: lazy reads, partial day, missing case, daily history, live completion, year range and mobile passed.');
}finally{await browser.close();}
