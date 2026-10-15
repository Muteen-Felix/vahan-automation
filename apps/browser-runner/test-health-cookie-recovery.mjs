// PLAN_STATE_VAHAN WP-R: bounded recovery from a stored cookie that VAHAN answers with 404,
// revision-fenced state saving, deadlines and late commits. Real Chromium, a cookie-aware fixture
// server and a fake API that implements the same compare-and-swap as PUT /api/runner-state.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import test, {before, after} from 'node:test';
import {chromium} from 'playwright';
import {inspectControls} from './ui-health-contract.mjs';
import {runHealthCheck, StateStore, BUDGET, STALE_COOKIE, digestState} from './health-cookie-recovery.mjs';

const CONTROLS = [{field: 'states', selector: '#stateName', tag: 'select', multiple: true},
  {field: 'apply', selector: '#applyTrigger', tag: 'button'}];
const PAGE = '<select id="stateName" multiple><option>State</option></select><button id="applyTrigger">Apply</button>';
const BLANK = '<html><body>Not the report</body></html>';
const STALE_VALUE = 'STALE-SECRET-VALUE';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const deferred = () => { let release; const promise = new Promise(resolve => { release = resolve; }); return {promise, release}; };

// ---- fixture VAHAN ----------------------------------------------------------------------------
const parseCookies = header => Object.fromEntries(String(header || '').split(/;\s*/).filter(Boolean).map(part => {
  const index = part.indexOf('=');
  return [part.slice(0, index), part.slice(index + 1)];
}));
const ISSUE = {
  none: [],
  same: ['analytics_sh_cok=FRESH-A; Path=/; HttpOnly; SameSite=Lax'],
  both: ['analytics_sh_cok=FRESH-A; Path=/; HttpOnly', 'JSESSIONID=SESS-1; Path=/'],
  otherPath: ['analytics_sh_cok=FRESH-B; Path=/report; HttpOnly'],
  extra: ['analytics_sh_cok=FRESH-A; Path=/', 'TRACKING=x; Path=/'],
  expireOther: ['analytics_sh_cok=FRESH-A; Path=/', 'JSESSIONID=; Path=/; Max-Age=0'],
};
let respond;
const requests = [];
const server = createServer((req, res) => {
  if (req.url === '/pending.js') return;
  const cookies = parseCookies(req.headers.cookie);
  requests.push({url: req.url, cookies});
  const verdict = respond(cookies, req) || {};
  if (verdict.hang) return;
  res.statusCode = verdict.status ?? 200;
  if (verdict.location) res.setHeader('Location', verdict.location);
  for (const cookie of verdict.setCookie || []) res.appendHeader('Set-Cookie', cookie);
  res.setHeader('Content-Type', 'text/html');
  res.end(verdict.body ?? (res.statusCode === 200 ? PAGE : 'error'));
});
// Real server behaviour: the stored value is rejected, anything else (or no cookie) is served.
function vahan({issue = 'same', requireBoth = false, confirm404 = false, always404 = false, blankWithoutCookie = false,
  hangFresh = false, status = null} = {}) {
  return cookies => {
    if (status) return {status};
    if (always404) return {status: 404};
    if (cookies[STALE_COOKIE] === STALE_VALUE) return {status: 404};
    if (cookies[STALE_COOKIE] === 'FRESH-A') {
      if (hangFresh) return {hang: true};
      if (confirm404) return {status: 404};
      if (requireBoth && !cookies.JSESSIONID) return {status: 404};
      return {status: 200};
    }
    if (blankWithoutCookie) return {status: 200, body: BLANK};
    return {status: 200, setCookie: ISSUE[issue]};
  };
}

