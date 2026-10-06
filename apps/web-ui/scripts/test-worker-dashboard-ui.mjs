import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';

const scenarios = Array.from({length: 4}, (_, index) => ({
  name: 'Maker Month Wise Data of Office ' + index,
  filters: {states: [index < 2 ? 'ASSAM' : 'Andaman & Nicobar Island'],
    rtos: ['Office ' + index]},
}));
const recovery = {
  version: 2, status: 'stopped', queueIndices: [0, 1, 2, 3], nextPosition: 2,
  currentIndex: null, activeJobId: null, stopRequested: true, hadErrors: true,
  log: [
    {index: 0, name: scenarios[0].name, status: 'ok', detail: 'Saved', rowCount: 25,
      completedAt: '2026-10-05T01:00:00Z'},
    {index: 2, name: scenarios[2].name, status: 'error', detail: 'Report error',
      completedAt: '2026-10-05T01:01:00Z'},
  ],
  failedAtIndex: 2, progress: {done: 2, total: 4, current: ''}, sessionId: 'fixture-2-worker',
  source: 'new', year: 2026, startedAt: '2026-10-05T01:00:00Z', finishedAt: null,
  lanes: [
    {runnerId: 'playwright-2', indices: [0, 1], nextPosition: 1, currentIndex: null,
      activeJobId: null, lastJobId: null, retryQueueIndices: [], retryIndex: null,
      lastRetryCheckpoint: 0, currentFilterStartedAt: null},
    {runnerId: 'playwright-1', indices: [2, 3], nextPosition: 1, currentIndex: null,
      activeJobId: null, lastJobId: null, retryQueueIndices: [2], retryIndex: null,
      lastRetryCheckpoint: 0, currentFilterStartedAt: null},
  ],
};
let state = {
  vahanStateRtoMatrixV1: {year: 2026, states: ['ASSAM', 'Andaman & Nicobar Island'], scenarios},
  vahanStateRtoBatchRecoveryV1: recovery,
};

