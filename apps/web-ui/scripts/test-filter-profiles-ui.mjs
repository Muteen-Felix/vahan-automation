import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const browser=await chromium.launch({headless:true});
let forceBusy=false;
let profiles=[],state={vahanRunSettingsV1:{year:2024,workerCount:2}},previewCalls=0,queueBody,queueSnapshot;
const id='11111111-1111-4111-8111-111111111111';
const runners=[1,2].map(index=>({id:`playwright-${index}`,name:`Crawler ${index}`,source:'new',status:'ONLINE',lastSeenAt:new Date().toISOString()}));
const options={delhiNcr:['ALL STATES'],states:['State A','State B'],rtos:['RTO A'],
  categoryGroups:['Two Wheeler','Three Wheeler'],subCategories:['Sub A','Sub B'],classes:['Class A','Class B'],evTypes:['EV 1','EV 2'],
  fuels:['ELECTRIC(BOV)','PURE EV'],archivedFlags:['ACTIVE_COMPLIANT','ACTIVE_NON_COMPLIANT','PERMANENT_ARCHIVE','TEMPORARY_ARCHIVE'],emissions:[],makers:[],statuses:[],ownerTypes:[],vehicleType:[],fitness:['NO','YES']};
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];
  await page.route('https://fonts.googleapis.com/**',route=>route.abort());
  await page.route('https://fonts.gstatic.com/**',route=>route.abort());
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>localStorage.setItem('vahanUiAccessToken','fixture-token'));
  await page.routeWebSocket('**/socket.io/**',socket=>{
    socket.send('0'+JSON.stringify({sid:'fixture-engine',upgrades:[],pingInterval:60000,pingTimeout:60000,maxPayload:1000000}));
    socket.onMessage(message=>{if(String(message).startsWith('40/ui,'))socket.send('40/ui,'+JSON.stringify({sid:'fixture-ui'}));});
  });
  await page.route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url()),path=url.pathname;let body={};
    if(path==='/api/auth/status')body={configured:true};
    else if(path==='/api/auth/me')body={username:'fixture',role:'admin'};
    else if(path==='/api/auth/renew')body={accessToken:'fixture-token'};
    else if(path==='/api/user-state')body=state;
    else if(path.startsWith('/api/user-state/'))state[decodeURIComponent(path.slice('/api/user-state/'.length))]=request.postDataJSON().value;
    else if(path==='/api/runners')body=forceBusy?runners.map(runner=>({...runner,status:'BUSY',currentJobId:'busy-fixture'})):runners;
    else if(path==='/api/worker-pool')body={enabled:true,desiredCount:2,runningCount:2,phase:'ready',workers:[]};
    else if(path==='/api/maker-updates'||path==='/api/jobs')body=[];
    else if(path==='/api/filter-profiles'&&request.method()==='GET')body=profiles;
    else if((path==='/api/filter-profiles'||path===`/api/filter-profiles/${id}`)&&['POST','PUT'].includes(request.method())){
      const input=request.postDataJSON();body={id,name:input.name,definition:input.definition,revision:(profiles[0]?.revision||0)+1,updatedAt:new Date().toISOString()};profiles=[body];
    }
    else if(path==='/api/filter-profiles/options'){
      assert.equal(forceBusy,false,'option reads must not target busy workers');
      const context=request.postDataJSON().context;body={...options,rtos:context.states.length?['RTO A']:[],
        subCategories:context.categoryGroups.includes('Three Wheeler')?['Three-wheel subcategory']:['Sub A','Sub B']};
    }
    else if(path===`/api/filter-profiles/${id}/preview`){
      previewCalls++;const year=request.postDataJSON().year;assert.equal(year,2023);
      const definition=profiles[0].definition;
      const scenarios=['ELECTRIC(BOV)','PURE EV'].map((fuel,index)=>{
        const filters=Object.fromEntries(Object.entries(definition.fields).map(([field,policy])=>[field,['delhiNcr','vehicleType','fitness'].includes(field)?policy.values[0]||'':policy.values]));
        Object.assign(filters,{states:['State A'],rtos:['RTO A'],fuels:[fuel],fromYear:String(year),toYear:String(year),period:'CALENDAR YEAR',yAxis:'Maker',xAxis:'Month Wise',autoApply:true,autoExport:true});
        return {name:`Fixture RTO A (${year}) ${fuel}`,caseKey:`case-${index}`,filters};
      });
      const plan={year,states:['State A'],scenarios,profileId:id,profileRevision:profiles[0].revision,profileName:profiles[0].name,skippedBranches:0};
      await route.fulfill({status:200,contentType:'application/x-ndjson',body:JSON.stringify({type:'progress',message:'Checking valid combinations'})+'\n'+JSON.stringify({type:'ready',plan})+'\n'});return;
    }
    else if(path==='/api/batch-queue/sessions'){
      queueBody=request.postDataJSON();body=queueSnapshot={sessionId:queueBody.sessionId,status:'RUNNING',maxWorkers:2,tasks:queueBody.tasks.map((task,position)=>({position,name:task.name,status:'PENDING',attempts:0,failures:0,runnerId:null,jobId:null,error:null}))};
    }
    else if(path.endsWith('/claim')){queueSnapshot.status='PAUSED';body={type:'paused'};}
    else if(path.startsWith('/api/batch-queue/sessions/'))body=queueSnapshot;
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto(process.env.WORKER_UI_URL||'http://127.0.0.1:5184/#filters');
  await page.getByRole('heading',{name:'Filters',exact:true}).waitFor();
  assert.equal(await page.getByLabel('Report from year',{exact:true}).inputValue(),String(new Date().getFullYear()),'new profile defaults to the current year rather than saved home settings');
  assert.equal(await page.getByLabel('Report to year',{exact:true}).inputValue(),String(new Date().getFullYear()));
  await page.getByLabel('Profile name',{exact:true}).fill('Customer filters');
  await page.getByLabel('Report from year',{exact:true}).selectOption('2023');
  assert.equal(await page.getByLabel('Report to year',{exact:true}).inputValue(),'2023');
  await page.getByLabel('Report to year',{exact:true}).selectOption('2022');
  assert.equal(await page.getByLabel('Report from year',{exact:true}).inputValue(),'2022');
  await page.getByLabel('Report from year',{exact:true}).selectOption('2023');
  await page.waitForFunction(()=>!document.body.textContent.includes('Loading live VAHAN options'));
  const group=page.locator('.profile-field-row').filter({has:page.getByText('Category Group',{exact:true})});
  const boxes=()=>page.locator('.profile-field-row').evaluateAll(rows=>rows.map(row=>{const box=row.getBoundingClientRect();return {y:box.y+scrollY,height:box.height};}));
  assert.equal(await page.locator('.profile-field-row').count(),15);
  assert.equal(await page.locator('.profile-field-row .profile-picker-trigger').count(),15,'one value picker per field');
  assert.equal(await page.locator('.profile-field-row select:visible').count(),0,'Mode is inside the value menu');
  for(const row of await page.locator('.profile-field-row').all()){
    await row.scrollIntoViewIfNeeded();const trigger=row.locator('.profile-picker-trigger');await trigger.click();
    const menu=page.getByRole('dialog',{name:await trigger.getAttribute('aria-label'),exact:true});await menu.waitFor();
    assert.ok(await menu.evaluate(element=>element.matches(':popover-open')),'value picker uses an anchored non-modal popover');
    const anchor=await trigger.boundingBox(),panel=await menu.boundingBox();
    assert.ok(Math.abs(panel.y-anchor.y-anchor.height-6)<2,'every menu opens directly beneath its field');
    assert.ok(Math.abs(panel.width-anchor.width)<2,'menu width matches its field');
    await menu.getByRole('button',{name:'Done',exact:true}).click();
  }
  await group.scrollIntoViewIfNeeded();const before=await boxes();
  await group.getByRole('button',{name:/^Category Group/}).click();
  const groupDialog=page.getByRole('dialog',{name:'Category Group',exact:true});
  await groupDialog.getByRole('checkbox',{name:'Three Wheeler',exact:true}).waitFor();
  const originalOrder=await groupDialog.locator('.profile-picker-options label').allTextContents();
  await groupDialog.getByRole('checkbox',{name:'Two Wheeler',exact:true}).uncheck();
  await groupDialog.getByRole('checkbox',{name:'Three Wheeler',exact:true}).check();
  assert.deepEqual(await groupDialog.locator('.profile-picker-options label').allTextContents(),originalOrder,
    'selecting a value keeps the original order instead of moving it to the top');
  assert.deepEqual(await boxes(),before,'opening the value dialog and selecting values does not move editor rows');
  await page.screenshot({path:'/tmp/vahan-filter-picker-overlay.png'});
  await groupDialog.getByRole('button',{name:'Done',exact:true}).click();
  const sub=page.locator('.profile-field-row').filter({has:page.getByText('Sub-Category',{exact:true})});
  await sub.getByRole('button',{name:/^Sub-Category/}).click();
  const subDialog=page.getByRole('dialog',{name:'Sub-Category',exact:true});
  await subDialog.getByRole('checkbox',{name:'Three-wheel subcategory'}).waitFor();
  await subDialog.getByRole('checkbox',{name:'Three-wheel subcategory'}).check();
  await page.keyboard.press('Escape');await subDialog.waitFor({state:'hidden'});
  const fuelRow=page.locator('.profile-field-row').filter({has:page.getByText('Fuel',{exact:true})});
  await fuelRow.getByRole('button',{name:/^Fuel/}).click();
  const fuelDialog=page.getByRole('dialog',{name:'Fuel',exact:true});
  await fuelDialog.getByLabel('Fuel mode',{exact:true}).selectOption('iterate');
  await fuelDialog.getByRole('button',{name:'Done',exact:true}).click();
  const stateRow=page.locator('.profile-field-row').filter({has:page.getByText('State',{exact:true})});
  await stateRow.getByRole('button',{name:'State',exact:true}).click();
  const stateDialog=page.getByRole('dialog',{name:'State',exact:true});
  await stateDialog.getByRole('checkbox',{name:'State A',exact:true}).check();
  await stateDialog.getByRole('button',{name:'Exclusions (0)',exact:true}).click();
  await stateDialog.getByRole('checkbox',{name:'State B',exact:true}).check();
  await stateDialog.getByRole('button',{name:'Done',exact:true}).click();
  await page.waitForFunction(()=>!document.body.textContent.includes('Loading live VAHAN options'));
  await page.getByRole('button',{name:'Edit rules',exact:true}).click();
  const rulesDialog=page.getByRole('dialog',{name:'Combination rules',exact:true});
  const beforeRules=await boxes();
  await rulesDialog.getByRole('button',{name:'Add rule',exact:true}).click();
  await rulesDialog.getByRole('button',{name:/If values/}).click();
  const ifDialog=page.getByRole('dialog',{name:'If values',exact:true});await ifDialog.waitFor();
  await page.keyboard.press('Escape');await ifDialog.waitFor({state:'hidden'});
  assert.ok(await rulesDialog.isVisible(),'closing a nested value picker keeps the rules dialog open');
  assert.deepEqual(await boxes(),beforeRules,'adding rules in a dialog keeps editor rows fixed');
  await rulesDialog.getByRole('button',{name:'Remove',exact:true}).click();
  await rulesDialog.getByRole('button',{name:'Done',exact:true}).click();
  await page.getByRole('button',{name:'Save to SQL',exact:true}).click();
  await page.getByText('Saved to SQL.',{exact:true}).waitFor();
  assert.equal(profiles[0].definition.report.year,2023,'report year is included in the SQL profile');
  assert.equal(profiles[0].definition.fields.categoryGroups.values[0],'Three Wheeler');
  assert.deepEqual(profiles[0].definition.fields.classes.values,[],'changing a parent clears dependent selections');
  assert.equal(profiles[0].definition.fields.fuels.mode,'iterate');
  assert.deepEqual(profiles[0].definition.fields.states.include,['State A']);
  assert.deepEqual(profiles[0].definition.fields.states.exclude,['State B']);
  await page.getByRole('button',{name:'Save & preview',exact:true}).click();
  await page.getByRole('button',{name:'Use on home page'}).waitFor();
  assert.equal(previewCalls,1);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'/tmp/vahan-filter-profiles-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'Use on home page'}).click();
  assert.equal(await page.getByLabel('Filter profile',{exact:true}).inputValue(),id);
  await page.getByRole('button',{name:'Run all · 2 workers',exact:true}).click();
  await page.waitForFunction(()=>document.body.textContent.includes('Continue · 2 workers'));
  assert.equal(previewCalls,2,'starting a run must recheck live options and the saved revision');
  assert.equal(queueBody.tasks.length,2);assert.deepEqual(queueBody.tasks.map(task=>task.filters.fuels[0]),['ELECTRIC(BOV)','PURE EV']);
  assert.ok(queueBody.tasks.every(task=>task.filters.categoryGroups[0]==='Three Wheeler'&&task.filters.fromYear==='2023'));
  assert.equal(await page.getByLabel('Crawl year',{exact:true}).count(),0,'home has no separate year selector');
  await page.reload();await page.getByLabel('Filter profile',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('Filter profile',{exact:true}).inputValue(),id,'profile choice persists through reload');
  await page.getByRole('link',{name:'Filters',exact:true}).click();await page.setViewportSize({width:390,height:844});
  await page.getByRole('heading',{name:'Filters',exact:true}).waitFor();
  await page.locator('.profile-list').getByRole('button',{name:/Customer filters/}).click();
  assert.equal(await page.getByLabel('Report from year',{exact:true}).inputValue(),'2023','saved year survives reload');
  const mobileRow=page.locator('.profile-field-row').first();await mobileRow.scrollIntoViewIfNeeded();
  const mobileBefore=await boxes();await mobileRow.getByRole('button').click();
  const mobileDialog=page.getByRole('dialog',{name:'Active / Archive Type',exact:true});await mobileDialog.waitFor();
  assert.deepEqual(await boxes(),mobileBefore,'mobile overlay keeps rows fixed');
  const modalBox=await mobileDialog.boundingBox();assert.ok(modalBox.x>=0&&modalBox.x+modalBox.width<=390);
  await page.screenshot({path:'/tmp/vahan-filter-picker-mobile.png'});
  await mobileDialog.getByRole('button',{name:'Done',exact:true}).click();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'filter editor fits mobile width');
  await page.screenshot({path:'/tmp/vahan-filter-profiles-mobile.png',fullPage:true});
  assert.ok(Array.isArray(state.vahanFilterOptionsV1),'live option snapshots persist in the SQL-backed user state');
  forceBusy=true;await page.reload();await page.getByRole('heading',{name:'Filters',exact:true}).waitFor();
  await page.locator('.profile-list').getByRole('button',{name:/Customer filters/}).click();
  const cachedState=page.locator('.profile-field-row').filter({has:page.getByText('State',{exact:true})});
  await cachedState.getByRole('button',{name:'State',exact:true}).click();
  const cachedDialog=page.getByRole('dialog',{name:'State',exact:true});
  await cachedDialog.getByRole('checkbox',{name:'State A',exact:true}).uncheck();
  await cachedDialog.getByRole('checkbox',{name:'State A',exact:true}).check();
  assert.ok(await cachedDialog.getByRole('checkbox',{name:'State B',exact:true}).isEnabled(),'State choices remain available when every worker is busy');
  await cachedDialog.getByRole('button',{name:'Done',exact:true}).click();
  state.vahanFilterOptionsV1=[];state.vahanSelectedFilterProfileV1='';state.vahanRunSettingsV1={year:2026,workerCount:2};
  delete state.vahanStateRtoBatchRecoveryV1;delete state.vahanActiveJobId;
  state.vahanStateRtoMatrixV1={year:2026,states:['Recorded State'],scenarios:[{name:'Recorded office',filters:{states:['Recorded State'],rtos:['Recorded Office'],fromYear:'2026',toYear:'2026',delhiNcr:'ALL STATES',yAxis:'Maker',xAxis:'Month Wise'}}]};
  await page.reload();await page.getByRole('heading',{name:'Filters',exact:true}).waitFor();
  await page.locator('.profile-field-row').filter({has:page.getByText('State',{exact:true})}).getByRole('button',{name:'State',exact:true}).click();
  const recorded=page.getByRole('dialog',{name:'State',exact:true});
  await recorded.getByRole('checkbox',{name:'Recorded State',exact:true}).check();
  await recorded.getByRole('button',{name:'Done',exact:true}).click();
  await page.locator('.profile-field-row').filter({has:page.getByText('RTO',{exact:true})}).getByRole('button',{name:'RTO',exact:true}).click();
  await page.getByRole('dialog',{name:'RTO',exact:true}).getByRole('checkbox',{name:'Recorded Office',exact:true}).waitFor();
  await page.keyboard.press('Escape');
  assert.deepEqual(errors,[]);console.log('Filters UI: dependent selections, SQL saves, live preview, home choice, two scopes at one RTO, year and reload passed.');
}finally{await browser.close();}