// ---- fake API with the real compare-and-swap ---------------------------------------------------
const httpError = (status, body) => Object.assign(new Error(`API ${status}: ${JSON.stringify(body || {})}`), {status, body});
class FakeApi {
  constructor() { this.state = null; this.revision = 0; this.fenced = true; this.failPut = null; this.log = []; this.logs = []; this.hooks = {}; }
  async http(path, init = {}) {
    const timeout = init.timeoutMs ?? 60_000;
    assert.ok(timeout > 0, `non-positive timeout for ${path}`);
    let timer;
    const work = this.handle(path, init);
    work.catch(() => {});
    const guard = new Promise((_, reject) => {
      timer = setTimeout(() => reject(Object.assign(new Error('The operation was aborted due to timeout'), {name: 'TimeoutError'})), timeout);
    });
    try { return await Promise.race([work, guard]); } finally { clearTimeout(timer); }
  }
  async handle(path, init) {
    const method = (init.method || 'GET').toUpperCase();
    if (path === '/api/ui-health/contract') return {controls: CONTROLS, revision: 1};
    if (path.startsWith('/api/runner-state/') && method === 'GET') {
      const answer = {state: this.state, revision: this.revision};
      this.log.push({op: 'GET', revision: this.revision});
      await this.hooks.afterGet?.();
      return answer;
    }
    if (path.startsWith('/api/runner-state/') && method === 'PUT') {
      const body = JSON.parse(init.body);
      this.log.push({op: 'PUT-sent', expected: body.expectedRevision, marker: body.value?.marker});
      await this.hooks.beforeCommit?.(body);
      if (this.failPut) throw httpError(this.failPut, {detail: 'injected'});
      if (this.fenced && body.expectedRevision !== this.revision) {
        this.log.push({op: 'PUT-409', expected: body.expectedRevision, current: this.revision, marker: body.value?.marker});
        throw httpError(409, {detail: {code: 'STATE_REVISION_CONFLICT', currentRevision: this.revision}});
      }
      this.state = body.value; this.revision += 1;
      this.log.push({op: 'PUT-commit', revision: this.revision, marker: body.value?.marker});
      await this.hooks.afterCommit?.(body);
      return {ok: true, revision: this.revision};
    }
    if (path === '/api/ui-health/logs') {
      const body = JSON.parse(init.body);
      this.log.push({op: 'POST-sent', status: body.healthCheck.status});
      await this.hooks.beforeLog?.(body);
      this.logs.push(body.healthCheck);
      this.log.push({op: 'POST-commit', status: body.healthCheck.status});
      return {ok: true, validation: {allowed: body.healthCheck.status === 'PASS'}};
    }
    throw new Error('unexpected path ' + path);
  }
  ops(name) { return this.log.filter(entry => entry.op === name); }
}

// ---- environment per test ---------------------------------------------------------------------
let browser, origin, URL_;
before(async () => {
  await new Promise(resolve => server.listen(0, resolve));
  origin = `http://localhost:${server.address().port}`;
  URL_ = origin + '/report';
  browser = await chromium.launch({headless: true});
});
after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });

const staleCookie = (overrides = {}) => ({name: STALE_COOKIE, value: STALE_VALUE, domain: 'localhost', path: '/',
  expires: -1, httpOnly: true, secure: false, sameSite: 'Lax', ...overrides});
const jsession = (overrides = {}) => ({name: 'JSESSIONID', value: 'OLD-SESSION', domain: 'localhost', path: '/analytics',
  expires: -1, httpOnly: true, secure: false, sameSite: 'Lax', ...overrides});

async function makeEnv({cookies = [staleCookie()], budget, connected = true, wrapContext, epoch} = {}) {
  respond = vahan();
  requests.length = 0;
  const api = new FakeApi();
  let primary = await browser.newContext({storageState: {cookies, origins: []}});
  if (wrapContext) primary = wrapContext(primary);
  const state = {epoch: 1, tainted: false, rebuilt: 0, pageReset: 0, connected};
  const timeouts = [];
  const spy = {
    newContext: async options => {
      const context = await browser.newContext(options);
      return new Proxy(context, {get(target, key) {
        if (key === 'newPage') {
          return async () => {
            const page = await target.newPage();
            return new Proxy(page, {get(pageTarget, pageKey) {
              if (pageKey === 'goto' || pageKey === 'waitForFunction') {
                return (...args) => {
                  timeouts.push({fn: pageKey, timeout: args[pageKey === 'goto' ? 1 : 2]?.timeout});
                  return pageTarget[pageKey](...args);
                };
              }
              const value = pageTarget[pageKey];
              return typeof value === 'function' ? value.bind(pageTarget) : value;
            }});
          };
        }
        const value = target[key];
        return typeof value === 'function' ? value.bind(target) : value;
      }});
    },
    contexts: () => browser.contexts(),
  };
  const store = new StateStore({http: (path, init) => api.http(path, init), id: 'fixture-worker', isConnected: () => state.connected});
  const deps = {browser: () => spy, context: () => primary, launch: async () => {}, http: (path, init) => api.http(path, init),
    URL: URL_, target: new globalThis.URL(URL_), ID: 'fixture-worker', randomUUID: () => 'fixture-check', inspectControls,
    store, epoch: epoch || (() => state.epoch), isTainted: () => state.tainted, setTainted: () => { state.tainted = true; },
    markPageNeedsReset: () => { state.pageReset += 1; }, rebuildPrimary: async () => { state.rebuilt += 1; },
    UrlCtor: globalThis.URL, budget: budget || BUDGET};
  store.setRevision(0);
  const dispose = async () => { await primary.close().catch(() => {}); };
  return {api, deps, store, state, timeouts, primary: () => primary, dispose,
    run: (request = {requestId: 'check-' + Math.random().toString(16).slice(2)}) => runHealthCheck(deps, request),
    last: () => api.logs[api.logs.length - 1],
    jar: async name => (await primary.cookies()).filter(cookie => !name || cookie.name === name)};
}
const byName = (cookies, name) => cookies.filter(cookie => cookie.name === name);
const stateCookies = (api, name) => (api.state?.cookies || []).filter(cookie => cookie.name === name);

