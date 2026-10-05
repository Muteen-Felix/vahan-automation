import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import {normalizeJobFilters, VAHAN_OPTION_SELECTORS} from './config.mjs';

const browser = await chromium.launch({headless: true});
const driver = fileURLToPath(new URL('./page-driver.js', import.meta.url));
const requested = {
  period: 'CALENDAR YEAR', financialYears: ['2025-2026'], reportYear: '2026', reportMonth: 'OCTOBER',
  fromYear: '2026', toYear: '2026', delhiNcr: 'ALL STATES',
  states: ['Test State'], rtos: ['Test RTO'], categoryGroups: ['Two Wheeler'],
  subCategories: ['TWO WHEELER(NT)'], classes: ['MOTOR CYCLE'], evTypes: ['PURE EV'],
  fuels: ['ELECTRIC(BOV)'], archivedFlags: ['ACTIVE_COMPLIANT'], emissions: ['ZERO'],
  makers: ['Maker Alpha', 'Maker Beta', 'Maker Gamma'], statuses: ['ACTIVE'], ownerTypes: ['PRIVATE'],
  vehicleType: 'NON TRANSPORT', fitness: 'VALID', yAxis: 'Maker', xAxis: 'Month Wise',
  autoApply: true, autoExport: true,
};
const delayed = {states: ['Test State'], rtos: ['Test RTO'], subCategories: ['TWO WHEELER(NT)'], classes: ['MOTOR CYCLE'],
  fuels: ['ELECTRIC(BOV)'], xAxis: ['Month Wise']};
