import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';

const url=process.env.SOC_TEST_UI_URL;
if(!url?.startsWith('http://127.0.0.1:18080/')||!process.env.SOC_TEST_USER?.startsWith('soc-browser-'))throw new Error('Use the dedicated disposable SOC fixture.');
function otp(secret){
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';let bits='';
  for(const c of secret.replace(/=+$/,''))bits+=alphabet.indexOf(c).toString(2).padStart(5,'0');
  const bytes=[];for(let i=0;i+8<=bits.length;i+=8)bytes.push(parseInt(bits.slice(i,i+8),2));
  const counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));
  const digest=createHmac('sha1',Buffer.from(bytes)).update(counter).digest(),offset=digest[19]&15;
  return String((digest.readUInt32BE(offset)&0x7fffffff)%1000000).padStart(6,'0');
}
const browser=await chromium.launch({headless:true});
try{
  const context=await browser.newContext();const page=await context.newPage();const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);
  await page.getByLabel('Username',{exact:true}).fill(process.env.SOC_TEST_USER);
  await page.getByLabel('Password',{exact:true}).fill(process.env.SOC_TEST_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('heading',{name:'Set up two-step verification'}).waitFor();
  const secret=await page.locator('.auth-card code').innerText();
  await page.getByLabel('Verification code',{exact:true}).fill(otp(secret));
  await page.getByRole('button',{name:'Verify and continue'}).click();
  await page.getByRole('heading',{name:'Save your recovery codes'}).waitFor();
  assert.equal((await page.locator('.auth-card pre').innerText()).trim().split('\n').length,10);
  await page.getByRole('button',{name:'I saved the codes — open dashboard'}).click();
  await page.getByRole('navigation',{name:'Main navigation'}).waitFor();
  assert.equal(await page.evaluate(()=>localStorage.getItem('vahanUiAccessToken')),null);
  assert.ok(await page.evaluate(()=>localStorage.getItem('vahanUiSessionMarker')));
  assert.equal(await page.evaluate(()=>document.cookie.includes('vahan_session_')),false);
  const cookie=(await context.cookies()).find(value=>value.name==='vahan_session_soc-validation');
  assert.equal(cookie.httpOnly,true);assert.equal(cookie.sameSite,'Strict');
  const second=await context.newPage();await second.goto(url);
  await second.getByRole('navigation',{name:'Main navigation'}).waitFor();
  await page.getByRole('link',{name:'Settings',exact:true}).click();
  await page.getByRole('heading',{name:'Security operations',exact:true}).waitFor();
  await page.getByRole('button',{name:'Account',exact:true}).click();
  await page.getByRole('button',{name:'Log out',exact:true}).click();
  await page.getByRole('heading',{name:'Welcome back',exact:true}).waitFor();
  await second.getByRole('heading',{name:'Welcome back',exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('Live MFA UI, recovery codes, HttpOnly cookie, reload, security status and cross-tab logout passed.');
}finally{await browser.close();}
