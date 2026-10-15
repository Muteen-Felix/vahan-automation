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
    approvedApplySelector: '#applyTrigger',
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
        click: async options => { assert.equal(options.noWaitAfter, true); assert.equal(storedState, 'SUBMITTING'); calls.push('click'); },
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
const renamedApply = fixture();renamedApply.context.approvedApplySelector='#verifiedApply';
const originalLocator=renamedApply.context.page.locator;
renamedApply.context.page.locator=selector=>{
  if(selector!=='#externalCaptcha')assert.equal(selector,'#verifiedApply','Apply uses the SQL-approved renamed control');
  return originalLocator(selector);
};
assert.equal((await renamedApply.submit(renamedApply.job,'operator-challenge','ABC123')).ok,true);
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
    setTimeout: callback => queueMicrotask(callback),
    assertCurrent: () => {},
    page: {url: () => url, evaluate: async () => {evaluations++; return evaluate();},
      waitForLoadState: async () => {if (evaluations) url = load || url;}},
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

const openingStart = source.indexOf('async function ensurePage(');
const openingEnd = source.indexOf('async function saveState(', openingStart);
function openingFixture({initial = 'about:blank', gotoError, responseStatus = 200, redirect, controlError} = {}) {
  let current = initial;
  const calls = [];
  const context = {
    pageNeedsReset:false, retireReportPage:async()=>{}, stableDocumentRead:async(_page,read)=>read(),
    globalThis: {URL}, URL: official, target: new URL(official), authRequired: false,
    http: async () => ({blocked:false,versionId:'fixture-contract',revision:1,controls:[]}),
    VAHAN_OPTION_SELECTORS: {states:{selector:'#stateName'}},
    selectorOverrides: () => ({}), approvedSelectors: {}, contractRevision:0,
    launch: async () => {}, newPage: async () => {},
    page: {isClosed: () => false, url: () => current,
      evaluate: async () => {},
      goto: async (url, options) => {
        calls.push('navigate'); assert.equal(url, official); assert.equal(options.waitUntil, 'commit');
        current = redirect || official;
        if (gotoError) throw new Error(gotoError);
        return {status: () => responseStatus};
      },
      locator: selector => ({first: () => ({waitFor: async options => {
        calls.push('controls'); assert.equal(selector, '#stateName option');
        assert.equal(options.state, 'attached'); assert.equal(options.timeout, 60_000);
        if (controlError) throw new Error(controlError);
      }})}),
    },
  };
  const ensure = runInNewContext(`${source.slice(openingStart, openingEnd)}\nensurePage`, context);
  return {ensure, calls};
}
const loading = openingFixture(); await loading.ensure();
assert.deepEqual(loading.calls, ['navigate', 'controls']);
const timedOutWithControls = openingFixture({gotoError: 'page.goto: Timeout 45000ms exceeded'});
await timedOutWithControls.ensure();
assert.deepEqual(timedOutWithControls.calls, ['navigate', 'controls'], 'ready controls recover a navigation timeout without reloading');
const missingControls = openingFixture({initial: official, controlError: 'Timeout waiting for State'});
await assert.rejects(missingControls.ensure(), /VAHAN_PAGE_NOT_READY/);
const forbidden = openingFixture({responseStatus: 401});
await assert.rejects(forbidden.ensure(), /VAHAN_AUTH_REQUIRED/);
assert.deepEqual(forbidden.calls, ['navigate']);
const landing = openingFixture({redirect: homepage});
await assert.rejects(landing.ensure(), /VAHAN_REPORT_NAVIGATED_AWAY/);
assert.deepEqual(landing.calls, ['navigate']);
console.log('5 page-readiness checks passed: navigation commit, usable timeout recovery, missing controls, authentication and redirect.');

