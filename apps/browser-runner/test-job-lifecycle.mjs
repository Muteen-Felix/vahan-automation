import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

// Execute the actual worker submission function without launching a worker or
// accessing VAHAN. These tests supply an operator's value; no solver is used.
const source = readFileSync(new URL('./runner.mjs', import.meta.url), 'utf8');
const start = source.indexOf('async function submitCaptchaInternal(');
const end = source.indexOf('async function autoSolveCaptcha(', start);
assert.ok(start >= 0 && end > start);

function fixture(backendState = 'WAITING_CAPTCHA', rejectSubmitting = false, rejectVerification = false) {
  const calls = [];
  let storedState = backendState;
  const job = {jobId: 'fixture-job', status: 'WAITING_CAPTCHA', filters: {rtos: ['Port Blair DTO - AN1']}};
  const context = {
    RESULT_TIMEOUT: 5000,
    randomUUID: () => 'click-id',
    normalizeJobFilters: value => value,
    page: {
      evaluate: async (fn, value) => {
        if (fn.toString().includes('verifyFilters')) {
          calls.push('verify');
          if (rejectVerification) throw new Error('FILTER_VERIFICATION_FAILED');
          return {checks: []};
        }
        return value ? calls.push('prepare') : {captchaId: 'operator-challenge'};
      },
      locator: selector => ({
        fill: async () => calls.push('fill'),
        click: async () => { assert.equal(storedState, 'SUBMITTING'); calls.push('click'); },
      }),
    },
    assertCurrent: candidate => assert.equal(candidate, job),
    challenge: async () => calls.push('refresh'),
    status: async (status, _error, candidate) => {
      calls.push(status);
      if (rejectSubmitting) throw new Error('Job changed before submission.');
      storedState = status; candidate.status = status;
    },
    ack: async (event, payload) => {
      assert.equal(storedState, 'SUBMITTING'); assert.equal(payload.jobId, job.jobId);
      calls.push(event === 'job:filters-verified' ? 'save-verification' : 'record-apply'); return {ok: true};
    },
    waitForResult: async () => calls.push('read-result'),
    fail: async error => calls.push(`failed: ${error.message}`),
  };
  const submit = runInNewContext(`${source.slice(start, end)}\nsubmitCaptchaInternal`, context);
  return {submit, job, calls, context};
}

for (const initial of ['WAITING_CAPTCHA', 'SUBMITTING']) {
  const {submit, job, calls} = fixture(initial);
  assert.equal((await submit(job, 'operator-challenge', 'ABC123')).ok, true);
  assert.deepEqual(calls, ['SUBMITTING', 'verify', 'save-verification', 'fill', 'prepare', 'click', 'record-apply', 'WAITING_RESULT', 'read-result']);
  assert.equal(job.status, 'WAITING_RESULT');
}
const denied = fixture('WAITING_CAPTCHA', true);
assert.equal((await denied.submit(denied.job, 'operator-challenge', 'ABC123')).ok, false);
assert.ok(!denied.calls.includes('click'));
const stale = fixture();
assert.equal((await stale.submit(stale.job, 'old-challenge', 'ABC123')).ok, true);
assert.deepEqual(stale.calls, ['refresh']);
const duplicate = fixture();
const submissions = await Promise.all([
  duplicate.submit(duplicate.job, 'operator-challenge', 'ABC123'),
  duplicate.submit(duplicate.job, 'operator-challenge', 'ABC123'),
]);
assert.equal(submissions.filter(result => result.ok).length, 1);
assert.equal(duplicate.calls.filter(call => call === 'click').length, 1);
const mismatch = fixture('WAITING_CAPTCHA', false, true);
assert.equal((await mismatch.submit(mismatch.job, 'operator-challenge', 'ABC123')).ok, false);
assert.ok(!mismatch.calls.includes('click'));
console.log('6 worker lifecycle checks passed: submission state, UI state, cancellation, stale challenge, duplicate submission and mismatched filters.');

const resultStart = source.indexOf('async function waitForResult(');
const resultEnd = source.indexOf("socket.on('connect'", resultStart);
assert.ok(resultStart >= 0 && resultEnd > resultStart);
const official = 'https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en';
const homepage = 'https://analytics.parivahan.gov.in/analytics/home';
function resultFixture(initialUrl, evaluate, load) {
  const job = {jobId: 'result-job', filters: {rtos: ['KAMRUP(RURAL) - AS25']}};
  let url = initialUrl;
  let evaluations = 0;
  const context = {
    URL, target: new URL(official), RESULT_TIMEOUT: 90_000, active: job, authRequired: false,
    assertCurrent: () => {},
    page: {url: () => url, evaluate: async () => {evaluations++; return evaluate();},
      waitForLoadState: async () => {url = load || url;}},
  };
  const wait = runInNewContext(`${source.slice(resultStart, resultEnd)}\nwaitForResult`, context);
  return {wait: () => wait(job), evaluations: () => evaluations};
}
const alreadyAway = resultFixture(homepage, () => ({type: 'TIMEOUT'}));
await assert.rejects(alreadyAway.wait(), /VAHAN_REPORT_NAVIGATED_AWAY/);
assert.equal(alreadyAway.evaluations(), 0, 'a redirected page must fail without waiting 90 seconds');
const redirected = resultFixture(official, () => {throw new Error('Execution context was destroyed');}, homepage);
await assert.rejects(redirected.wait(), /VAHAN_REPORT_NAVIGATED_AWAY/);
assert.equal(redirected.evaluations(), 1, 'navigation after Apply is classified before a second result wait');
const stalled = resultFixture(official, () => ({type: 'TIMEOUT'}));
await assert.rejects(stalled.wait(), /VAHAN_RESULT_TIMEOUT/);
console.log('Report navigation away is distinct from a genuine result timeout.');
