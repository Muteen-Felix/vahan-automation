// No API or Socket.IO mocks: check the installed production build with real sessions/data.
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';

const base = process.env.INSTALLED_UI_URL;
const artifacts = process.env.UI_TEST_ARTIFACT_DIR;
assert.ok(base && artifacts && process.env.REVIEW_ADMIN_PASSWORD && process.env.REVIEW_MEMBER_PASSWORD,
  'Use test-review-package.py to supply isolated URLs and private credentials.');
await mkdir(artifacts,{recursive:true});
const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
const results = [];
try {
  const context = await browser.newContext({viewport:{width:1440,height:1000}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror',error=>errors.push(error.message));
  const login = async (target, username, password) => {
    await target.goto(base+'/#reports');
    await target.getByLabel('Username',{exact:true}).fill(username);
    await target.getByLabel('Password',{exact:true}).fill(password);
    await target.getByRole('button',{name:'Sign in',exact:true}).click();
    await target.getByRole('heading',{name:'Exported Reports',exact:true}).waitFor();
  };
  await login(page,process.env.REVIEW_ADMIN_USERNAME || 'admin',process.env.REVIEW_ADMIN_PASSWORD);
  await page.getByRole('rowheader',{name:'ROUND5 SYNTHETIC MAKER 0000',exact:true}).waitFor();
  assert.equal(await page.locator('.annual-table tbody tr').count(),100);
  results.push('Real admin login and paginated synthetic SQL reports on the Nginx build.');
  let requestedExports=0;
  page.on('request',request=>{if(new URL(request.url()).pathname==='/api/annual-reports/export') requestedExports++;});
  page.once('dialog',async dialog=>{assert.match(dialog.message(),/1,000/);await dialog.dismiss();});
  await page.getByRole('button',{name:'Export all to Excel',exact:true}).click();
  assert.equal(requestedExports,0,'cancelled export must not call the real download API');
  page.once('dialog',dialog=>dialog.accept());
  const download = page.waitForEvent('download');
  await page.getByRole('button',{name:'Export all to Excel',exact:true}).click();
  await (await download).saveAs(join(artifacts,'ui-export-all-SYNTHETIC.xlsx'));
  await page.getByLabel('Search State').fill('ROUND5');
  await page.waitForFunction(()=>document.querySelector('.annual-export-button')?.disabled===false);
  page.once('dialog',dialog=>dialog.accept());
  const filteredDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export filtered to Excel',exact:true}).click();
  await (await filteredDownload).saveAs(join(artifacts,'ui-export-filtered-SYNTHETIC.xlsx'));
  results.push('Real UI export confirmation cancel/accept; full and filtered workbook downloads.');
  await page.screenshot({path:join(artifacts,'installed-reports-1440.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:join(artifacts,'installed-reports-390.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('link',{name:'Run History',exact:true}).click();
  await page.getByRole('heading',{name:'Run History',exact:true}).waitFor();
  await page.getByRole('link',{name:'Settings',exact:true}).click();
  await page.getByRole('heading',{name:'Automatic report schedule',exact:true}).waitFor();
  assert.equal(await page.getByLabel('Parallel task limit',{exact:true}).count(),0);
  assert.equal(await page.getByLabel('Number of workers',{exact:true}).count(),0);
  results.push('Admin Run History/Settings navigation; removed schedule worker inputs absent; responsive reports.');

  const memberContext=await browser.newContext();
  const memberPage=await memberContext.newPage();
  const privateRequests=[];
  memberPage.on('request',request=>{
    if(['/api/annual-reports/run-history','/api/run-schedules','/api/filter-profiles','/api/users'].includes(new URL(request.url()).pathname))
      privateRequests.push(new URL(request.url()).pathname);
  });
  await login(memberPage,'round5-member',process.env.REVIEW_MEMBER_PASSWORD);
  await memberPage.getByRole('rowheader',{name:'ROUND5 SYNTHETIC MAKER 0000',exact:true}).waitFor();
  for(const name of ['Run History','Settings','Filters']) assert.equal(await memberPage.getByRole('link',{name,exact:true}).count(),0);
  // A hash-only goto keeps the current SPA mounted. Use a fresh document to
  // exercise the initial direct-route redirect with the existing real session.
  await memberPage.goto('about:blank');
  await memberPage.goto(base+'/#run-history');
  await memberPage.getByRole('heading',{name:'Exported Reports',exact:true}).waitFor();
  assert.equal(new URL(memberPage.url()).hash,'#reports');
  assert.deepEqual(privateRequests,[]);
  assert.deepEqual(errors,[],'installed admin dashboard must have no JavaScript exceptions');
  results.push('Real member login: reports visible, private navigation/direct history route denied, no private API requests.');
  console.log(JSON.stringify({scope:'Real installed Nginx build + production API/SQL; explicitly synthetic report data',passed:true,results},null,2));
} finally {await browser.close();}
