import harness as h
import subprocess,json
container=h.ENV['project']+'-runner-3'
payload={'base':h.ENV['baseUrl'],'username':h.CONFIG.get('VAHAN_UI_AUTH_USERNAME','admin'),'password':h.CONFIG['VAHAN_UI_AUTH_PASSWORD']}
script="""
const {chromium}=require('playwright');const net=require('node:net');
const cfg=JSON.parse(process.env.D3_INPUT);
(async()=>{
 // Transparent TCP forwarding keeps the browser's exact approved staging Origin.
 // All HTTP/WebSocket bytes still reach the real packaged web/API services.
 const forward=net.createServer(s=>{const u=net.connect(15187,'host.docker.internal');s.pipe(u);u.pipe(s);s.on('error',()=>u.destroy());u.on('error',()=>s.destroy());});
 await new Promise(resolve=>forward.listen(15187,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true,chromiumSandbox:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}); const errors=[];let uiSocketConnected=false;
 page.on('websocket',ws=>ws.on('framereceived',e=>{if(String(e.payload).startsWith('40/ui,'))uiSocketConnected=true}));
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(cfg.base,{waitUntil:'networkidle'});
 await page.getByLabel('Username',{exact:true}).fill(cfg.username);
 await page.getByLabel('Password',{exact:true}).fill(cfg.password);
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('navigation',{name:'Main navigation'}).waitFor({timeout:30000});
 const results=[];
 for(const hash of ['#reports','#filters','#settings-ui-health','#run-history','#settings']) {
  await page.goto(cfg.base+'/'+hash);await page.waitForTimeout(2200);
  const text=await page.locator('body').innerText();
  await page.screenshot({path:'/tmp/d3-'+hash.slice(1)+'.png',fullPage:true});
  results.push({hash,title:await page.title(),body:text,screenshot:'ui-'+hash.slice(1)+'.png'});
 }
 await page.getByRole('button',{name:/account/i}).click();
 await page.getByRole('button',{name:'Log out',exact:true}).click();
 await page.getByRole('heading',{name:'Welcome back'}).waitFor();
 await page.screenshot({path:'/tmp/d3-logout.png'});
 console.log(JSON.stringify({results,errors,uiSocketConnected,logoutReturnedToLogin:true}));await browser.close();await new Promise(resolve=>forward.close(resolve));
})().catch(e=>{console.error(e.message);process.exit(1)});
"""
# Pass credentials only through exec stdin, never in command arguments or evidence.
wrapper='process.env.D3_INPUT='+json.dumps(json.dumps(payload))+';\n'+script
r=subprocess.run(['docker','exec','-i',container,'node'],input=wrapper,capture_output=True,text=True,encoding='utf-8',timeout=150)
h.save('browser-ui-'+('pass' if r.returncode==0 else 'harness-attempt')+'.json',{'at':h.now(),'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
assert r.returncode==0,h.clean(r.stderr)
data=json.loads(r.stdout);assert not data['errors'],data['errors'];assert data['uiSocketConnected'],'UI socket did not connect with exact staging Origin'
for entry in data['results']:
    result=h.cmd(['docker','cp',container+':/tmp/d3-'+entry['hash'][1:]+'.png',str(h.ROOT/entry['screenshot'])]);assert result['returncode']==0
h.cmd(['docker','cp',container+':/tmp/d3-logout.png',str(h.ROOT/'ui-logout.png')])
print(json.dumps({'pages':[x['hash'] for x in data['results']],'pageErrors':data['errors'],'logout':True}))
