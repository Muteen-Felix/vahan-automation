import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
const origin = process.env.PERMISSIONS_UI_URL || 'http://127.0.0.1:5193/';
try {
  for (const role of ['user','admin']) {
    const page = await browser.newPage();
    const errors=[], privateRequests=[], roleChanges=[], exports=[];
    let delegatedRole='user';
    page.on('pageerror', error=>errors.push(error.message));
    await page.addInitScript(()=>localStorage.setItem('vahanUiAccessToken','fixture'));
    await page.route('https://fonts.googleapis.com/**',r=>r.abort());
    await page.route('https://fonts.gstatic.com/**',r=>r.abort());
    await page.routeWebSocket('**/socket.io/**',s=>{
      assert.equal(role,'admin','Members must not connect to administrative socket');
      s.send('0'+JSON.stringify({sid:'fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));
      s.onMessage(m=>{if(String(m).startsWith('40/ui,'))s.send('40/ui,'+JSON.stringify({sid:'ui'}));});
    });
    await page.route('**/api/**', async route=>{
      const req=route.request(), path=new URL(req.url()).pathname;
      if (/^\/api\/(filter-profiles|run-schedules|runners|ui-health|users)/.test(path)) privateRequests.push(path);
      let body=[];
      if(path==='/api/auth/status')body={configured:true};
      else if(path==='/api/auth/me')body={username:'admin-fixture',role};
      else if(path==='/api/auth/activity')body={};
      else if(path==='/api/user-state')body={};
      else if(path==='/api/network/status')body={online:true};
      else if(path==='/api/ui-health/status')body={blocked:false,latestPreflight:null};
      else if(path==='/api/users')body=[{username:'admin-fixture',role:'admin',active:true},{username:'delegate',role:delegatedRole,active:true}];
      else if(path==='/api/users/delegate' && req.method()==='PATCH'){
        const update=req.postDataJSON();roleChanges.push(update);delegatedRole=update.role;body={ok:true};
      } else if(path==='/api/annual-reports/export') {
        exports.push(req.url());
        return route.fulfill({contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers:{'Content-Disposition':"attachment; filename*=UTF-8''fixture.xlsx"},body:'fixture workbook transport'});
      } else if(path==='/api/annual-reports')body={year:2026,datasetId:'fixture',datasets:[{id:'fixture',label:'Fixture report'}],years:[2026],states:['State A'],rtos:['Office A'],rows:[{id:'1',state:'State A',rto:'Office A',rto_code:'A1',maker:'Fixture Maker',months:Array(12).fill(1)}],coverage:[1],summary:{rows:1,makers:1,offices:1,updatedAt:null}};
      await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
    });
    await page.goto(origin);
    const nav=page.getByRole('navigation',{name:'Main navigation'});
    await nav.waitFor();
    assert.deepEqual(await nav.locator('a').allTextContents(),role==='user'?['Exported Reports']:['Exported Reports','Filters','Settings']);
    if(role==='user') {
      for(const target of ['#filters','#settings','#settings-ui-health','#health','#configure?scheduled=fixture','filters','settings','#unknown']) {
        await page.goto(origin+target);
        await page.getByRole('heading',{name:'Bạn không có quyền truy cập trang này.',exact:true}).waitFor();
        assert.equal(await page.locator('.settings-page, .filter-profiles').count(),0);
      }
      await page.goto(origin+'#reports');await nav.waitFor();
      await page.getByRole('rowheader',{name:'Fixture Maker',exact:true}).waitFor();
      page.once('dialog',dialog=>dialog.accept());
      const download=page.waitForEvent('download');
      await page.getByRole('button',{name:'Export all to Excel',exact:true}).click();
      assert.match((await download).suggestedFilename(),/\.xlsx$/);
      assert.equal(exports.length,1,'Members can export reports');
      await page.getByRole('button',{name:'Account',exact:true}).click();
      await page.getByText('Workspace member',{exact:true}).waitFor();
      assert.equal(await page.getByText('Manage user accounts',{exact:true}).count(),0);
      assert.equal(await page.getByRole('button',{name:'Log out',exact:true}).count(),1);
      assert.deepEqual(privateRequests,[],'Members must not load profiles, schedules, workers, health or accounts');
    } else {
      await nav.getByRole('link',{name:'Settings',exact:true}).click();
      await page.getByRole('heading',{name:'Automatic report schedule',exact:true}).waitFor();
      await page.getByRole('button',{name:'Account',exact:true}).click();
      await page.getByText('Manage user accounts',{exact:true}).click();
      await page.getByRole('button',{name:'Grant admin',exact:true}).click();
      await page.getByRole('button',{name:'Revoke admin',exact:true}).waitFor();
      await page.getByRole('button',{name:'Revoke admin',exact:true}).click();
      await page.getByRole('button',{name:'Grant admin',exact:true}).waitFor();
      assert.deepEqual(roleChanges,[{role:'admin'},{role:'user'}]);
    }
    assert.deepEqual(errors,[]);
    await page.close();
  }
  console.log('Permissions UI passed: member reports-only navigation and direct-route denial, no private requests/socket, admin schedules, grant/revoke role.');
} finally {await browser.close();}
