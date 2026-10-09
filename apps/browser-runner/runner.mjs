import { chromium } from 'playwright';
import {saveWithBackpressure} from './save-pressure.mjs';
import { io } from 'socket.io-client';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import {retireReportPage, stableDocumentRead, isConnectionError} from './page-recovery.mjs';
import {imageBytes, runImageCommand} from './image-pipe.mjs';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import {inspectControls,selectorOverrides} from './ui-health-contract.mjs';
import { normalizeJobFilters, VAHAN_OPTION_SELECTORS } from './config.mjs';

const API = process.env.VAHAN_API_URL || 'http://api:8000';
const TOKEN = process.env.VAHAN_API_RUNNER_TOKEN;
const ID = process.env.VAHAN_RUNNER_ID || 'playwright-1';
const URL = process.env.VAHAN_URL || 'https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en';
const LOCAL_FIXTURE = process.env.VAHAN_ALLOW_LOCAL_FIXTURE === 'true';
const DRIVER = fileURLToPath(new globalThis.URL('./page-driver.js', import.meta.url));
// Result detection watches the live report DOM and must allow the server time
// to finish the query. Five seconds caused real reports to be marked failed
// while VAHAN was still rendering them.
const RESULT_TIMEOUT = Number(process.env.VAHAN_RESULT_TIMEOUT_MS || 90_000);
// The API waits 115 s and the UI 125 s. Finish (and release the page) first.
const OPTIONS_TIMEOUT = 110_000;
if (!TOKEN || TOKEN === 'change-me') throw new Error('Set a private VAHAN_API_RUNNER_TOKEN.');
const target = new globalThis.URL(URL);
if (!LOCAL_FIXTURE && (target.origin !== 'https://analytics.parivahan.gov.in' || target.pathname !== '/analytics/vahanpublicreport')) {
  throw new Error('VAHAN_URL must be the official Public Report page.');
}

