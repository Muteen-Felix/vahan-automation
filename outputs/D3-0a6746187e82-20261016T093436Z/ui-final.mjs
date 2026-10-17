const {chromium}=require('playwright');const net=require('node:net');
const cfg=JSON.parse(process.env.D3_INPUT);
(async()=>{
 const forward=net.createServer(s=>{const u=net.connect(15187,'host.docker.internal');s.pipe(u);u.pipe(s);s.on('error',()=>u.destroy());u.on('error',()=>s.destroy());});
 await new Promise(r=>forward.listen(15187,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,chromiumSandbox:true});const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));let socketConnected=false;
 page.on('websocket',ws=>ws.on('framereceived',e=>{if(String(e.payload).startsWith('40/ui,'))socketConnected=true}));
 await page.goto(cfg.base);await page.getByLabel('Username',{exact:true}).fill(cfg.username);await page.getByLabel('Password',{exact:true}).fill(cfg.password);await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('navigation',{name:'Main navigation'}).waitFor();await page.waitForTimeout(2000);
 if(await page.locator('.network-notice').count())throw Error('Network notice still visible on exact staging Origin');
 const results={exports:[],downloadResponses:[],timeZones:[],screenshots:[],errors};
 page.on('response',async r=>{if(new URL(r.url()).pathname==='/api/annual-reports/export'){
  const headers=await r.allHeaders();results.downloadResponses.push({url:r.url(),status:r.status(),rowCount:Number(headers['x-report-row-count']),contentType:headers['content-type']});
 }});
 const shot=async(name)=>{await page.screenshot({path:'/tmp/d3-'+name+'.png',fullPage:true});results.screenshots.push('ui-final-'+name+'.png')};
 await page.goto(cfg.base+'/#reports');await page.getByLabel('Year',{exact:true}).selectOption('2018');await page.waitForTimeout(1800);
 const all=page.getByRole('button',{name:'Export all to Excel',exact:true});await all.waitFor();
 await all.click();let dialog=page.getByRole('dialog',{name:'Export the full report?'});await dialog.waitFor();
 await shot('export-all-confirm');results.exports.push({kind:'all',confirmation:await dialog.innerText()});
 await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
 await all.click();dialog=page.getByRole('dialog',{name:'Export the full report?'});let download=page.waitForEvent('download');await dialog.getByRole('button',{name:'Export to Excel',exact:true}).click();await(await download).saveAs('/tmp/d3-ui-export-all.xlsx');
 const filteredResponse=page.waitForResponse(r=>{const u=new URL(r.url());return u.pathname==='/api/annual-reports'&&u.searchParams.get('state')==='Karnataka'&&r.status()===200});
 await page.getByLabel('Search State',{exact:true}).fill('Karnataka');await filteredResponse;await page.waitForTimeout(500);
 await page.getByRole('button',{name:'Export filtered to Excel',exact:true}).click();dialog=page.getByRole('dialog',{name:'Export filtered results?'});await dialog.waitFor();await shot('export-filtered-confirm');results.exports.push({kind:'filtered',confirmation:await dialog.innerText()});
 download=page.waitForEvent('download');await dialog.getByRole('button',{name:'Export to Excel',exact:true}).click();await(await download).saveAs('/tmp/d3-ui-export-filtered.xlsx');await shot('reports');
 for(const [zone,label] of [['Asia/Kolkata','India time (UTC+05:30)'],['Asia/Ho_Chi_Minh','Vietnam time (UTC+07:00)']]){
  await page.goto(cfg.base+'/#settings');await page.getByRole('button',{name:'Account',exact:true}).click();await page.getByLabel('Display time zone',{exact:true}).selectOption(zone);await page.waitForTimeout(1200);await page.getByRole('button',{name:'Close account settings',exact:true}).click();
  await page.goto(cfg.base+'/#run-history');await page.waitForTimeout(1200);const text=await page.locator('body').innerText();if(!text.includes(label))throw Error('Run History does not display '+label);
  results.timeZones.push({zone,label,body:text});await shot(zone==='Asia/Kolkata'?'history-india':'history-vietnam');
  if(zone==='Asia/Ho_Chi_Minh'){
   results.history=await page.evaluate(async()=>{const r=await fetch('/api/annual-reports/run-history',{headers:{Authorization:'Bearer '+localStorage.getItem('vahanUiAccessToken')}});return r.json()});
   const rows=await page.locator('.run-history-table tbody tr').count();if(rows!==results.history.runs.length)throw Error('UI history row count differs from API');results.historyUIRows=rows;
  }
 }
 await page.goto(cfg.base+'/#settings');await page.getByRole('button',{name:'Account',exact:true}).click();await page.getByRole('button',{name:'Log out',exact:true}).click();await page.getByRole('heading',{name:'Welcome back'}).waitFor();
 results.logoutReturnedToLogin=true;results.uiSocketConnected=socketConnected;
 // Natural idle-expired test session, if due, must return the browser to login.
 if(cfg.idleToken && Date.now()/1000>cfg.idleExpiresAt+3){
  await page.evaluate(token=>localStorage.setItem('vahanUiAccessToken',token),cfg.idleToken);await page.reload();await page.getByRole('heading',{name:'Welcome back'}).waitFor();results.expiredSessionRedirectsToLogin=true;await shot('expired-session');
 }
 if(errors.length)throw Error('Browser page errors: '+errors.join(';'));
 console.log(JSON.stringify(results));await browser.close();await new Promise(r=>forward.close(r));
})().catch(e=>{console.error(e.message);process.exit(1)});