// =============================== A. cookie scope ==============================================
test('RA1 stale 404 -> retry 200 -> order retry, save, then PASS; only the new cookie remains', async () => {
  const env = await makeEnv({cookies: [staleCookie(), jsession()]});
  try {
    respond = vahan({issue: 'same'});
    await env.run();
    const result = env.last();
    assert.equal(result.status, 'PASS');
    assert.equal(result.recovery.recovered, true);
    assert.equal(result.recovery.confirm, 'done');
    assert.deepEqual(env.api.log.map(entry => entry.op).filter(op => op !== 'GET'), ['PUT-sent', 'PUT-commit', 'POST-sent', 'POST-commit']);
    const analytics = await env.jar(STALE_COOKIE);
    assert.equal(analytics.length, 1);
    assert.equal(analytics[0].value, 'FRESH-A');
    assert.equal((await env.jar('JSESSIONID')).length, 1, 'unrelated cookie kept');
    assert.deepEqual(stateCookies(env.api, STALE_COOKIE).map(cookie => cookie.value), ['FRESH-A']);
    assert.equal(env.state.pageReset, 1);
  } finally { await env.dispose(); }
});

test('RA2 server cookie on another domain/path never duplicates the old one', async () => {
  const env = await makeEnv({cookies: [staleCookie({domain: '.localhost'}), jsession()]});
  try {
    respond = vahan({issue: 'otherPath'});
    await env.run();
    assert.equal(env.last().status, 'PASS', JSON.stringify(env.last()));
    const analytics = await env.jar(STALE_COOKIE);
    assert.equal(analytics.length, 1, 'exactly one analytics_sh_cok');
    assert.equal(analytics[0].path, '/report');
    assert.equal(analytics[0].value, 'FRESH-B');
    assert.equal(stateCookies(env.api, STALE_COOKIE).length, 1);
    assert.ok(!JSON.stringify(env.api.state).includes(STALE_VALUE), 'the old value is not in the stored state');
  } finally { await env.dispose(); }
});

test('RA3 server issues no cookie: primary and stored state have none, others stay', async () => {
  const env = await makeEnv({cookies: [staleCookie(), jsession()]});
  try {
    respond = vahan({issue: 'none'});
    await env.run();
    assert.equal(env.last().status, 'PASS');
    assert.equal(env.last().recovery.confirm, 'skipped');
    assert.equal((await env.jar(STALE_COOKIE)).length, 0);
    assert.equal(stateCookies(env.api, STALE_COOKIE).length, 0);
    assert.equal(stateCookies(env.api, 'JSESSIONID').length, 1);
    assert.equal(requests.filter(request => request.url === '/report').length, 2, 'retry only; no confirmation request');
  } finally { await env.dispose(); }
});

test('RA4 two stored copies (dotted and host-only) are both removed', async () => {
  const env = await makeEnv({cookies: [staleCookie({domain: '.localhost'}), staleCookie({domain: 'localhost'})]});
  try {
    respond = vahan({issue: 'same'});
    await env.run();
    assert.equal(env.last().status, 'PASS', JSON.stringify(env.last()));
    const analytics = await env.jar(STALE_COOKIE);
    assert.deepEqual(analytics.map(cookie => cookie.value), ['FRESH-A']);
    assert.ok(!JSON.stringify(env.api.state).includes(STALE_VALUE));
  } finally { await env.dispose(); }
});

test('RA5 exact-tuple removal that does not take effect fails closed; no unfiltered clearCookies', async () => {
  const calls = [];
  const env = await makeEnv({wrapContext: context => new Proxy(context, {get(target, key) {
    if (key === 'clearCookies') {
      return async (options) => { calls.push(options); /* ignores the filter: removes nothing */ };
    }
    const value = target[key];
    return typeof value === 'function' ? value.bind(target) : value;
  }})});
  try {
    respond = vahan({issue: 'same'});
    await env.run();
    const result = env.last();
    assert.equal(result.status, 'CHECK_ERROR');
    assert.equal(result.errorCode, 'STATE_COOKIE_SCOPE_UNSUPPORTED');
    assert.ok(calls.length >= 1);
    assert.ok(calls.every(options => options && options.name && options.domain && options.path), 'every clear is by exact tuple');
    assert.equal(env.api.ops('PUT-sent').length, 0);
    assert.equal(byName(await env.jar(), STALE_COOKIE).length, 1, 'stale cookie still there (restored)');
    assert.equal(env.last().status === 'PASS', false);
  } finally { await env.dispose(); }
});

