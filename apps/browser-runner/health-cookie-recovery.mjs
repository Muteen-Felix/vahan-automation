// Health check with bounded recovery from a stored cookie that VAHAN answers with HTTP 404, plus the
// revision-fenced browser-state store (PLAN_STATE_VAHAN WP-R). Everything here is dependency-injected
// so it can be exercised against real Chromium and a fake API without starting the runner.
import {createHash} from 'node:crypto';

export const STALE_COOKIE = 'analytics_sh_cok';
// The only cookies a recovery may add or change (the set observed on the real runners).
export const ALLOWED_DELTA_NAMES = new Set([STALE_COOKIE, 'JSESSIONID']);

// All values are assumptions to be tuned after measurement (PLAN §4.7).
export const BUDGET = {
  hard: 50_000, logReserve: 8_000, minStep: 1_000, finishWait: 10_000, launchContract: 10_000,
  nav1: 30_000, control: 15_000, controlMin: 3_000, inspectMin: 2_000, retryNav: 15_000,
  confirmNav: 12_000, apply: 2_000, persist: 8_000, post: 8_000, recoveryMin: 35_000, close: 2_000,
};

export class HealthError extends Error {
  constructor(code, message) { super(message || code); this.code = code; }
}

/** One deadline for the whole check. Every timeout is derived from it and is always > 0. */
export class Deadline {
  constructor(budget = BUDGET, now = Date.now, startedAt) {
    this.b = budget; this.now = now; this.start = startedAt ?? now();
  }
  get stepEnd() { return this.start + this.b.hard - this.b.logReserve; }
  get hardEnd() { return this.start + this.b.hard; }
  remaining() { return this.stepEnd - this.now(); }
  slice(maxMs, reserveAfterMs = 0, label = 'next step') {
    const ms = Math.floor(Math.min(maxMs, this.remaining() - reserveAfterMs));
    // Playwright treats timeout 0 as "no timeout" and AbortSignal.timeout(0) as "abort now":
    // never hand either of them a non-positive value.
    if (!(ms >= this.b.minStep)) throw new HealthError('HEALTH_DEADLINE_EXCEEDED', `Health check ran out of time before ${label}.`);
    return ms;
  }
  logTimeout() {
    const ms = Math.floor(Math.min(this.b.post, this.hardEnd - this.now()));
    if (!(ms >= this.b.minStep)) throw new HealthError('HEALTH_DEADLINE_EXCEEDED', 'No time was left to record the health check.');
    return ms;
  }
  async run(label, maxMs, reserveAfterMs, fn) {
    const ms = this.slice(maxMs, reserveAfterMs, label);
    let timer;
    try {
      return await Promise.race([fn(ms), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new HealthError('HEALTH_DEADLINE_EXCEEDED', `Health check step "${label}" timed out.`)), ms + 250);
      })]);
    } finally { clearTimeout(timer); }
  }
}