const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  let uiSocket;
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/socket.io/**', socket => {
    uiSocket = socket;
    socket.send('0' + JSON.stringify({sid: 'fixture-engine', upgrades: [], pingInterval: 60_000,
      pingTimeout: 60_000, maxPayload: 1_000_000}));
    socket.onMessage(message => {
      if (String(message).startsWith('40/ui,')) socket.send('40/ui,' + JSON.stringify({sid: 'fixture-ui'}));
    });
  });
  await page.addInitScript(() => localStorage.setItem('vahanUiAccessToken', 'fixture-token'));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body = {};
    if (path === '/api/auth/status') body = {configured: true};
    else if (path === '/api/auth/me') body = {username: 'fixture', role: 'admin'};
    else if (path === '/api/auth/renew') body = {accessToken: 'fixture-token'};
    else if (path === '/api/user-state') body = state;
    else if (path === '/api/runners') body = Array.from({length: 10}, (_, index) => ({
      id: 'playwright-' + (index + 1), name: 'Crawler ' + (index + 1),
      source: 'new', status: 'ONLINE', lastSeenAt: '2026-10-05T01:00:00Z',
    }));
    else if (path === '/api/maker-updates') body = [];
    else if (path === '/api/health') body = {status: 'ok'};
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body),
      headers: {'access-control-allow-origin': '*'}});
  });

  await page.goto(process.env.WORKER_UI_URL || 'http://127.0.0.1:5174/#configure');
  await page.getByRole('heading', {name: '2-worker crawl monitor'}).waitFor();
  await page.getByText('10/10 workers online').waitFor();
  assert.equal(await page.locator('.worker-card').count(), 2);
  assert.match(await page.locator('.worker-card').first().innerText(), /Worker 1[\s\S]*playwright-1[\s\S]*#3–#4/);
  assert.match(await page.locator('.worker-card').last().innerText(), /Worker 2[\s\S]*playwright-2[\s\S]*#1–#2/);
  assert.match(await page.locator('.worker-card').first().innerText(), /1\s*To retry/);
  assert.match(await page.locator('.worker-card').last().innerText(), /25 rows to SQL/);
  assert.equal(await page.getByRole('progressbar', {name: 'Worker 1 progress'}).getAttribute('aria-valuenow'), '50');
  assert.equal(await page.getByRole('progressbar', {name: 'Worker 2 progress'}).getAttribute('aria-valuenow'), '50');
  assert.ok(await page.getByRole('button', {name: 'Continue saved run (2 workers)'}).isVisible());

  const tenScenarios = Array.from({length: 20}, (_, index) => ({
    name: 'Maker Month Wise Data of Office ' + index,
    filters: {states: ['State ' + index], rtos: ['Office ' + index]},
  }));
  const tenLanes = Array.from({length: 10}, (_, index) => ({
    runnerId: 'playwright-' + (index + 1), indices: [index * 2, index * 2 + 1],
    nextPosition: 1, currentIndex: null, activeJobId: null, lastJobId: 'job-' + (index + 1),
    retryQueueIndices: [], retryIndex: null, lastRetryCheckpoint: 0, currentFilterStartedAt: null,
  }));
  state = {
    vahanStateRtoMatrixV1: {year: 2026, states: tenScenarios.map(s => s.filters.states[0]),
      scenarios: tenScenarios},
    vahanStateRtoBatchRecoveryV1: {...recovery, queueIndices: Array.from({length: 20}, (_, i) => i),
      nextPosition: 10, log: tenLanes.map((lane, index) => ({
        index: lane.indices[0], name: tenScenarios[lane.indices[0]].name,
        status: 'ok', detail: 'Saved', rowCount: index + 1,
        completedAt: '2026-10-05T01:00:00Z',
      })), failedAtIndex: null, hadErrors: false, progress: {done: 10, total: 20, current: ''},
      sessionId: 'fixture-10-worker', lanes: tenLanes},
  };
  await page.reload();
  await page.getByRole('heading', {name: '10-worker crawl monitor'}).waitFor();
  await page.getByText('10/10 workers online').waitFor();
  assert.equal(await page.locator('.worker-card').count(), 10);
  assert.match(await page.locator('.worker-card').first().innerText(), /Worker 1[\s\S]*#1–#2/);
  assert.match(await page.locator('.worker-card').last().innerText(), /Worker 10[\s\S]*#19–#20/);
  assert.ok(await page.getByRole('button', {name: 'Continue saved run (10 workers)'}).isVisible());
  for (let index = 0; index < 10; index++) {
    uiSocket.send('42/ui,' + JSON.stringify(['job:status', {
      id: 'job-' + (index + 1), runnerId: 'playwright-' + (index + 1),
      status: 'SUBMITTING', filters: tenScenarios[index * 2].filters,
    }]));
  }
  await page.locator('.activity-worker').nth(9).waitFor();
  const positions = await page.locator('.activity-worker').evaluateAll(nodes => nodes.map(node =>
    ({x: Math.round(node.getBoundingClientRect().x), y: Math.round(node.getBoundingClientRect().y)})));
  assert.equal(new Set(positions.slice(0, 5).map(item => item.y)).size, 1,
    'first five Activity cards share one desktop row');
  assert.ok(positions[5].y > positions[4].y, 'sixth Activity card starts the second row');
  await page.screenshot({path: '/tmp/vahan-worker-dashboard-desktop.png', fullPage: true});

  const sharedLanes = Array.from({length: 10}, (_, index) => ({
    runnerId: 'playwright-' + (index + 1), indices: [index, index + 10],
    nextPosition: 1, currentIndex: null, activeJobId: null, lastJobId: null,
    retryQueueIndices: [], retryIndex: null, lastRetryCheckpoint: 0, currentFilterStartedAt: null,
  }));
  state = {
    ...state,
    vahanStateRtoBatchRecoveryV1: {...state.vahanStateRtoBatchRecoveryV1, version: 3,
      sessionId: 'fixture-shared-queue', lanes: sharedLanes,
      log: sharedLanes.map((lane) => ({index: lane.indices[0], name: tenScenarios[lane.indices[0]].name,
        status: 'ok', detail: 'Saved', completedAt: '2026-10-05T01:00:00Z'}))},
  };
  await page.reload();
  await page.getByText(/workers take the next available State/).waitFor();
  assert.match(await page.locator('.worker-card').first().innerText(), /2 claimed[\s\S]*1 settled/);
  assert.doesNotMatch(await page.locator('.worker-card').first().innerText(), /#1–#2/);
  assert.equal(await page.locator('.worker-card').count(), 10);
  await page.screenshot({path: '/tmp/vahan-shared-queue-dashboard-desktop.png', fullPage: true});

  const workerCards = page.locator('.worker-card');
  const beforeLongText = await workerCards.evaluateAll(cards => cards.map(card => {
    const {x, y, width, height} = card.getBoundingClientRect();
    return {x, y, width, height};
  }));
  assert.equal(new Set(beforeLongText.slice(0, 5).map(box => box.y)).size, 1,
    'first five worker cards share one desktop row');
  assert.ok(beforeLongText[5].y > beforeLongText[4].y,
    'sixth worker card starts the second row');
  const stressSelectors = [
    '.worker-card-title > div > span', '.worker-card-assignment strong',
    '.worker-card-progress-title strong', '.worker-current-heading strong',
    '.worker-current-name', '.worker-card-footer strong',
  ];
  const originalWorkerText = await workerCards.first().evaluate((card, selectors) =>
    selectors.map(selector => card.querySelector(selector)?.textContent || ''), stressSelectors);
  await workerCards.first().evaluate((card, selectors) => {
    const longText = 'StateWithAnUnbrokenStateAndRtoName'.repeat(24);
    selectors.forEach(selector => {
      const element = card.querySelector(selector);
      if (element) element.textContent = longText;
    });
  }, stressSelectors);
  await page.waitForTimeout(50);
  const afterLongText = await workerCards.evaluateAll(cards => cards.map(card => {
    const {x, y, width, height} = card.getBoundingClientRect();
    return {x, y, width, height};
  }));
  assert.deepEqual(afterLongText, beforeLongText,
    'very long worker text does not resize cards or move the grid');
  await workerCards.first().evaluate((card, state) => state.selectors.forEach((selector, index) => {
    const element = card.querySelector(selector);
    if (element) element.textContent = state.text[index];
  }), {selectors: stressSelectors, text: originalWorkerText});

  await page.setViewportSize({width: 390, height: 844});
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    'mobile page has no horizontal overflow');
  await page.screenshot({path: '/tmp/vahan-worker-dashboard-mobile.png', fullPage: true});
  assert.deepEqual(errors, []);
  console.log('Ten-worker home UI: legacy saved run, ten assignments, controls and mobile width passed.');
} finally {
  await browser.close();
}
