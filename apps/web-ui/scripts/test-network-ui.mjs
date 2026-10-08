import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];let online=true,unreachable=false,socket;
 page.on('pageerror',e=>errors.push(e.message));await page.addInitScript(()=>localStorage.setItem('vahanUiAccessToken','fixture'));
 await page.route('https://fonts.googleapis.com/**',r=>r.abort());await page.route('https://fonts.gstatic.com/**',r=>r.abort());
 await page.routeWebSocket('**/socket.io/**',s=>{socket=s;s.send('0'+JSON.stringify({sid:'fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));s.onMessage(m=>{if(String(m).startsWith('40/ui,'))s.send('40/ui,'+JSON.stringify({sid:'ui'}));});});
 await page.route('**/api/**',async r=>{
  const p=new URL(r.request().url()).pathname;let body=[];
  if(p==='/api/auth/status')body={configured:true};else if(p==='/api/auth/me')body={username:'fixture',role:'admin'};
  else if(p==='/api/auth/activity')body={accessToken:'fixture'};else if(p==='/api/user-state')body={};
  else if(p==='/api/ui-health/status')body={blocked:false};
  else if(p==='/api/network/status'){if(unreachable)return r.abort('failed');body={online,checkedAt:new Date().toISOString()};}
  else if(p==='/api/annual-reports')body={year:2026,datasetId:'fixture',datasets:[],years:[2026],states:[],rtos:[],rows:[],coverage:[],summary:{rows:0,makers:0,offices:0,updatedAt:null}};
  await r.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto(process.env.NETWORK_UI_URL||'http://127.0.0.1:5189/');await page.getByRole('link',{name:'Settings',exact:true}).waitFor();
 assert.equal(await page.locator('.network-notice').count(),0);
 online=false;socket.send('42/ui,'+JSON.stringify(['network:status',{online:false}]));
 await page.getByRole('alert').getByText('Network unavailable · reports paused',{exact:true}).waitFor();
 await page.getByRole('link',{name:'Settings',exact:true}).click();await page.getByRole('alert').getByText('Network unavailable · reports paused',{exact:true}).waitFor();
 online=true;socket.send('42/ui,'+JSON.stringify(['network:status',{online:true}]));await page.locator('.network-notice').waitFor({state:'detached'});
 await page.evaluate(()=>{Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>false});dispatchEvent(new Event('offline'));});
 await page.getByRole('alert').getByText('Your browser is offline',{exact:true}).waitFor();
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.evaluate(()=>{Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>true});dispatchEvent(new Event('online'));});await page.locator('.network-notice').waitFor({state:'detached'});
 unreachable=true;await page.getByRole('alert').getByText('Connection to the system was lost',{exact:true}).waitFor();
 unreachable=false;await page.locator('.network-notice').waitFor({state:'detached'});
 assert.deepEqual(errors,[]);console.log('Network UI: main-page outage banner, cross-page visibility, browser offline, backend failure, automatic reconnect and mobile fit passed.');
}finally{await browser.close();}
