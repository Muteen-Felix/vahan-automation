import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
function loadFunction(startMarker, endMarker, name, context) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start);
  const compiled = ts.transpileModule(source.slice(start, end), {
    compilerOptions: {target: ts.ScriptTarget.ES2022},
  }).outputText;
  return runInNewContext(compiled + '\n' + name, context);
}

const split = loadFunction('function splitParallelLanes(', 'function validParallelLanes(',
  'splitParallelLanes', {});
const allIndices = Array.from({length: 1676}, (_, index) => index);
const runnerIds = Array.from({length: 10}, (_, index) => 'playwright-' + (index + 1));
const fullLanes = split(allIndices, runnerIds);
const validLanes = loadFunction('function validParallelLanes(', 'function readBatchRecovery(',
  'validParallelLanes', {TARGET_WORKER_COUNT: 10});
assert.deepEqual(fullLanes.map((lane) => lane.indices.length),
  [168, 168, 168, 168, 168, 168, 167, 167, 167, 167]);
assert.deepEqual(fullLanes.flatMap((lane) => lane.indices), allIndices);
assert.equal(fullLanes[0].indices.at(-1), 167);
assert.equal(fullLanes[9].indices.at(-1), 1675);
assert.equal(validLanes(fullLanes, allIndices), true);
assert.equal(validLanes(fullLanes.map((lane, index) => index === 9
  ? {...lane, runnerId: 'playwright-1'} : lane), allIndices), false);
assert.equal(validLanes([...fullLanes].reverse(), allIndices), false);
assert.equal(validLanes(fullLanes.slice(0, 9), allIndices), false);
const legacyLanes = split(allIndices, ['playwright-1', 'playwright-2']);
assert.deepEqual(legacyLanes.map((lane) => lane.indices.length), [838, 838]);
assert.equal(validLanes(legacyLanes, allIndices), true, 'saved two-worker runs remain resumable');
assert.throws(() => split(allIndices, ['playwright-1', 'playwright-1']), /distinct runner ID/);

const noop = () => {};
const snapshotsRef = {current: new Map()};
let renderedSnapshots = {};
const rememberJob = loadFunction('  function rememberJob(', '  function logRunOutcome(',
  'rememberJob', {jobSnapshotsRef: snapshotsRef, JOB_SNAPSHOT_LIMIT: 32,
    setJobSnapshots: (update) => {renderedSnapshots = update(renderedSnapshots);}});
