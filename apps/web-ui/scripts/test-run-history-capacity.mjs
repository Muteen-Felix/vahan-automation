import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createServer} from 'vite';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const server=await createServer({root,server:{host:'127.0.0.1',port:5194,strictPort:true}});
await server.listen();
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),details=[],errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>localStorage.setItem('vahanUiAccessToken','fixture'));
 await page.route('https://fonts.googleapis.com/**',r=>r.abort());await page.route('https://fonts.gstatic.com/**',r=>r.abort());
 const summary={sessionId:'fixture-session',sessionFolder:'fixture-session',startedAt:'2026-10-08T10:00:00Z',updatedAt:'2026-10-08T11:00:00Z',jobCount:2500,completedCount:2500,noDataCount:0,failedCount:0,cancelledCount:0,activeCount:0,fileCount:0,totalFileSize:0,sources:['new'],jobs:[]};
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url());let body=[];
  if(url.pathname==='/api/jobs/reports/sessions')body=[summary];
  else if(url.pathname.endsWith('/fixture-session')){
   const offset=Number(url.searchParams.get('offset'));details.push(offset);
   assert.equal(url.searchParams.get('limit'),'100');
   body={...summary,offset,limit:100,hasMore:true,jobs:Array.from({length:100},(_,i)=>({jobId:`job-${offset+i}`,scenarioName:`Office ${offset+i}`,state:'ASSAM',rto:'AS27',status:'COMPLETED',source:'new',filters:{states:['ASSAM']},fileSize:0,createdAt:summary.startedAt,updatedAt:summary.updatedAt}))};
  }
  await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto('http://127.0.0.1:5194/scripts/fixtures/run-history.html');
 const button=page.getByRole('button',{name:'View details (2500)',exact:true});await button.waitFor();assert.deepEqual(details,[]);
 await button.click();const dialog=page.getByRole('dialog',{name:'Session details'});
 await dialog.getByRole('status').getByText('1–100 of 2500 cases',{exact:true}).waitFor();
 assert.equal(await dialog.locator('.report-detail-case').count(),100);assert.deepEqual(details,[0]);
 await dialog.getByRole('button',{name:'Next cases',exact:true}).click();
 await dialog.getByRole('status').getByText('101–200 of 2500 cases',{exact:true}).waitFor();
 assert.equal(await dialog.locator('.report-detail-case').count(),100);assert.deepEqual(details,[0,100]);
 await dialog.getByRole('button',{name:'Previous cases',exact:true}).click();
 await dialog.getByRole('status').getByText('1–100 of 2500 cases',{exact:true}).waitFor();
 await dialog.getByRole('button',{name:'Close details',exact:true}).click();await dialog.waitFor({state:'hidden'});
 assert.deepEqual(errors,[]);console.log('Run history: summary-only polling, lazy details and bounded 100-case pages passed.');
}finally{await browser.close();await server.close();}