let browser, browserPromise, context, page, active, optionsBusy = false, authRequired = false, stopping = false;
let optionsCancellation = null;
let pageNeedsReset = false;
const socket = io(`${API}/runner`, {autoConnect: false, transports: ['websocket'], auth: {
  runnerId: ID, runnerName: process.env.VAHAN_RUNNER_NAME || 'Chromium Playwright', token: TOKEN,
  source: 'new', engine: 'playwright', version: '0.2.0',
}});
const headers = {'X-VAHAN-RUNNER-TOKEN': TOKEN, 'X-VAHAN-RUNNER-ID': ID};
async function http(path, init = {}) {
  const response = await fetch(`${API}${path}`, {...init, headers: {...headers, ...init.headers}, signal: AbortSignal.timeout(60_000)});
  if (!response.ok) {
    const message=await response.text();let body={};
    try{body=JSON.parse(message);}catch{}
    throw Object.assign(new Error(`API ${response.status}: ${message}`),{
      status:response.status,code:body.code,retryAfter:response.headers.get('retry-after'),
    });
  }
  return response.json();
}
async function ack(event, payload, timeout = 15_000) {
  const response = await socket.timeout(timeout).emitWithAck(event, payload);
  if (!response?.ok) throw new Error(response?.error || `${event} was rejected.`);
  return response;
}
function assertCurrent(job) {
  if (!job || job !== active || job.cancelled) throw new Error('Job was cancelled.');
}
async function submitCaptchaInternal(job, captchaId, value) {
  if (!job || job.status !== 'WAITING_CAPTCHA') return {ok: false, error: 'Stale job.'};
  try {
    const current = await page.evaluate(() => globalThis.vahanDriver.captureCaptcha());
    if (current.captchaId !== captchaId) {
      await challenge('captcha:refreshed', job); return {ok: true};
    }
    assertCurrent(job);
    if (job.status !== 'WAITING_CAPTCHA') return {ok: false, error: 'Submission is already in progress.'};
    // Claim the local submission synchronously, then persist the state before
    // clicking Apply. UI submissions may already have set it in the backend.
    job.status = 'SUBMITTING';
    await status('SUBMITTING', undefined, job);
    const verified = await page.evaluate(config => globalThis.vahanDriver.verifyFilters(config), normalizeJobFilters(job.filters));
    assertCurrent(job);
    await ack('job:filters-verified', {jobId: job.jobId, phase: 'before-apply', execution: verified});
    await page.locator('#externalCaptcha').fill(value.trim());
    await page.evaluate(({timeout, rto}) => globalThis.vahanDriver.prepareResult(timeout, rto),
      {timeout: RESULT_TIMEOUT, rto: job.filters.rtos?.[0] || ''});
    // The click only submits the form. Result/navigation waiting belongs to
    // waitForResult, otherwise a completed click can time out before that stage.
    await page.locator(approvedApplySelector).click({noWaitAfter: true});
    await ack('job:apply-clicked', {jobId: job.jobId, clickId: randomUUID()});
    await status('WAITING_RESULT', undefined, job);
    waitForResult(job).catch(error => fail(error, job));
    return {ok: true};
  } catch (error) {
    await fail(error, job);
    return {ok: false, error: error.message};
  }
}
async function refreshCaptchaInternal(job, captchaId) {
  if (!job || job !== active || job.cancelled || job.status !== 'WAITING_CAPTCHA'
      || job.captchaId !== captchaId || job.refreshingCaptchaId) {
    return {ok: false, error: 'Stale CAPTCHA or job.'};
  }
  job.refreshingCaptchaId = captchaId;
  try {
    const captcha = await page.evaluate(id => globalThis.vahanDriver.refreshCaptcha(id), captchaId);
    if (job !== active || job.cancelled || job.status !== 'WAITING_CAPTCHA'
        || job.captchaId !== captchaId) return {ok: false, error: 'Stale CAPTCHA or job.'};
    const update = {jobId: job.jobId, captchaId: captcha.captchaId};
    try {
      await ack('captcha:refreshed', update);
    } catch (error) {
      // The API may have committed the new challenge while its ACK was lost.
      // Repeating the same challenge is idempotent and restores the local ID.
      if (job !== active || job.cancelled || job.status !== 'WAITING_CAPTCHA') throw error;
      await ack('captcha:refreshed', update);
    }
    if (job !== active || job.cancelled || job.status !== 'WAITING_CAPTCHA') {
      return {ok: false, error: 'Stale CAPTCHA or job.'};
    }
    job.captchaId = captcha.captchaId;
    autoSolveCaptcha(job, captcha.captchaId, captcha.imageDataUrl).catch(console.error);
    return {ok: true};
  } catch (error) {
    console.error('Failed to refresh captcha:', error.message);
    if (job === active && !job.cancelled && job.status === 'WAITING_CAPTCHA') {
      await fail(new Error(`CAPTCHA_REFRESH_FAILED: ${error.message}`), job);
    }
    return {ok: false, error: error.message};
  } finally {
    if (job.refreshingCaptchaId === captchaId) job.refreshingCaptchaId = null;
  }
}

