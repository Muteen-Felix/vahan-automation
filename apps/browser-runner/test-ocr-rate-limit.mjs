import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source = readFileSync(new URL('./runner.mjs', import.meta.url), 'utf8');
const start = source.indexOf('async function autoSolveCaptcha(job, captchaId, imageDataUrl)');
const end = source.indexOf('async function status(', start);
assert.ok(start >= 0 && end > start);
assert.ok(!source.includes('OCR raw output:'));
assert.ok(!source.includes('Auto-OCR result:'));

function fixture(reservation) {
  const calls = [];
  const job = {jobId:'ocr-job', status:'WAITING_CAPTCHA', captchaId:'captcha-1'};
  const context = {
    active:job,
    http:async(path, init) => {
      calls.push('reserve');
      assert.equal(path, '/api/runner/ocr/start');
      assert.equal(JSON.stringify(JSON.parse(init.body)), JSON.stringify({jobId:'ocr-job', captchaId:'captcha-1'}));
      return reservation;
    },
    runImageCommand:async() => {calls.push('ocr'); return {stdout:'AB C123'};},
    imageBytes:() => Buffer.from('fixture'),
    process:{env:{}},
    saveState:async() => calls.push('save-state'),
    submitCaptchaInternal:async(_job, _captchaId, value) => calls.push(`submit:${value}`),
    refreshCaptchaInternal:async() => calls.push('refresh'),
    console:{log:(...values) => calls.push(`log:${values.join(' ')}`), error:(...values) => calls.push(`error:${values.join(' ')}`)},
  };
  const run = runInNewContext(source.slice(start, end) + '\nautoSolveCaptcha', context);
  return {run, context, job, calls};
}

const allowed = fixture({allowed:true, remaining:19});
await allowed.run(allowed.job, 'captcha-1', 'data:image/png;base64,AA==');
assert.deepEqual(allowed.calls.slice(0, 2), ['reserve', 'ocr']);
assert.ok(allowed.calls.includes('submit:ABC123'));

const limited = fixture({allowed:false, code:'OCR_RATE_LIMIT', error:'OCR_RATE_LIMIT: system limit'});
await limited.run(limited.job, 'captcha-1', 'data:image/png;base64,AA==');
assert.equal(limited.job.status, 'FAILED');
assert.equal(limited.context.active, null);
assert.deepEqual(limited.calls, ['reserve', 'save-state']);

const duplicate = fixture({allowed:false, code:'OCR_ALREADY_STARTED'});
await duplicate.run(duplicate.job, 'captcha-1', 'data:image/png;base64,AA==');
assert.equal(duplicate.job.status, 'WAITING_CAPTCHA');
assert.equal(duplicate.context.active, duplicate.job);
assert.deepEqual(duplicate.calls, ['reserve']);

const cancelled = fixture({allowed:true});
cancelled.context.http = async() => {
  cancelled.calls.push('reserve');
  cancelled.job.cancelled = true;
  return {allowed:true};
};
await cancelled.run(cancelled.job, 'captcha-1', 'data:image/png;base64,AA==');
assert.deepEqual(cancelled.calls, ['reserve']);

console.log('OCR rate-limit runner checks passed: shared reservation precedes Tesseract, denied work stops without refreshing, and OCR text is not logged.');