// =============================== G. state delta / acceptance ====================================
test('RG1 JSESSIONID issued with the cookie is saved; a context built from the stored state is accepted', async () => {
  const env = await makeEnv({cookies: [staleCookie()]});
  try {
    respond = vahan({issue: 'both', requireBoth: true});
    await env.run();
    assert.equal(env.last().status, 'PASS', JSON.stringify(env.last()));
    assert.deepEqual(env.last().recovery.deltaNames, ['JSESSIONID', 'analytics_sh_cok']);
    assert.equal(stateCookies(env.api, 'JSESSIONID').length, 1);
    // what a restart would load: the state exactly as stored
    const restarted = await browser.newContext({storageState: JSON.parse(JSON.stringify(env.api.state))});
    try {
      const page = await restarted.newPage();
      const response = await page.goto(URL_, {waitUntil: 'commit'});
      assert.equal(response.status(), 200, 'stored state is accepted by the fixture that requires both cookies');
    } finally { await restarted.close(); }
  } finally { await env.dispose(); }
});

test('RG2 only analytics_sh_cok issued (no JSESSIONID): saved state works on the next request', async () => {
  const env = await makeEnv({cookies: [staleCookie()]});
  try {
    respond = vahan({issue: 'same'});
    await env.run();
    assert.equal(env.last().status, 'PASS');
    assert.equal(stateCookies(env.api, 'JSESSIONID').length, 0);
    const restarted = await browser.newContext({storageState: JSON.parse(JSON.stringify(env.api.state))});
    try {
      const page = await restarted.newPage();
      assert.equal((await page.goto(URL_, {waitUntil: 'commit'})).status(), 200);
    } finally { await restarted.close(); }
  } finally { await env.dispose(); }
});

test('RG3/RG4 unexpected cookie names or server-side removal fail closed without touching state', async () => {
  for (const issue of ['extra', 'expireOther']) {
    const env = await makeEnv({cookies: [staleCookie(), jsession({path: '/'})]});
    try {
      respond = vahan({issue});
      await env.run();
      const result = env.last();
      assert.equal(result.status, 'CHECK_ERROR', issue);
      assert.equal(result.errorCode, 'STATE_DELTA_UNEXPECTED');
      assert.equal(env.api.ops('PUT-sent').length, 0);
      assert.equal((await env.jar(STALE_COOKIE))[0].value, STALE_VALUE, 'primary untouched');
      assert.ok(!JSON.stringify(result).includes('FRESH-A') && !JSON.stringify(result).includes(STALE_VALUE), 'only names in the log');
    } finally { await env.dispose(); }
  }
});

test('RG5 a candidate that would send different cookies is rejected (necessary condition)', async () => {
  const env = await makeEnv({cookies: [staleCookie()]});
  try {
    respond = vahan({issue: 'both'});
    let opened = 0;
    const real = env.deps.browser();
    env.deps.browser = () => ({newContext: async options => {
      opened += 1;
      if (opened === 3) { options = {...options, storageState: {...options.storageState, cookies: options.storageState.cookies.filter(cookie => cookie.name !== 'JSESSIONID')}}; }
      return real.newContext(options);
    }});
    await env.run();
    assert.equal(env.last().errorCode, 'RECOVERY_EQUIVALENCE_FAILED');
    assert.equal(env.api.ops('PUT-sent').length, 0);
  } finally { await env.dispose(); }
});

test('RG6 confirmation request rejected by VAHAN: nothing applied or saved', async () => {
  const env = await makeEnv({cookies: [staleCookie()]});
  try {
    respond = vahan({issue: 'same', confirm404: true});
    await env.run();
    const result = env.last();
    assert.equal(result.status, 'CHECK_ERROR');
    assert.equal(result.errorCode, 'RECOVERY_CONFIRM_FAILED');
    assert.match(result.error, /^Health check received HTTP 404 from VAHAN\./);
    assert.equal(env.api.ops('PUT-sent').length, 0);
    assert.equal((await env.jar(STALE_COOKIE))[0].value, STALE_VALUE);
  } finally { await env.dispose(); }
});

test('RG7 confirmation request that hangs ends within the budget without applying', async () => {
  const budget = {...BUDGET, hard: 9_000, logReserve: 1_500, recoveryMin: 4_000, nav1: 3_000, retryNav: 3_000, confirmNav: 1_500, control: 2_000, controlMin: 500, inspectMin: 300, persist: 1_500, apply: 500, minStep: 100, post: 1_500};
  const env = await makeEnv({cookies: [staleCookie()], budget});
  try {
    respond = vahan({issue: 'same', hangFresh: true});
    const started = Date.now();
    await env.run();
    assert.equal(env.last().status, 'CHECK_ERROR');
    assert.ok(Date.now() - started < budget.hard, 'answered before the hard deadline');
    assert.equal(env.api.ops('PUT-sent').length, 0);
    assert.equal((await env.jar(STALE_COOKIE))[0].value, STALE_VALUE);
  } finally { await env.dispose(); }
});

