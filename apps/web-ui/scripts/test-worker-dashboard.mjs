import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import ts from 'typescript';
import {renderToStaticMarkup} from 'react-dom/server';

const require = createRequire(import.meta.url);
function loadComponent() {
  const source = readFileSync(new URL('../src/components/WorkerDashboard.tsx', import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  const exports = {};
  const module = {exports};
  new Function('require', 'module', 'exports', compiled)((name) => {
    if (name === '../batch-timing') return {estimateBatchTiming: () => ({remainingMs: 30_000})};
    if (name === '../worker-settings') return {
      TARGET_WORKER_COUNT: 10,
      compareRunnerIds: (left, right) => left.localeCompare(right, undefined, {numeric: true}),
      plannedWorkerRange: (total, workers, position) => {
        const base = Math.floor(total / workers), extra = total % workers;
        const start = position * base + Math.min(position, extra);
        const count = base + (position < extra ? 1 : 0);
        return {start, end: start + count - 1, count};
      },
    };
    return require(name);
  }, module, exports);
  return module.exports.WorkerDashboard;
}

const WorkerDashboard = loadComponent();
const React = require('react');
const scenarios = Array.from({length: 4}, (_, index) => ({
  name: 'Office ' + index,
  filters: {states: ['State ' + index], rtos: ['RTO ' + index]},
}));
const lanes = [
  {runnerId: 'playwright-1', indices: [0, 1], nextPosition: 1, currentIndex: 1,
    activeJobId: 'job-1', retryQueueIndices: [], retryIndex: null, currentFilterStartedAt: Date.now() - 5_000},
  {runnerId: 'playwright-2', indices: [2, 3], nextPosition: 1, currentIndex: 3,
    activeJobId: 'job-3', retryQueueIndices: [2], retryIndex: 3, currentFilterStartedAt: Date.now() - 3_000},
];
const props = {
  runners: [
    {id: 'playwright-1', name: 'Crawler A', source: 'new', status: 'BUSY'},
    {id: 'playwright-2', name: 'Crawler B', source: 'new', status: 'BUSY'},
  ],
  connection: 'connected', scenarios, lanes,
  jobs: {'job-1': {id: 'job-1', status: 'WAITING_RESULT'},
    'job-3': {id: 'job-3', status: 'WAITING_CAPTCHA'}},
  log: [
    {index: 0, status: 'ok', rowCount: 25, completedAt: '2026-10-05T01:00:00Z'},
    {index: 2, status: 'error', completedAt: '2026-10-05T01:00:01Z'},
  ],
  progress: {done: 2, total: 4}, status: 'running', running: true, loading: false,
  disabled: true, legacySession: false, timings: [], currentFilterStartedAt: null,
  activeElapsedMs: 30_000, activeSegmentStartedAt: null,
  captchaJobIds: ['job-3'],
  onRunAll() {}, onContinue() {}, onRestart() {}, onStop() {},
};
const render = (overrides = {}) => renderToStaticMarkup(React.createElement(WorkerDashboard, {...props, ...overrides}));

const running = render();
assert.match(running, /#1–#2/);
assert.match(running, /#3–#4/);
assert.match(running, /State 1 · RTO 1/);
assert.match(running, /State 3 · RTO 3/);
assert.match(running, /Waiting for result/);
assert.match(running, /CAPTCHA required/);
assert.match(running, /Open this worker&#x27;s CAPTCHA/);
assert.match(running, /25 rows to SQL/);
assert.match(running, /Stop active workers/);
assert.equal((running.match(/aria-valuenow="50"/g) || []).length, 3);

const offline = render({connection: 'disconnected', status: 'stopped', running: false,
  jobs: {}, captchaJobIds: []});
assert.match(offline, /0\/10 workers online/);
assert.match(offline, /Continue saved run \(2 workers\)/);
assert.match(offline, /Restart with 10 workers/);
assert.match(offline, /Paused/);

const previewScenarios = Array.from({length: 20}, (_, index) => ({
  name: 'Case ' + index, filters: {states: ['State ' + index], rtos: ['RTO ' + index]},
}));
const projected = render({lanes: [], log: [], jobs: {}, status: 'idle', running: false,
  scenarios: previewScenarios, progress: {done: 0, total: 0}, captchaJobIds: []});
assert.match(projected, /#1–#2/);
assert.match(projected, /#19–#20/);
assert.match(projected, /Run all with 10 workers/);
assert.equal((projected.match(/aria-valuenow="0"/g) || []).length, 11);

const tenLanes = Array.from({length: 10}, (_, index) => ({
  runnerId: 'playwright-' + (index + 1), indices: [index * 2, index * 2 + 1],
  nextPosition: 1, currentIndex: null, activeJobId: null, retryQueueIndices: [],
  retryIndex: null, currentFilterStartedAt: null,
}));
const tenRunners = Array.from({length: 10}, (_, index) => ({
  id: 'playwright-' + (index + 1), name: 'Crawler ' + (index + 1),
  source: 'new', status: 'ONLINE',
}));
const ten = render({lanes: tenLanes, runners: tenRunners, scenarios: previewScenarios,
  progress: {done: 10, total: 20}, status: 'stopped', running: false,
  log: [], jobs: {}, captchaJobIds: []});
assert.match(ten, /10\/10 workers online/);
assert.match(ten, /10-worker crawl monitor/);
assert.match(ten, /Worker 10/);
assert.match(ten, /#19–#20/);
assert.equal((ten.match(/class="worker-card"/g) || []).length, 10);

console.log('Worker dashboard: ten-card split, legacy two-worker progress, stages, CAPTCHA and recovery passed.');