const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
async function fixture({path = driver, lateReset = false, xhr = false, xAxisDelays = [], rtoResponses = []} = {}) {
  const page = await browser.newPage();
  await page.addInitScript({path});
  let xAxisRequests = 0;
  let rtoRequests = 0;
  await page.route('http://fill.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname !== '/') {
      const delayMs = url.pathname === '/xAxis' ? (xAxisDelays[xAxisRequests++] ?? 140) : 140;
      await new Promise(resolve => setTimeout(resolve, delayMs));
      return route.fulfill({contentType: 'application/json', body: JSON.stringify(
        url.pathname.includes('vehicle-makers') ? [url.searchParams.get('search')] :
        url.pathname === '/rtos' ? (rtoResponses[rtoRequests++] ?? delayed.rtos) : delayed[url.pathname.slice(1)] || [])});
    }
    const selects = Object.entries(VAHAN_OPTION_SELECTORS).map(([key, definition]) => {
      const labels = key in delayed || key === 'makers' ? [] :
        Array.isArray(requested[key]) ? requested[key] : requested[key] ? [requested[key]] : ['2026'];
      return `<select id="${definition.selector.slice(1)}" ${definition.multiple ? 'multiple' : ''}>` +
        `<option value="old" selected>${definition.multiple ? 'Old value' : 'ALL'}</option>` +
        labels.map(label => `<option value="${esc(label)}">${esc(label)}</option>`).join('') + '</select>';
    }).join('');
    return route.fulfill({contentType: 'text/html', body: selects + '<select id="vehicleMaker" multiple><option selected>Old maker</option></select>' +
      '<input id="fromYear"><input id="toYear"><input id="fromDate" value="2025-01-01"><input id="toDate" value="2025-12-31"><input type="hidden" id="xAxis_hidden" value="old">'});
  });
  await page.goto('http://fill.test/');
  assert.equal(await page.locator('#vehicleMaker').count(), 1, (await page.content()).slice(0, 1000));
  page.on('pageerror', error => console.error('Fixture page error:', error.message));
  await page.evaluate(({lateReset, xhr}) => {
    window.fixtureStats = {active: 0, peak: 0};
    const links = [ ['delhiNcr', 'stateName', 'states'], ['stateName', 'rtoCode', 'rtos'], ['vehicleCategoryGroup', 'vehicleSubCategory', 'subCategories'],
      ['vehicleSubCategory', 'vehicleClass', 'classes'], ['evType', 'vehicleFuel', 'fuels'], ['yAxis', 'xAxis', 'xAxis'] ];
    for (const [source, target, endpoint] of links) {
      document.getElementById(source).addEventListener('change', async () => {
        const select = document.getElementById(target);
        select.disabled = true;
        fixtureStats.peak = Math.max(fixtureStats.peak, ++fixtureStats.active);
        try {
          const labels = xhr ? await new Promise((resolve, reject) => {
            const request = new XMLHttpRequest(); request.open('GET', '/' + endpoint);
            request.onload = () => resolve(JSON.parse(request.responseText));
            request.onerror = request.onabort = () => reject(new Error('aborted'));
            request.send();
          }) : await (await fetch('/' + endpoint)).json();
          select.replaceChildren(...labels.map(label => new Option(label, label)));
        } catch { /* A failed sibling cancels requests; it must not write options. */ }
        finally { select.disabled = false; fixtureStats.active--; }
      });
    }
    if (lateReset) document.getElementById('reportType').addEventListener('change', async () => {
      await (await fetch('/period')).json();
      document.getElementById('stateName').selectedIndex = -1;
      document.getElementById('fromYear').value = '';
      document.getElementById('vehicleFuel').selectedIndex = -1;
    });
  }, {lateReset, xhr});
  return page;
}
let passed = 0;
async function check(name, test) { await test(); passed++; console.log(`PASS ${name}`); }
try {
  await check('concurrent groups respect delayed dependencies and verify every requested field', async () => {
    const page = await fixture();
    try {
      const proof = await page.evaluate(config => vahanDriver.fill(config), normalizeJobFilters(requested));
      assert.ok(proof.checks.every(check => check.match));
      for (const key of Object.keys(requested).filter(key => !key.startsWith('auto'))) assert.ok(proof.checks.some(check => check.field === key), key);
      assert.ok(proof.checks.filter(check => ['fromDate', 'toDate'].includes(check.field)).every(check => check.actual[0] === ''));
      assert.equal(await page.locator('#xAxis_hidden').inputValue(), 'Month Wise');
      const dates = {...requested, fromDate: '2026-01-01', toDate: '2026-10-02'};
      await page.evaluate(config => vahanDriver.fill(config), dates);
      assert.equal(await page.locator('#fromDate').inputValue(), dates.fromDate);
      assert.equal(await page.locator('#toDate').inputValue(), dates.toDate);
      assert.ok(await page.evaluate(() => fixtureStats.peak) >= 3);
      const starts = proof.groups.filter(group => ['period', 'geography', 'vehicle', 'axis', 'independent'].includes(group.name)).map(group => group.startedMs);
      assert.ok(Math.max(...starts) - Math.min(...starts) < 80, JSON.stringify(proof.groups));
      console.log(`  fill=${proof.durationMs}ms, checked=${proof.fieldCount}, peak dependencies=${await page.evaluate(() => fixtureStats.peak)}`);
    } finally { await page.close(); }
  });
  await check('late period reset is repaired without dropping requested fields', async () => {
    const page = await fixture({lateReset: true, xhr: true});
    try {
      const proof = await page.evaluate(config => vahanDriver.fill(config), requested);
      assert.ok(proof.repairPasses > 0 && proof.repairPasses <= 2);
      assert.ok(proof.checks.every(check => check.match));
    } finally { await page.close(); }
  });
  await check('maker names containing commas remain one label and searches overlap', async () => {
    const page = await fixture();
    try {
      const config = normalizeJobFilters({...requested, makers: ['Maker, Incorporated', 'Maker Beta']});
      assert.deepEqual(config.makers, ['Maker, Incorporated', 'Maker Beta']);
      const proof = await page.evaluate(config => vahanDriver.fill(config), config);
      assert.deepEqual(proof.checks.find(check => check.field === 'makers').actual, config.makers);
    } finally { await page.close(); }
  });
  await check('omitted optional filters and old date ranges are cleared on reuse', async () => {
    const page = await fixture();
    try {
      await page.evaluate(config => vahanDriver.fill(config), requested);
      const {makers, statuses, ownerTypes, vehicleType, fitness, emissions, ...next} = requested;
      const proof = await page.evaluate(config => vahanDriver.fill(config), next);
      for (const key of ['makers', 'statuses', 'ownerTypes', 'emissions']) assert.deepEqual(proof.checks.find(check => check.field === key).actual, []);
      assert.ok(proof.checks.every(check => check.match));
    } finally { await page.close(); }
  });
  await check('Fitness NO default is accepted only when Fitness is omitted', async () => {
    const page = await fixture();
    try {
      await page.locator('#fitnessCheck').evaluate(select => {
        select.replaceChildren(new Option('NO', 'NO', true, true), new Option('YES', 'YES'));
      });
      const {fitness, ...withoutFitness} = requested;
      const neutral = await page.evaluate(config => vahanDriver.fill(config), withoutFitness);
      assert.deepEqual(neutral.checks.find(check => check.field === 'fitness').actual, ['NO']);
      assert.equal(neutral.checks.find(check => check.field === 'fitness').match, true);
      const selected = await page.evaluate(config => vahanDriver.fill(config), {...withoutFitness, fitness: 'YES'});
      assert.deepEqual(selected.checks.find(check => check.field === 'fitness').actual, ['YES']);
      assert.equal(selected.checks.find(check => check.field === 'fitness').match, true);
    } finally { await page.close(); }
  });
  await check('slow X-Axis options reload once and wait for the settled list', async () => {
    const page = await fixture({xAxisDelays: [1000, 50]});
    try {
      await page.evaluate(() => {
        window.fixtureAxisReloads = 0;
        document.querySelector('#yAxis').addEventListener('change', () => { window.fixtureAxisReloads++; });
        const originalTimeout = window.setTimeout;
        window.setTimeout = function (callback, ms, ...args) {
          return originalTimeout.call(window, callback, ms === 15_000 ? 900 : ms, ...args);
        };
      });
      const proof = await page.evaluate(config => vahanDriver.fill(config), requested);
      assert.ok(proof.checks.every(check => check.match));
      assert.ok((await page.evaluate(() => window.fixtureAxisReloads)) >= 2,
        'Y-Axis must be signalled again after the first X-Axis wait expires');
      assert.equal(await page.locator('#xAxis_hidden').inputValue(), 'Month Wise');
    } finally { await page.close(); }
  });
  await check('missing RTO options reload the selected State once and preserve all filters', async () => {
    const page = await fixture({rtoResponses: [[], ['Test RTO']]});
    try {
      await page.evaluate(() => {
        window.fixtureStateReloads = 0;
        document.querySelector('#stateName').addEventListener('change', () => { window.fixtureStateReloads++; });
        const originalTimeout = window.setTimeout;
        window.setTimeout = function (callback, ms, ...args) {
          return originalTimeout.call(window, callback, ms === 15_000 ? 900 : ms, ...args);
        };
      });
      const proof = await page.evaluate(config => vahanDriver.fill(config), requested);
      assert.ok(proof.checks.every(check => check.match));
      assert.equal(await page.evaluate(() => fixtureStateReloads), 2);
      assert.deepEqual(proof.checks.find(check => check.field === 'rtos').actual, ['Test RTO']);
    } finally { await page.close(); }
  });
  await check('RTO reload exhaustion stops the filter with a specific error', async () => {
    const page = await fixture({rtoResponses: [[], []]});
    try {
      await page.evaluate(() => {
        const originalTimeout = window.setTimeout;
        window.setTimeout = function (callback, ms, ...args) {
          return originalTimeout.call(window, callback, ms === 15_000 ? 900 : ms, ...args);
        };
      });
      await assert.rejects(page.evaluate(config => vahanDriver.fill(config), requested), /RTO_OPTIONS_TIMEOUT/);
    } finally { await page.close(); }
  });
  await check('before-Apply verification rejects silent changes, disabled controls and duplicates', async () => {
    const page = await fixture();
    try {
      await page.evaluate(config => vahanDriver.fill(config), requested);
      await page.locator('#rtoCode').evaluate(select => { select.selectedIndex = -1; });
      await assert.rejects(page.evaluate(config => vahanDriver.verifyFilters(config), requested), /FILTER_VERIFICATION_FAILED.*rtos/);
      await page.evaluate(config => vahanDriver.fill(config), requested);
      await page.locator('#vehicleFuel').evaluate(select => { select.disabled = true; });
      await assert.rejects(page.evaluate(config => vahanDriver.verifyFilters(config), requested), /FILTER_VERIFICATION_FAILED.*fuels/);
      await page.locator('#vehicleFuel').evaluate(select => { select.disabled = false; });
      await assert.rejects(page.evaluate(config => vahanDriver.verifyFilters({...config, makers: ['Maker Alpha', 'Maker Alpha', 'Maker Gamma']}), requested), /FILTER_VERIFICATION_FAILED.*makers/);
    } finally { await page.close(); }
  });
  await check('unknown fields fail explicitly and aborted sibling tasks cannot corrupt next case', async () => {
    const page = await fixture();
    try {
      await assert.rejects(page.evaluate(() => vahanDriver.fill({newFilter: 'unsupported'})), /FILTER_UNSUPPORTED/);
      await page.locator('#vehicleMaker').evaluate(select => { select.loadOptions = () => { throw new Error('fixture widget failure'); }; });
      await assert.rejects(page.evaluate(config => vahanDriver.fill(config), requested), /fixture widget failure/);
      await page.locator('#vehicleMaker').evaluate(select => { delete select.loadOptions; });
      const proof = await page.evaluate(config => vahanDriver.fill(config), requested);
      assert.ok(proof.checks.every(check => check.match));
      await page.waitForTimeout(200);
      assert.ok((await page.evaluate(config => vahanDriver.verifyFilters(config), requested)).checks.every(check => check.match));
    } finally { await page.close(); }
  });
  await check('a concurrent second fill is refused', async () => {
    const page = await fixture();
    try {
      const outcomes = await page.evaluate(config => Promise.allSettled([vahanDriver.fill(config), vahanDriver.fill(config)]).then(results => results.map(result => ({status: result.status, error: result.reason?.message}))), requested);
      assert.equal(outcomes.filter(result => result.status === 'fulfilled').length, 1);
      assert.match(outcomes.find(result => result.status === 'rejected').error, /FILTER_FILL_BUSY/);
    } finally { await page.close(); }
  });
  if (process.env.VAHAN_BASELINE_DRIVER) {
    const durations = {before: [], after: []};
    for (let iteration = 0; iteration < 3; iteration++) {
      for (const [name, path] of [['before', process.env.VAHAN_BASELINE_DRIVER], ['after', driver]]) {
        const page = await fixture({path});
        try {
          const config = name === 'before' ? Object.fromEntries(Object.entries(requested).map(([key, value]) => [key, Array.isArray(value) ? value.join(',') : value])) : requested;
          const milliseconds = await page.evaluate(async config => { const start = performance.now(); await vahanDriver.fill(config); return Math.round(performance.now() - start); }, config);
          durations[name].push(milliseconds);
        } finally { await page.close(); }
      }
    }
    const median = values => [...values].sort((a, b) => a - b)[1];
    console.log(`BENCHMARK synthetic delayed options: ${JSON.stringify(durations)}, median reduction ${Math.round((1 - median(durations.after) / median(durations.before)) * 100)}%`);
    assert.ok(median(durations.after) < median(durations.before), 'Parallel fixture must be faster while verifying all requested values.');
  }
  console.log(`${passed} filter-fill checks passed.`);
} finally { await browser.close(); }