// =============================== D. real failures ===============================================
test('RD1 404 whatever the cookie: exactly one retry, CHECK_ERROR, nothing saved', async () => {
  const env = await makeEnv();
  try {
    respond = vahan({always404: true});
    await env.run();
    const result = env.last();
    assert.equal(result.status, 'CHECK_ERROR');
    assert.match(result.error, /HTTP 404/);
    assert.equal(result.errorCode, 'RECOVERY_RETRY_FAILED');
    assert.equal(requests.filter(request => request.url === '/report').length, 2);
    assert.equal(env.api.ops('PUT-sent').length, 0);
    assert.deepEqual(Array.from(result.observedControls), []);
    assert.equal((await env.jar(STALE_COOKIE))[0].value, STALE_VALUE);
  } finally { await env.dispose(); }
});

test('RD2/RD3 no stored cookie, or a status other than 404, never starts a recovery', async () => {
  for (const [cookies, status, pattern] of [[[], 404, /HTTP 404/], [[staleCookie()], 503, /HTTP 503/], [[staleCookie()], 401, /expected public report/]]) {
    const env = await makeEnv({cookies});
    try {
      respond = vahan({status});
      await env.run();
      assert.equal(env.last().status, 'CHECK_ERROR');
      assert.match(env.last().error, pattern);
      assert.equal(requests.filter(request => request.url === '/report').length, 1, `status ${status}: a single request`);
      assert.equal(env.last().recovery, undefined);
    } finally { await env.dispose(); }
  }
});

test('RD4 retry answers 200 but is not the Public Report: not recovered', async () => {
  const env = await makeEnv();
  try {
    respond = vahan({blankWithoutCookie: true});
    await env.run();
    assert.equal(env.last().errorCode, 'RECOVERY_DOM_REJECTED');
    assert.equal(env.api.ops('PUT-sent').length, 0);
    assert.equal((await env.jar(STALE_COOKIE))[0].value, STALE_VALUE);
  } finally { await env.dispose(); }
});

// =============================== P. persistence, crashes ========================================
test('RP1 PUT 500 after the cookie change: CHECK_ERROR, never PASS, cookie kept', async () => {
  const env = await makeEnv();
  try {
    respond = vahan({issue: 'same'});
    env.api.failPut = 500;
    await env.run();
    const result = env.last();
    assert.equal(result.status, 'CHECK_ERROR');
    assert.equal(result.errorCode, 'STATE_PERSIST_UNKNOWN');
    assert.equal(env.api.logs.some(log => log.status === 'PASS'), false);
    assert.equal((await env.jar(STALE_COOKIE))[0].value, 'FRESH-A', 'validated cookie is kept (I5)');
    assert.equal(result.recovery.cookieChanged, true);
  } finally { await env.dispose(); }
});

test('RP2 worker disconnected: no PUT is attempted and there is no PASS', async () => {
  const env = await makeEnv({connected: false});
  try {
    respond = vahan({issue: 'same'});
    await env.run();
    assert.equal(env.last().errorCode, 'STATE_PERSIST_FAILED');
    assert.equal(env.api.ops('PUT-sent').length, 0);
  } finally { await env.dispose(); }
});

test('RP3/RP4 PUT outcome unknown (timeout): no PASS; the next check re-reads the revision and passes', async () => {
  const env = await makeEnv();
  try {
    respond = vahan({issue: 'same'});
    const gate = deferred();
    env.api.hooks.beforeCommit = async () => { await gate.promise; };
    const budget = {...BUDGET, persist: 1_500};
    env.deps.budget = budget;
    await env.run();
    assert.equal(env.last().errorCode, 'STATE_PERSIST_UNKNOWN');
    assert.equal(env.store.revision, null, 'revision is unknown after a timeout');
    assert.equal(env.api.logs.some(log => log.status === 'PASS'), false);
    gate.release();                                      // the timed-out write commits late
    await sleep(100);
    env.api.hooks.beforeCommit = null;
    await env.run();                                     // jar already clean: ordinary path, re-reads revision
    assert.equal(env.last().status, 'PASS');
    assert.ok(env.api.ops('GET').length >= 1);
    assert.ok(!JSON.stringify(env.api.state).includes(STALE_VALUE));
  } finally { await env.dispose(); }
});

