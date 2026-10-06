// DOM driver for VAHAN filters and report results.
(() => {
const splitValues = (value) => (Array.isArray(value) ? value : String(value ?? "").split(","))
  .map((item) => String(item ?? "").trim()).filter(Boolean);
const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let activeFillContext;
let pendingPageRequests = 0;
const assertFillActive = () => {
  if (activeFillContext?.controller.signal.aborted) throw activeFillContext.controller.signal.reason;
};

// Watch the page's own asynchronous filter handlers without changing responses.
// The barrier also includes outstanding initial option loads. Requests begun
// during a fill are additionally cancelled if that fill fails.
function trackFilterRequest() {
  const context = activeFillContext;
  pendingPageRequests++;
  if (context) context.pending++;
  let finished = false;
  return () => {
    if (finished) return;
    finished = true;
    pendingPageRequests--;
    if (context) context.pending--;
    document.dispatchEvent(new Event('vahan:filter-request-settled'));
  };
}
const originalFetch = globalThis.fetch;
globalThis.fetch = function (...args) {
  const context = activeFillContext;
  if (context) {
    const signal = context.controller.signal;
    const init = args[1] || {};
    const priorSignal = init.signal || args[0]?.signal;
    args[1] = {...init, signal: priorSignal ? AbortSignal.any([signal, priorSignal]) : signal};
  }
  const finish = trackFilterRequest();
  try {
    return originalFetch.apply(this, args).then(response => {
      // fetch resolves at headers; dependent options may still be parsing JSON.
      if (context || /json/i.test(response.headers.get('content-type') || '')) response.clone().arrayBuffer().then(finish, finish);
      else finish();
      return response;
    }, error => { finish(); throw error; });
  } catch (error) { finish(); throw error; }
};
const originalXhrSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.send = function (...args) {
  const finish = trackFilterRequest();
  const signal = activeFillContext?.controller.signal;
  const abort = () => this.abort();
  const settled = () => { signal?.removeEventListener('abort', abort); finish(); };
  signal?.addEventListener('abort', abort, {once: true});
  this.addEventListener('loadend', settled, {once: true});
  try { return originalXhrSend.apply(this, args); }
  catch (error) { this.removeEventListener('loadend', settled); settled(); throw error; }
};

const getActiveVahanAuthHold = async () => null;
function getOptionMap(select) {
  return [...select.options].map((option) => ({
    label: normalize(option.label || option.textContent),
    value: option.value,
  }));
}

function selectOptionsSignature(selector) {
  const select = document.querySelector(selector);
  if (!select) return "";
  return [...select.options]
    .map((option) => `${option.value}\u0000${normalize(option.label || option.textContent)}`)
    .join("\u0001");
}

async function waitForSelectOptionsChange(selector, previousSignature, timeout = 15_000) {
  await waitForDomCondition(
    () => {
      const signature = selectOptionsSignature(selector);
      return Boolean(signature && signature !== previousSignature);
    },
    timeout,
    0,
    `${selector}: options did not update after the filter changed.`,
  );
}

async function waitForOptions(selector, labels, timeout = 15000, previousSignature = null, stableMs = 0) {
  const expected = labels.map(normalize);
  const isReady = () => {
    const select = document.querySelector(selector);
    if (!select || select.disabled) return false;
    const available = getOptionMap(select).map((option) => option.label);
    const optionsChanged = previousSignature === null
      || selectOptionsSignature(selector) !== previousSignature;
    return optionsChanged && expected.every((label) => available.includes(label))
      ? (stableMs ? selectOptionsSignature(selector) : true) : false;
  };
  await waitForDomCondition(
    isReady,
    timeout,
    stableMs,
    `${selector}: dynamic options did not load within ${timeout} ms.`,
  );
}

function waitForDomCondition(check, timeout, stableMs, timeoutMessage) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let stableTimer;
    let stableValue;
    const signal = activeFillContext?.controller.signal;
    const observer = new MutationObserver(evaluate);
    const timeoutTimer = window.setTimeout(() => {
      finish(reject, new Error(timeoutMessage));
    }, timeout);

    function finish(callback, value) {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutTimer);
      window.clearTimeout(stableTimer);
      observer.disconnect();
      signal?.removeEventListener('abort', aborted);
      document.removeEventListener('change', evaluate, true);
      document.removeEventListener('input', evaluate, true);
      document.removeEventListener('vahan:filter-request-settled', evaluate);
      callback(value);
    }

    function evaluate() {
      if (settled) return;
      let value;
      try { assertFillActive(); value = check(); }
      catch (error) { finish(reject, error); return; }
      if (!value) {
        window.clearTimeout(stableTimer);
        stableTimer = undefined;
        stableValue = undefined;
        return;
      }
      if (!stableMs) {
        finish(resolve);
        return;
      }
      if (stableTimer === undefined || value !== stableValue) {
        window.clearTimeout(stableTimer);
        stableValue = value;
        stableTimer = window.setTimeout(() => {
          stableTimer = undefined;
          try {
            assertFillActive();
            const confirmed = check();
            if (confirmed && confirmed === stableValue) finish(resolve);
            else evaluate();
          } catch (error) { finish(reject, error); }
        }, stableMs);
      }
    }
    function aborted() { finish(reject, signal.reason); }
    signal?.addEventListener('abort', aborted, {once: true});
    document.addEventListener('change', evaluate, true);
    document.addEventListener('input', evaluate, true);
    document.addEventListener('vahan:filter-request-settled', evaluate);
    observer.observe(document, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ['disabled', 'selected', 'value'],
    });
    evaluate();
  });
}

