import assert from 'node:assert/strict';
import {testArtifactPath} from './test-artifact-path.mjs';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'America/New_York'});
  const errors = []; page.on('pageerror',error=>errors.push(error.message));
  let schedules = [], posted, imageRequests = 0, uiSocket;
  const queueWrites = [];
  const resumedWorkers = [];
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
    else if(path==='/api/auth/renew') body={accessToken:'fixture-token'};
    else if(path==='/api/users') body=[{username:'fixture',role:'admin',active:true}];
    else if(path==='/api/filter-profiles') body=[profile];
    else if(path==='/api/user-state') body={vahanStateRtoMatrixV1:{year:2026,states:['State'],scenarios:[{name:'Fixture office',filters:{states:['State'],rtos:['Office']}}]}};
    else if(['/api/runners','/api/jobs','/api/maker-updates'].includes(path)) body=[];
    else if(path==='/api/worker-pool') body={enabled:true,desiredCount:8,runningCount:8,phase:'ready',workers:[]};
    else if(path==='/api/ui-health/status') body={revision:2,versionId:'fixture',blocked:false,latestPreflight:null};
    else if(path==='/api/ui-health/schedule') body={intervalDays:3,updatedAt:new Date().toISOString(),nextCheckAt:new Date(Date.now()+3*86400000).toISOString()};
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
      const count=request.postDataJSON().workerCount;resumedWorkers.push(count);
      schedules[0]={...schedules[0],status:'RESUMING',canResume:false,workerCount:count,message:`Preparing ${count} workers to continue the saved session.`};body=schedules[0];
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
  await page.getByLabel('Report / filter profile',{exact:true}).selectOption(profile.id);
  await page.getByLabel('Active workers',{exact:true}).selectOption('8');
  const future=new Date(Date.now()+86400_000);
  await page.getByLabel('Start date',{exact:true}).fill(future.toISOString().slice(0,10));
  await page.getByLabel('Start time',{exact:true}).fill('09:30');
  await page.getByLabel('Repeat',{exact:true}).selectOption('daily');
  await page.getByRole('button',{name:'Add schedule',exact:true}).click();
  await page.getByText(/Schedule saved for/).waitFor();
  assert.equal(posted.workerCount,8);assert.equal(posted.year,2024);assert.equal(posted.repeat,'daily');
  assert.equal(posted.profileId,profile.id);assert.ok(posted.startsAt.endsWith('T09:30:00+07:00'));
  const card=page.locator('.run-schedule-card').first();
  assert.equal(await page.getByRole('link',{name:/Create Report/}).count(),0);
  assert.equal(await card.locator('.run-schedule-actions > *').count(),3);
  const bounds=()=>page.locator('.automatic-run-settings').evaluate(root=>{
    const selectors=['.automatic-run-form','.automatic-run-form-footer','.schedule-help-slot','.schedule-feedback',
      '.run-schedule-list-heading','.run-schedule-card','.run-schedule-title','.run-schedule-details','.run-schedule-actions',
      '.run-schedule-card .schedule-status','.run-schedule-progress','.schedule-progress-header','.schedule-progress-count','.schedule-progress-speed'];
    return Object.fromEntries(selectors.map(selector=>{const rect=root.querySelector(selector).getBoundingClientRect();
      return [selector,[rect.x+scrollX,rect.y+scrollY,rect.width,rect.height].map(Math.round)];}));
  });
  await page.getByRole('button',{name:'Disable future runs',exact:true}).click();
  await page.getByRole('button',{name:'Enable schedule',exact:true}).waitFor();
  assert.equal(schedules[0].enabled,false);
  const desktop=await bounds();
  assert.ok(desktop['.run-schedule-card'][3] < 240,'Desktop schedule card is compact');
  schedules[0]={...schedules[0],enabled:true,profileName:'Long report name '.repeat(50),status:'COMPLETED_WITH_ERRORS',
    total:999999,done:888888,failed:111111,message:'A long processing error '.repeat(100)};
  await card.locator('.schedule-status').getByText('Completed with errors',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),desktop,'Long names and counters preserve desktop geometry');
  assert.equal((await card.innerText()).includes('processing error'),false);
  schedules[0]={...schedules[0],profileName:profile.name,enabled:true,status:'RUNNING',sessionId:'session-1',lastSessionId:'session-1',
    total:10,done:2,withData:1,noData:1,failed:0,lastRunAt:new Date(Date.now()-120_000).toISOString(),message:'Collected 2/10 cases.'};
  await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),desktop);
  await page.getByRole('button',{name:'Hide form',exact:true}).click();
  await page.locator('.settings-page').screenshot({path:testArtifactPath('settings-compact-desktop.png')});
  await page.getByRole('button',{name:'New schedule',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Delete schedule',exact:true}).isDisabled(),true);
  assert.match(await card.locator('.schedule-progress-numbers').innerText(),/2\s*\/\s*10 cases/);
  assert.match(await card.locator('.schedule-progress-speed').innerText(),/\d+\.\d\s*cases\/min/);
  const diagnosticsPanel=page.locator('.run-diagnostics').first();
  schedules[0]={...schedules[0],status:'PREPARING',message:'A worker is still busy.',
    operation:{stage:'Docker worker pool',detail:'A worker is still busy.',startedAt:new Date(Date.now()-360_000).toISOString(),
      progressAt:new Date().toISOString(),heartbeatAt:new Date().toISOString(),error:'A worker is still busy.'},
    diagnostics:{checkedAt:new Date().toISOString(),heartbeatAgeSeconds:2,stageAgeSeconds:360,
      warning:'Preparation has remained at this step for over 5 minutes.',workers:[{id:'playwright-8',selected:false,connected:true,
        browserReady:true,optionsBusy:true,heartbeatAgeSeconds:3,jobId:null,status:'IDLE',case:null,error:null,jobAgeSeconds:null}]}};
  await diagnosticsPanel.getByText('Docker worker pool',{exact:true}).waitFor();
  await diagnosticsPanel.getByText('A worker is still busy.',{exact:true}).waitFor();
  await diagnosticsPanel.getByRole('alert').waitFor();
  await diagnosticsPanel.getByRole('button',{name:'View details',exact:true}).click();
  await diagnosticsPanel.locator('summary').click();
  await diagnosticsPanel.getByText('Loading options / checking website',{exact:true}).waitFor();
  await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:new URL(process.env.SCHEDULE_UI_URL||'http://127.0.0.1:5186/').origin});
  await diagnosticsPanel.getByRole('button',{name:'Copy diagnostics',exact:true}).click();
  await diagnosticsPanel.getByText('Copied',{exact:true}).waitFor();
  const copiedDiagnostics=JSON.parse(await page.evaluate(()=>navigator.clipboard.readText()));
  assert.equal(copiedDiagnostics.operation.stage,'Docker worker pool');
  assert.equal(copiedDiagnostics.diagnostics.workers[0].optionsBusy,true);
  assert.deepEqual(await bounds(),desktop,'Operational diagnostics leave the schedule controls in place');
  await diagnosticsPanel.locator('summary').click();
  await diagnosticsPanel.getByRole('button',{name:'Hide details',exact:true}).click();
  schedules[0]={...schedules[0],status:'RUNNING',message:'Collected 2/10 cases.',operation:null,diagnostics:undefined};
  await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  const savedTasks=tasks.map(task=>({...task}));
  const retry={phase:'CHECKPOINT',checkpointStart:0,checkpointEnd:10,lastCheckpoint:0,finalPassStarted:false,failedRemaining:2,pendingRetries:2,complete:false};
  schedules[0]={...schedules[0],failed:2,retryProgress:retry};
  await card.getByText('10-case error checkpoint',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),desktop,'Retry phases do not move the schedule card controls');
  Object.assign(tasks[1],{status:'PENDING',attempts:2,failures:2,error:'Original report timeout'});
  Object.assign(tasks[2],{status:'PROCESSING',attempts:3,failures:2,error:'Original RTO options error'});
  schedules[0]={...schedules[0],retryProgress:{...retry,phase:'FINAL',finalPassStarted:true}};
  await card.getByText('Final failed-case recovery',{exact:true}).waitFor();
  await page.getByText('Failed cases (2)',{exact:true}).click();
  await page.getByText('Original report timeout',{exact:true}).waitFor();
  await page.getByText('Original RTO options error',{exact:true}).waitFor();
  assert.equal(await page.locator('.schedule-failed-scroll tbody tr').count(),2);
  await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:new URL(process.env.SCHEDULE_UI_URL||'http://127.0.0.1:5186/').origin});
  await page.getByRole('button',{name:'Copy failed cases',exact:true}).click();
  await page.getByRole('button',{name:'Copied',exact:true}).waitFor();
  const recovery=JSON.parse(await page.evaluate(()=>navigator.clipboard.readText()));
  assert.equal(recovery.sessionId,'session-1');assert.deepEqual(recovery.cases.map(item=>item.error),['Original report timeout','Original RTO options error']);
  assert.deepEqual(await bounds(),desktop,'Viewing failures leaves the card itself stable');
  await page.getByText('Failed cases (2)',{exact:true}).click();
  tasks.forEach((task,index)=>Object.assign(task,savedTasks[index]));
  schedules[0]={...schedules[0],failed:0,retryProgress:null};
  await card.getByText('Errors are checked every 10 cases, then all remaining failures receive a final recovery pass.',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  const mobile=await bounds();
  assert.ok(mobile['.run-schedule-card'][3] < 340,'Mobile schedule card is compact');
  assert.ok(await card.locator('.run-schedule-details').evaluate(node=>[...node.children].every(child=>child.getBoundingClientRect().bottom<=node.getBoundingClientRect().bottom+1)),'Mobile metadata fits its row');
  await page.getByRole('button',{name:'Hide form',exact:true}).click();
  await page.locator('.settings-page').screenshot({path:testArtifactPath('settings-compact-mobile.png')});
  await page.getByRole('button',{name:'New schedule',exact:true}).click();
  schedules[0]={...schedules[0],profileName:'Extremely long name '.repeat(50),status:'PREPARING',message:'A worker is still busy. Stop its job before changing containers.'};
  await card.locator('.schedule-status').getByText('Preparing',{exact:true}).waitFor();
  assert.deepEqual(await bounds(),mobile,'Mobile layout stays fixed during status and text changes');
  await card.locator('.schedule-run-message').getByText('A worker is still busy. Stop its job before changing containers.',{exact:true}).waitFor();
  schedules[0]={...schedules[0],status:'RESUMING',message:'Waiting for 7 connected, idle workers.'};
  await card.locator('.schedule-run-message').getByText('Waiting for 7 connected, idle workers.',{exact:true}).waitFor();
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
  const paused=await bounds();
  await page.getByLabel(`Workers for ${profile.name}`,{exact:true}).selectOption('10');
  await page.getByRole('button',{name:'Disable future runs',exact:true}).click();
  assert.equal(await page.getByLabel(`Workers for ${profile.name}`,{exact:true}).inputValue(),'10','Toggle preserves the paused worker draft');
  await page.getByRole('button',{name:'Continue run',exact:true}).click();
  await card.locator('.schedule-worker-setting select:disabled').waitFor();
  await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  assert.equal(schedules[0].workerCount,10);assert.equal(schedules[0].done,5);
  assert.deepEqual(await bounds(),paused,'Continuation preserves fixed card geometry');
  await page.getByRole('button',{name:'Pause run',exact:true}).click();
  await page.getByRole('button',{name:'Continue run',exact:true}).waitFor();
  await page.getByLabel(`Workers for ${profile.name}`,{exact:true}).selectOption('3');
  await page.getByRole('button',{name:'Continue run',exact:true}).click();
  await card.locator('.schedule-worker-setting select:disabled').waitFor();
  await card.locator('.schedule-status').getByText('Running',{exact:true}).waitFor();
  assert.deepEqual(resumedWorkers,[10,3]);assert.equal(schedules[0].sessionId,'session-1');assert.equal(schedules[0].done,6);
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
  await page.getByRole('alert').filter({hasText:'Wait for active cases to finish saving'}).waitFor();
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
  console.log('Settings schedules: create, fixed desktop/mobile layout, pause/drain, worker increase/decrease, same session and report refresh passed.');
} finally {await browser.close();}