test('RP5 apply fails halfway: previous cookies restored and nothing is saved', async () => {
  let blocked = true;
  const env = await makeEnv({wrapContext: context => new Proxy(context, {get(target, key) {
    if (key === 'addCookies') {
      return async (...args) => {
        if (blocked) { blocked = false; throw new Error('injected addCookies failure'); }
        return target.addCookies(...args);
      };
    }
    const value = target[key];
    return typeof value === 'function' ? value.bind(target) : value;
  }})});
  try {
    respond = vahan({issue: 'same'});
    await env.run();
    assert.equal(env.last().errorCode, 'STATE_APPLY_FAILED');
    assert.equal(env.api.ops('PUT-sent').length, 0);
    assert.equal((await env.jar(STALE_COOKIE))[0].value, STALE_VALUE, 'restored');
    assert.equal(env.state.rebuilt, 0);
  } finally { await env.dispose(); }
});

test('RP6/RP7 restore fails: context is rebuilt from the stored state; if that fails it is quarantined', async () => {
  const broken = context => new Proxy(context, {get(target, key) {
    if (key === 'addCookies') return async () => { throw new Error('addCookies unavailable'); };
    const value = target[key];
    return typeof value === 'function' ? value.bind(target) : value;
  }});
  const env = await makeEnv({wrapContext: broken});
  try {
    respond = vahan({issue: 'same'});
    await env.run();
    assert.equal(env.state.rebuilt, 1);
    assert.equal(env.state.tainted, false);
    assert.equal(env.api.ops('PUT-sent').length, 0);
  } finally { await env.dispose(); }
  const env2 = await makeEnv({wrapContext: broken});
  try {
    respond = vahan({issue: 'same'});
    env2.deps.rebuildPrimary = async () => { throw new Error('cannot rebuild'); };
    await env2.run();
    assert.equal(env2.state.tainted, true);
    await env2.run();
    assert.equal(env2.last().errorCode, 'STATE_TAINTED');
  } finally { await env2.dispose(); }
});

test('RP8 browser relaunch while the state is being saved: CONTEXT_CHANGED, no PASS', async () => {
  const env = await makeEnv();
  try {
    respond = vahan({issue: 'same'});
    env.api.hooks.afterCommit = async () => { env.state.epoch += 1; };
    await env.run();
    assert.equal(env.last().errorCode, 'CONTEXT_CHANGED');
    assert.equal(env.api.logs.some(log => log.status === 'PASS'), false);
  } finally { await env.dispose(); }
});

test('RP9 a new process with the same id loads the saved state and is accepted (default random id starts empty)', async () => {
  const env = await makeEnv({cookies: [staleCookie(), jsession()]});
  try {
    respond = vahan({issue: 'both', requireBoth: true});
    await env.run();
    assert.equal(env.last().status, 'PASS');
    const relaunched = new StateStore({http: (path, init) => env.api.http(path, init), id: 'fixture-worker'});
    const loaded = await env.api.http('/api/runner-state/fixture-worker');
    relaunched.setRevision(loaded.revision);
    assert.equal(loaded.revision, env.api.revision);
    const context = await browser.newContext({storageState: loaded.state});
    try {
      const page = await context.newPage();
      assert.equal((await page.goto(URL_, {waitUntil: 'commit'})).status(), 200);
    } finally { await context.close(); }
    const fresh = await browser.newContext();     // random id: nothing is loaded, no stale cookie either
    try { assert.equal((await fresh.cookies()).length, 0); } finally { await fresh.close(); }
  } finally { await env.dispose(); }
});

test('RP10 a heartbeat save queued before the recovery cannot leave the stale cookie in the store', async () => {
  const env = await makeEnv();
  try {
    respond = vahan({issue: 'same'});
    env.api.hooks.beforeCommit = async body => { if (body.value?.marker === 'hb') await sleep(150); };
    const heartbeat = env.store.persist(async () => ({...(await env.primary().storageState()), marker: 'hb'}));
    await env.run();
    await heartbeat;
    assert.equal(env.last().status, 'PASS');
    assert.ok(!JSON.stringify(env.api.state).includes(STALE_VALUE));
    assert.equal(stateCookies(env.api, STALE_COOKIE)[0].value, 'FRESH-A');
  } finally { await env.dispose(); }
});

// =============================== F. fencing against late writes =================================
function heartbeatState(env) { return async () => ({...(await env.primary().storageState()), marker: 'heartbeat-old'}); }