async function refreshXAxisOptions(yAxisLabel, { resetSelection = false } = {}) {
  const yAxis = document.querySelector("#yAxis");
  const xAxis = document.querySelector("#xAxis");
  if (!yAxis || !xAxis) throw new Error("Could not find #yAxis or #xAxis.");
  const match = getOptionMap(yAxis).find((option) => option.label === normalize(yAxisLabel));
  if (!match) throw new Error(`#yAxis: could not find "${yAxisLabel}".`);
  const previousYAxisValue = yAxis.value;
  const previousXAxisOptions = selectOptionsSignature("#xAxis");

  // VAHAN restores X-Axis from a hidden field while rebuilding its options.
  // Clear both values during job fills so a previous scenario cannot affect
  // the requested selection. Option lookups keep the page's current choice.
  const hiddenXAxis = document.querySelector("#xAxis_hidden");
  if (resetSelection) {
    xAxis.value = "";
    if (hiddenXAxis) hiddenXAxis.value = "";
  }
  if (previousYAxisValue !== match.value || resetSelection) {
    yAxis.value = match.value;
    yAxis.dispatchEvent(new Event("change", { bubbles: true }));
    yAxis.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
  }
  if (previousYAxisValue !== match.value) {
    await waitForSelectOptionsChange("#xAxis", previousXAxisOptions);
  }
  return [...xAxis.options]
    .filter((option) => option.value)
    .map((option) => (option.label || option.textContent || "").replace(/\s+/g, " ").trim());
}

async function waitForXAxisOptions(yAxisLabel, labels, timeout = 15000) {
  const expected = labels.map(normalize);
  let available = [];
  const isReady = () => {
    const xAxis = document.querySelector("#xAxis");
    if (xAxis) {
      available = [...xAxis.options]
        .filter((option) => option.value)
        .map((option) => (option.label || option.textContent || "").replace(/\s+/g, " ").trim());
      const availableNormalized = available.map(normalize);
      // X-Axis readiness depends on this select's options. Other filter
      // requests may still be in flight; the final fill barrier and filter
      // verification below wait for them before Apply.
      return !xAxis.disabled && expected.every((label) => availableNormalized.includes(label));
    }
    return false;
  };
  try {
    // Keep the requested option present briefly so an old list is not
    // mistaken for the options VAHAN is rebuilding after the Y-Axis change.
    await waitForDomCondition(isReady, timeout, 400, "X-Axis options did not settle.");
    return;
  } catch {
    // Keep the existing, detailed selector error for the caller.
  }
  const missing = labels.filter((label, index) => !available.map(normalize).includes(expected[index]));
  throw new Error(
    `#xAxis: requested option(s) "${missing.join(", ")}" did not load for Y-Axis "${yAxisLabel}" `
    + `within ${timeout} ms. Available X-Axis options: ${available.join(", ") || "(none)"}.`,
  );
}

async function selectLabels(selector, rawValue) {
  assertFillActive();
  const labels = splitValues(rawValue);
  const select = document.querySelector(selector);
  if (!select) throw new Error(`Could not find ${selector}.`);
  const options = getOptionMap(select);
  if (!labels.length && !select.multiple) return;
  const values = labels.map((label) => options.find((option) => option.label === normalize(label))?.value);
  if (values.some((value) => value === undefined)) throw new Error(`${selector}: could not find "${labels.join(", ")}".`);
  const selected = [...select.selectedOptions].map((option) => option.value);
  if (selected.length === values.length && values.every((value) => selected.includes(value))) return false;

  // Write to the native select first. The VAHAN multi-select widget can omit
  // filtered/lazy rows from its DOM, so clicking visible widget rows is not a
  // reliable way to update RTO and other dynamic multi-selects.
  for (const option of select.options) option.selected = values.includes(option.value);
  select.dispatchEvent(new Event("change", { bubbles: true }));
  if (typeof select.loadOptions === "function") select.loadOptions();
  // Native selection and event handlers are synchronous; yield to widget
  // microtasks without a timer that Chrome may heavily throttle in a hidden tab.
  await Promise.resolve();

  const actual = [...select.selectedOptions].map((option) => normalize(option.label || option.textContent));
  const expected = labels.map(normalize);
  if (actual.length !== expected.length || expected.some((label) => !actual.includes(label))) {
    throw new Error(`${selector}: VAHAN widget did not apply the requested selection.`);
  }
  return true;
}

async function clearSelect(selector) {
  assertFillActive();
  const select = document.querySelector(selector);
  if (!select) return;
  if (![...select.options].some((option) => option.selected)) return;
  for (const option of select.options) option.selected = false;
  select.dispatchEvent(new Event("change", { bubbles: true }));
  if (typeof select.loadOptions === "function") select.loadOptions();
  await Promise.resolve();
}

async function loadMakerOptions(rawValue) {
  const makers = splitValues(rawValue);
  const select = document.querySelector("#vehicleMaker");
  if (!makers.length || !select) return;
  const missing = [...new Set(makers)].filter(maker => ![...select.options].some(
    option => normalize(option.label || option.textContent) === normalize(maker)));
  let cursor = 0;
  const loaded = await Promise.allSettled(Array.from({length: Math.min(4, missing.length)}, async () => {
    while (cursor < missing.length) {
      assertFillActive();
      const values = await fetchMakers(missing[cursor++]);
      assertFillActive();
      const current = document.querySelector('#vehicleMaker');
      if (!current) throw new Error('FILTER_CONTROL_MISSING: #vehicleMaker.');
      for (const value of values) {
        if (![...current.options].some(option => option.value === value)) current.add(new Option(value, value));
      }
    }
  }));
  const failure = loaded.find(result => result.status === 'rejected');
  if (failure) throw failure.reason;
  if (typeof select.loadOptions === "function") select.loadOptions();
}