for (let index = 0; index < 10; index++) rememberJob({id: 'job-' + index, status: 'ASSIGNED'});
assert.equal(snapshotsRef.current.size, 10, 'all ten active jobs remain available to the coordinator');
assert.equal(Object.keys(renderedSnapshots).length, 10, 'all ten job stages remain visible in the UI');
const scenarios = Array.from({length: 120}, (_, index) => ({
  name: 'Case ' + index,
  filters: {states: ['State ' + index], rtos: ['RTO ' + index]},
}));
const plan = {year: 2026, scenarios};
const runnersRef = {current: [...runnerIds].reverse().map((id) => ({
  id, source: 'new', status: 'ONLINE', currentJobId: null,
}))};
const recoveryRef = {current: null};
const logRef = {current: []};
const stopRef = {current: false};
const calls = [];
const created = [];
const firstStarted = [];
const firstReleases = [];
const errors = [];
let blockFirst = true;
class ApiError extends Error {constructor(status) {super('API error'); this.status = status;}}
const api = {
  createJob: async (runnerId, filters, scenarioName, sessionId, retryOfJobId) => {
    const index = Number(scenarioName.slice(5));
    const item = {runnerId, index, retryOfJobId, sessionId};
    calls.push(item);
    const job = {id: (retryOfJobId ? 'retry-' : 'primary-') + index,
      runnerId, scenarioName, sessionId, retryOfJobId, filters, status: 'ASSIGNED'};
    created.push(job);
    if (blockFirst && index % 12 === 0 && !retryOfJobId) {
      firstStarted.push(index);
      await new Promise((resolve) => firstReleases.push(resolve));
    }
    return job;
  },
  jobs: async () => created,
  getJob: async (id) => created.find((job) => job.id === id),
};
const context = {
  currentReportYear: () => 2026,
  TARGET_WORKER_COUNT: 10,
  compareRunnerIds: (left, right) => left.localeCompare(right, undefined, {numeric: true}),
  validParallelLanes: validLanes, splitParallelLanes: split,
  matrixOfficeKey: (scenario) => scenario.name,
  refreshRunners: async () => {}, runnersRef,
  persistentState: {removeItem: noop}, ACTIVE_JOB_STORAGE_KEY: 'active',
  crypto: {randomUUID: () => 'session-ten-workers'},
  batchLogRef: logRef, batchRecoveryRef: recoveryRef,
  failedAtIndexRef: {current: null}, batchRunningRef: {current: false},
  batchLoopStartedRef: {current: false}, batchStopRef: stopRef,
  setBatchLog: noop, setFailedAtIndex: noop, setParallelCaptchas: noop,
  setBatchRunning: noop, setBatchStatus: noop, setBatchStartedAt: noop,
  setBatchFinishedAt: noop, setBatchTimings: noop, setBatchActiveElapsedMs: noop,
  setBatchActiveSegmentStartedAt: noop, setBatchProgress: noop,
  setCurrentFilterStartedAt: noop, setError: (message) => errors.push(message), setNotice: noop,
  setReportsTrigger: noop, setJobSnapshots: noop, setJob: noop,
  jobSnapshotsRef: {current: new Map()}, logRunOutcome: noop,
  rememberJob: noop,
  writeBatchRecovery: (value) => {recoveryRef.current = value;},
  MAX_AUTO_RETRY_ATTEMPTS: 1, AUTO_RETRY_CHECKPOINT_SIZE: 10,
  waitForExistingJob: async (id) => {
    const index = Number(id.split('-').at(-1));
    const failed = index % 12 === 1 && id.startsWith('primary-');
    return {id, status: failed ? 'FAILED' : 'COMPLETED',
      error: failed ? 'Report failed' : null,
      mainReportSavedAt: failed ? null : '2026-10-05T00:00:00Z',
      mainReportSummary: {parsedRows: failed ? 0 : 3},
      updatedAt: '2026-10-05T00:00:00Z'};
  },
  subscribeJob: async () => {}, sleep: async () => {},
  api, ApiError,
};
const run = loadFunction('  async function runParallelScenarioQueue(', '  async function stopBatch()',
  'runParallelScenarioQueue', context);
const running = run(plan);
for (let turn = 0; turn < 40 && firstStarted.length < 10; turn += 1) {
  await new Promise((resolve) => setImmediate(resolve));
}
assert.deepEqual([...firstStarted].sort((a, b) => a - b),
  Array.from({length: 10}, (_, index) => index * 12),
  'all ten segments start before any first report finishes');
assert.equal(calls.length, 10, 'each worker runs only its first case before the release');
firstReleases.forEach((release) => release());
await running;
blockFirst = false;

assert.equal(recoveryRef.current.status, 'completed');
assert.equal(recoveryRef.current.progress.done, 120);
assert.equal(logRef.current.length, 120);
assert.equal(logRef.current.filter((entry) => entry.status === 'error').length, 0);
for (const [workerIndex, runnerId] of runnerIds.entries()) {
  const start = workerIndex * 12;
  assert.deepEqual(calls.filter((call) => call.runnerId === runnerId).map((call) => call.index),
    [...Array.from({length: 10}, (_, offset) => start + offset), start + 1, start + 10, start + 11],
    runnerId + ' retries its first ten-case group before advancing');
}
assert.ok(calls.every((call) => call.sessionId === 'session-ten-workers'));
assert.deepEqual(recoveryRef.current.lanes.map((lane) => lane.nextPosition), Array(10).fill(12));
assert.deepEqual(recoveryRef.current.lanes.map((lane) => lane.runnerId), runnerIds,
  'numeric runner ordering prevents playwright-10 from preceding playwright-2');