test('RF1 an old write sent first and committed last cannot win; PASS only after the ack', async () => {
  const env = await makeEnv();
  try {
    respond = vahan({issue: 'same'});
    const gate = deferred();
    env.api.hooks.beforeCommit = async body => { if (body.value?.marker === 'heartbeat-old') await gate.promise; };
    env.store.setRevision(0);
    await assert.rejects(env.store.persist(heartbeatState(env), {timeoutFor: () => 100}), error => error.code === 'STATE_PERSIST_UNKNOWN');
    assert.equal(env.store.revision, null);
    await env.run();                                  // resync GET -> PUT#2 acked -> PASS
    assert.equal(env.last().status, 'PASS');
    const committed = env.api.revision;
    gate.release();                                   // the old write now reaches the commit
    await sleep(100);
    assert.equal(env.api.ops('PUT-409').some(entry => entry.marker === 'heartbeat-old'), true, 'old write was rejected');
    assert.equal(env.api.revision, committed);
    assert.notEqual(env.api.state.marker, 'heartbeat-old');
    assert.ok(!JSON.stringify(env.api.state).includes(STALE_VALUE));
    const ackAt = env.api.log.findIndex(entry => entry.op === 'PUT-commit' && entry.marker === undefined);
    const postAt = env.api.log.findIndex(entry => entry.op === 'POST-sent' && entry.status === 'PASS');
    assert.ok(ackAt >= 0 && postAt > ackAt, 'PASS posted after the recovery write was acknowledged');
  } finally { await env.dispose(); }
});

test('RF2 old write commits between the revision read and the new write: conflict, re-read, then PASS', async () => {
  const env = await makeEnv();
  try {
    respond = vahan({issue: 'same'});
    const gate = deferred();
    env.api.hooks.beforeCommit = async body => { if (body.value?.marker === 'heartbeat-old') await gate.promise; };
    await assert.rejects(env.store.persist(heartbeatState(env), {timeoutFor: () => 100}));
    let released = false;
    env.api.hooks.afterGet = async () => {            // the old write commits right after the revision was read
      if (released) return;
      released = true; gate.release(); await sleep(60);
    };
    await env.run();
    assert.equal(env.last().status, 'PASS');
    assert.ok(env.api.ops('PUT-409').length >= 1, 'the new write was rejected once and retried with a fresh state');
    assert.notEqual(env.api.state.marker, 'heartbeat-old');
    assert.ok(!JSON.stringify(env.api.state).includes(STALE_VALUE));
  } finally { await env.dispose(); }
});

test('RF3 control: without fencing the same sequence does regress the stored state', async () => {
  const env = await makeEnv();
  try {
    respond = vahan({issue: 'same'});
    env.api.fenced = false;
    const gate = deferred();
    env.api.hooks.beforeCommit = async body => { if (body.value?.marker === 'heartbeat-old') await gate.promise; };
    await assert.rejects(env.store.persist(heartbeatState(env), {timeoutFor: () => 100}));
    await env.run();
    gate.release();
    await sleep(100);
    assert.equal(env.api.state.marker, 'heartbeat-old', 'the old write wins when nothing fences it');
  } finally { await env.dispose(); }
});

test('RF4 ordinary PASS after the store was changed by someone else re-reads and saves again', async () => {
  const env = await makeEnv({cookies: []});
  try {
    respond = vahan({issue: 'same'});
    await env.run();
    assert.equal(env.last().status, 'PASS');
    env.api.revision += 5; env.api.state = {cookies: [], origins: [], marker: 'foreign'};
    await env.run();
    assert.equal(env.last().status, 'PASS');
    assert.ok(env.api.ops('PUT-409').length >= 1);
    assert.notEqual(env.api.state.marker, 'foreign');
  } finally { await env.dispose(); }
});

test('RF5 primary changes cookies while the PUT waits: not PASS on that ack; saved again and then PASS', async () => {
  const env = await makeEnv({cookies: []});
  try {
    respond = vahan({issue: 'same'});
    let first = true;
    env.api.hooks.beforeCommit = async () => {
      if (!first) return;
      first = false;
      await env.primary().addCookies([{name: 'LATE', value: 'v1', domain: 'localhost', path: '/', expires: -1, httpOnly: false, secure: false, sameSite: 'Lax'}]);
    };
    await env.run();
    assert.equal(env.last().status, 'PASS');
    assert.equal(env.api.ops('PUT-commit').length, 2, 'snapshot saved twice');
    assert.equal(stateCookies(env.api, 'LATE').length, 1, 'the stored state includes the late cookie');
    assert.equal(digestState(env.api.state) === digestState(await env.primary().storageState()), true);
  } finally { await env.dispose(); }
});

test('RF6 primary keeps changing after every save: STATE_CHANGED_DURING_PERSIST, no PASS', async () => {
  const env = await makeEnv({cookies: []});
  try {
    respond = vahan({issue: 'same'});
    let n = 0;
    env.api.hooks.afterCommit = async () => {
      n += 1;
      await env.primary().addCookies([{name: 'CHURN', value: 'v' + n, domain: 'localhost', path: '/', expires: -1, httpOnly: false, secure: false, sameSite: 'Lax'}]);
    };
    await env.run();
    assert.equal(env.last().errorCode, 'STATE_CHANGED_DURING_PERSIST');
    assert.equal(env.api.logs.some(log => log.status === 'PASS'), false);
  } finally { await env.dispose(); }
});