const refreshStart = source.indexOf('async function refreshCaptchaInternal(');
const refreshEnd = source.indexOf('async function autoSolveCaptcha(', refreshStart);
assert.ok(refreshStart >= 0 && refreshEnd > refreshStart);
function refreshFixture(ackFailures = 0) {
  const calls = [];
  const job = {jobId: 'refresh-job', status: 'WAITING_CAPTCHA', captchaId: 'old-captcha'};
  let releasePage;
  const context = {
    active: job,
    page: {evaluate: async () => {
      calls.push('refresh-page');
      await new Promise(resolve => { releasePage = resolve; });
      return {captchaId: 'new-captcha', imageDataUrl: 'data:image/png;base64,AA=='};
    }},
    ack: async (_event,payload) => {assert.equal('imageDataUrl' in payload,false);calls.push('ack'); if (ackFailures-- > 0) throw new Error('operation has timed out'); return {ok: true};},
    autoSolveCaptcha: async (_job,id,dataUrl) => {assert.equal(id,'new-captcha');assert.equal(dataUrl,'data:image/png;base64,AA==');calls.push('solve-next');},
    fail: async () => calls.push('failed-job'),
    console: {error: () => calls.push('refresh-error')},
  };
  const refresh = runInNewContext(`${source.slice(refreshStart, refreshEnd)}\nrefreshCaptchaInternal`, context);
  return {refresh, job, calls, releasePage: () => releasePage()};
}
const refreshOnce = refreshFixture();
const firstRefresh = refreshOnce.refresh(refreshOnce.job, 'old-captcha');
assert.equal((await refreshOnce.refresh(refreshOnce.job, 'old-captcha')).ok, false);
refreshOnce.releasePage();
assert.equal((await firstRefresh).ok, true);
assert.deepEqual(refreshOnce.calls, ['refresh-page', 'ack', 'solve-next']);
assert.equal(refreshOnce.job.captchaId, 'new-captcha');
const staleRefresh = refreshFixture();
const staleAttempt = staleRefresh.refresh(staleRefresh.job, 'old-captcha');
staleRefresh.job.status = 'SUBMITTING';
staleRefresh.releasePage();
assert.equal((await staleAttempt).ok, false);
assert.deepEqual(staleRefresh.calls, ['refresh-page']);
const lostAck = refreshFixture(1);
const recoveredAck = lostAck.refresh(lostAck.job, 'old-captcha');
lostAck.releasePage();
assert.equal((await recoveredAck).ok, true);
assert.deepEqual(lostAck.calls, ['refresh-page', 'ack', 'ack', 'solve-next']);
const exhaustedAck = refreshFixture(2);
const failedRefresh = exhaustedAck.refresh(exhaustedAck.job, 'old-captcha');
exhaustedAck.releasePage();
assert.equal((await failedRefresh).ok, false);
assert.deepEqual(exhaustedAck.calls, ['refresh-page', 'ack', 'ack', 'refresh-error', 'failed-job']);
console.log('CAPTCHA refresh stays single-flight, retries a lost ACK and fails a stalled job.');

const failStart = source.indexOf('async function fail(');
const failEnd = source.indexOf('async function execute(', failStart);
const failedJob = {jobId: 'unreported-job', cancelled: false};
const recoveryCalls = [];
const failContext = {
  isConnectionError:()=>false,
  active: failedJob, stopping: false, page:{}, pageNeedsReset:false,
  retireReportPage:async()=>recoveryCalls.push('retire-page'),
  snapshot: async () => recoveryCalls.push('snapshot'),
  status: async () => {throw new Error('status ACK lost');},
  saveState: async () => recoveryCalls.push('save-state'),
  socket: {disconnect: () => recoveryCalls.push('disconnect'), connect: () => recoveryCalls.push('reconnect')},
  console: {error: () => recoveryCalls.push('status-error')},
};
const reportFailure = runInNewContext(`${source.slice(failStart, failEnd)}\nfail`, failContext);
await reportFailure(new Error('CAPTCHA_REFRESH_FAILED'), failedJob);
assert.deepEqual(recoveryCalls, ['snapshot', 'retire-page', 'status-error', 'save-state', 'disconnect', 'reconnect']);
console.log('A lost failure ACK reconnects the runner for server-side reconciliation.');

const executeStart = source.indexOf('async function execute(');
const executeEnd = source.indexOf('async function finalizeResult(', executeStart);
const activeAssignment = {jobId: 'same-job', finishing: false};
const duplicateDispatchCalls = [];
const executeDuplicate = runInNewContext(`${source.slice(executeStart, executeEnd)}\nexecute`, {
  active: activeAssignment, optionsBusy: false,
  ack: async () => duplicateDispatchCalls.push('failed-busy'),
  status: async () => duplicateDispatchCalls.push('opened'),
});
await executeDuplicate({jobId: 'same-job'});
assert.deepEqual(duplicateDispatchCalls, [], 'replayed assignment for the same job must be harmless');
console.log('A recovered assignment does not fail or restart the active job.');
