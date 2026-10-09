import assert from 'node:assert/strict';
import {saveWithBackpressure} from './save-pressure.mjs';
const busy=()=>Object.assign(new Error('SQL busy'),{status:503,code:'DATABASE_BUSY',retryAfter:3});
let calls=0,waits=[];
assert.deepEqual(await saveWithBackpressure(async()=>{if(++calls<3)throw busy();return {status:'COMPLETED'};},{sleep:async ms=>waits.push(ms)}),{status:'COMPLETED'});
assert.equal(calls,3);assert.deepEqual(waits,[3000,6000]);
for(const error of [Object.assign(new Error('parse'),{status:400}),Object.assign(new Error('checksum'),{status:409}),new Error('unknown transport state'),Object.assign(new Error('unclassified 503'),{status:503})]){
 calls=0;await assert.rejects(saveWithBackpressure(async()=>{calls++;throw error;},{sleep:async()=>{throw new Error('must not replay');}}),e=>e===error);assert.equal(calls,1);
}
calls=0;let cancelled=false;
await assert.rejects(saveWithBackpressure(async()=>{calls++;throw busy();},{check:()=>{if(cancelled)throw new Error('cancelled');},sleep:async()=>{cancelled=true;}}),/cancelled/);assert.equal(calls,1);
calls=0;await assert.rejects(saveWithBackpressure(async()=>{calls++;throw busy();},{sleep:async()=>{},maxAttempts:3}),/SQL busy/);assert.equal(calls,3);
console.log('SQL save backpressure: bounded retry, cancellation, checksum rejection and no ambiguous transport replay passed.');
