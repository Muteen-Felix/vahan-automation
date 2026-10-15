import assert from 'node:assert/strict';
import {testArtifactPath} from './test-artifact-path.mjs';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'America/New_York'});
  const errors = []; page.on('pageerror',error=>errors.push(error.message));
  let schedules = [], posted, imageRequests = 0, uiSocket, timeZoneUpdates = [];
  const queueWrites = [];
  const resumeBodies = [];
  let annualReads = 0,deleteFails=false,deleteCalls=0;
  const tasks = Array.from({length:10},(_,position)=>({position,name:`Scheduled office ${position+1}`,
    status:position===0?'COMPLETED':position===1?'NO_DATA':position===2?'PROCESSING':'PENDING',
    attempts:position<3?1:0,failures:0,runnerId:position<3?'playwright-1':null,jobId:position<3?`scheduled-job-${position}`:null,error:null}));
  const profile = {id:'126250e2-25a7-4baa-8314-8f3ac4647764',name:'Electric two-wheelers 2024',revision:3,
    definition:{report:{year:2024},fields:{},rules:[],maxCases:3000}};
  await page.addInitScript(()=>localStorage.setItem('vahanUiAccessToken','fixture-token'));
  await page.route('https://fonts.googleapis.com/**',r=>r.abort());
  await page.route('https://fonts.gstatic.com/**',r=>r.abort());
  await page.routeWebSocket('**/socket.io/**',socket=>{
    uiSocket=socket;
    socket.send('0'+JSON.stringify({sid:'fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));
    socket.onMessage(m=>{if(String(m).startsWith('40/ui,'))socket.send('40/ui,'+JSON.stringify({sid:'ui'}));});
  });
  await page.route('**/api/**', async route=>{
    const request=route.request(), path=new URL(request.url()).pathname; let body={};
    if(path==='/api/auth/status') body={configured:true};
    else if(path==='/api/auth/me') body={username:'fixture',role:'admin'};
    else if(path==='/api/auth/activity') body={accessToken:'fixture-token'};
    else if(path==='/api/users') body=[{username:'fixture',role:'admin',active:true}];
    else if(path==='/api/filter-profiles') body=[profile];
    else if(path==='/api/user-state') body={vahanStateRtoMatrixV1:{year:2026,states:['State'],scenarios:[{name:'Fixture office',filters:{states:['State'],rtos:['Office']}}]}};
    else if(['/api/runners','/api/jobs'].includes(path)) body=[];
    else if(path==='/api/worker-pool') body={enabled:true,desiredCount:8,runningCount:8,phase:'ready',workers:[]};
    else if(path==='/api/ui-health/status') body={revision:2,versionId:'fixture',blocked:false,latestPreflight:null};
    else if(path==='/api/ui-health/reports') body={selectedDate:null,availableDates:[],reports:[],rows:[]};
    else if(path==='/api/annual-reports') {
      annualReads++;
      const makers=['Manual maker','Scheduled maker',...(schedules[0]?.done>=4?['New scheduled maker']:[])];
      body={year:Number(new URL(request.url()).searchParams.get('year')),datasetId:'shared-electric',
        datasets:[{id:'shared-electric',label:'Electric two-wheelers'}],years:[2024,2026],states:['State'],rtos:['Office'],
        rows:makers.map((maker,i)=>({id:`row-${i}`,state:'State',rto:'Office',rto_code:'1',maker,months:Array(12).fill(i+1)})),
        coverage:Array(12).fill(100),summary:{rows:makers.length,makers:makers.length,offices:1,updatedAt:new Date().toISOString()}};
    }
    else if(path==='/api/annual-reports/coverage') body={matrixLoaded:true,total:1,covered:1,missing:0,withData:1,noData:0,firstMissing:null,lastSaved:null};
    else if(path==='/api/annual-reports/update-status') body={datasets:[],coverageBasis:''};
    else if(path==='/api/run-schedules/captchas') {imageRequests++;body=[];}
    else if(path==='/api/run-schedules' && request.method()==='POST') {
      posted=request.postDataJSON();
      const saved={...posted,id:'schedule-1',profileName:profile.name,profileRevision:3,timeZone:'Asia/Ho_Chi_Minh',
        nextRunAt:posted.startsAt,enabled:true,status:'WAITING',sessionId:null,lastSessionId:null,
        message:'Waiting for the scheduled start time.',total:0,done:0,withData:0,noData:0,failed:0};
      schedules.push(saved);body=saved;
    } else if(path==='/api/run-schedules/time-zone' && request.method()==='POST') {
      const update=request.postDataJSON();timeZoneUpdates.push(update);
      schedules=schedules.map(schedule=>({...schedule,timeZone:update.timeZone}));body=schedules;
    } else if(path==='/api/run-schedules') body=schedules;
    else if(path.startsWith('/api/batch-queue/')) {
      if(request.method()!=='GET') queueWrites.push(path);
      body={sessionId:'session-1',status:schedules[0]?.status==='RUNNING'?'RUNNING':'PAUSED',maxWorkers:schedules[0]?.workerCount??8,tasks};
    }
    else if(path.startsWith('/api/jobs/scheduled-job-')) {
      const position=Number(path.split('-').at(-1));
      body={id:`scheduled-job-${position}`,runnerId:tasks[position].runnerId??'playwright-1',sessionId:'session-1',source:'new',
        scenarioName:tasks[position].name,status:tasks[position].status==='PROCESSING'?'WAITING_RESULT':tasks[position].status,
        filters:{states:['Scheduled state'],rtos:[`Scheduled office ${position+1}`]},
        createdAt:new Date(Date.now()-60_000).toISOString(),updatedAt:new Date().toISOString(),
        mainReportSavedAt:position<2?new Date().toISOString():null};
    }
    else if(path==='/api/run-schedules/schedule-1' && request.method()==='PATCH') {
      schedules[0]={...schedules[0],...request.postDataJSON()};body=schedules[0];
    } else if(path==='/api/run-schedules/schedule-1/stop') {
      schedules[0]={...schedules[0],enabled:false,status:'STOPPED',sessionId:null,nextRunAt:null,message:'Scheduled run stopped.'};body=schedules[0];
    } else if(path==='/api/run-schedules/schedule-1/pause') {
      schedules[0]={...schedules[0],status:'PAUSING',message:'Pausing: waiting for active cases to save.'};body=schedules[0];
      setTimeout(()=>{
        const active=tasks.filter(task=>task.status==='PROCESSING');
        for(const task of active) task.status='COMPLETED';
        schedules[0]={...schedules[0],status:'PAUSED',canResume:true,done:schedules[0].done+active.length,
          withData:schedules[0].withData+active.length,activeElapsedMs:120_000,activeSegmentStartedAt:null,
          message:'Run paused. Choose workers and continue the saved session.'};
      },500);
    } else if(path==='/api/run-schedules/schedule-1/resume') {
      resumeBodies.push(request.postDataJSON());
      schedules[0]={...schedules[0],status:'RESUMING',canResume:false,message:`Preparing connected workers to continue the saved session.`};body=schedules[0];
      setTimeout(()=>{
        if(schedules[0]?.status!=='RESUMING')return; // Fence a late resume callback after a newer pause.
        const next=tasks.find(task=>task.status==='PENDING');
        if(next)Object.assign(next,{status:'PROCESSING',runnerId:'playwright-1',jobId:`scheduled-job-${next.position}`,attempts:1});
        schedules[0]={...schedules[0],status:'RUNNING',activeSegmentStartedAt:new Date().toISOString(),message:'Scheduled report collection is running.'};
      },500);
    } else if(path==='/api/run-schedules/schedule-1' && request.method()==='DELETE') {
      deleteCalls++;
      if(deleteFails)return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Wait for active cases to finish saving before deleting the schedule.'})});
      schedules=[];body={ok:true};
    }
    await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto(process.env.SCHEDULE_UI_URL || 'http://127.0.0.1:5186/#settings');
  await page.getByRole('heading',{name:'Automatic report schedule',exact:true}).waitFor();
  await page.getByRole('button',{name:'Create schedule',exact:true}).click();
  await page.getByLabel('Saved filters',{exact:true}).selectOption(profile.id);
  assert.equal(await page.locator('#new-schedule-form input[type="number"]').count(),0,'The schedule form omits parallel task limit and report year');
  const future=new Date(Date.now()+86400_000);
  await page.getByLabel('Start date',{exact:true}).fill(future.toISOString().slice(0,10));
  await page.getByLabel('Start time',{exact:true}).fill('09:30');
  const repeatSelect=page.getByLabel('Repeat',{exact:true});
  assert.deepEqual(await repeatSelect.locator('option').evaluateAll(options=>options.map(option=>option.value)),['once','monthly']);
  await repeatSelect.selectOption('once');
  await page.getByText(/Runs once on the selected date and time, using the saved filters and selected time zone\. It will not repeat or create a filter or schedule for a following year\./).waitFor();
  await repeatSelect.selectOption('monthly');
  await page.getByText(/Uses the saved filters above to collect reports for year 2024\. Runs on day \d+ of each month at the selected time and time zone\./).waitFor();
  await page.getByText(/After the final run for report year 2024, this schedule ends\. If it is still enabled, the system creates a separate copy of the saved filters with the same search settings and only the report year changed to 2025\. A new monthly schedule then uses the same day, time, and time zone\. This repeats automatically each year\. Disable this schedule to stop the rollover\./).waitFor();
  assert.equal(await page.locator('.schedule-help').evaluate(element=>getComputedStyle(element).display),'block');
  await page.getByRole('button',{name:'Add schedule',exact:true}).click();
  await page.getByText(/Schedule saved for/).waitFor();
  assert.equal(Object.hasOwn(posted,'workerCount'),false);assert.equal(posted.year,2024);assert.equal(posted.repeat,'monthly');
  assert.equal(posted.profileId,profile.id);assert.ok(posted.startsAt.endsWith('T09:30:00+07:00'));
  const card=page.locator('.run-schedule-card').first();
  const monthlyDay=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Ho_Chi_Minh',day:'numeric'}).format(new Date(posted.startsAt));
  await card.getByText(`Day ${monthlyDay} · month-end if needed · new filter each year`,{exact:true}).waitFor();
  assert.equal(await page.getByRole('link',{name:/Create Report/}).count(),0);
  assert.equal(await page.getByLabel('Schedule time zone').count(),0,'The time zone control lives in Account settings');
  assert.equal(await card.locator('.run-schedule-actions > *').count(),3);
  const bounds=()=>page.locator('.automatic-run-settings').evaluate(root=>{
    const selectors=['.automatic-run-form','.automatic-run-form-footer','.schedule-help-slot','.schedule-feedback',
      '.run-schedule-list-heading','.run-schedule-card','.run-schedule-title','.run-schedule-details','.run-schedule-actions',
      '.run-schedule-card .schedule-status','.run-schedule-progress','.schedule-progress-header','.schedule-progress-count','.schedule-progress-speed'];
    return Object.fromEntries(selectors.map(selector=>{const rect=root.querySelector(selector).getBoundingClientRect();
      return [selector,rect.width===0 && rect.height===0 ? [0,0,0,0] :
        [rect.x+scrollX,rect.y+scrollY,rect.width,rect.height].map(Math.round)];}));
  });
  await page.getByRole('button',{name:'Disable future runs',exact:true}).click();
  await page.getByRole('button',{name:'Enable schedule',exact:true}).waitFor();
  assert.equal(schedules[0].enabled,false);
  const desktop=await bounds();
  assert.ok(desktop['.run-schedule-card'][3] < 290,'Desktop schedule card fits progress and the ETA');
  schedules[0]={...schedules[0],enabled:true,profileName:'Long report name '.repeat(50),status:'COMPLETED_WITH_ERRORS',
    total:999999,done:888888,failed:111111,message:'A long processing error '.repeat(100)};
  await card.locator('.schedule-status').getByText('Some reports unfinished',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),desktop,'Long names and counters preserve desktop geometry');
  assert.equal((await card.innerText()).includes('processing error'),false);
  schedules[0]={...schedules[0],profileName:profile.name,enabled:true,status:'RUNNING',sessionId:'session-1',lastSessionId:'session-1',
    total:10,done:2,withData:1,noData:1,failed:0,lastRunAt:new Date(Date.now()-120_000).toISOString(),message:'Collected 2/10 cases.'};
  await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),desktop);
  await page.locator('.settings-page').screenshot({path:testArtifactPath('settings-compact-desktop.png')});
  assert.equal(await page.getByRole('button',{name:'Delete schedule',exact:true}).isDisabled(),true);
  assert.match(await card.locator('.schedule-progress-numbers').innerText(),/2\s*\/\s*10 reports/);
  assert.match(await card.locator('.schedule-progress-speed').innerText(),/\d+\.\d\s*reports\/min/);
  await card.getByLabel('Estimated finish').getByText(/About \d+m remaining/).waitFor();
  assert.ok(await card.getByLabel('Estimated finish').locator('time').getAttribute('datetime'));
  assert.match(await card.getByLabel('Estimated finish').innerText(), /Vietnam time \(UTC\+07:00\)/);
  schedules[0]={...schedules[0],timeZone:'Asia/Kolkata'};
  await card.getByLabel('Estimated finish').getByText('Vietnam time (UTC+07:00)',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Account',exact:true}).click();
  const accountDialog=page.getByRole('dialog',{name:'Account settings'});
  await accountDialog.getByLabel('Display time zone',{exact:true}).selectOption('Asia/Kolkata');
  await accountDialog.getByRole('status').getByText(/Times across the interface now use India time/).waitFor();
  assert.deepEqual(timeZoneUpdates,[{timeZone:'Asia/Kolkata'}]);
  await card.getByLabel('Estimated finish').getByText('India time (UTC+05:30)',{exact:true}).waitFor();
  const finish=await card.getByLabel('Estimated finish').locator('time').getAttribute('datetime');
  const indiaFinish=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',
    year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(finish));
  assert.equal(await card.getByLabel('Estimated finish').locator('time').innerText(),indiaFinish);
  await accountDialog.getByLabel('Display time zone',{exact:true}).selectOption('Asia/Ho_Chi_Minh');
  await accountDialog.getByRole('status').getByText(/Times across the interface now use Vietnam time/).waitFor();
  assert.deepEqual(timeZoneUpdates,[{timeZone:'Asia/Kolkata'},{timeZone:'Asia/Ho_Chi_Minh'}]);
  await page.getByRole('button',{name:'Close account settings'}).click();
  const diagnosticsPanel=page.locator('.run-diagnostics').first();
  schedules[0]={...schedules[0],status:'PREPARING',message:'A worker is still busy.',
    operation:{stage:'Docker worker pool',detail:'A worker is still busy.',startedAt:new Date(Date.now()-360_000).toISOString(),
      progressAt:new Date().toISOString(),heartbeatAt:new Date().toISOString(),error:'A worker is still busy.'},
    diagnostics:{checkedAt:new Date().toISOString(),heartbeatAgeSeconds:2,stageAgeSeconds:360,
      warning:'Preparation has remained at this step for over 5 minutes.',workers:[{id:'playwright-8',selected:false,connected:true,
        browserReady:true,optionsBusy:true,heartbeatAgeSeconds:3,jobId:null,status:'IDLE',case:null,error:null,jobAgeSeconds:null}]}};
  await diagnosticsPanel.getByText('Preparing report browsers',{exact:true}).waitFor();
  await diagnosticsPanel.locator(':scope > .run-diagnostics-detail').filter({hasText:'A report browser is still busy.'}).waitFor();
  await diagnosticsPanel.getByRole('alert').waitFor();

  await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:new URL(process.env.SCHEDULE_UI_URL||'http://127.0.0.1:5186/').origin});
  await diagnosticsPanel.getByRole('button',{name:'Copy for support',exact:true}).click();
  await diagnosticsPanel.getByText('Copied',{exact:true}).waitFor();
  const copiedDiagnostics=JSON.parse(await page.evaluate(()=>navigator.clipboard.readText()));
  assert.equal(copiedDiagnostics.operation.stage,'Docker worker pool');
  assert.equal(copiedDiagnostics.diagnostics.workers[0].optionsBusy,true);
  assert.deepEqual(await bounds(),desktop,'Operational diagnostics leave the schedule controls in place');
  await diagnosticsPanel.getByRole('button',{name:'View details',exact:true}).click();
  const activityDialog=diagnosticsPanel.getByRole('dialog',{name:'Activity details'});
  await activityDialog.getByText('Loading choices / checking website',{exact:true}).waitFor();
  assert.equal(await activityDialog.getByText('Details for support',{exact:true}).count(),0,'Raw schedule JSON is hidden from activity details');
  assert.equal(await activityDialog.getByText('Details for support',{exact:true}).count(),0,'Raw schedule JSON is hidden from activity details');
  await activityDialog.getByRole('button',{name:'Close details',exact:true}).click();
  schedules[0]={...schedules[0],status:'RUNNING',message:'Collected 2/10 cases.',operation:null,diagnostics:undefined};
  await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  const savedTasks=tasks.map(task=>({...task}));
  const retry={phase:'CHECKPOINT',checkpointStart:0,checkpointEnd:10,lastCheckpoint:0,finalPassStarted:false,failedRemaining:2,pendingRetries:2,complete:false};
  schedules[0]={...schedules[0],failed:2,retryProgress:retry};
  await card.getByText('Checking unfinished reports in this group (10)',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),desktop,'Retry phases do not move the schedule card controls');
  schedules[0]={...schedules[0],retryProgress:{...retry,checkpointEnd:25}};
  await card.getByText('Checking unfinished reports in this group (25)',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),desktop,'Larger report groups preserve the same layout');
  Object.assign(tasks[1],{status:'PENDING',attempts:2,failures:2,error:'Original report timeout'});
  Object.assign(tasks[2],{status:'PROCESSING',attempts:3,failures:2,error:'Original RTO options error'});
  schedules[0]={...schedules[0],retryProgress:{...retry,phase:'FINAL',finalPassStarted:true}};
  await card.getByText('Final check of unfinished reports',{exact:true}).waitFor();
  await page.getByText('Reports needing attention (2)',{exact:true}).click();
  await page.getByText('Original report timeout',{exact:true}).waitFor();
  await page.getByText('Original RTO options error',{exact:true}).waitFor();
  assert.equal(await page.locator('.schedule-failed-scroll tbody tr').count(),2);
  await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:new URL(process.env.SCHEDULE_UI_URL||'http://127.0.0.1:5186/').origin});
  await page.getByRole('button',{name:'Copy issues for support',exact:true}).click();
  await page.getByRole('button',{name:'Copied',exact:true}).waitFor();
  const recovery=JSON.parse(await page.evaluate(()=>navigator.clipboard.readText()));
  assert.equal(recovery.sessionId,'session-1');assert.deepEqual(recovery.cases.map(item=>item.error),['Original report timeout','Original RTO options error']);
  assert.deepEqual(await bounds(),desktop,'Viewing failures leaves the card itself stable');
  await page.getByText('Reports needing attention (2)',{exact:true}).click();
  tasks.forEach((task,index)=>Object.assign(task,savedTasks[index]));
  schedules[0]={...schedules[0],failed:0,retryProgress:null};
  await card.getByText('Unfinished reports are tried again after each group, with one final check at the end.',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  const mobile=await bounds();
  assert.ok(mobile['.run-schedule-card'][3] < 410,'Mobile schedule card fits progress, the ETA and actions compactly');
  assert.ok(await card.locator('.run-schedule-details').evaluate(node=>[...node.children].every(child=>child.getBoundingClientRect().bottom<=node.getBoundingClientRect().bottom+1)),'Mobile metadata fits its row');
  await page.locator('.settings-page').screenshot({path:testArtifactPath('settings-compact-mobile.png')});
  schedules[0]={...schedules[0],profileName:'Extremely long name '.repeat(50),status:'PREPARING',message:'A worker is still busy. Stop its job before changing containers.'};
  await card.locator('.schedule-status').getByText('Preparing',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),mobile,'Mobile layout stays fixed during status and text changes');
  await card.locator('.schedule-run-message').getByText('A report browser is still working. Wait for its current report to finish before changing the number of browsers.',{exact:true}).waitFor();
  schedules[0]={...schedules[0],status:'RESUMING',message:'Waiting for 7 connected, idle workers.'};
  await card.locator('.schedule-run-message').getByText('Waiting for 7 connected, available report browsers.',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),mobile,'A preparation reason occupies the existing fixed feedback slot');
  schedules[0]={...schedules[0],profileName:profile.name,status:'RUNNING',message:'Scheduled report collection is running.'};
  await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.reload();await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  assert.equal(await page.locator('.scheduled-report-run,.worker-dashboard').count(),0);
  await page.getByRole('link',{name:'Exported Reports',exact:true}).click();
  await page.getByText('Manual maker',{exact:true}).waitFor();
  await page.getByText('Scheduled maker',{exact:true}).waitFor();
  const before=annualReads;
  Object.assign(tasks[3],{status:'NO_DATA',runnerId:'playwright-2',jobId:'scheduled-job-3',attempts:1});
  Object.assign(tasks[4],{status:'NO_DATA',runnerId:'playwright-2',jobId:'scheduled-job-4',attempts:1});
  schedules[0]={...schedules[0],done:4,noData:3};
  await page.getByText('New scheduled maker',{exact:true}).waitFor();
  assert.ok(annualReads>before,'Schedule progress refreshes saved report data');
  await page.getByRole('link',{name:'Settings',exact:true}).click();
  await page.getByRole('button',{name:'Pause run',exact:true}).click();
  await page.getByRole('button',{name:'Continue run',exact:true}).waitFor();
  assert.equal(schedules[0].sessionId,'session-1');assert.equal(schedules[0].done,5);
  assert.equal(await page.getByRole('button',{name:'Delete schedule',exact:true}).isEnabled(),true);
  assert.equal(await card.locator('.schedule-progress-speed strong').innerText(),'—');
  assert.equal(await card.getByLabel('Estimated finish').locator('time').count(),0,'Paused schedules do not show a stale forecast');
  const paused=await bounds();
  assert.equal(await card.locator('input[type=number]').count(),0);
  await page.getByRole('button',{name:'Disable future runs',exact:true}).click();
  assert.equal(await card.locator('input[type=number]').count(),0);
  await page.getByRole('button',{name:'Continue run',exact:true}).click();
  assert.equal(await card.locator('input[type=number]').count(),0);
  await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  assert.equal(Object.hasOwn(resumeBodies[0],'workerCount'),false);assert.equal(schedules[0].done,5);
  assert.deepEqual(await bounds(),paused,'Continuation preserves fixed card geometry');
  await page.getByRole('button',{name:'Pause run',exact:true}).click();
  await page.getByRole('button',{name:'Continue run',exact:true}).waitFor();
  // A legacy response may still include a large worker count; controls ignore it.
  schedules[0].workerCount=9999;
  await page.getByRole('button',{name:'Continue run',exact:true}).click();
  assert.equal(await card.locator('input[type=number]').count(),0);
  await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  assert.deepEqual(resumeBodies,[{},{}]);assert.equal(schedules[0].sessionId,'session-1');assert.equal(schedules[0].done,6);
  assert.deepEqual(queueWrites,[],'Only backend schedule controls dispatch work');
  await card.screenshot({path:testArtifactPath('vahan-settings-schedule-mobile.png')});
  await page.setViewportSize({width:1440,height:1000});
  await card.screenshot({path:testArtifactPath('vahan-settings-schedule-desktop.png')});
  await page.getByRole('button',{name:'Pause run',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Delete schedule',exact:true}).isDisabled(),true,'Delete waits while active cases drain');
  await page.getByRole('button',{name:'Continue run',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Delete schedule',exact:true}).isEnabled(),true);
  await page.setViewportSize({width:320,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await card.screenshot({path:testArtifactPath('vahan-paused-delete-mobile.png')});
  await page.setViewportSize({width:1440,height:1000});
  await card.screenshot({path:testArtifactPath('vahan-paused-delete-desktop.png')});
  deleteFails=true;
  await page.getByRole('button',{name:'Delete schedule',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Wait for active reports to finish saving'}).waitFor();
  assert.equal(await card.count(),1,'A rejected delete retains the card and paused session');
  assert.equal(schedules[0].sessionId,'session-1');
  deleteFails=false;
  await page.getByRole('button',{name:'Delete schedule',exact:true}).click();
  await page.getByText('No automatic report schedules yet.',{exact:true}).waitFor();
  assert.equal(deleteCalls,2);
  await page.getByRole('link',{name:'Exported Reports',exact:true}).click();
  await page.getByText('Scheduled maker',{exact:true}).waitFor();
  assert.deepEqual(queueWrites,[],'Deletion uses the schedule API, never a second browser dispatch loop');
  assert.equal(await page.locator('.captcha-inbox,.captcha-panel,.settings-captcha-panel,img[src^="data:image/"]').count(),0);
  assert.equal(imageRequests,0);assert.deepEqual(errors,[]);
  console.log('Settings schedules: create, fixed desktop/mobile layout, pause/drain, automatic connected workers, same session and report refresh passed.');
} finally {await browser.close();}
