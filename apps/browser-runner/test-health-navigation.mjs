import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {chromium} from 'playwright';
import {inspectControls} from './ui-health-contract.mjs';
import {runHealthCheck, StateStore} from './health-cookie-recovery.mjs';

const controls=[{field:'states',selector:'#stateName',tag:'select',multiple:true},
  {field:'apply',selector:'#applyTrigger',tag:'button'}];
let mode='slow-assets';
const server=createServer((req,res)=>{
  if(req.url==='/pending.js') return; // Leave an asset pending after the document commits.
  if(mode==='http-error') {res.writeHead(503);res.end('Unavailable');return;}
  if(mode==='redirect' && req.url==='/report') {res.writeHead(302,{Location:'/other'});res.end();return;}
  res.setHeader('Content-Type','text/html');
  res.end('<select id="stateName" multiple><option>State</option></select><button id="applyTrigger">Apply</button><script src="/pending.js"></script>');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true});
const context=await browser.newContext();
try {
  let saved;
  let revision=1;
  const http=async(path,options={})=>{
    if(path==='/api/ui-health/contract') return {controls,revision:1};
    if(path==='/api/runner-state/fixture-worker') return options.method==='PUT'?{ok:true,revision:++revision}:{state:null,revision};
    assert.equal(path,'/api/ui-health/logs');saved=JSON.parse(options.body).healthCheck;
    assert.ok(options.timeoutMs>0,'the log POST always gets a positive timeout');
    return {ok:true,validation:{allowed:saved.status==='PASS'}};
  };
  const deps={browser:()=>browser,context:()=>context,launch:async()=>{},http,URL:origin+'/report',target:new URL(origin+'/report'),
    ID:'fixture-worker',randomUUID:()=> 'fixture-check',inspectControls,epoch:()=>1,isTainted:()=>false,setTainted(){},
    markPageNeedsReset(){},rebuildPrimary:async()=>{},UrlCtor:URL,
    store:new StateStore({http,id:'fixture-worker'})};
  deps.store.setRevision(revision);
  const run=request=>runHealthCheck(deps,request);
  const started=Date.now();
  const passing=await run({requestId:'pending-asset'});
  assert.equal(passing.validation.allowed,true);
  assert.equal(saved.status,'PASS');
  assert.equal(saved.observedControls.length,2);
  assert.ok(Date.now()-started<5000,'A committed report must not wait for the unfinished script');
  for(const [value,pattern] of [['http-error',/HTTP 503/],['redirect',/expected public report/]]) {
    mode=value;await run({requestId:value});
    assert.equal(saved.status,'CHECK_ERROR');assert.match(saved.error,pattern);
    assert.deepEqual(Array.from(saved.observedControls),[]);
  }
  assert.equal(browser.contexts().length,1,'Every isolated health-check context is closed');
  console.log('Health navigation: unfinished assets, HTTP failure, redirected page and isolated-context cleanup passed.');
} finally {await context.close();await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
