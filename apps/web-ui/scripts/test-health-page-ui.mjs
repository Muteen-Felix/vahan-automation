import assert from 'node:assert/strict';
import {testArtifactPath} from './test-artifact-path.mjs';
import {chromium, webkit} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser=await (process.env.HEALTH_UI_BROWSER==='webkit'?webkit:chromium).launch({headless:true});
try {
 const url=(process.env.HEALTH_UI_URL||'http://127.0.0.1:5184/').split('#')[0];
 const page=await browser.newPage({viewport:{width:1440,height:1000}});let blocked=false,uiSocket;
 const extraHealthRequests=[];
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:new URL(url).origin});
 await page.addInitScript(()=>localStorage.setItem('vahanUiAccessToken','fixture-token'));
 await page.route('https://fonts.googleapis.com/**',r=>r.abort());await page.route('https://fonts.gstatic.com/**',r=>r.abort());
 await page.routeWebSocket('**/socket.io/**',s=>{uiSocket=s;s.send('0'+JSON.stringify({sid:'fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));s.onMessage(m=>{if(String(m).startsWith('40/ui,'))s.send('40/ui,'+JSON.stringify({sid:'ui'}));});});
 const report={code:'UI_CONTRACT_MISMATCH',title:'Maker control is missing after a website change',target:'makers',selector:'#vehicleMaker',expected:{tag:'select',multiple:true},actual:{found:false,count:0,diagnostic:'unbroken-diagnostic-'.repeat(100)}};
 const failed=number=>({runnerId:`playwright-${number}`,checkId:`failed-${number}`,checkedAt:'2026-10-07T15:00:00Z',status:'UI_DRIFT',allowed:false,attempts:2,reports:[report]});
 const profile={id:'11111111-1111-4111-8111-111111111111',name:'Electric two-wheelers 2025',revision:2,definition:{report:{year:2025},fields:{},rules:[],maxCases:3000}};
 const schedule={id:'fixture-schedule',profileId:profile.id,profileName:profile.name,profileRevision:2,year:2025,workerCount:8,
   startsAt:'2026-10-08T11:51:00+07:00',nextRunAt:null,repeat:'once',timeZone:'Asia/Ho_Chi_Minh',enabled:false,
   status:'PAUSED',sessionId:'fixture-session',lastSessionId:'fixture-session',canResume:true,total:1676,done:465,withData:400,noData:65,failed:0,message:'Paused'};
 const sqlState=()=>({revision:2,versionId:'fixture',blocked,runnerErrors:blocked?{'playwright-1':failed(1),'playwright-2':failed(2)}:{},lastCheck:blocked?failed(2):{allowed:true,status:'DATA_CHANGED',repairs:[{field:'states',after:'#newState'}]},latestPreflight:blocked?{id:'gate-failed',status:'BLOCKED',runner_ids:['playwright-1','playwright-2'],created_at:'2026-10-07T15:00:01Z',reports:[failed(1),failed(2)]}:{status:'PASS'}});
 await page.route('**/api/**',async r=>{
  const p=new URL(r.request().url()).pathname;let body={};
  if(p==='/api/auth/status')body={configured:true};else if(p==='/api/auth/me')body={username:'fixture',role:'admin'};else if(p==='/api/auth/renew')body={accessToken:'fixture-token'};
  else if(p==='/api/users')body=[{username:'fixture',role:'admin',active:true}];
  else if(p==='/api/filter-profiles')body=[profile];
  else if(p==='/api/run-schedules')body=[schedule];
  else if(['/api/runners','/api/jobs','/api/maker-updates'].includes(p))body=[];
  else if(p==='/api/worker-pool')body={enabled:true,desiredCount:8,runningCount:8,phase:'ready',workers:[]};
  else if(p==='/api/ui-health/status')body=sqlState();
  else if(['/api/ui-health/schedule','/api/ui-health/run-now','/api/ui-health/reports'].includes(p))extraHealthRequests.push(p);
  await r.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto(url+'#settings');await page.getByRole('heading',{name:'Automatic report schedule',exact:true}).waitFor();
 await page.locator('.run-schedule-card').waitFor();
 await page.getByRole('button',{name:'Account',exact:true}).waitFor();
 assert.equal(await page.getByRole('heading',{name:'User accounts',exact:true}).count(),0);
 const scheduleBounds=()=>page.locator('.automatic-run-settings').evaluate(node=>{const r=node.getBoundingClientRect();return {x:r.x,width:r.width};});
 const healthyBounds=await scheduleBounds();
 assert.equal(await page.getByLabel('Start time',{exact:true}).isVisible(),false,'Existing schedules keep the creation form closed');
 assert.ok((await page.locator('.run-schedule-card').boundingBox()).height<240);
 await page.getByRole('button',{name:'New schedule',exact:true}).click();
 await page.getByLabel('Start time',{exact:true}).fill('11:51');
 await page.getByLabel('Active workers',{exact:true}).selectOption('7');
 assert.equal(await page.getByRole('link',{name:'UI Health' ,exact:true}).count(),0,'UI Health lives inside Settings');
 assert.equal(await page.getByRole('link',{name:'Settings',exact:true}).getAttribute('aria-current'),'page');
 assert.equal(await page.locator('.settings-ui-health').count(),0,'A healthy check does not render any UI Health section');
 assert.equal(await page.getByRole('button',{name:'Copy all errors',exact:true}).count(),0);
 assert.equal(await page.getByLabel('Check again after').count(),0);
 assert.equal(await page.getByRole('button',{name:'Check now',exact:true}).count(),0);
 assert.equal(await page.getByText('Check history and CSV reports',{exact:true}).count(),0);
 blocked=true;uiSocket.send('42/ui,'+JSON.stringify(['ui-health:blocked',sqlState()]));
 await page.locator('.website-alert-table tbody').getByText(report.title,{exact:true}).waitFor();
 assert.deepEqual(await scheduleBounds(),healthyBounds,'An error cannot shrink or move the schedule into another column');
 const layout=async()=>{
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Settings has no horizontal page overflow');
   assert.ok(await page.locator('.website-alert-scroll').evaluate(node=>node.scrollWidth<=node.clientWidth+1),'The error report fits without horizontal scrolling');
   const sections=await page.locator('#settings > :is(.settings-ui-health,.automatic-run-settings,.data-panel)').evaluateAll(nodes=>nodes.map(node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,bottom:r.bottom,width:r.width};}));
   assert.equal(sections.length,2);
   for(const r of sections){assert.ok(Math.abs(r.x-sections[0].x)<1);assert.ok(Math.abs(r.width-sections[0].width)<1);}
   assert.ok(sections[0].bottom<=sections[1].y,'Health and schedule stack in separate rows; accounts stay in their dialog');
 };
 await layout();
 assert.equal(await page.getByLabel('Start time',{exact:true}).inputValue(),'11:51');
 assert.equal(await page.getByLabel('Active workers',{exact:true}).inputValue(),'7','Showing an error preserves the schedule draft');
 assert.equal(await page.locator('.website-alert-table tbody tr').count(),1,'the same SQL error across workers/retries appears once');
 assert.match(await page.locator('.website-alert-table tbody').innerText(),/playwright-1, playwright-2/);
 await page.getByRole('button',{name:'Copy for dev',exact:true}).click();await page.getByRole('button',{name:'Copied',exact:true}).waitFor();
 const copied=JSON.parse(await page.evaluate(()=>navigator.clipboard.readText()));
 assert.equal(copied.alerts[0].code,report.code);assert.deepEqual(copied.alerts[0].workers,['playwright-1','playwright-2']);
 assert.deepEqual(copied.alerts[0].expected,report.expected);assert.deepEqual(copied.alerts[0].actual,report.actual);assert.equal(copied.alerts[0].checks[0].attempts,2);assert.equal(copied.preflight.id,'gate-failed');
 await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('denied');}}}));
 await page.getByRole('button',{name:'Copy all errors',exact:true}).click();await page.getByText('Could not copy the report. Allow clipboard access and try again.',{exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'Copied',exact:true}).count(),0,'denied clipboard access is not reported as success');
 await page.reload();await page.locator('.website-alert-table tbody').getByText(report.title,{exact:true}).waitFor();
 for(const width of [1920,1440,1024,768,390,320]){
   await page.setViewportSize({width,height:1000});
   await layout();
   const details=page.locator('.website-alert-table details');
   await details.locator('summary').click();
   await layout();
   assert.ok(await details.locator('pre').evaluate(node=>node.scrollWidth<=node.clientWidth+1),'Long diagnostics wrap inside the report');
   await details.locator('summary').click();
   if(width===1440||width===390)await page.screenshot({path:testArtifactPath(`vahan-ui-health-fixed-${width}.png`),fullPage:true});
 }
 const blockedBounds=await scheduleBounds();
 blocked=false;uiSocket.send('42/ui,'+JSON.stringify(['ui-health:verified',sqlState()]));
 await page.locator('.settings-ui-health').waitFor({state:'detached'});
 assert.equal(await page.getByRole('button',{name:'Copy all errors',exact:true}).count(),0);
 assert.deepEqual(await scheduleBounds(),blockedBounds,'Recovery keeps the schedule width and alignment');
 await page.goto(url+'#health');await page.getByRole('heading',{name:'Automatic report schedule',exact:true}).waitFor();
 assert.equal(await page.locator('.settings-ui-health').count(),0);
 assert.equal(await page.getByRole('link',{name:'Settings',exact:true}).getAttribute('aria-current'),'page');
 assert.ok(page.url().endsWith('#settings-ui-health'),'old UI Health links redirect to the Settings section');
 assert.deepEqual(errors,[]);
 assert.deepEqual(extraHealthRequests,[],'Settings never loads check scheduling, manual checks or history');
 console.log('UI Health: hidden when healthy; error-only reports, grouped developer copy, reload, recovery and mobile work without schedule/history requests.');
} finally {await browser.close();}
