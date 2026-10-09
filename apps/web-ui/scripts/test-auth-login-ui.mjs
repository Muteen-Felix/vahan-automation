import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';
const origin=process.env.NAV_UI_URL || 'http://127.0.0.1:5184/';
const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || undefined});
async function scenario(retryAfter) {
 const context=await browser.newContext();
 let authenticated=false, attempts=0;
 const requests=[],errors=[];
 await context.routeWebSocket('**/socket.io/**',socket=>{
  socket.send('0'+JSON.stringify({sid:'login-fixture',upgrades:[],pingInterval:60000,pingTimeout:60000}));
  socket.onMessage(message=>{if(String(message).startsWith('40/ui,'))socket.send('40/ui,'+JSON.stringify({sid:'login-ui'}));});
 });
 await context.route('**/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  requests.push(path);
  let body=[];
  if(path==='/api/auth/status')body={configured:true,adminMfaRequired:false};
  else if(path==='/api/auth/me'){
   if(!authenticated)return route.fulfill({status:401,json:{detail:'Sign in first'}});
   body={username:'fixture',role:'admin',csrfToken:'fixture-csrf'};
  } else if(path==='/api/auth/login'){
   attempts++;
   assert.equal(request.postDataJSON().otp,undefined);
   if(retryAfter!==undefined && attempts===1)return route.fulfill({status:429,headers:retryAfter?{'Retry-After':retryAfter}:{},json:{detail:'Too many requests. Please try again later.'}});
   if(request.postDataJSON().password!=='Fixture password')return route.fulfill({status:401,json:{detail:'The username or password is incorrect.'}});
   authenticated=true;
   body={accessToken:null,sessionMarker:'fixture-marker',csrfToken:'fixture-csrf',username:'fixture',tokenType:'Cookie',expiresIn:43200};
  } else if(path==='/api/user-state')body={};
  else if(path==='/api/network/status')body={online:true};
  else if(path==='/api/ui-health/status')body={blocked:false};
  else if(path==='/api/annual-reports')body={year:2026,datasets:[],years:[2026],states:[],rtos:[],rows:[],coverage:[],summary:{rows:0,makers:0,offices:0}};
  await route.fulfill({json:body});
 });
 try {
  const page=await context.newPage();
  page.on('pageerror',error=>errors.push(error.message));
  if(retryAfter!==undefined)await page.clock.install();
  await page.goto(origin);
  await page.getByRole('heading',{name:'Welcome back',exact:true}).waitFor();
  assert.equal(await page.getByLabel('Verification code',{exact:true}).count(),0);
  await page.getByLabel('Username',{exact:true}).fill('fixture');
  await page.getByLabel('Password',{exact:true}).fill(retryAfter===undefined?'Wrong password':'Fixture password');
  const button=page.getByRole('button',{name:'Sign in',exact:true});
  await button.click();
  if(retryAfter!==undefined){
   await page.getByRole('alert').filter({hasText:retryAfter?'Try again in 0:03.':'Try again in 1:00.'}).waitFor();
   assert.equal(await button.isDisabled(),true);
   await page.locator('form').evaluate(form=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
   assert.equal(attempts,1);
   await page.clock.fastForward(retryAfter?4000:61000);
   assert.equal(await button.isDisabled(),false);
  }else{
   await page.getByRole('alert').filter({hasText:'The username or password is incorrect.'}).waitFor();
   assert.equal(await page.getByRole('navigation',{name:'Main navigation'}).count(),0);
   await page.getByLabel('Password',{exact:true}).fill('Fixture password');
  }
  await button.click();
  await page.getByRole('navigation',{name:'Main navigation'}).waitFor();
  assert.equal(requests.some(path=>path.startsWith('/api/auth/mfa/')),false);
  assert.equal(await page.getByRole('heading',{name:'Set up two-step verification'}).count(),0);
  const stored=await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}));
  assert.equal(stored.includes('Fixture password'),false);
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
}
try{
 for(const retryAfter of [undefined,'3',null])await scenario(retryAfter);
 console.log('Password login UI: direct dashboard access, invalid-password rejection and rate-limit countdown passed.');
}finally{await browser.close();}