const reloadLanes = split(Array.from({length: 120}, (_, index) => index), runnerIds);
for (const lane of reloadLanes) {
  lane.currentIndex = lane.indices[0];
  lane.activeJobId = 'primary-' + lane.currentIndex;
}
const reloadRecovery = {
  version: 2, status: 'running', queueIndices: Array.from({length: 120}, (_, index) => index),
  queueOfficeKeys: scenarios.map((scenario) => scenario.name),
  nextPosition: 0, currentIndex: null, activeJobId: null, stopRequested: false,
  hadErrors: false, log: [], failedAtIndex: null,
  progress: {done: 0, total: 120, current: ''},
  sessionId: 'session-ten-workers-reload', year: 2026,
  startedAt: '2026-10-05T00:00:00Z', timings: [], lanes: reloadLanes,
};
recoveryRef.current = reloadRecovery;
logRef.current = [];
const callsBeforeReload = calls.length;
await run(plan, reloadRecovery);
const afterReload = calls.slice(callsBeforeReload);
assert.ok(!afterReload.some((call) => call.index % 12 === 0 && !call.retryOfJobId),
  'reload waits for all ten active jobs instead of creating duplicates');
assert.equal(recoveryRef.current.progress.done, 120);

const oldPlan = {year: 2026, scenarios: scenarios.slice(0, 22)};
const oldQueue = Array.from({length: 22}, (_, index) => index);
const oldLanes = split(oldQueue, ['playwright-1', 'playwright-2']);
for (const lane of oldLanes) {
  lane.currentIndex = lane.indices[0];
  lane.activeJobId = 'primary-' + lane.currentIndex;
}
const oldRecovery = {...reloadRecovery, queueIndices: oldQueue,
  queueOfficeKeys: oldPlan.scenarios.map((scenario) => scenario.name),
  progress: {done: 0, total: 22, current: ''}, lanes: oldLanes,
  sessionId: 'saved-two-worker-run'};
recoveryRef.current = oldRecovery;
logRef.current = [];
await run(oldPlan, oldRecovery);
assert.equal(recoveryRef.current.progress.done, 22,
  'a saved two-worker run resumes with its original assignment');

runnersRef.current = runnersRef.current.slice(0, 9);
const beforeShortage = calls.length;
await run(plan);
assert.match(errors.at(-1), /10 online, idle browser workers are required/);
assert.equal(calls.length, beforeShortage, 'a missing worker cannot start a partial new run');
runnersRef.current = [...runnerIds].reverse().map((id) => ({
  id, source: 'new', status: 'ONLINE', currentJobId: null,
}));

const activeRecovery = {...reloadRecovery, status: 'running',
  lanes: reloadLanes.map((lane, index) => ({...lane, activeJobId: 'active-worker-' + (index + 1)}))};
const cancelledIds = [];
const stopContext = {
  batchStopRef: {current: false}, batchRecoveryRef: {current: activeRecovery},
  updateBatchRecovery: (patch) => Object.assign(activeRecovery, patch),
  api: {cancelJob: async (id) => {
    cancelledIds.push(id);
    return {id, status: 'CANCELLED'};
  }, getJob: async () => null},
  jobSnapshotsRef: {current: new Map()}, setJobSnapshots: noop, setParallelCaptchas: noop,
  rememberJob: noop,
  resolveTerminal: noop, refreshRunners: async () => {}, setError: noop,
};
const stop = loadFunction('  async function stopBatch()', '  async function continueStoppedBatch()',
  'stopBatch', stopContext);
await stop();
assert.deepEqual(cancelledIds.sort((a, b) => a.localeCompare(b, undefined, {numeric: true})),
  runnerIds.map((_, index) => 'active-worker-' + (index + 1)));
assert.equal(stopContext.batchStopRef.current, true);
console.log('Ten segments run concurrently, sequentially per worker, with checkpoint retries and saved two-worker recovery.');
