import assert from 'node:assert/strict';
import {testArtifactPath} from './test-artifact-path.mjs';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[],manualWrites=[];
  let logoutFails=true,logoutCalls=0;
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>localStorage.setItem('vahanUiSessionMarker','fixture'));
  await page.route('https://fonts.googleapis.com/**',r=>r.abort());
  await page.route('https://fonts.gstatic.com/**',r=>r.abort());
  await page.routeWebSocket('**/socket.io/**',socket=>{
    socket.send('0'+JSON.stringify({sid:'fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));
    socket.onMessage(message=>{if(String(message).startsWith('40/ui,'))socket.send('40/ui,'+JSON.stringify({sid:'ui'}));});
  });
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(path.startsWith('/api/batch-queue/')||path==='/api/jobs'&&request.method()==='POST')manualWrites.push(path);
    let body=[];
    if(path==='/api/auth/status')body={configured:true};
    else if(path==='/api/auth/me')body={username:'fixture',role:'admin'};
    else if(path==='/api/auth/activity')body={accessToken:'fixture'};
    else if(path==='/api/user-state')body={};
    else if(path==='/api/ui-health/status')body={blocked:false,latestPreflight:null};
    else if(path==='/api/annual-reports')body={year:2026,datasetId:'fixture',datasets:[],years:[2026],states:[],rtos:[],rows:[],coverage:[],
      summary:{rows:0,makers:0,offices:0,updatedAt:null}};
    else if(path==='/api/auth/logout'){
      logoutCalls++;
      if(logoutFails)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Fixture logout failure'})});
      body={ok:true};
    }
    await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
  });
  const origin=process.env.NAV_UI_URL||'http://127.0.0.1:5186/';
  await page.goto(origin);
  const nav=page.getByRole('navigation',{name:'Main navigation'});
  await nav.getByRole('link',{name:'Settings',exact:true}).waitFor();
  assert.deepEqual(await nav.locator('a').allTextContents(),['Exported Reports','Filters','Settings']);
  assert.ok(page.url().endsWith('#reports'),'Default page is Exported Reports');
  assert.equal(await page.getByRole('button',{name:'Log out',exact:true}).count(),0);
  assert.equal(await page.getByRole('link',{name:/Create Report/}).count(),0);
  for(const width of [1440,1024,768,390,320]){
    await page.setViewportSize({width,height:1000});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`Header and reports fit ${width}px`);
    const links=await nav.locator('a').all();
    const rects=await Promise.all(links.map(link=>link.boundingBox()));
    assert.ok(rects[0].x<rects[1].x&&rects[1].x<rects[2].x,'Navigation keeps its order');
    if(width===1440||width===390)await page.locator('.site-header').screenshot({path:testArtifactPath(`vahan-header-new-${width}.png`)});
  }
  await nav.getByRole('link',{name:'Settings',exact:true}).click();
  await page.getByRole('heading',{name:'Automatic report schedule',exact:true}).waitFor();
  await page.getByRole('button',{name:'Account',exact:true}).click();
  const logout=page.getByRole('button',{name:'Log out',exact:true});
  assert.equal(await logout.evaluate(node=>Boolean(node.closest('#settings .settings-intro'))),true,'Regular users can log out in Settings');
  assert.equal(await page.locator('.site-header button').count(),0);
  await logout.click();await page.getByRole('alert').filter({hasText:'Fixture logout failure'}).waitFor();
  await page.getByRole('button',{name:'Account',exact:true}).click();
  assert.equal(await logout.isEnabled(),true,'Failed logout is retryable');
  assert.equal(await page.evaluate(()=>localStorage.getItem('vahanUiSessionMarker')),'fixture','Failed logout preserves auth');
  await page.getByRole('button',{name:'Close account settings',exact:true}).click();
  for(const hash of ['#configure','#configure?scheduled=old-schedule']){
    await page.goto(origin+hash);
    await nav.waitFor();
    const expected='Settings';
    await page.waitForFunction(label=>document.querySelector('.main-nav [aria-current="page"]')?.textContent===label,expected);
    assert.equal(await page.getByRole('heading',{name:'Create Report',exact:true}).count(),0);
    assert.equal(await page.getByRole('link',{name:'View in Create Report',exact:true}).count(),0);
  }
  await nav.getByRole('link',{name:'Filters',exact:true}).click();
  await page.getByRole('heading',{name:'Filters',exact:true}).waitFor();
  await nav.getByRole('link',{name:'Settings',exact:true}).click();
  await page.getByRole('button',{name:'Account',exact:true}).click();
  await logout.waitFor();logoutFails=false;await logout.click();
  await page.getByRole('heading',{name:'Welcome back',exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>localStorage.getItem('vahanUiSessionMarker')),null);
  assert.equal(logoutCalls,2);assert.deepEqual(manualWrites,[]);assert.deepEqual(errors,[]);
  console.log('Navigation: ordered tabs, default reports, retired routes, Settings-only logout, retry/sign-out and 320–1440px layouts passed.');
} finally {await browser.close();}