function readOptions(selectors) {
  return Object.fromEntries(Object.entries(selectors).map(([id, definition]) => {
    const select = document.querySelector(definition.selector);
    const labels = select
      ? [...select.options].map((option) => (option.label || option.textContent || "").replace(/\s+/g, " ").trim()).filter(Boolean)
      : [];
    return [id, labels];
  }));
}

async function fetchRtos(stateLabels) {
  const labels = splitValues(stateLabels);
  if (labels.length !== 1) return [];
  const state = [...document.querySelectorAll("#stateName option")]
    .find((option) => normalize(option.label || option.textContent) === normalize(labels[0]));
  if (!state) return [];
  const url = new URL("/analytics/json_rtos", location.origin);
  url.searchParams.set("stateCode", state.value);
  const response = await fetch(url, { credentials: "same-origin", signal: activeFillContext?.controller.signal });
  if (!response.ok) throw new Error(`Could not load RTO options (${response.status}).`);
  return (await response.json()).map((rto) => rto.rtoName);
}

async function fetchMakers(search) {
  const url = new URL("/analytics/vahanpublicreport/lazy/vehicle-makers", location.origin);
  url.search = new URLSearchParams({ page: "0", size: "20", search }).toString();
  const response = await fetch(url, { credentials: "same-origin", signal: activeFillContext?.controller.signal });
  if (!response.ok) throw new Error(`Could not search Maker options (${response.status}).`);
  const payload = await response.json();
  const rows = Array.isArray(payload)
    ? payload
    : payload.content || payload.results || payload.data || payload.items || [];
  return rows.map((item) => typeof item === "string"
    ? item
    : item.label || item.name || item.value || item.makerName,
  ).filter(Boolean);
}

async function getXAxisOptions(yAxisLabel) {
  if (!yAxisLabel) return [];
  return refreshXAxisOptions(yAxisLabel);
}

async function getStateOptions(delhiNcrLabel) {
  const previousStateOptions = selectOptionsSignature("#stateName");
  const delhiNcrChanged = await selectLabels("#delhiNcr", delhiNcrLabel);
  if (delhiNcrChanged) {
    await waitForSelectOptionsChange("#stateName", previousStateOptions);
  }
  const state = document.querySelector("#stateName");
  return state
    ? [...state.options]
        .map((option) => (option.label || option.textContent || "").replace(/\s+/g, " ").trim())
        .filter(Boolean)
    : [];
}