// ---- cookie helpers (values are only ever compared in memory, never logged) --------------------
const sha = value => createHash('sha256').update(String(value)).digest('hex');
export const tupleKey = cookie => `${cookie.name}\u0000${cookie.domain}\u0000${cookie.path}`;
export function cookieSet(cookies) {
  return (cookies || []).map(cookie => `${tupleKey(cookie)}\u0000${sha(cookie.value)}`).sort();
}
export const sameSet = (a, b) => a.length === b.length && a.every((value, index) => value === b[index]);
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}
/** Digest of a whole storageState (cookies + origins). In-memory only. */
export function digestState(state) {
  const part = items => [...(items || [])].map(item => JSON.stringify(canonical(item))).sort();
  return sha(JSON.stringify({cookies: part(state?.cookies), origins: part(state?.origins)}));
}
export function withoutCookieByName(state, name) {
  const copy = JSON.parse(JSON.stringify(state || {cookies: [], origins: []}));
  copy.cookies = (copy.cookies || []).filter(cookie => cookie.name !== name);
  return copy;
}
/** What changed in `after` relative to `base`, keyed by (name, domain, path). */
export function computeDelta(base, after) {
  const before = new Map((base || []).map(cookie => [tupleKey(cookie), cookie]));
  const next = new Map((after || []).map(cookie => [tupleKey(cookie), cookie]));
  const added = [], changed = [], removed = [];
  for (const [key, cookie] of next) {
    if (!before.has(key)) added.push(cookie);
    else if (before.get(key).value !== cookie.value) changed.push(cookie);
  }
  for (const [key, cookie] of before) if (!next.has(key)) removed.push(cookie);
  return {added, changed, removed};
}
export function deltaViolations(delta, hostMatches = () => true) {
  const names = new Set();
  for (const cookie of [...delta.added, ...delta.changed]) {
    if (!ALLOWED_DELTA_NAMES.has(cookie.name) || !hostMatches(cookie.domain)) names.add(cookie.name);
  }
  for (const cookie of delta.removed) names.add(cookie.name);
  return [...names].sort();
}

/** Stricter than the SQL structural validation, so it can safely gate a cookie change. */
export function localContractAccepts(rows, controls) {
  const fail = (field, reason) => ({ok: false, field, reason});
  if (!Array.isArray(rows) || !Array.isArray(controls) || !controls.length) return fail(null, 'no contract to compare');
  const byField = new Map(rows.map(row => [row.field, row]));
  const selectors = new Set();
  for (const control of controls) {
    const row = byField.get(control.field);
    if (!row || row.found !== true || row.count !== 1) return fail(control.field, 'control missing or ambiguous');
    if (row.tag !== control.tag) return fail(control.field, 'control type changed');
    if (control.tag === 'select' && row.multiple !== control.multiple) return fail(control.field, 'selection behavior changed');
    if (control.tag === 'input') {
      const allowed = String(control.field).endsWith('Year') ? ['text', 'number'] : ['text', 'date'];
      if (!allowed.includes(row.inputType)) return fail(control.field, 'input behavior changed');
    }
    if (typeof row.selector !== 'string' || !row.selector || row.selector.length > 250) return fail(control.field, 'invalid selector');
    if (selectors.has(row.selector)) return fail(control.field, 'two fields resolve to one control');
    selectors.add(row.selector);
    if (row.matchedBy !== 'selector' || row.selector !== control.selector) return fail(control.field, 'selector is not the verified one');
    if (control.name && row.name !== control.name && control.label && row.label !== control.label) return fail(control.field, 'name and label both changed');
  }
  const states = byField.get('states');
  if (!states || !(states.optionCount > 0)) return fail('states', 'State control has no options');
  if (!byField.get('apply')?.found) return fail('apply', 'apply control missing');
  return {ok: true};
}

// ---- cookie operations on the primary context (always by exact tuple; never clearCookies()) ----
const addable = cookie => ({name: cookie.name, value: cookie.value, domain: cookie.domain, path: cookie.path,
  expires: cookie.expires, httpOnly: cookie.httpOnly, secure: cookie.secure, sameSite: cookie.sameSite});

async function clearTuples(context, tuples) {
  for (const tuple of tuples) await context.clearCookies({name: tuple.name, domain: tuple.domain, path: tuple.path});
}

/** Restore exactly `pre` for the tuples that were touched. Throws when it cannot be verified. */
async function restoreCookies(context, pre, touched) {
  await clearTuples(context, [...touched.values()]);
  const originals = pre.filter(cookie => touched.has(tupleKey(cookie)));
  if (originals.length) await context.addCookies(originals.map(addable));
  if (!sameSet(cookieSet(await context.cookies()), cookieSet(pre))) throw new HealthError('STATE_RESTORE_FAILED', 'Could not restore the previous cookies.');
}