test('RF7 change after the digest check is outside the claim: PASS is sent for the saved snapshot', async () => {
  const env = await makeEnv({cookies: []});
  try {
    respond = vahan({issue: 'same'});
    env.api.hooks.beforeLog = async () => {
      await env.primary().addCookies([{name: 'AFTER', value: 'x', domain: 'localhost', path: '/', expires: -1, httpOnly: false, secure: false, sameSite: 'Lax'}]);
    };
    await env.run();
    assert.equal(env.last().status, 'PASS');
    assert.equal(stateCookies(env.api, 'AFTER').length, 0, 'the saved state is the snapshot that was acknowledged');
  } finally { await env.dispose(); }
});

// =============================== E. deadline ====================================================
const SMALL = {...BUDGET, hard: 6_000, logReserve: 1_500, nav1: 2_000, retryNav: 2_000, confirmNav: 1_500, control: 1_500, controlMin: 300,
  inspectMin: 200, persist: 1_000, apply: 300, minStep: 100, post: 1_000, recoveryMin: 2_500, launchContract: 1_500, close: 500};

test('RE0 every timeout handed to Playwright or HTTP is positive, even with almost no time left', async () => {
  for (const hard of [1_600, 1_900, 2_600, 6_000]) {
    const budget = {...SMALL, hard};
    const env = await makeEnv({budget});
    try {
      respond = vahan({issue: 'same'});
      try { await env.run(); } catch (error) { assert.match(error.code || '', /HEALTH_DEADLINE_EXCEEDED/); }
      assert.ok(env.timeouts.every(entry => Number.isFinite(entry.timeout) && entry.timeout > 0), JSON.stringify(env.timeouts));
    } finally { await env.dispose(); }
  }
});

test('RE1 navigation that never answers: reply before the hard deadline, contexts closed, no PUT', async () => {
  const before = browser.contexts().length;
  const env = await makeEnv({budget: SMALL});
  try {
    respond = () => ({hang: true});
    const started = Date.now();
    await env.run();
    assert.ok(Date.now() - started < SMALL.hard, 'answered before the hard deadline');
    assert.equal(env.last().status, 'CHECK_ERROR');
    assert.equal(env.api.ops('PUT-sent').length, 0);
    await sleep(100);
    assert.equal(browser.contexts().length, before + 1, 'only the primary context remains');
  } finally { await env.dispose(); }
});

test('RE5 a launch that never completes is answered before the hard deadline', async () => {
  const env = await makeEnv({budget: SMALL});
  try {
    env.deps.launch = () => new Promise(() => {});
    const started = Date.now();
    await env.run();
    assert.equal(env.last().errorCode, 'HEALTH_DEADLINE_EXCEEDED');
    assert.ok(Date.now() - started < SMALL.hard);
    assert.equal(env.api.ops('PUT-sent').length, 0);
  } finally { await env.dispose(); }
});

test('RE4 the log POST commits after the client gave up: not retried, ordered after the save', async () => {
  const env = await makeEnv({cookies: [], budget: {...SMALL, post: 300, hard: 8_000}});
  try {
    respond = vahan({issue: 'same'});
    env.api.hooks.beforeLog = async () => { await sleep(900); };
    await assert.rejects(env.run(), error => error.name === 'TimeoutError' || /timeout|aborted/i.test(error.message));
    await sleep(1_200);
    assert.equal(env.api.ops('POST-sent').length, 1, 'exactly one POST for the check');
    assert.equal(env.api.logs.length, 1, 'the late commit still happened');
    const putAt = env.api.log.findIndex(entry => entry.op === 'PUT-commit');
    const postAt = env.api.log.findIndex(entry => entry.op === 'POST-sent');
    assert.ok(putAt >= 0 && postAt > putAt);
  } finally { await env.dispose(); }
});

// =============================== H. hygiene =====================================================
test('RH1 cookie values never appear in the health payload or the recovery evidence', async () => {
  const env = await makeEnv({cookies: [staleCookie(), jsession()]});
  try {
    respond = vahan({issue: 'both'});
    await env.run();
    const text = JSON.stringify(env.api.logs);
    for (const secret of [STALE_VALUE, 'FRESH-A', 'SESS-1', 'OLD-SESSION']) assert.ok(!text.includes(secret), `${secret} leaked`);
    assert.equal(env.last().status, 'PASS');
  } finally { await env.dispose(); }
});

test('RH2 check ids/sequence are copied and a health check always posts exactly once', async () => {
  const env = await makeEnv({cookies: []});
  try {
    respond = vahan({issue: 'same'});
    await env.run({requestId: 'req-1', checkSeq: 42, trigger: 'preflight'});
    assert.equal(env.last().checkId, 'req-1');
    assert.equal(env.last().checkSeq, 42);
    assert.equal(env.api.ops('POST-sent').length, 1);
  } finally { await env.dispose(); }
});
