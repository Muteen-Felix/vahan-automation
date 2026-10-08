import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('./runner.mjs',import.meta.url),'utf8');
const events=new Map();
const calls=[];
const context={socket:{connected:true,on:(name,handler)=>events.set(name,handler)},
  active:null,optionsBusy:false,stopping:false,launch:async()=>calls.push('launch'),
  ack:async name=>{calls.push(name);return {};},saveState:async()=>calls.push('save'),
  http:async path=>{throw new Error(`Unexpected health schedule request: ${path}`);},console,
  healthCheck:async request=>{assert.equal(context.optionsBusy,true);calls.push(request);return {validation:{allowed:true}};},
  Date:{now:()=>Date.parse('2099-01-01T00:00:00Z')},setInterval:handler=>{context.heartbeat=handler;return 1;},
};
runInNewContext(source.slice(source.indexOf("socket.on('connect', async"),source.indexOf("socket.on('connect_error'")),context);
await events.get('connect')();
assert.deepEqual(calls,['runner:recover','launch'],'Connecting a worker does not load a periodic check schedule');
calls.length=0;
runInNewContext(source.slice(source.indexOf('const timer = setInterval('),source.indexOf('createServer((request, response)')),context);
await context.heartbeat();
assert.deepEqual(calls,['runner:heartbeat','save'],'Even at a future time, heartbeat does not open a health-check tab');
calls.length=0;
runInNewContext(source.slice(source.indexOf("socket.on('ui-health:preflight'"),source.indexOf("socket.on('ui-health:run-now'")),context);
const request={requestId:'session-check',trigger:'preflight'};
let reply;
await events.get('ui-health:preflight')(request,value=>{reply=value;});
assert.equal(calls.length,1);assert.equal(calls[0],request);assert.equal(reply.ok,true);assert.equal(context.optionsBusy,false);
context.active={jobId:'running-job'};
await events.get('ui-health:preflight')(request,value=>{reply=value;});
assert.equal(reply.ok,false);assert.equal(calls.length,1,'A busy report worker is not interrupted by another check');
console.log('Runner health checks: explicit preflight only, no connection/heartbeat schedule, and busy-job protection passed.');
