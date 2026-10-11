import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {chromium} from 'playwright';
import {inspectControls} from './ui-health-contract.mjs';

const source=readFileSync(new URL('./runner.mjs',import.meta.url),'utf8');
const code=source.slice(source.indexOf('async function healthCheck('),source.indexOf("socket.on('ui-health:preflight'"))+'\nhealthCheck';
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
  const run=runInNewContext(code,{browser,context,launch:async()=>{},URL:origin+'/report',target:new URL(origin+'/report'),
    globalThis:{URL},Date,ID:'fixture-worker',randomUUID:()=> 'fixture-check',inspectControls,
    http:async(path,options)=>{
      if(path==='/api/ui-health/contract') return {controls,revision:1};
      assert.equal(path,'/api/ui-health/logs');saved=JSON.parse(options.body).healthCheck;
      return {ok:true,validation:{allowed:saved.status==='PASS'}};
    }});
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
