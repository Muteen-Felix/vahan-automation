import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source = readFileSync(new URL('./runner.mjs', import.meta.url), 'utf8');
const start = source.indexOf('async function autoSolveCaptcha(job, captchaId, imageDataUrl)');
const end = source.indexOf('async function status(', start);
assert.ok(start >= 0 && end > start);
assert.ok(!source.includes('OCR raw output:'));
assert.ok(!source.includes('Auto-OCR result:'));

function fixture() {
  const calls = [];
  const context = {
    active:null,
    http:async(path, init) => {
      calls.push('start');
      assert.equal(path, '/api/runner/ocr/start');
      const payload = JSON.parse(init.body);
      assert.equal(payload.jobId, context.active.jobId);
      assert.equal(payload.captchaId, context.active.captchaId);
      return {allowed:true};
    },
    runImageCommand:async() => {calls.push('ocr'); return {stdout:'AB C123'};},
    imageBytes:() => Buffer.from('fixture'),
    process:{env:{}},
    submitCaptchaInternal:async(_job, _captchaId, value) => calls.push(`submit:${value}`),
    refreshCaptchaInternal:async() => calls.push('refresh'),
    console:{log:(...values) => calls.push(`log:${values.join(' ')}`), error:(...values) => calls.push(`error:${values.join(' ')}`)},
  };
  const run = runInNewContext(source.slice(start, end) + '\nautoSolveCaptcha', context);
  return {run, context, calls};
}

const many = fixture();
for (let index = 0; index < 25; index++) {
  const job = {jobId:`ocr-job-${index}`, status:'WAITING_CAPTCHA', captchaId:`captcha-${index}`};
  many.context.active = job;
  await many.run(job, job.captchaId, 'data:image/png;base64,AA==');
}
assert.equal(many.calls.filter(call => call === 'start').length, 25);
assert.equal(many.calls.filter(call => call === 'ocr').length, 25);
assert.equal(many.calls.filter(call => call.startsWith('submit:')).length, 25);

const duplicate = fixture();
const sameJob = {jobId:'duplicate-job', status:'WAITING_CAPTCHA', captchaId:'same-challenge'};
duplicate.context.active = sameJob;
await Promise.all([
  duplicate.run(sameJob, sameJob.captchaId, 'data:image/png;base64,AA=='),
  duplicate.run(sameJob, sameJob.captchaId, 'data:image/png;base64,AA=='),
]);
assert.equal(duplicate.calls.filter(call => call === 'start').length, 1);
assert.equal(duplicate.calls.filter(call => call === 'ocr').length, 1);
assert.equal(duplicate.calls.filter(call => call.startsWith('submit:')).length, 1);

const stale = fixture();
const staleJob = {jobId:'stale-job', status:'WAITING_CAPTCHA', captchaId:'captcha-1', refreshingCaptchaId:'captcha-1'};
stale.context.active = staleJob;
await stale.run(staleJob, staleJob.captchaId, 'data:image/png;base64,AA==');
assert.deepEqual(stale.calls, []);

console.log('OCR start checks passed: 25 runner starts are allowed, duplicate work for one challenge is suppressed locally, and active CAPTCHA guards remain.');