async function autoSolveCaptcha(job, captchaId, imageDataUrl) {
  try {
    const { stdout } = await runImageCommand('tesseract', ['stdin', 'stdout', '-l', 'eng', '--psm', '6'], imageBytes(imageDataUrl), {
      timeout: 3000, env: {...process.env, OMP_THREAD_LIMIT: '1'},
    });
    if (job !== active || job.cancelled || job.status !== 'WAITING_CAPTCHA'
        || job.captchaId !== captchaId || job.refreshingCaptchaId) return;

    const rawText = stdout.trim();
    const text = rawText.replace(/[^A-Z0-9]/ig, '').toUpperCase();
    console.log('Image recognition finished. Validation text is excluded from logs.');
    if (text.length === 6) {
      console.log('Valid captcha detected, auto-submitting...');
      await submitCaptchaInternal(job, captchaId, text);
    } else {
      console.log('Captcha length not 6, auto-refreshing...');
      await refreshCaptchaInternal(job, captchaId);
    }
  } catch (err) {
    if (job !== active || job.cancelled || job.status !== 'WAITING_CAPTCHA'
        || job.captchaId !== captchaId || job.refreshingCaptchaId) return;
    console.error('Auto-OCR failed, auto-refreshing...', err.message);
    await refreshCaptchaInternal(job, captchaId);
  }
}
async function status(value, error, job = active) {
  assertCurrent(job);
  await ack('job:status', {jobId: job.jobId, status: value, ...(error ? {error} : {})});
  assertCurrent(job); job.status = value;
}
async function launch() {
  if (browserPromise) return browserPromise;
  if (browser?.isConnected() && context) return;
  browserPromise = (async () => {
    browser = await chromium.launch({headless: true, chromiumSandbox: process.env.VAHAN_CHROMIUM_SANDBOX !== 'false'});
    const saved = await http(`/api/runner-state/${ID}`);
    context = await browser.newContext({acceptDownloads: true, storageState: saved.state || undefined, viewport: {width: 1440, height: 1000}});
    await context.addInitScript({path: DRIVER});
    await newPage();
  })();
  try { await browserPromise; }
  catch (error) { await browser?.close(); browser = context = page = undefined; throw error; }
  finally { browserPromise = undefined; }
}
async function newPage() {
  page = await context.newPage();
  const monitored = page;
  page.on('response', response => {
    if (page === monitored && response.status() === 401 && response.request().isNavigationRequest() && response.request().frame() === monitored.mainFrame()) authRequired = true;
  });
}
async function ensurePage(isCancelled = () => false) {
  await launch();
  if (isCancelled()) throw new Error('VAHAN_OPTIONS_TIMEOUT: options loading was cancelled.');
  if (page.isClosed() || pageNeedsReset) {
    await retireReportPage(page);
    await newPage();
    pageNeedsReset = false;
  }
  if (isCancelled()) {
    await page.close().catch(() => {});
    throw new Error('VAHAN_OPTIONS_TIMEOUT: options loading was cancelled.');
  }
  const contract=await http('/api/ui-health/contract');
  if(contract.blocked||!contract.versionId)throw new Error('UI_HEALTH_BLOCKED: a successful SQL preflight is required.');
  const seeds=[...Object.entries(VAHAN_OPTION_SELECTORS).map(([field,value])=>({field,selector:value.selector})),...['fromYear','toYear','fromDate','toDate'].map(field=>({field,selector:'#'+field})),{field:'apply',selector:'#applyTrigger'}];
  const overrides=selectorOverrides(contract.controls,seeds);
  approvedSelectors=Object.fromEntries(Object.entries(VAHAN_OPTION_SELECTORS).map(([field,value])=>[field,{...value,selector:contract.controls.find(control=>control.field===field)?.selector||value.selector}]));
  approvedApplySelector=contract.controls.find(control=>control.field==='apply')?.selector||'#applyTrigger';
  if(contractRevision&&contractRevision!==contract.revision)await page.goto('about:blank');
  contractRevision=contract.revision;
  const isReportPage = () => {
    const current = new globalThis.URL(page.url());
    return current.origin === target.origin && current.pathname === target.pathname;
  };
  if (!isReportPage()) {
    authRequired = false;
    let response;
    try {
      response = await page.goto(URL, {waitUntil: 'commit', timeout: 45_000});
    } catch (error) {
      // A navigation timeout need not mean that the report failed to open.
      // Check its actual controls before deciding; never submit the form twice.
      if (!/timeout/i.test(error.message) || !isReportPage()) throw error;
    }
    if (response?.status() === 401 || authRequired) throw new Error('VAHAN_AUTH_REQUIRED: operator authentication is required.');
    if (!isReportPage()) throw new Error('VAHAN_REPORT_NAVIGATED_AWAY: VAHAN redirected away while opening the Public Report page.');
  }
  try {
    // VAHAN's multiselect plugin hides the native select and renders a proxy.
    // The driver reads native options, so visibility is not page readiness.
    await page.locator(approvedSelectors.states.selector+' option').first().waitFor({state: 'attached', timeout: 60_000});
  } catch (error) {
    if (authRequired) throw new Error('VAHAN_AUTH_REQUIRED: operator authentication is required.');
    if (!isReportPage()) throw new Error('VAHAN_REPORT_NAVIGATED_AWAY: VAHAN redirected away while loading the report controls.');
    throw new Error(`VAHAN_PAGE_NOT_READY: the State control did not become available. ${error.message}`);
  }
  await stableDocumentRead(page, () => page.evaluate(value=>{globalThis.vahanSelectorOverrides=value;},overrides));
  if (authRequired) throw new Error('VAHAN_AUTH_REQUIRED: operator authentication is required.');
  if (!isReportPage()) throw new Error('VAHAN_REPORT_NAVIGATED_AWAY: VAHAN redirected away before filters could be filled.');
}
async function saveState() {
  if (context && socket.connected) await http(`/api/runner-state/${ID}`, {method: 'PUT',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({value: await context.storageState()})});
}
async function snapshot(label, job = active) {
  if (!job || job !== active || job.cancelled || page?.isClosed()) return;
  try {
    const form = new FormData();
    form.append('file', new Blob([await page.screenshot({fullPage: true, timeout: 5000, animations: 'disabled',
      mask:[page.locator('#captchaImage'),page.locator('#externalCaptcha')],maskColor:'#ffffff'})], {type: 'image/png'}), `${label}.png`);
    await http(`/api/jobs/${job.jobId}/artifacts`, {method: 'POST', body: form});
  } catch (error) { console.error('Snapshot could not be stored:', error.message); }
}
async function challenge(event = 'captcha:required', job = active) {
  assertCurrent(job);
  const captcha = await page.evaluate(() => globalThis.vahanDriver.captureCaptcha());
  assertCurrent(job); job.captchaId = captcha.captchaId;
  await ack(event, {jobId: job.jobId, captchaId: captcha.captchaId});
  assertCurrent(job); job.status = 'WAITING_CAPTCHA';
  autoSolveCaptcha(job, captcha.captchaId, captcha.imageDataUrl).catch(console.error);
}
async function fail(error, job = active) {
  if (!job || job !== active || job.cancelled) return;
  if (isConnectionError(error)) {
    try {await ack('network:problem', {}, 12000);} catch {}
    if (job !== active || job.cancelled) return;
  }
  if (job.finishing) return; // Duplicate error paths must not retire another case's page.
  job.finishing = true;
  job.finishPromise = new Promise(resolve => {job.finish = resolve;});
  let statusLost = false;
  try {
    // Capture diagnostics before retiring the damaged document. Keep the
    // session's cookies; the next case gets a new page in the same context.
    pageNeedsReset = true;
    await snapshot('failure', job);
    await retireReportPage(page);
    try { await status('FAILED', error.message, job); }
    catch (failure) { statusLost = true; console.error(failure.message); }
    if (active === job) active = null;
    await saveState().catch(error => console.error(error.message));
    if (statusLost && !stopping) {
      socket.disconnect();
      socket.connect();
    }
  } finally {job.finish();}
}
async function execute(job) {
  if (active?.jobId === job.jobId) return;
  // A committed result can release the server's worker before its HTTP response arrives.
  // Wait for that response before accepting the next assignment on this browser.
  if (active?.finishing) await active.finishPromise;
  if (active || optionsBusy) {
    await ack('job:status', {jobId: job.jobId, status: 'FAILED', error: 'Browser worker is busy.'});
    return;
  }
  const work = active = {...job, retries: 0, cancelled: false};
  try {
    await status('OPENING_VAHAN', undefined, work);
    await ensurePage();
    await status('FILLING_FILTERS', undefined, work);
    const execution = await page.evaluate(config => globalThis.vahanDriver.fill(config), normalizeJobFilters(job.filters));
    assertCurrent(work);
    await ack('job:filters-verified', {jobId: work.jobId, phase: 'filled', execution});
    assertCurrent(work); await challenge('captcha:required', work);
  } catch (error) { await fail(error, work); }
}
async function finalizeResult(job, operation) {
  job.finishing = true;
  job.finishPromise = new Promise(resolve => { job.finish = resolve; });
  try {
    const saved = await saveWithBackpressure(operation, {
      check: () => assertCurrent(job),
      onWait: (attempt, seconds) => console.log('DATABASE_BACKPRESSURE', JSON.stringify({jobId:job.jobId,attempt,waitSeconds:seconds})),
    });
    assertCurrent(job);
    if (!['COMPLETED', 'NO_DATA'].includes(saved.status)) throw new Error('MAIN_REPORT_SAVE_NOT_CONFIRMED');
    job.status = saved.status;
    if (active === job) active = null;
    return saved;
  } finally { job.finishing = false; job.finish(); }
}
async function waitForResult(job) {
  assertCurrent(job);
  const resultWaitStartedAt = Date.now();
  const jobPage = page;
  const assertReportPage = () => {
    const current = new globalThis.URL(jobPage.url());
    if (current.origin !== target.origin || current.pathname !== target.pathname) {
      throw new Error(`VAHAN_REPORT_NAVIGATED_AWAY: the Public Report page changed to ${current.pathname || '/'} before the result was confirmed.`);
    }
  };
  const deadline = Date.now() + RESULT_TIMEOUT;
  let result;
  while (!result) {
    assertCurrent(job);
    if (authRequired) throw new Error('VAHAN_AUTH_REQUIRED');
    assertReportPage();
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new Error('VAHAN_RESULT_TIMEOUT: no confirmed report within the result timeout.');
    try {
      // An Apply POST replaces the document. DOMContentLoaded can refer to the
      // old document when navigation has only just started, so even the next
      // evaluation may lose its context. Reattach the reader as often as needed
      // within ONE result deadline; never click Apply again here.
      await jobPage.waitForLoadState('domcontentloaded', {timeout: remaining});
      assertCurrent(job);
      if (authRequired) throw new Error('VAHAN_AUTH_REQUIRED');
      assertReportPage();
      const readTimeout = deadline - Date.now();
      if (readTimeout <= 0) throw new Error('VAHAN_RESULT_TIMEOUT: no confirmed report within the result timeout.');
      result = await jobPage.evaluate(({timeout, rto}) => globalThis.vahanDriver.result(timeout, rto),
        {timeout: readTimeout, rto: job.filters.rtos?.[0] || ''});
    } catch (error) {
      if (/Timeout.*exceeded/i.test(error.message)) {
        throw new Error('VAHAN_RESULT_TIMEOUT: the report document did not finish loading within the result timeout.');
      }
      if (!/Execution context was destroyed|Cannot find context with specified id/i.test(error.message)) throw error;
      assertCurrent(job);
      // Only back off after a destroyed context, rather than spin against a
      // document in the middle of another navigation.
      await new Promise(resolve => setTimeout(resolve, Math.min(100, Math.max(0, deadline - Date.now()))));
    }
  }
  const resultReadyAt = Date.now();
  assertReportPage();
  if (active !== job || job.cancelled) return;
  if (authRequired || result.type === 'AUTH_REQUIRED') throw new Error('VAHAN_AUTH_REQUIRED');
  if (result.type === 'INVALID_CAPTCHA') {
    if (++job.retries >= 3) throw new Error('CAPTCHA was rejected three times.');
    await challenge('captcha:invalid', job);
    return;
  }
  if (result.type === 'DATA_READY') {
    if (!result.downloadReady) throw new Error('MAIN_REPORT_EXPORT_MISSING: full manufacturer export is required.');
    const downloadPromise = jobPage.waitForEvent('download', {timeout: 30_000});
    await jobPage.evaluate(() => globalThis.vahanDriver.clickExcel());
    const download = await downloadPromise;
    try {
      const failure = await download.failure();
      if (failure) throw new Error(failure);
      assertCurrent(job);
      const data = await readFile(await download.path());
      const exportReadyAt = Date.now();
      const form = new FormData();
      form.append('file', new Blob([data], {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}), download.suggestedFilename());
      form.append('observedAt', result.report.observedAt);
      form.append('pageUrl', result.report.pageUrl || '');
      await finalizeResult(job, () => http(`/api/jobs/${job.jobId}/main-report`, {method: 'POST', body: form}));
      console.log('RESULT_STAGE', JSON.stringify({jobId: job.jobId, outcome: 'COMPLETED',
        resultWaitMs: resultReadyAt - resultWaitStartedAt,
        exportMs: exportReadyAt - resultReadyAt, saveMs: Date.now() - exportReadyAt}));
    } finally { await download.delete(); }
  } else if (result.type === 'NO_RECORD') {
    assertCurrent(job);
    await finalizeResult(job, () => http(`/api/jobs/${job.jobId}/report-result`, {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(result.report)}));
    console.log('RESULT_STAGE', JSON.stringify({jobId: job.jobId, outcome: 'NO_DATA',
      resultWaitMs: resultReadyAt - resultWaitStartedAt, exportMs: 0,
      saveMs: Date.now() - resultReadyAt}));
  } else if (result.type === 'TIMEOUT') {
    throw new Error('VAHAN_RESULT_TIMEOUT: no confirmed report within the result timeout.');
  } else throw new Error(`Unexpected result: ${result.type}`);
  if (active === job) active = null;
  await saveState();
}
socket.on('connect', async () => {
  try {
    const recovered = await ack('runner:recover', {activeJobId: active?.jobId || null});
    if (active && recovered.activeJobId !== active.jobId) {
      active.cancelled = true; active = null; await page?.close().catch(() => {});
    }
    await launch();
  } catch (error) { console.error('Browser initialization failed:', error.message); }
});
socket.on('connect_error', error => console.error('API connection:', error.message));
const originalError = console.error.bind(console);
console.error = (...parts) => {
  const safeParts=parts.map(value=>String(value).replaceAll(TOKEN,'[redacted]')
    .replace(/Bearer\s+[^\s"']+/ig,'Bearer [redacted]'));
  originalError(...safeParts);
  if (socket.connected) {
    const message = safeParts.join(' ').slice(0, 8000);
    http('/api/runner-logs', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({level: 'error', message, jobId: active?.jobId || null})}).catch(() => {});
  }
};
socket.on('job:assigned', job => execute(job).catch(error => console.error(error.message)));
socket.on('captcha:submit', async (payload, respond) => {
  const job = active;
  if (!job || payload.jobId !== job.jobId || payload.captchaId !== job.captchaId || job.status !== 'WAITING_CAPTCHA') {
    respond({ok: false, error: 'Stale CAPTCHA or job.'}); return;
  }
  if (typeof payload.value !== 'string' || payload.value.trim().length !== 6) {
    respond({ok: false, error: 'Enter exactly six CAPTCHA characters.'}); return;
  }
  const result = await submitCaptchaInternal(job, payload.captchaId, payload.value);
  respond(result);
});
socket.on('captcha:refresh', async (payload, respond) => {
  const job = active;
  if (!job || payload.jobId !== job.jobId || payload.captchaId !== job.captchaId || job.status !== 'WAITING_CAPTCHA') {
    respond({ok: false, error: 'No waiting job.'}); return;
  }
  respond(await refreshCaptchaInternal(job, payload.captchaId));
});
socket.on('job:cancelled', async ({jobId}) => {
  if (active?.jobId === jobId) { const cancelled = active; cancelled.cancelled = true; pageNeedsReset = true; await retireReportPage(page); if (active === cancelled) active = null; }
});
async function runnerOptions(request, respond) {
  if (active?.finishing) await active.finishPromise;
  if (active || optionsBusy) { respond({ok: false, error: 'Worker is busy.', code: 'RUNNER_BUSY', retryAfterMs: 1000}); return; }
  optionsBusy = true;
  let timer, expired = false, rejectCancellation;
  const cancelled = new Promise((_, reject) => {rejectCancellation = reject;});
  let finished;
  const completion = new Promise(resolve => {finished = resolve;});
  const cancellation = optionsCancellation = {requestId: request.requestId || null, cancel: async () => {
    expired = true; rejectCancellation(new Error('VAHAN_OPTIONS_CANCELLED: options loading was cancelled.')); await completion;
  }};
  const work = async () => {
    await ensurePage(() => expired);
    if (expired) throw new Error('VAHAN_OPTIONS_TIMEOUT: options loading was cancelled.');
    const operations = {GET_ALL_OPTIONS: ['readOptions', approvedSelectors], GET_STATE_OPTIONS: ['states', request.delhiNcr],
      GET_RTO_OPTIONS: ['rtos', request.stateLabels], GET_X_AXIS_OPTIONS: ['xAxis', request.yAxis], SEARCH_MAKERS: ['makers', request.search],
      GET_FILTER_CONTEXT: ['filterContext', request.filters], GET_ALL_MAKERS: ['allMakers', null]};
    const operation = operations[request.type];
    if (!operation) throw new Error('Unsupported options request.');
    return page.evaluate(([method, value]) => globalThis.vahanDriver[method](value), operation);
  };
  try {
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => {
        expired = true;
        reject(new Error(`VAHAN_OPTIONS_TIMEOUT: ${request.type} did not finish within ${OPTIONS_TIMEOUT / 1000} seconds. Please retry.`));
      }, OPTIONS_TIMEOUT);
    });
    const options = await Promise.race([work(), deadline, cancelled]);
    respond({ok: true, options});
  } catch (error) {
    // Closing the page also aborts page.evaluate/fetch; a Promise timeout alone
    // would leave the old request running and every retry would see busy.
    pageNeedsReset = true;
    await retireReportPage(page);
    respond({ok: false, error: error.message});
  } finally { clearTimeout(timer); optionsBusy = false; if (optionsCancellation === cancellation) optionsCancellation = null; finished(); }
}
socket.on('runner:options', runnerOptions);
socket.on('runner:cancel-options', async (request, respond) => {
  if (!optionsBusy) {respond({ok:true});return;}
  const cancellation = optionsCancellation;
  if (!request.requestId || cancellation?.requestId !== request.requestId) {respond({ok:false,error:'Stale options request.'});return;}
  await cancellation.cancel();respond({ok:true});
});
let contractRevision=0;
let approvedSelectors=VAHAN_OPTION_SELECTORS;
let approvedApplySelector='#applyTrigger';
async function healthCheck(request = {}) {
  let result;let isolated;
  try {
    await launch();
    const contract=await http('/api/ui-health/contract');
    isolated=await browser.newContext({storageState:await context.storageState(),viewport:{width:1440,height:1000}});
    const healthPage=await isolated.newPage();
    const response=await healthPage.goto(URL,{waitUntil:'domcontentloaded',timeout:30000});
    const location=new globalThis.URL(healthPage.url());
    if(response?.status()===401||location.origin!==target.origin||location.pathname!==target.pathname)throw new Error('Health check did not reach the expected public report page.');
    // Allow asynchronous controls to settle, including uniquely renamed controls.
    // This reads option metadata only; Maker requests and report jobs start later.
    await healthPage.waitForFunction(controls=>controls.every(control=>{
      try {
        const direct=document.querySelector(control.selector);
        const semantic=control.name?[...document.querySelectorAll('select,input,button')].filter(el=>el.getAttribute('name')===control.name):[];
        const element=direct||(semantic.length===1?semantic[0]:null);
        // Dependent selects such as RTO and Maker can legitimately be empty.
        return element && (control.field!=='states'||element.options?.length);
      }catch{return false;}
    }),contract.controls,{timeout:10000}).catch(()=>{});
    const observedControls=await inspectControls(healthPage,contract);
    result={status:'PASS',observedControls,checkedAt:new Date().toISOString(),contract:{path:target.pathname,revision:contract.revision}};
  }catch(error){result={status:'CHECK_ERROR',error:error.message,observedControls:[],checkedAt:new Date().toISOString()};}
  finally{await isolated?.close().catch(()=>{});}
  result.trigger=request.trigger||'preflight';result.logId=request.requestId||randomUUID();result.checkId=result.logId;
  const saved=await http('/api/ui-health/logs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({runnerId:ID,pageUrl:URL,healthCheck:result})});
  return saved;
}
socket.on('ui-health:preflight',async(request,respond)=>{
  // SQL can release a committed job just before the worker finishes its final
  // acknowledgement. Let that bounded cleanup finish before checking the page.
  if(active?.finishing)await active.finishPromise;
  if(active||optionsBusy){respond({ok:false,error:'Worker is busy.',code:'RUNNER_BUSY',retryAfterMs:1000});return;}
  optionsBusy=true;
  try{const result=await healthCheck(request);respond({ok:true,...result});}
  catch(error){respond({ok:false,error:error.message});}
  finally{optionsBusy=false;}
});
socket.on('ui-health:run-now', request => healthCheck(request).catch(error => console.error(error.message)));
const timer = setInterval(async () => {
  if (!socket.connected || stopping) return;
  try {
    await ack('runner:heartbeat', {});
    await saveState();
  } catch (error) { console.error('Worker heartbeat:', error.message); }
}, 15_000);
createServer((request, response) => {
  response.writeHead(socket.connected && context && browser?.isConnected() ? 200 : 503, {'Content-Type': 'application/json'});
  response.end(JSON.stringify({connected: socket.connected, browserReady: !!context && !!browser?.isConnected(), activeJobId: active?.jobId || null, optionsBusy}));
}).listen(3001, '0.0.0.0');
async function stop() {
  if (stopping) return; stopping = true; clearInterval(timer);
  await saveState().catch(() => {}); socket.disconnect(); await browser?.close(); process.exit(0);
}
process.on('SIGTERM', stop); process.on('SIGINT', stop);
socket.connect();