function fill(selector, value) {
  assertFillActive();
  if (value === undefined || value === null) return;
  const input = document.querySelector(selector);
  if (!input) throw new Error(`Could not find ${selector}.`);
  const nextValue = String(value);
  if (input.value === nextValue) return;
  input.value = nextValue;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

const FILTER_SELECTORS = Object.freeze({
  archivedFlags: '#archivedFlags', period: '#reportType', financialYears: '#financialYearSelect',
  reportYear: '#reportYear', reportMonth: '#reportMonth', delhiNcr: '#delhiNcr',
  states: '#stateName', rtos: '#rtoCode', categoryGroups: '#vehicleCategoryGroup',
  subCategories: '#vehicleSubCategory', classes: '#vehicleClass', fuels: '#vehicleFuel',
  evTypes: '#evType', statuses: '#vehicleStatus', ownerTypes: '#vehicleOwnerType',
  vehicleType: '#vehicleType', fitness: '#fitnessCheck', emissions: '#vehicleEmission',
  makers: '#vehicleMaker', yAxis: '#yAxis', xAxis: '#xAxis',
});
const INPUT_SELECTORS = Object.freeze({fromYear: '#fromYear', toYear: '#toYear', fromDate: '#fromDate', toDate: '#toDate'});
const RESET_FIELDS = new Set(['categoryGroups', 'subCategories', 'classes', 'fuels', 'evTypes',
  'statuses', 'ownerTypes', 'vehicleType', 'fitness', 'emissions', 'makers']);
const hasFilter = (config, key) => Object.prototype.hasOwnProperty.call(config, key);
const sameLabels = (actual, expected) => {
  const left = actual.map(normalize).sort();
  const right = expected.map(normalize).sort();
  return left.length === right.length && left.every((label, index) => label === right[index]);
};
const neutralOption = (option, field = '') => {
  const label = compactText(option.label || option.textContent);
  return !option.value
    || /^(?:all(?:\s+.*)?|any|both|none|select(?:\s+.*)?|choose(?:\s+.*)?|[-–—])$/i.test(label)
    // VAHAN exposes Fitness as a Yes/No select without a blank option; NO is
    // its neutral/default state when a case does not specify Fitness.
    || (field === 'fitness' && /^no$/i.test(label));
};

function validateSupportedFilters(config) {
  for (const key of Object.keys(config)) {
    if (!(key in FILTER_SELECTORS) && !(key in INPUT_SELECTORS) && !['autoApply', 'autoExport'].includes(key)) {
      throw new Error(`FILTER_UNSUPPORTED: ${key} has no control mapping; the case was not applied.`);
    }
  }
}
async function resetFilter(key) {
  assertFillActive();
  const select = document.querySelector(FILTER_SELECTORS[key]);
  if (!select) return;
  if (select.multiple) { await clearSelect(FILTER_SELECTORS[key]); return; }
  const neutral = [...select.options].find(option => neutralOption(option, key));
  const next = neutral ? [...select.options].indexOf(neutral) : -1;
  if (select.selectedIndex === next) return;
  select.selectedIndex = next;
  select.dispatchEvent(new Event('change', {bubbles: true}));
  if (typeof select.loadOptions === 'function') select.loadOptions();
  await Promise.resolve();
}
async function setFilter(config, key, stableMs = 0) {
  const labels = splitValues(config[key]);
  const selector = FILTER_SELECTORS[key];
  if (!labels.length) {
    if (RESET_FIELDS.has(key)) await resetFilter(key);
    else if (document.querySelector(selector)?.multiple) await clearSelect(selector);
    return;
  }
  if (key === 'xAxis') {
    const yAxisLabel = String(config.yAxis || document.querySelector('#yAxis')?.selectedOptions?.[0]?.textContent || '');
    try {
      await waitForXAxisOptions(yAxisLabel, labels, 15_000);
    } catch (firstError) {
      // A long VAHAN request can leave the previous X-Axis list disabled or
      // stale. Re-trigger the selected parent once, then wait for the new
      // options and all page requests to settle before selecting anything.
      assertFillActive();
      const yAxis = document.querySelector('#yAxis');
      const match = yAxis && getOptionMap(yAxis).find(option => option.label === normalize(yAxisLabel));
      if (!yAxis || !match) throw firstError;
      const xAxis = document.querySelector('#xAxis');
      const hidden = document.querySelector('#xAxis_hidden');
      if (xAxis) xAxis.value = '';
      if (hidden) hidden.value = '';
      yAxis.value = match.value;
      yAxis.dispatchEvent(new Event('change', {bubbles: true}));
      yAxis.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
      if (typeof yAxis.loadOptions === 'function') yAxis.loadOptions();
      await waitForXAxisOptions(yAxisLabel, labels, 15_000);
    }
  } else if (key === 'rtos') {
    try {
      await waitForOptions(selector, labels, 15_000, null, stableMs);
    } catch (firstError) {
      assertFillActive();
      const state = document.querySelector('#stateName');
      const expected = splitValues(config.states).map(normalize);
      const actual = state ? [...state.selectedOptions].map(option => normalize(option.label || option.textContent)) : [];
      if (!state || !expected.length || expected.length !== actual.length || expected.some(label => !actual.includes(label))) throw firstError;
      // Reissue the official dependent load once, preserving the requested
      // State. Final verification still waits for all outstanding responses.
      state.dispatchEvent(new Event('change', {bubbles: true}));
      try { await waitForOptions(selector, labels, 15_000, null, stableMs); }
      catch (error) {
        assertFillActive();
        throw new Error(`RTO_OPTIONS_TIMEOUT: ${selector}: requested RTO options did not load after reloading the selected State. ${error.message}`);
      }
    }
  } else {
    await waitForOptions(selector, labels, 15_000, null, stableMs);
  }
  const changed = await selectLabels(selector, config[key]);
  if (key === 'xAxis') {
    const hidden = document.querySelector('#xAxis_hidden');
    if (hidden) hidden.value = document.querySelector(selector).value;
  }
  return changed;
}
async function setParentFilter(config, parent, child, stableMs = 0) {
  const changed = await setFilter(config, parent, stableMs);
  const expected = splitValues(config[child]);
  if (changed || !expected.length) return;
  const control = document.querySelector(FILTER_SELECTORS[child]);
  if (control?.disabled) return; // The page already has a dependent load running.
  const available = control ? getOptionMap(control).map(option => option.label) : [];
  if (!expected.every(label => available.includes(normalize(label)))) {
    assertFillActive();
    document.querySelector(FILTER_SELECTORS[parent])?.dispatchEvent(new Event('change', {bubbles: true}));
  }
}
async function drainCancelledRequests(context) {
  // Aborted page handlers also have finally blocks. Let them finish before a
  // reused page may start the next fill; they must not clear its controls.
  if (!context.pending) { await delay(0); return; }
  await new Promise(resolve => {
    const finish = () => {
      clearTimeout(timer);
      document.removeEventListener('vahan:filter-request-settled', settled);
      setTimeout(resolve, 0);
    };
    const settled = () => { if (!context.pending) finish(); };
    const timer = setTimeout(finish, 1000);
    document.addEventListener('vahan:filter-request-settled', settled);
    settled();
  });
}
function filterChecks(config) {
  const checks = [];
  for (const [field, selector] of Object.entries(FILTER_SELECTORS)) {
    const requested = hasFilter(config, field);
    if (!requested && !RESET_FIELDS.has(field)) continue;
    const select = document.querySelector(selector);
    const expected = requested ? splitValues(config[field]) : [];
    const actual = select ? [...select.selectedOptions].map(option => compactText(option.label || option.textContent)) : [];
    let match;
    if (!expected.length && !select) match = true; // Absent, unconstrained optional control.
    else if (!expected.length && !select.multiple) {
      // Blank time selectors retain the period's default; optional filters must be neutral.
      match = RESET_FIELDS.has(field) ? !select.selectedOptions.length || [...select.selectedOptions].every(option => neutralOption(option, field)) : true;
    } else match = Boolean(select) && !select.disabled && sameLabels(actual, expected);
    checks.push({field, selector, expected, actual, match, mode: requested ? 'requested' : 'reset'});
  }
  for (const [field, selector] of Object.entries(INPUT_SELECTORS)) {
    if (!hasFilter(config, field) && !['fromDate', 'toDate'].includes(field)) continue;
    const input = document.querySelector(selector);
    const expected = String(config[field] ?? '').trim();
    const actual = input?.value?.trim() ?? '';
    checks.push({field, selector, expected: [expected], actual: [actual],
      match: expected === actual && (Boolean(input) || !expected) && (!expected || !input?.disabled), mode: 'requested'});
  }
  if (hasFilter(config, 'xAxis') && splitValues(config.xAxis).length) {
    const hidden = document.querySelector('#xAxis_hidden');
    if (hidden) checks.push({field: 'xAxis_hidden', selector: '#xAxis_hidden',
      expected: [document.querySelector('#xAxis')?.value || ''], actual: [hidden.value],
      match: hidden.value === document.querySelector('#xAxis')?.value, mode: 'hidden'});
  }
  return checks;
}
async function verifyFilters(config) {
  validateSupportedFilters(config);
  const started = performance.now();
  let checks;
  try {
    await waitForDomCondition(() => {
      checks = filterChecks(config);
      return pendingPageRequests === 0 && checks.every(check => check.match)
        ? JSON.stringify(checks) : false;
    }, 1500, 80, 'FILTER_VERIFY_TIMEOUT');
  } catch (error) {
    assertFillActive();
    checks = filterChecks(config);
    const mismatches = checks.filter(check => !check.match).map(check =>
      `${check.field}: expected ${JSON.stringify(check.expected)}, got ${JSON.stringify(check.actual)}`);
    throw new Error(`FILTER_VERIFICATION_FAILED: ${mismatches.join('; ') || error.message}`);
  }
  return {version: 'parallel-fill-v1', checks, fieldCount: checks.length,
    validatedAt: new Date().toISOString(), verificationMs: Math.round(performance.now() - started)};
}
async function fillVahan(config) {
  validateSupportedFilters(config);
  if (activeFillContext) throw new Error('FILTER_FILL_BUSY: another fill is still active.');
  const context = activeFillContext = {controller: new AbortController(), pending: 0};
  const started = performance.now();
  const timings = new Map();
  const has = key => hasFilter(config, key);
  async function timed(name, task) {
    const metric = timings.get(name) || {name, durationMs: 0, attempts: 0, startedMs: Math.round(performance.now() - started)};
    timings.set(name, metric);
    metric.attempts++;
    const stageStart = performance.now();
    try { assertFillActive(); return await task(); }
    finally { metric.durationMs += Math.round(performance.now() - stageStart); }
  }
  async function fillInputs() {
    for (const [key, selector] of Object.entries(INPUT_SELECTORS)) {
      if (!has(key) && !['fromDate', 'toDate'].includes(key)) continue;
      const value = config[key] ?? '';
      if (String(value).trim()) {
        await waitForDomCondition(() => Boolean(document.querySelector(selector)), 15_000, 0,
          `FILTER_CONTROL_MISSING: ${selector}`);
      }
      if (document.querySelector(selector)) fill(selector, value);
    }
  }
  const plan = [
    {name: 'period', keys: ['period', 'financialYears', 'reportYear', 'reportMonth', ...Object.keys(INPUT_SELECTORS)], run: async () => {
      if (has('period')) await setFilter(config, 'period');
      for (const key of ['financialYears', 'reportYear', 'reportMonth']) {
        if (has(key)) await setFilter(config, key);
      }
      await fillInputs();
    }},
    {name: 'geography', keys: ['delhiNcr', 'states', 'rtos'], run: async () => {
      if (has('delhiNcr')) await setParentFilter(config, 'delhiNcr', 'states');
      if (has('states')) await setParentFilter(config, 'states', 'rtos', 40);
      if (has('rtos')) await setFilter(config, 'rtos', 40);
    }},
    {name: 'vehicle', keys: ['categoryGroups', 'subCategories', 'classes', 'evTypes', 'fuels', 'vehicleType'], run: async () => {
      await timed('classification', async () => {
        if (has('categoryGroups')) await setParentFilter(config, 'categoryGroups', 'subCategories');
        if (has('subCategories')) await setParentFilter(config, 'subCategories', 'classes', 60);
        if (has('classes')) await setFilter(config, 'classes', 60);
      });
      await timed('fuel', async () => {
        if (has('evTypes')) await setParentFilter(config, 'evTypes', 'fuels');
        if (has('fuels')) await setFilter(config, 'fuels', 60);
      });
      if (has('vehicleType')) await setFilter(config, 'vehicleType');
    }},
    {name: 'axis', keys: ['yAxis', 'xAxis', 'xAxis_hidden'], run: async () => {
      if (has('yAxis')) await setParentFilter(config, 'yAxis', 'xAxis');
      if (has('xAxis')) await setFilter(config, 'xAxis', 60);
    }},
    {name: 'independent', keys: ['archivedFlags', 'emissions', 'makers', 'statuses', 'ownerTypes', 'fitness'], run: async () => {
      for (const key of ['archivedFlags', 'emissions', 'makers', 'statuses', 'ownerTypes', 'fitness']) {
        if (!has(key)) continue;
        if (key === 'makers') await loadMakerOptions(config.makers);
        await setFilter(config, key);
      }
    }},
  ];
  let repairs = 0;
  try {
    // A browser page is a shared mutable form: sequence its controls while
    // separate browser workers continue to process cases concurrently.
    for (const key of RESET_FIELDS) if (!has(key)) await resetFilter(key);
    for (const stage of plan) await timed(stage.name, stage.run);
    for (;;) {
      await waitForDomCondition(() => pendingPageRequests === 0, 15_000, 60, 'FILTER_NETWORK_TIMEOUT: option requests did not settle.');
      // Dependent VAHAN requests may repopulate form controls after another
      // filter changes. Restore year/date inputs only after those requests end.
      await fillInputs();
      await waitForDomCondition(() => pendingPageRequests === 0, 15_000, 60, 'FILTER_NETWORK_TIMEOUT: input updates did not settle.');
      const wrong = filterChecks(config).filter(check => !check.match);
      if (!wrong.length) break;
      if (repairs++ >= 2) throw new Error(`FILTER_VERIFICATION_FAILED: ${wrong.map(check =>
        `${check.field} expected ${JSON.stringify(check.expected)}, got ${JSON.stringify(check.actual)}`).join('; ')}.`);
      const fields = new Set(wrong.map(check => check.field));
      for (const key of RESET_FIELDS) if (!has(key) && fields.has(key)) await resetFilter(key);
      const affected = plan.filter(stage => stage.keys.some(key => fields.has(key)));
      for (const stage of affected) await timed(stage.name, stage.run);
    }
    const verified = await verifyFilters(config);
    return {...verified, version: 'sequential-mutation-v2', durationMs: Math.round(performance.now() - started),
      groups: [...timings.values()], repairPasses: repairs};
  } catch (error) {
    context.controller.abort(error);
    await drainCancelledRequests(context);
    throw error;
  } finally { if (activeFillContext === context) activeFillContext = undefined; }
}

async function captureCaptcha(timeout = 15000) {
  const deadline = Date.now() + timeout;
  let image;
  while (Date.now() < deadline) {
    image = document.querySelector("#captchaImage");
    if (image?.complete && image.naturalWidth > 0 && image.naturalHeight > 0) break;
    await delay(200);
  }
  if (!image?.complete || !image.naturalWidth || !image.naturalHeight) {
    throw new Error("CAPTCHA image did not load within the allowed time.");
  }

  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Could not create a canvas for the CAPTCHA image.");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  const sourceUrl = image.currentSrc || image.src || image.getAttribute("src");
  if (!sourceUrl) throw new Error("The CAPTCHA image has no identifier.");
  const imageDataUrl = canvas.toDataURL("image/png");
  let hash = 2166136261;
  for (let index = 0; index < imageDataUrl.length; index += 1) {
    hash ^= imageDataUrl.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return {
    captchaId: `${sourceUrl}#${(hash >>> 0).toString(16)}`,
    imageDataUrl,
  };
}

let isRefreshingCaptcha = false;

async function refreshCaptcha(previousCaptchaId, timeout = 15000) {
  const refreshButton = document.querySelector("#captchaImg");
  if (!refreshButton || !isVisible(refreshButton)) {
    throw new Error("Could not find the official VAHAN CAPTCHA refresh button.");
  }

  // The official page owns CAPTCHA generation through #captchaImg. Do not
  // synthesize an image URL: clicking this control keeps the request in the
  // user's authenticated VAHAN session and clears the old CAPTCHA value.
  isRefreshingCaptcha = true;
  try {
    refreshButton.click();

    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      try {
        const captcha = await captureCaptcha(1_000);
        if (!previousCaptchaId || captcha.captchaId !== previousCaptchaId) return captcha;
      } catch (_error) {
        // The image is briefly unavailable while the official page replaces it.
      }
      await delay(150);
    }
    throw new Error("VAHAN did not provide a new CAPTCHA image in time.");
  } finally {
    // Settle window so DOM load and mutation observer events from this refresh don't re-trigger.
    setTimeout(() => {
      isRefreshingCaptcha = false;
    }, 500);
  }
}

let captchaRefreshTimer;
const NO_RECORD_TEXT = /\bno\s+record\s+found\b/i;
const INVALID_CAPTCHA_TEXT = /\binvalid\s+captcha\b/i;
// Export controls may remain visible for empty reports. Table rows and explicit
// no-data messages decide the outcome; an Excel export is optional.
const NO_RECORD_CONFIRMATION_MS = 500;
const EXCEL_BUTTON_SELECTOR = "#downloadMakerAllExcel, #downloadBtn1";
const compactText = (value) => String(value || "").replace(/\s+/g, " ").trim();
const isVisible = (element) => {
  if (!element || element.getClientRects().length === 0) return false;
  if (element.getAttribute?.("aria-hidden") === "true") return false;
  if (element.closest?.('[aria-hidden="true"]')) return false;
  const style = window.getComputedStyle(element);
  return style.display !== "none"
    && style.visibility !== "hidden"
    && style.opacity !== "0";
};
// A new navigation can expose the driver before the parser creates <body>.
const getResultRegion = () => document.querySelector(".report-main-column")
  || document.body || document.documentElement || document;
const findExcelDownloadButton = () => {
  const buttons = [...document.querySelectorAll(EXCEL_BUTTON_SELECTOR)];
  const named = buttons.find(isVisible);
  if (named) return named;
  return [...getResultRegion().querySelectorAll("button, a")].find((element) =>
    isVisible(element) && /download\s+all\s+records\s+excel/i.test(compactText(element.textContent))) || buttons[0] || null;
};
const isUsableExcelButton = (button) => isVisible(button)
  && !button.disabled && button.getAttribute("aria-disabled") !== "true";
// Read report tables independently of the selected axis (Maker, Fuel, Class, ...).
function readReportTables() {
  return [...getResultRegion().querySelectorAll("table")].filter((table) =>
    isVisible(table) && !table.querySelector("table, select, input, textarea")
  ).map((table) => {
    const rows = [...table.rows].filter(isVisible).map((row) => ({
      section: row.parentElement?.tagName === "THEAD" ||
        (row.cells.length && [...row.cells].every((cell) => cell.tagName === "TH")) ||
        (!table.tHead && row.rowIndex === 0 && [...row.cells].some((cell) =>
          /^(?:maker|fuel|vehicle class|vehicle category|state|rto|s\.?\s*no\.?|serial no\.?)$/i.test(compactText(cell.textContent))))
        ? "head" : row.parentElement?.tagName === "TFOOT" ? "foot" : "body",
      cells: [...row.cells].map((cell) => compactText(cell.textContent)),
      spans: [...row.cells].map((cell) => ({rowSpan: cell.rowSpan, colSpan: cell.colSpan})),
    }));
    return {element: table, id: table.id || "", caption: compactText(table.caption?.textContent), rows};
  }).filter((table) => table.rows.length);
}
function readReportResult() {
  const tables = readReportTables();
  const dataTables = tables.filter((table) => table.rows.some((row) =>
    row.section === "body" && row.cells.length > 1 && row.cells.some(Boolean)
    && !row.cells.some((cell) => NO_RECORD_TEXT.test(cell))
    && !/^(?:page\s+total|grand\s+total|total)$/i.test(row.cells[0])
  ));
  const noRecord = findVisiblePageMessages(NO_RECORD_TEXT).length > 0;
  return {
    type: dataTables.length ? "DATA" : noRecord ? "NO_RECORD" : null,
    table: tables.at(-1)?.element || null,
    fingerprint: JSON.stringify(tables.map(({element, ...table}) => table)) + (noRecord ? "NO_RECORD" : ""),
    tables,
  };
}
function captureReport(result) {
  const report = readReportResult();
  if (isResultLoading() || report.type !== (result === "DATA" ? "DATA" : "NO_RECORD")) {
    throw new Error("Report changed or is still loading; no result was saved.");
  }
  return {result, message: result === "NO_RECORD" ? "No record found" : "Data found",
    observedAt: new Date().toISOString(), pageUrl: location.href,
    tables: result === "DATA" ? report.tables.map(({element, ...table}) => table) : []};
}
const findVisiblePageMessages = (pattern, root = getResultRegion()) => [...root.querySelectorAll("*")]
  .filter(isVisible)
  .filter((element) => {
    const text = compactText(element.textContent);
    if (!pattern.test(text) || text.length > 240) return false;
    // If a parent contains the same message through a child, let the leaf
    // node decide. This avoids matching the whole result page/container.
    return ![...element.children].some((child) =>
      isVisible(child) && pattern.test(compactText(child.textContent)));
  });
function captureVahanResultBaseline() {
  const result = readReportResult();
  return {
    invalidCaptchaNodes: new Set(findVisiblePageMessages(INVALID_CAPTCHA_TEXT)),
    resultTable: result.table,
    noRecordNodes: new Set(findVisiblePageMessages(NO_RECORD_TEXT)),
    resultFingerprint: result.fingerprint,
    regionFingerprint: compactText(getResultRegion().textContent),
  };
}
const RESULT_LOADING_SELECTOR = [
  '[aria-busy="true"]', '[role="progressbar"]', ".spinner-border", ".spinner-grow",
  ".loading-spinner", ".loading-overlay", ".chart-loading", ".fa-spinner.fa-spin",
  ".loader", "#applyTrigger:disabled",
].join(", ");
const isResultLoading = () => {
  const root = getResultRegion();
  if (document.readyState === "loading" || document.querySelector("#applyTrigger")?.disabled) return true;
  const loadingIndicators = root.querySelectorAll(RESULT_LOADING_SELECTOR);
  if (root.matches?.(RESULT_LOADING_SELECTOR) && isVisible(root)) return true;
  return [...loadingIndicators].some(isVisible);
};
const isApplyPending = () => document.readyState === "loading"
  || Boolean(document.querySelector("#applyTrigger")?.disabled);
const mutationCanChangeResult = (mutation) => {
  const nodes = [mutation.target, ...mutation.addedNodes, ...mutation.removedNodes];
  return nodes.some((node) => {
    const target = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    if (!target || target.nodeType !== Node.ELEMENT_NODE) return false;
    if (mutation.type === "attributes") {
      if (target.id === "applyTrigger" && mutation.attributeName === "disabled") return true;
      if (
        mutation.attributeName === "class"
        && /(?:^|\s)(?:spinner-border|spinner-grow|loading-spinner|loading-overlay|chart-loading|fa-spinner|fa-spin|loader)(?:\s|$)/i.test(mutation.oldValue || "")
      ) return true;
      if (mutation.attributeName === "aria-busy" && mutation.oldValue === "true") return true;
      if (mutation.attributeName === "role" && mutation.oldValue === "progressbar") return true;
    }
    if (target.matches?.("table") || target.closest?.("table") || target.querySelector?.("table")) return true;
    if (target.matches?.(EXCEL_BUTTON_SELECTOR) || target.closest?.(EXCEL_BUTTON_SELECTOR) || target.querySelector?.(EXCEL_BUTTON_SELECTOR)) return true;
    if (mutation.type !== "attributes" && target.closest?.(".report-main-column")) return true;
    if (
      target.matches?.(RESULT_LOADING_SELECTOR)
      || target.closest?.(RESULT_LOADING_SELECTOR)
      || target.querySelector?.(RESULT_LOADING_SELECTOR)
    ) return true;
    const text = compactText(target.textContent);
    return text.length <= 240 && (NO_RECORD_TEXT.test(text) || INVALID_CAPTCHA_TEXT.test(text));
  });
};

function waitForVahanResult(timeoutMs = 90_000, baseline = null, expectedRto = "") {
  return new Promise((resolve) => {
    let settled = false;
    let checkQueued = false;
    let noRecordTimer;
    let timeoutTimer;
    let observer;
    let observedLoading = false;
    const baselineInvalidNodes = baseline?.invalidCaptchaNodes || new Set();
    let invalidCaptchaWasCleared = !baseline || baselineInvalidNodes.size === 0;
    const baselineNoRecordNodes = baseline?.noRecordNodes || new Set();
    let noRecordWasCleared = !baseline || baselineNoRecordNodes.size === 0;

    const refreshResultTransitions = () => {
      if ([...baselineNoRecordNodes].some((node) =>
        !node.isConnected || !isVisible(node) || !NO_RECORD_TEXT.test(compactText(node.textContent)))) {
        noRecordWasCleared = true;
      }
      if ([...baselineInvalidNodes].some((node) =>
        !node.isConnected || !isVisible(node) || !INVALID_CAPTCHA_TEXT.test(compactText(node.textContent)))) {
        invalidCaptchaWasCleared = true;
      }
    };
    const hasFreshMessage = (pattern, initialNodes, wasCleared) => {
      const currentNodes = findVisiblePageMessages(pattern);
      if (!baseline) return currentNodes.length > 0;
      return currentNodes.some((node) => !initialNodes.has(node)) || (wasCleared && currentNodes.length > 0);
    };
    const tableChanged = (result) => !baseline || result.fingerprint !== baseline.resultFingerprint
      || Boolean(result.table && result.table !== baseline.resultTable);
    const matchesExpectedRto = () => {
      if (!expectedRto) return true;
      const reportText = compactText(getResultRegion().textContent);
      const rtoLabel = /\bRTO\s*\(/i.exec(reportText);
      if (!rtoLabel) return false;
      const open = rtoLabel.index + rtoLabel[0].length - 1;
      let depth = 0;
      let close = -1;
      for (let index = open; index < reportText.length; index += 1) {
        if (reportText[index] === '(') depth += 1;
        else if (reportText[index] === ')' && --depth === 0) { close = index; break; }
      }
      const displayedRto = close > open ? reportText.slice(open + 1, close) : '';
      if (!displayedRto) return false;
      const normalizeRto = (value) => compactText(value).toLocaleLowerCase()
        .replace(/[‐‑‒–—]/g, "-").replace(/\s*[-,]\s*/g, "-");
      const expectedCode = compactText(expectedRto).match(/-\s*([a-z]{1,3}\d+)\s*$/i)?.[1];
      return normalizeRto(displayedRto) === normalizeRto(expectedRto)
        || Boolean(expectedCode && new RegExp(`\\b${expectedCode}\\b`, "i").test(displayedRto));
    };
    const hasFreshReport = (result) => matchesExpectedRto() && (tableChanged(result)
      || (result.type === "NO_RECORD" && hasFreshMessage(NO_RECORD_TEXT, baselineNoRecordNodes, noRecordWasCleared))
      || (observedLoading && !isResultLoading()) || Boolean(
      result.table && baseline
      && compactText(getResultRegion().textContent) !== baseline.regionFingerprint
      && matchesExpectedRto()
    ));

    const finish = (result) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(noRecordTimer);
      window.clearTimeout(timeoutTimer);
      observer?.disconnect();
      document.removeEventListener("DOMContentLoaded", queueCheck);
      document.removeEventListener("readystatechange", queueCheck);
      resolve(result);
    };

    const checkDom = () => {
      if (settled) return;
      if (isResultLoading()) observedLoading = true;
      refreshResultTransitions();
      if (hasFreshMessage(INVALID_CAPTCHA_TEXT, baselineInvalidNodes, invalidCaptchaWasCleared)) {
        finish({ type: "INVALID_CAPTCHA" });
        return;
      }
      const report = readReportResult();
      const fresh = hasFreshReport(report);
      if (fresh && report.type === "DATA" && !isResultLoading() && !isApplyPending()) {
        finish({ type: "DATA_READY", report: captureReport("DATA"),
          downloadReady: isUsableExcelButton(findExcelDownloadButton()) });
        return;
      }
      if (fresh && report.type === "NO_RECORD") {
        if (isResultLoading()) {
          window.clearTimeout(noRecordTimer);
          noRecordTimer = undefined;
          return;
        }
        if (noRecordTimer === undefined) {
          // Confirm only after the current report area is idle. The short
          // window remains, while an active render can no longer create a
          // premature no-data result.
          noRecordTimer = window.setTimeout(() => {
            noRecordTimer = undefined;
            refreshResultTransitions();
            const confirmed = readReportResult();
            if (hasFreshReport(confirmed) && confirmed.type === "DATA"
              && !isApplyPending()
              && !isResultLoading()) {
              finish({ type: "DATA_READY", report: captureReport("DATA"),
                downloadReady: isUsableExcelButton(findExcelDownloadButton()) });
            } else if (hasFreshReport(confirmed) && confirmed.type === "NO_RECORD" && !isResultLoading()) {
              finish({ type: "NO_RECORD", report: captureReport("NO_RECORD") });
            } else {
              queueCheck();
            }
          }, NO_RECORD_CONFIRMATION_MS);
        }
        return;
      }
      window.clearTimeout(noRecordTimer);
      noRecordTimer = undefined;
    };

    const queueCheck = () => {
      if (settled || checkQueued) return;
      checkQueued = true;
      queueMicrotask(() => {
        checkQueued = false;
        checkDom();
      });
    };

    const checkAuthHold = () => {
      getActiveVahanAuthHold().then((hold) => {
        if (hold) finish({ type: "AUTH_REQUIRED", hold });
      }).catch(() => {});
    };

    observer = new MutationObserver((mutations) => {
      if (mutations.some(mutationCanChangeResult)) queueCheck();
    });
    observer.observe(document, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeOldValue: true,
      attributeFilter: ["class", "style", "hidden", "aria-hidden", "aria-busy", "disabled", "href", "download", "aria-label", "role"],
    });
    document.addEventListener("DOMContentLoaded", queueCheck);
    document.addEventListener("readystatechange", queueCheck);
    timeoutTimer = window.setTimeout(() => finish({ type: "TIMEOUT" }), timeoutMs);
    checkAuthHold();
    checkDom();
  });
}


let pendingResult;
globalThis.vahanDriver = {
  fill: fillVahan, captureCaptcha, refreshCaptcha, readOptions, captureReport, verifyFilters,
  states: getStateOptions, rtos: fetchRtos, xAxis: getXAxisOptions, makers: fetchMakers,
  prepareResult(timeout, rto) {
    pendingResult = waitForVahanResult(timeout, captureVahanResultBaseline(), rto);
    return true;
  },
  result(timeout, rto) { return pendingResult || waitForVahanResult(timeout, null, rto); },
  clickExcel() {
    const button = findExcelDownloadButton();
    if (readReportResult().type !== "DATA" || !isUsableExcelButton(button)) {
      throw new Error("No data rows or no usable Excel download button.");
    }
    button.click();
  },
};
})();
