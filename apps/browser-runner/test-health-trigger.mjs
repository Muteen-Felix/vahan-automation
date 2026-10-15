import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('./runner.mjs',import.meta.url),'utf8');
const events=new Map();
const calls=[];
const context={socket:{connected:true,on:(name,handler)=>events.set(name,handler)},
  consumeQueue:()=>{},active:null,optionsBusy:false,stopping:false,launch:async()=>calls.push('launch'),
  ack:async name=>{calls.push(name);return {};},saveState:async()=>calls.push('save'),
  http:async path=>{throw new Error(`Unexpected health schedule request: ${path}`);},console,
  healthCheck:async (request,extra)=>{assert.equal(context.optionsBusy,true);context.startedAtSeen=extra?.startedAt;calls.push(request);return {validation:{allowed:true}};},
  HEALTH_BUDGET:{finishWait:50},setTimeout,clearTimeout,
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
assert.equal(source.includes("socket.on('ui-health:run-now'"),false,'The retired manual-check event is not registered');
runInNewContext(source.slice(source.indexOf("socket.on('ui-health:preflight'"),source.indexOf('const timer = setInterval(')),context);
const request={requestId:'session-check',trigger:'preflight'};
let reply;
await events.get('ui-health:preflight')(request,value=>{reply=value;});
assert.equal(calls.length,1);assert.equal(calls[0],request);assert.equal(reply.ok,true);assert.equal(context.optionsBusy,false);
context.active={jobId:'running-job'};
await events.get('ui-health:preflight')(request,value=>{reply=value;});
assert.equal(reply.ok,false);assert.equal(calls.length,1,'A busy report worker is not interrupted by another check');
// The check shares one deadline with the wait for a finishing job: it must not wait forever.
context.active={jobId:'finishing-job',finishing:true,finishPromise:new Promise(()=>{})};
const waitStarted=Date.now();
await events.get('ui-health:preflight')(request,value=>{reply=value;});
assert.equal(reply.ok,false);assert.equal(reply.code,'RUNNER_BUSY');
assert.ok(Date.now()-waitStarted<2000,'a job that never finishes is answered as busy within the finish wait');
assert.equal(calls.length,1,'no check ran');
context.active=null;
await events.get('ui-health:preflight')(request,value=>{reply=value;});
assert.equal(reply.ok,true);
assert.equal(typeof calls.at(-1),'object');
assert.equal(typeof context.startedAtSeen,'number','the handler passes the time it received the request');
console.log('Runner health checks: explicit preflight only, no connection/heartbeat schedule, and busy-job protection passed.');