/** Replace the stale cookie(s) with the delta on the live context, verifying every step. */
export async function applyDeltaToPrimary(context, delta, {rebuild, setTainted} = {}) {
  const pre = await context.cookies();
  const touched = new Map();
  for (const cookie of pre.filter(item => item.name === STALE_COOKIE)) touched.set(tupleKey(cookie), cookie);
  const incoming = [...delta.added, ...delta.changed];
  for (const cookie of incoming) touched.set(tupleKey(cookie), cookie);
  try {
    await clearTuples(context, [...touched.values()]);
    if ((await context.cookies()).some(cookie => touched.has(tupleKey(cookie)))) {
      throw new HealthError('STATE_COOKIE_SCOPE_UNSUPPORTED', 'Cookies could not be removed by exact name, domain and path.');
    }
    if (incoming.length) await context.addCookies(incoming.map(addable));
    const expected = [...pre.filter(cookie => !touched.has(tupleKey(cookie))), ...incoming];
    if (!sameSet(cookieSet(await context.cookies()), cookieSet(expected))) {
      throw new HealthError('STATE_APPLY_FAILED', 'The browser cookies do not match the verified candidate.');
    }
  } catch (error) {
    try {
      await restoreCookies(context, pre, touched);
    } catch {
      // The live jar is unknown: rebuild it from the stored state (not yet changed by this check).
      try { await rebuild?.(); } catch { setTainted?.(); }
    }
    throw error instanceof HealthError ? error : new HealthError('STATE_APPLY_FAILED', error.message);
  }
  return {replaced: [...touched.values()].map(cookie => `${cookie.name}@${cookie.domain}${cookie.path}`)};
}

// ---- revision-fenced browser-state store ------------------------------------------------------
export class StateStore {
  constructor({http, id, isConnected = () => true}) {
    this.http = http; this.id = id; this.isConnected = isConnected;
    this.revision = null;           // null = unknown: the next write must re-read the revision
    this.queue = Promise.resolve();
  }
  setRevision(value) { this.revision = Number.isInteger(value) ? value : null; }
  /** Serialize every state write (heartbeat, job end, recovery). A failed task does not poison the queue. */
  exclusive(task) {
    const run = this.queue.then(task, task);
    this.queue = run.then(() => {}, () => {});
    return run;
  }
  async resync(timeoutMs) {
    const saved = await this.http(`/api/runner-state/${this.id}`, {timeoutMs});
    if (!Number.isInteger(saved?.revision)) {
      throw new HealthError('STATE_PERSIST_FAILED', 'The API does not report a state revision; it must be upgraded first.');
    }
    this.revision = saved.revision;
  }
  /** Caller holds the queue (inside exclusive()). `getState` is called again after a conflict so a
   *  stale body is never re-sent. */
  async persistLocked(getState, {timeoutFor = () => 60_000, strict = false} = {}) {
    if (!this.isConnected()) {
      if (strict) throw new HealthError('STATE_PERSIST_FAILED', 'The worker is not connected to the API.');
      return null;
    }
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        if (this.revision === null) await this.resync(timeoutFor());
        const state = await getState();
        const response = await this.http(`/api/runner-state/${this.id}`, {method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({value: state, expectedRevision: this.revision}), timeoutMs: timeoutFor()});
        if (!Number.isInteger(response?.revision)) {
          this.revision = null;
          throw new HealthError('STATE_PERSIST_UNKNOWN', 'The API did not acknowledge a state revision.');
        }
        this.revision = response.revision;
        return {revision: response.revision, state};
      } catch (error) {
        if (error instanceof HealthError) throw error;
        if (error.status === 409) {
          const current = error.body?.detail?.currentRevision;
          this.revision = Number.isInteger(current) ? current : null;
          continue;
        }
        this.revision = null;        // the write may or may not have been committed
        const definitive = error.status >= 400 && error.status < 500;
        throw new HealthError(definitive ? 'STATE_PERSIST_FAILED' : 'STATE_PERSIST_UNKNOWN', `State could not be stored: ${error.message}`);
      }
    }
    throw new HealthError('STATE_PERSIST_FAILED', 'The stored state kept changing; it was not saved.');
  }
  persist(getState, options) { return this.exclusive(() => this.persistLocked(getState, options)); }
}

