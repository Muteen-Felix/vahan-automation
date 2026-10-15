import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
import {testArtifactPath} from './test-artifact-path.mjs';
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];let changed=[],resets=[],timeZoneChanges=[],role='admin';
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>localStorage.setItem('vahanUiAccessToken','fixture'));
 await page.route('https://fonts.googleapis.com/**',r=>r.abort());await page.route('https://fonts.gstatic.com/**',r=>r.abort());
 await page.routeWebSocket('**/socket.io/**',s=>{s.send('0'+JSON.stringify({sid:'fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));s.onMessage(m=>{if(String(m).startsWith('40/ui,'))s.send('40/ui,'+JSON.stringify({sid:'ui'}));});});
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;let body=[];
  if(path==='/api/auth/status')body={configured:true};
  else if(path==='/api/auth/me')body={username:role==='admin'?'admin-fixture':'member-fixture',role};
  else if(path==='/api/auth/activity')body={accessToken:'fixture'};
  else if(path==='/api/user-state')body={};
  else if(path==='/api/annual-reports/run-history')body={runs:[{sessionId:'timezone-fixture',filterName:'Timezone fixture',runNumber:1,totalRuns:1,
   startedAt:'2026-01-01T18:00:00.000Z',status:'COMPLETED',processed:1,totalCases:1,withData:1,noData:0,failed:0,
   pending:0,running:0,lastActivityAt:null,finishedAt:'2026-01-01T18:00:00.000Z'}],total:1};
  else if(path==='/api/ui-health/status')body={blocked:false,latestPreflight:null};
  else if(path==='/api/users')body=[{username:'admin-fixture',role:'admin',active:true},{username:'member-fixture',role:'user',active:true}];
  else if(path==='/api/auth/password') {
   const payload=req.postDataJSON();changed.push(payload);
   if(payload.currentPassword==='Wrong password fixture')return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'The current password is incorrect.'})});
   body={ok:true};
  }else if(path==='/api/run-schedules/time-zone') {
   timeZoneChanges.push(req.postDataJSON());body=[];
  }else if(path==='/api/users/member-fixture/password'){resets.push(req.postDataJSON());body={ok:true};}
  await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto((process.env.ACCOUNT_UI_URL||'http://127.0.0.1:5189/')+'#settings');
 await page.getByRole('heading',{name:'Automatic report schedule',exact:true}).waitFor();
 assert.equal(await page.getByRole('heading',{name:'User accounts',exact:true}).count(),0);
 assert.equal(await page.getByRole('button',{name:'Log out',exact:true}).count(),0);
 await page.getByRole('button',{name:'Account',exact:true}).click();const dialog=page.getByRole('dialog',{name:'Account settings'});
 await dialog.locator('.account-identity strong').filter({hasText:'admin-fixture'}).waitFor();assert.equal(await dialog.locator('.account-identity strong').innerText(),'admin-fixture');
 assert.equal(await dialog.locator('.account-timezone-hint').count(),0,'Display time zone has no explanatory line under the selector');
 await dialog.getByLabel('Display time zone',{exact:true}).selectOption('Asia/Kolkata');
 await dialog.getByRole('status').getByText(/Times across the interface now use India time \(UTC\+05:30\)/).waitFor();
 assert.deepEqual(timeZoneChanges,[{timeZone:'Asia/Kolkata'}]);
 await page.getByRole('button',{name:'Close account settings'}).click();
 await page.getByRole('link',{name:'Run History',exact:true}).click();
 await page.getByText(/One row per run, newest first · India time \(UTC\+05:30\)/).waitFor();
 await page.locator('.run-history-times time').first().getByText('01/01/2026, 23:30:00',{exact:true}).waitFor();
 await page.getByRole('link',{name:'Settings',exact:true}).click();
 await page.getByRole('button',{name:'Account',exact:true}).click();
 await dialog.getByLabel('Current password',{exact:true}).fill('Wrong password fixture');
 await dialog.locator('.account-password-form').getByLabel('New password',{exact:true}).fill('New password fixture');
 await dialog.locator('.account-password-form').getByLabel('Confirm new password',{exact:true}).fill('Mismatch password fixture');
 await dialog.getByRole('button',{name:'Update password'}).click();await dialog.getByRole('alert').getByText('The new passwords do not match.').waitFor();assert.equal(changed.length,0);
 await dialog.locator('.account-password-form').getByLabel('Confirm new password',{exact:true}).fill('New password fixture');
 await dialog.getByRole('button',{name:'Update password'}).click();await dialog.getByRole('alert').getByText('The current password is incorrect.').waitFor();
 await dialog.getByLabel('Current password',{exact:true}).fill('Current password fixture');
 await dialog.getByRole('button',{name:'Update password'}).click();await dialog.getByRole('status').getByText(/Password changed/).waitFor();
 assert.equal(await dialog.locator('.account-password-form').getByLabel('New password',{exact:true}).inputValue(),'');
 assert.equal(changed.length,2);
 await dialog.getByRole('tab',{name:'Manage user accounts',exact:true}).click();await dialog.getByText('member-fixture',{exact:true}).waitFor();
 assert.equal(await dialog.getByRole('button',{name:'Reset password',exact:true}).count(),1,'Admin must use verified current-password flow for own account');
 await dialog.getByRole('button',{name:'Reset password',exact:true}).click();
 await page.getByRole('dialog',{name:'Reset password',exact:true}).getByLabel('New password',{exact:true}).fill('Admin reset fixture password');await page.getByRole('dialog',{name:'Reset password',exact:true}).getByLabel('Confirm new password',{exact:true}).fill('Admin reset fixture password');
 await page.getByRole('dialog',{name:'Reset password',exact:true}).getByRole('button',{name:'Save new password'}).click();await dialog.getByRole('status').getByText(/Password reset for member-fixture/).waitFor();
 assert.deepEqual(resets,[{password:'Admin reset fixture password'}]);
 await dialog.screenshot({path:testArtifactPath('account-settings-desktop.png')});
 await page.getByRole('button',{name:'Close account settings'}).click();
 await page.locator('.settings-page').screenshot({path:testArtifactPath('settings-redesign-desktop.png')});
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Account',exact:true}).click();
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 assert.ok(await dialog.evaluate(d=>d.scrollWidth<=d.clientWidth+1),'Account modal fits mobile');
 await dialog.screenshot({path:testArtifactPath('account-settings-mobile.png')});
 await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
 role='user';await page.getByRole('button',{name:'Account',exact:true}).click();await dialog.getByText('Workspace member',{exact:true}).waitFor();
 assert.equal(await dialog.locator('.account-timezone-hint').count(),0,'Members also see no explanatory line under the selector');
 await dialog.getByLabel('Display time zone',{exact:true}).selectOption('Asia/Ho_Chi_Minh');
 await dialog.getByRole('status').getByText(/Times across the interface now use Vietnam time/).waitFor();
 assert.deepEqual(timeZoneChanges,[{timeZone:'Asia/Kolkata'}],'Members change display time without changing administrator schedules');
 assert.equal(await page.evaluate(()=>localStorage.getItem('vahanScheduleTimeZoneV1:member-fixture')),'Asia/Ho_Chi_Minh');
 assert.equal(await dialog.getByText('Manage user accounts',{exact:true}).count(),0);
 assert.deepEqual(errors,[]);
 console.log('Account UI: hidden account controls, own password mismatch/error/success, admin reset, self-reset restriction, Escape and mobile layout passed.');
}finally{await browser.close();}