/** Persist a snapshot and prove the primary did not change meanwhile (ack proves only the snapshot).
 *  Must be called inside store.exclusive(). */
export async function persistStable(store, getState, deadline, {rounds = 2} = {}) {
  const end = Math.min(deadline.stepEnd, deadline.now() + deadline.b.persist);
  const timeoutFor = () => {
    const ms = Math.floor(end - deadline.now());
    if (!(ms >= deadline.b.minStep)) throw new HealthError('HEALTH_DEADLINE_EXCEEDED', 'Health check ran out of time while saving the browser state.');
    return ms;
  };
  for (let round = 0; round < rounds; round += 1) {
    let sent;
    const result = await store.persistLocked(async () => { sent = await getState(); return sent; }, {timeoutFor, strict: true});
    const sentDigest = digestState(sent);
    if (digestState(await getState()) === sentDigest) return {revision: result.revision, digest: sentDigest};
  }
  throw new HealthError('STATE_CHANGED_DURING_PERSIST', 'The browser state kept changing while it was being saved.');
}

// ---- the health check -------------------------------------------------------------------------
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function closeBounded(context, ms) {
  await Promise.race([context.close().catch(() => {}), delay(ms)]);
}

/**
 * deps: {browser(), context(), launch(), http(path,init), URL (string), target (URL object),
 *        ID, randomUUID(), inspectControls, store (StateStore), epoch(), isTainted(), setTainted(),
 *        markPageNeedsReset(), rebuildPrimary(), UrlCtor, budget?, now?}
 */
export async function runHealthCheck(deps, request = {}) {
  const budget = deps.budget || BUDGET;
  const clock = deps.now || Date.now;
  const deadline = new Deadline(budget, clock, request.startedAt);
  const Url = deps.UrlCtor || URL;
  const opened = [];
  const viewport = {width: 1440, height: 1000};
  const open = async options => { const context = await deps.browser().newContext(options); opened.push(context); return context; };
  const epoch0 = deps.epoch();
  const assertLive = () => {
    if (clock() > deadline.stepEnd) throw new HealthError('HEALTH_DEADLINE_EXCEEDED', 'Health check ran out of time.');
    if (deps.epoch() !== epoch0) throw new HealthError('CONTEXT_CHANGED', 'The browser was restarted during the check.');
    if (deps.isTainted()) throw new HealthError('STATE_TAINTED', 'Browser state is quarantined; restart this worker.');
  };
  const hostMatches = domain => {
    const host = deps.target.hostname;
    const bare = String(domain || '').replace(/^\./, '');
    return host === bare || host.endsWith('.' + bare) || bare.endsWith('.' + host);
  };
  let result;
  let recoveryTrace = null;
  try {
    assertLive();
    // Reserves are derived from the budget: launch and contract must leave room for the navigation.
    await deadline.run('launch', budget.launchContract, budget.nav1, () => deps.launch());
    const contract = await deps.http('/api/ui-health/contract', {timeoutMs: deadline.slice(budget.launchContract, Math.max(0, budget.nav1 - budget.launchContract), 'the contract')});
    const primary = deps.context();
    const snapshot = JSON.parse(JSON.stringify(await primary.storageState()));
    const staleInSnapshot = snapshot.cookies.filter(cookie => cookie.name === STALE_COOKIE);

    const onReportPage = (page) => {
      const location = new Url(page.url());
      return location.origin === deps.target.origin && location.pathname === deps.target.pathname;
    };
    // Waits for the controls, then reads them. Used by every navigation that may become PASS.
    const observe = async (page, reserveAfter) => {
      const waitMs = deadline.slice(budget.control, reserveAfter + budget.inspectMin, 'the control check');
      await page.waitForFunction(controls => controls.every(control => {
        try {
          const direct = document.querySelector(control.selector);
          const semantic = control.name ? [...document.querySelectorAll('select,input,button')].filter(el => el.getAttribute('name') === control.name) : [];
          const element = direct || (semantic.length === 1 ? semantic[0] : null);
          return element && (control.field !== 'states' || element.options?.length);
        } catch { return false; }
      }), contract.controls, {timeout: Math.min(waitMs, 10_000)}).catch(() => {});
      return deps.inspectControls(page, contract);
    };

    const first = await open({storageState: snapshot, viewport});
    const firstPage = await first.newPage();
    // The document commit is enough; a bounded control probe follows (slow assets must not fail the check).
    const response = await firstPage.goto(deps.URL, {waitUntil: 'commit',
      timeout: deadline.slice(budget.nav1, budget.controlMin + budget.inspectMin + budget.persist, 'navigation')});
    const status = response?.status();
    if (status === 401 || !onReportPage(firstPage)) throw new Error('Health check did not reach the expected public report page.');
    const recoverable = status === 404 && staleInSnapshot.length > 0 && deadline.remaining() >= budget.recoveryMin;
    if (status >= 400 && !recoverable) throw new Error(`Health check received HTTP ${status} from VAHAN.`);

    let rows;
    let recovery;
    if (!recoverable) {
      rows = await observe(firstPage, budget.persist);
      // PASS requires the primary's state to be stored (acknowledged revision) and unchanged.
      await deps.store.exclusive(async () => {
        assertLive();
        await persistStable(deps.store, () => primary.storageState(), deadline);
        assertLive();
      });
    } else {
      recoveryTrace = {attempted: true, recovered: false, droppedCookie: STALE_COOKIE, attempts: [{status: 404}]};
      const base = snapshot.cookies.filter(cookie => cookie.name !== STALE_COOKIE);
      const rejected = reason => new HealthError(reason.code, `Health check received HTTP 404 from VAHAN. ${reason.text}`);
      // Retry once, in a fresh isolated context, without the stale cookie.
      const retry = await open({storageState: withoutCookieByName(snapshot, STALE_COOKIE), viewport});
      const retryPage = await retry.newPage();
      const retryResponse = await retryPage.goto(deps.URL, {waitUntil: 'commit',
        timeout: deadline.slice(budget.retryNav, budget.controlMin + budget.inspectMin + budget.confirmNav + budget.apply + budget.persist, 'the retry')});
      const retryStatus = retryResponse?.status() ?? null;
      recoveryTrace.attempts.push({status: retryStatus});
      if (!(retryStatus >= 200 && retryStatus < 300) || !onReportPage(retryPage)) {
        throw rejected({code: 'RECOVERY_RETRY_FAILED', text: `Retry without ${STALE_COOKIE}: ${retryStatus === null ? 'no response' : 'HTTP ' + retryStatus}.`});
      }
      rows = await observe(retryPage, budget.confirmNav + budget.apply + budget.persist);
      const verdict = localContractAccepts(rows, contract.controls);
      if (!verdict.ok) throw rejected({code: 'RECOVERY_DOM_REJECTED', text: `Retry without ${STALE_COOKIE} did not show the Public Report (${verdict.field || 'contract'}: ${verdict.reason}).`});
      const afterState = JSON.parse(JSON.stringify(await retry.storageState()));
      const delta = computeDelta(base, afterState.cookies);
      const bad = deltaViolations(delta, hostMatches);
      recoveryTrace.deltaNames = [...new Set([...delta.added, ...delta.changed].map(cookie => cookie.name))].sort();
      if (bad.length) throw new HealthError('STATE_DELTA_UNEXPECTED', `Health check received HTTP 404 from VAHAN. The retry changed unexpected cookies: ${bad.join(', ')}.`);
      // Necessary condition: a context built from the candidate sends exactly what the retry sent.
      const candidate = await open({storageState: JSON.parse(JSON.stringify(afterState)), viewport});
      if (!sameSet(cookieSet(await candidate.cookies(deps.URL)), cookieSet(await retry.cookies(deps.URL)))) {
        throw new HealthError('RECOVERY_EQUIVALENCE_FAILED', 'The candidate state would not send the cookies that the retry sent.');
      }
      // Acceptance evidence: when the server issued/changed cookies, a request built only from
      // the candidate must also be accepted (the retry itself is the proof when nothing changed).
      let confirm = 'skipped';
      if (!sameSet(cookieSet(afterState.cookies), cookieSet(base))) {
        const confirmPage = await candidate.newPage();
        const confirmResponse = await confirmPage.goto(deps.URL, {waitUntil: 'commit',
          timeout: deadline.slice(budget.confirmNav, budget.controlMin + budget.inspectMin + budget.apply + budget.persist, 'the confirmation request')});
        const confirmStatus = confirmResponse?.status() ?? null;
        recoveryTrace.attempts.push({status: confirmStatus, confirm: true});
        if (!(confirmStatus >= 200 && confirmStatus < 300) || !onReportPage(confirmPage)) {
          throw new HealthError('RECOVERY_CONFIRM_FAILED', `Health check received HTTP 404 from VAHAN. The state to be saved was not accepted (${confirmStatus === null ? 'no response' : 'HTTP ' + confirmStatus}).`);
        }
        const confirmRows = await observe(confirmPage, budget.apply + budget.persist);
        const confirmVerdict = localContractAccepts(confirmRows, contract.controls);
        if (!confirmVerdict.ok) throw new HealthError('RECOVERY_CONFIRM_FAILED', `Health check received HTTP 404 from VAHAN. The state to be saved did not show the Public Report (${confirmVerdict.field || 'contract'}: ${confirmVerdict.reason}).`);
        confirm = 'done';
      }
      // Commit point: apply to the live context, then persist (fenced). Needs time for both.
      deadline.slice(budget.apply + budget.persist, 0, 'saving the recovered state');
      const stored = await deps.store.exclusive(async () => {
        assertLive();
        const applied = await applyDeltaToPrimary(primary, delta, {rebuild: deps.rebuildPrimary, setTainted: deps.setTainted});
        recoveryTrace.cookieChanged = true;
        recoveryTrace.replaced = applied.replaced.length;
        deps.markPageNeedsReset();
        assertLive();
        const saved = await persistStable(deps.store, () => primary.storageState(), deadline);
        assertLive();                       // a relaunch meanwhile means the saved state is not the live one
        return saved;
      });
      recovery = {...recoveryTrace, recovered: true, confirm, stateRevision: stored.revision, stateVerified: true};
    }
    result = {status: 'PASS', observedControls: rows, checkedAt: new Date().toISOString(),
      contract: {path: deps.target.pathname, revision: contract.revision}};
    if (recovery) result.recovery = recovery;
  } catch (error) {
    result = {status: 'CHECK_ERROR', error: error.message, errorCode: error.code, observedControls: [], checkedAt: new Date().toISOString()};
    if (recoveryTrace) result.recovery = {...recoveryTrace, recovered: false, errorCode: error.code};
  } finally {
    await Promise.all(opened.map(context => closeBounded(context, budget.close)));
  }
  result.trigger = request.trigger || 'preflight';
  result.logId = request.requestId || deps.randomUUID();
  result.checkId = result.logId;
  if (Number.isInteger(request.checkSeq)) result.checkSeq = request.checkSeq;
  // Exactly one POST per check (a repeated checkId re-runs evaluation without a new log row).
  return deps.http('/api/ui-health/logs', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({runnerId: deps.ID, pageUrl: deps.URL, healthCheck: result}), timeoutMs: deadline.logTimeout()});
}
