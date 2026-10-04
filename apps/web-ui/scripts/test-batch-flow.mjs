import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
function loadFunction(name, nextName, context) {
  const start = source.indexOf(`  async function ${name}(`);
  const end = [source.indexOf(`  async function ${nextName}(`, start),
    source.indexOf(`  function ${nextName}(`, start)].filter(index => index > start).sort((a, b) => a - b)[0];
  assert.ok(start >= 0 && end > start);
  const compiled = ts.transpileModule(source.slice(start, end), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return runInNewContext(`${compiled}\n${name}`, context);
}
const created = { id: "job-a", status: "WAITING_RESULT" };
const noop = () => {};
const runnersRef = {current: [{id: 'stale', source: 'new', status: 'RECONNECTING', currentJobId: null}]};
const refresh = loadFunction('refreshRunners', 'resolveTerminal', {
  api: {runners: async () => [{id: 'ready', source: 'new', status: 'ONLINE', currentJobId: null}]},
  runnersRef, setRunners: noop, setError: noop,
});
await refresh();
assert.equal(runnersRef.current[0].id, 'ready',
  'the batch runner reference must update before a React state render');
const create = loadFunction("createJob", "submitCaptcha", {
  api: { createJob: async () => created },
  setCreating: noop, setError: noop, setNotice: noop, setCaptcha: noop,
  setJob: noop, latestJobRef: { current: null },
  setReportsTrigger: noop,
  persistentState: { setItem: noop }, ACTIVE_JOB_STORAGE_KEY: "test",
  batchRecoveryRef: { current: null },
  batchStopRef: { current: false },
  subscribeJob: async () => { throw new Error("operation has timed out"); },
  refreshRunners: async () => {}, isSocketTimeout: () => true,
});
assert.equal((await create("runner-a", {})).id, "job-a",
  "a successful job creation must survive a failed live subscription");

let reconnectAttempts = 0;
const reconnect = loadFunction('runOneScenarioJob', 'waitForExistingJob', {
  createJob: async () => {
    reconnectAttempts++;
    if (reconnectAttempts === 1) throw new Error('Runner is reconnecting.');
    return {id: 'reconnected-job'};
  },
  waitForExistingJob: async id => ({id, status: 'COMPLETED'}),
  batchStopRef: {current: false}, batchRunningRef: {current: true}, setNotice: noop,
  terminalResolverRef: {current: null}, latestJobRef: {current: null},
  sleep: async () => {}, refreshRunners: async () => {}, pickAvailableRunner: () => 'runner-a',
});
assert.equal((await reconnect('runner-a', {})).status, 'COMPLETED');
assert.equal(reconnectAttempts, 2, 'reconnecting response retries job creation without skipping the case');

let runnerAvailable = false;
let runnerPolls = 0;
const waitForRunner = loadFunction('pickAvailableRunnerWithRetry', 'runOneScenarioJob', {
  batchStopRef: {current: false},
  pickAvailableRunner: () => runnerAvailable ? 'runner-a' : null,
  sleep: async () => {},
  refreshRunners: async () => { runnerPolls += 1; if (runnerPolls === 32) runnerAvailable = true; },
});
assert.equal(await waitForRunner(Infinity, 0), 'runner-a',
  'an offline batch automatically resumes when its worker returns after the old 30-second limit');
assert.equal(runnerPolls, 32);
const stoppedWait = loadFunction('pickAvailableRunnerWithRetry', 'runOneScenarioJob', {
  batchStopRef: {current: true}, pickAvailableRunner: () => null,
  sleep: async () => { throw new Error('stopped wait should not sleep'); }, refreshRunners: async () => {},
});
assert.equal(await stoppedWait(Infinity, 0), null, 'Stop interrupts an offline batch wait');

let longReconnectAttempts = 0;
const longReconnect = loadFunction('runOneScenarioJob', 'waitForExistingJob', {
  createJob: async () => {
    longReconnectAttempts += 1;
    if (longReconnectAttempts < 12) throw new Error('Runner is reconnecting.');
    return {id: 'reconnected-late'};
  },
  waitForExistingJob: async id => ({id, status: 'COMPLETED'}),
  batchStopRef: {current: false}, batchRunningRef: {current: true}, setNotice: noop,
  terminalResolverRef: {current: null}, latestJobRef: {current: null},
  sleep: async () => {}, refreshRunners: async () => {}, pickAvailableRunner: () => 'runner-a',
});
assert.equal((await longReconnect('runner-a', {})).status, 'COMPLETED');
assert.equal(longReconnectAttempts, 12, 'a late reconnect continues the same filter beyond ten retries');

class ApiError extends Error { constructor(status) { super(); this.status = status; } }
function waiterContext(getJob) {
  const scheduled = new Map();
  let timerId = 0;
  const context = {
    api: { getJob }, ApiError,
    latestJobRef: { current: created }, terminalResolverRef: { current: null },
    setJob: noop, setCaptcha: noop, setNotice: noop, setReportsTrigger: noop,
    persistentState: { removeItem: noop }, ACTIVE_JOB_STORAGE_KEY: "test",
    refreshRunners: async () => {}, uiSocket: { connected: false },
    setTimeout: (callback) => { scheduled.set(++timerId, callback); return timerId; },
    clearTimeout: (id) => scheduled.delete(id),
  };
  const wait = loadFunction("waitForExistingJob", "runScenarioQueue", context);
  return { context, scheduled, wait, async tick() {
    const [id, callback] = scheduled.entries().next().value;
    scheduled.delete(id);
    await callback();
    await new Promise((resolve) => setImmediate(resolve));
  } };
}
let calls = 0;
const polling = waiterContext(async () => {
  calls += 1;
  if (calls === 1) throw new TypeError("Failed to fetch");
  return { id: "job-a", status: "COMPLETED", excelFileName: "report.xlsx" };
});
let resolved = false;
const result = polling.wait("job-a").then((job) => { resolved = true; return job; });
await polling.tick();
assert.ok(!resolved, "temporary network failure must retain the current case");
assert.equal(polling.scheduled.size, 1);
await polling.tick();
assert.equal((await result).status, "COMPLETED");
assert.equal(polling.scheduled.size, 0);

const socket = waiterContext(async () => { throw new Error("Polling should have been cancelled"); });
const viaSocket = socket.wait("job-a");
socket.context.terminalResolverRef.current({ id: "another-job", status: "COMPLETED" });
assert.equal(socket.scheduled.size, 1, "unrelated terminal events must not release this case");
socket.context.terminalResolverRef.current({ id: "job-a", status: "NO_DATA" });
assert.equal((await viaSocket).status, "NO_DATA");
assert.equal(socket.scheduled.size, 0);

const missing = waiterContext(async () => { throw new ApiError(404); });
const rejected = assert.rejects(missing.wait("job-a"), /backend no longer has this job/);
await missing.tick();
await rejected;
assert.equal(missing.scheduled.size, 0);
console.log("Batch retains created jobs through subscription/network failures and recovers confirmed results.");

function batchHarness({ count = 23, fail = [1, 6, 11, 21], retryFail = [], retryThrow = [], runnerOfflineAtRetry = false,
  offlinePrimaryAt = null, cancelledPrimaryAt = null, reconnectingPrimaryAt = null,
  stopAtRetry = false, restored = null } = {}) {
  const scenarios = Array.from({ length: count }, (_, index) => ({
    name: `Case ${index + 1}`,
    filters: { states: [`State ${index}`], rtos: [`RTO ${index}`], reportYear: '2026', fuels: ['PURE EV'] },
  }));
  const plan = { year: 2026, scenarios };
  const calls = [], states = [], outcomes = [];
  const recoveryRef = { current: restored };
  const logRef = { current: restored?.log || [] };
  const stopRef = { current: false };
  let online = !runnerOfflineAtRetry && offlinePrimaryAt === null;
  let stopRetry = stopAtRetry;
  let cancelPrimary = cancelledPrimaryAt !== null;
  let reconnectPrimary = reconnectingPrimaryAt !== null;
  const context = {
    currentReportYear: () => 2026, updateMatrixYear: (value) => value,
    matrixOfficeKey: scenario => `${scenario.filters.states[0].toLowerCase()}\u0000${scenario.filters.rtos[0].toLowerCase()}`,
    matrixPlan: plan, scenarios, crypto: { randomUUID: () => 'session-original' },
    batchRunningRef: { current: false }, batchLoopStartedRef: { current: false },
    batchRecoveryRef: recoveryRef, batchLogRef: logRef, batchStopRef: stopRef,
    failedAtIndexRef: { current: null }, latestJobRef: { current: null },
    AUTO_RETRY_CHECKPOINT_SIZE: 10, MAX_AUTO_RETRY_ATTEMPTS: 1,
    persistentState: { setItem: noop, removeItem: noop }, ACTIVE_JOB_STORAGE_KEY: 'active',
    setBatchRunning: noop, setBatchTimings: noop, setBatchStartedAt: noop, setBatchFinishedAt: noop,
    setCurrentFilterStartedAt: noop, setBatchActiveElapsedMs: noop, setBatchActiveSegmentStartedAt: noop,
    setBatchStatus: (status) => states.push(status), setBatchLog: noop, setFailedAtIndex: noop,
    setError: noop, setNotice: noop, setReportsTrigger: noop, logRunOutcome: (outcome) => outcomes.push(outcome),
    writeBatchRecovery: (value) => { recoveryRef.current = value; },
    updateBatchRecovery: (patch) => { recoveryRef.current = { ...recoveryRef.current, ...patch }; },
    updateBatchProgress: (progress) => { recoveryRef.current = { ...recoveryRef.current, progress }; },
    pickAvailableRunnerWithRetry: async () => {
      if (recoveryRef.current?.retryIndex != null && !online) return null;
      if (recoveryRef.current?.retryIndex == null && recoveryRef.current?.currentIndex === offlinePrimaryAt && !online) return null;
      return 'runner';
    },
    runOneScenarioJob: async (runner, filters, name, sessionId, retryOfJobId) => {
      const index = scenarios.findIndex((scenario) => scenario.name === name);
      const isRetry = Boolean(retryOfJobId);
      calls.push({ index, filters, sessionId, retryOfJobId });
      if (!isRetry && index === reconnectingPrimaryAt && reconnectPrimary) {
        reconnectPrimary = false;
        throw new Error('Runner is reconnecting.');
      }
      if (!isRetry && index === cancelledPrimaryAt && cancelPrimary) {
        cancelPrimary = false;
        return {id: `cancelled-${index}`, status: 'CANCELLED'};
      }
      if (isRetry && retryThrow.includes(index)) throw new Error('API unavailable while creating retry');
      const status = isRetry
        ? retryFail.includes(index) ? 'FAILED' : index === 6 ? 'NO_DATA' : 'COMPLETED'
        : fail.includes(index) ? 'FAILED' : 'COMPLETED';
      if (isRetry && stopRetry) {
        stopRetry = false;
        stopRef.current = true;
        return { id: `stopped-${index}`, status: 'CANCELLED' };
      }
      const result = { id: `${isRetry ? 'retry' : 'original'}-${index}`, status, filters,
        sessionId, retryOfJobId, updatedAt: new Date().toISOString(),
        ...(['COMPLETED', 'NO_DATA'].includes(status) ? {mainReportSavedAt: '2026-10-03T01:00:00.000Z',
          mainReportSummary: {parsedRows: status === 'NO_DATA' ? 0 : 3}} : {})};
      context.latestJobRef.current = result;
      return result;
    },
    waitForExistingJob: async (id) => { calls.push({ restoredJobId: id }); return { id, status: 'COMPLETED' }; },
  };
  const run = loadFunction('runScenarioQueue', 'stopBatch', context);
  return { context, calls, states, outcomes, plan, recoveryRef, logRef,
    online: () => { online = true; },
    run: (options) => run(scenarios, options),
  };
}
const batch = batchHarness({ retryFail: [1] });
await batch.run();
assert.deepEqual(batch.calls.map(({ index }) => index), [
  ...Array.from({ length: 10 }, (_, i) => i), 1, 6,
  ...Array.from({ length: 10 }, (_, i) => i + 10), 11,
  20, 21, 22, 21,
], 'retry only the failed cases in the completed group before starting the next group');
assert.equal(batch.logRef.current.length, 23, 'retries replace the case result, without increasing case count');
assert.equal(batch.logRef.current.filter(({ status }) => status === 'ok').length, 21);
assert.equal(batch.logRef.current.filter(({ status }) => status === 'empty').length, 1);
assert.equal(batch.logRef.current.filter(({ status }) => status === 'error').length, 1);
assert.equal(batch.logRef.current.find(({status}) => status === 'ok').savedAt, '2026-10-03T01:00:00.000Z');
assert.equal(batch.logRef.current.find(({status}) => status === 'ok').rowCount, 3);
assert.equal(batch.logRef.current.find(({status}) => status === 'error').savedAt, undefined);
assert.equal(batch.recoveryRef.current.progress.done, 23);
assert.equal(batch.recoveryRef.current.status, 'completed_with_errors');
assert.equal(batch.outcomes.filter(entry => entry.status === 'failed').length, 5,
  'the error log retains every original failure and failed retry');
assert.ok(batch.outcomes.some(entry => entry.status === 'completed' && entry.filters.rtos[0] === 'RTO 11'),
  'successful retries send an exact-office recovery outcome to the error history');
const failedCreation = batchHarness({count: 10, fail: [9], retryThrow: [9]});
await failedCreation.run();
const recordedFailures = failedCreation.outcomes.filter(entry => entry.status === 'failed');
assert.equal(recordedFailures.length, 2);
assert.notEqual(recordedFailures[0].id, recordedFailures[1].id,
  'retry creation failure must be logged separately from the original failed job');
assert.equal(recordedFailures[1].jobId, undefined,
  'a failed retry creation must not claim the previous job identity');
for (const call of batch.calls.filter(({ retryOfJobId }) => retryOfJobId)) {
  assert.equal(call.retryOfJobId, `original-${call.index}`);
  assert.equal(call.sessionId, 'session-original');
  assert.deepEqual(call.filters, batch.plan.scenarios[call.index].filters);
}

const offline = batchHarness({ runnerOfflineAtRetry: true });
await offline.run();
assert.equal(offline.calls.length, 10, 'never move to case 11 before pending checkpoint retries');
assert.equal(offline.recoveryRef.current.status, 'stopped');
offline.online();
await offline.run({ clearLog: false, resumeState: { ...offline.recoveryRef.current, stopRequested: false } });
assert.equal(offline.calls[10].index, 1);
assert.equal(offline.calls[11].index, 6);
assert.equal(offline.calls[12].index, 10);
assert.equal(offline.recoveryRef.current.status, 'completed');

const stopped = batchHarness({ stopAtRetry: true });
await stopped.run();
assert.equal(stopped.logRef.current.find(({ index }) => index === 1).jobId, 'original-1',
  'cancelling a retry retains the original failed case without adding another error');
assert.equal(stopped.recoveryRef.current.retryQueueIndices[0], 1);
await stopped.run({ clearLog: false, resumeState: { ...stopped.recoveryRef.current, stopRequested: false } });
assert.equal(stopped.calls[11].retryOfJobId, 'original-1', 'continue the interrupted retry in the same case');
assert.equal(stopped.recoveryRef.current.status, 'completed');

const offlinePrimary = batchHarness({count: 3, fail: [], offlinePrimaryAt: 1});
await offlinePrimary.run();
assert.deepEqual(offlinePrimary.calls.map(({index}) => index), [0]);
assert.equal(offlinePrimary.recoveryRef.current.status, 'stopped');
assert.equal(offlinePrimary.recoveryRef.current.nextPosition, 1);
assert.equal(offlinePrimary.outcomes.filter(entry => entry.status === 'failed').length, 0);
offlinePrimary.online();
await offlinePrimary.run({clearLog: false, resumeState: {...offlinePrimary.recoveryRef.current, stopRequested: false}});
assert.deepEqual(offlinePrimary.calls.map(({index}) => index), [0, 1, 2],
  'an offline runner resumes at the case that was waiting');

const cancelledPrimary = batchHarness({count: 3, fail: [], cancelledPrimaryAt: 1});
await cancelledPrimary.run();
assert.equal(cancelledPrimary.recoveryRef.current.status, 'stopped');
assert.equal(cancelledPrimary.recoveryRef.current.nextPosition, 1);
assert.equal(cancelledPrimary.outcomes.filter(entry => entry.status === 'failed').length, 0);
await cancelledPrimary.run({clearLog: false, resumeState: {...cancelledPrimary.recoveryRef.current, stopRequested: false}});
assert.deepEqual(cancelledPrimary.calls.map(({index}) => index), [0, 1, 1, 2],
  'a cancelled job is rerun at the same case without marking it failed');

const reconnectingPrimary = batchHarness({count: 3, fail: [], reconnectingPrimaryAt: 1});
await reconnectingPrimary.run();
assert.equal(reconnectingPrimary.recoveryRef.current.status, 'stopped');
assert.equal(reconnectingPrimary.recoveryRef.current.nextPosition, 1);
assert.equal(reconnectingPrimary.outcomes.filter(entry => entry.status === 'failed').length, 0);
await reconnectingPrimary.run({clearLog: false, resumeState: {...reconnectingPrimary.recoveryRef.current, stopRequested: false}});
assert.deepEqual(reconnectingPrimary.calls.map(({index}) => index), [0, 1, 1, 2],
  'a reconnecting runner leaves the same case pending until it is available');

const manual = batchHarness({ retryFail: [1] });
await manual.run();
const beforeManual = manual.calls.length;
await manual.run({ clearLog: false, selectedIndices: [1], sessionIdOverride: 'session-original' });
assert.equal(manual.calls[beforeManual].retryOfJobId, 'retry-1');
assert.equal(manual.calls[beforeManual].sessionId, 'session-original');
assert.equal(manual.logRef.current.length, 23, 'manual retry also preserves other case results');

const resumedRetry = batchHarness();
await resumedRetry.run();
const recovery = { ...resumedRetry.recoveryRef.current, status: 'running', nextPosition: 10,
  progress: { done: 10, total: 23, current: 'Retrying' }, lastRetryCheckpoint: 10,
  retryIndex: 1, retryQueueIndices: [1], activeJobId: 'active-retry-1',
  log: resumedRetry.logRef.current.filter(({ index }) => index < 10)
    .map((entry) => entry.index === 1 ? { ...entry, status: 'error', jobId: 'original-1', autoRetryCount: 0 } : entry) };
const reload = batchHarness({ restored: recovery });
await reload.run({ clearLog: false, resumeState: recovery });
assert.equal(reload.calls[0].restoredJobId, 'active-retry-1', 'reload waits for an already-created retry');
assert.equal(reload.calls[1].index, 10);
assert.equal(reload.logRef.current.find(({ index }) => index === 1).status, 'ok');
console.log('10-case checkpoint order, final group, exact retry identity, counts, manual retry, offline/stop/reload recovery passed.');

const partialRecovery = { ...recovery, nextPosition: 8, lastRetryCheckpoint: 0,
  retryIndex: null, retryQueueIndices: [], activeJobId: null,
  progress: { done: 8, total: 23, current: 'Case 9' },
  log: recovery.log.filter(({ index }) => index < 8) };
const partial = batchHarness({ restored: partialRecovery });
await partial.run({ clearLog: false, resumeState: partialRecovery });
assert.deepEqual(partial.calls.slice(0, 4).map(({ index }) => index), [8, 9, 1, 10],
  'a mid-group reload completes cases 9 and 10 before auditing that group');

const boundaryRecovery = { ...partialRecovery, nextPosition: 10,
  progress: { done: 10, total: 23, current: 'Checkpoint' }, log: recovery.log };
const boundary = batchHarness({ restored: boundaryRecovery });
await boundary.run({ clearLog: false, resumeState: boundaryRecovery });
assert.deepEqual(boundary.calls.slice(0, 2).map(({ index }) => index), [1, 10],
  'reload at the boundary performs a pending checkpoint before case 11');

const savedPlan = {year: 2026, scenarios: [
  {name: 'Office A', filters: {states: ['State A'], rtos: ['RTO A']}},
  {name: 'Office B', filters: {states: ['State B'], rtos: ['RTO B']}},
]};
const savedRun = {status: 'stopped', year: 2026, queueIndices: [0, 1],
  queueOfficeKeys: ['state a\u0000rto a', 'state b\u0000rto b'],
  progress: {done: 1, total: 2}, log: [], stopRequested: false};
const continueCalls = [], continueErrors = [];
const continueContext = {
  batchRecoveryRef: {current: savedRun}, batchRunningRef: {current: false},
  matrixPlan: savedPlan, currentReportYear: () => 2026,
  matrixOfficeKey: scenario => `${scenario.filters.states[0].toLowerCase()}\u0000${scenario.filters.rtos[0].toLowerCase()}`,
  setError: message => continueErrors.push(message),
  runScenarioQueue: async (queue, options) => continueCalls.push({queue, options}),
};
const continueSaved = loadFunction('continueStoppedBatch', 'continueUncoveredReports', continueContext);
await continueSaved();
assert.equal(continueCalls.length, 1);
assert.equal(continueCalls[0].options.resumeState.queueIndices, savedRun.queueIndices,
  'Continue keeps the original full queue and pending checkpoint state');
assert.equal(continueCalls[0].options.clearLog, false);
continueContext.matrixPlan = {...savedPlan, scenarios: [...savedPlan.scenarios].reverse()};
await continueSaved();
assert.equal(continueCalls.length, 1, 'a changed office ordering cannot silently reassign saved indices');
assert.match(continueErrors.at(-1), /State\/RTO list changed/);

let fullRestarts = 0;
const restartContext = {batchRecoveryRef: {current: savedRun}, runAllScenarios: async () => {fullRestarts++;}};
const restartAll = loadFunction('restartStoppedBatch', 'runAllScenarios', restartContext);
await restartAll();
assert.equal(fullRestarts, 1, 'Restart uses the complete refreshed State/RTO matrix');
restartContext.batchRecoveryRef.current = {...savedRun, status: 'running'};
await restartAll();
assert.equal(fullRestarts, 1, 'Restart cannot replace an active session');

const controlSource = readFileSync(new URL('../src/components/MatrixRunner.tsx', import.meta.url), 'utf8');
const controlModule = {exports: {}};
const jsx = (type, props) => ({type, props});
const controlsCompiled = ts.transpileModule(controlSource, {compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
}}).outputText;
runInNewContext(controlsCompiled, {module: controlModule, exports: controlModule.exports,
  require: name => name === 'react' ? {useState: value => [value, noop], useEffect: noop}
    : name === 'react/jsx-runtime' ? {jsx, jsxs: jsx}
    : name === '../matrix-plan' ? {currentReportYear: () => 2026}
    : name === '../batch-timing' ? {estimateBatchTiming: () => ({remainingMs: null})}
    : name === './CompletedTasks' ? {CompletedTasks: noop}
    : (() => {throw new Error(`Unexpected import ${name}`);})(),
});
function visit(node, buttons = []) {
  if (Array.isArray(node)) node.forEach(child => visit(child, buttons));
  else if (node && typeof node === 'object') {
    if (node.type === 'button') buttons.push(node);
    visit(node.props?.children, buttons);
  }
  return buttons;
}
function label(node) {
  if (Array.isArray(node)) return node.map(label).join('');
  if (node && typeof node === 'object') return label(node.props?.children);
  return node == null || typeof node === 'boolean' ? '' : String(node);
}
let continued = 0, restarted = 0, retried = 0;
const controlProps = {plan: {...savedPlan, states: ['State A', 'State B']}, scenarios: savedPlan.scenarios,
  loading: false, loadingMessage: '', onRunAll: noop, onRunFrom: noop, onRunOne: noop,
  onRetryFailed: () => {retried++;}, onContinueStopped: () => {continued++;},
  onRestartAll: () => {restarted++;}, onStop: noop, running: false,
  progress: {done: 1, total: 2, current: 'Office B'}, batchStatus: 'stopped',
  startedAt: null, finishedAt: null, timings: [], currentFilterStartedAt: null,
  activeElapsedMs: 0, activeSegmentStartedAt: null, log: [{index: 0, status: 'error'}],
  failedAtIndex: 0, pendingRetries: 1, disabled: false};
const stoppedButtons = visit(controlModule.exports.MatrixRunner(controlProps));
assert.ok(stoppedButtons.some(button => label(button) === 'Continue saved session'));
assert.ok(stoppedButtons.some(button => label(button) === 'Restart all offices from start'));
assert.ok(!stoppedButtons.some(button => /Retry .*failed reports/.test(label(button))),
  'stopped sessions must not offer a separate retry that overwrites the saved queue');
stoppedButtons.find(button => label(button) === 'Continue saved session').props.onClick();
stoppedButtons.find(button => label(button) === 'Restart all offices from start').props.onClick();
assert.deepEqual([continued, restarted, retried], [1, 1, 0]);

const savedTasksSource = readFileSync(new URL('../src/components/CompletedTasks.tsx', import.meta.url), 'utf8');
function renderSavedTasks(log, page = 0) {
  const module = {exports: {}};
  const compiled = ts.transpileModule(savedTasksSource, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  }}).outputText;
  runInNewContext(compiled, {module, exports: module.exports,
    require: name => name === 'react' ? {useState: () => [page, noop]} : {jsx, jsxs: jsx}});
  return module.exports.CompletedTasks({log, scenarios: savedPlan.scenarios});
}
const savedTaskLog = Array.from({length: 12}, (_, index) => ({index, jobId: `saved-${index}`,
  state: 'State A', rto: `Saved RTO ${index}`, status: index === 0 ? 'empty' : 'ok',
  savedAt: `2026-10-03T01:00:${String(index).padStart(2, '0')}.000Z`}));
savedTaskLog.push({index: 50, jobId: 'failed-50', state: 'State A', rto: 'Failed office', status: 'error'});
savedTaskLog.push({index: 51, state: 'State A', rto: 'Unconfirmed office', status: 'ok'});
const recentSaved = renderSavedTasks(savedTaskLog);
assert.match(label(recentSaved), /12 saved/);
assert.ok(!label(recentSaved).includes('Failed office'));
assert.ok(!label(recentSaved).includes('Unconfirmed office'));
assert.ok(!label(recentSaved).includes('Saved RTO 0'), 'latest page is limited to ten saved tasks');
const olderSaved = renderSavedTasks(savedTaskLog, 1);
assert.match(label(olderSaved), /Saved RTO 0/);
assert.match(label(olderSaved), /No record found · saved/);
assert.match(label(olderSaved), /03\/10\/2026, 08:00:00/);
assert.match(label(renderSavedTasks([], 9)), /Tasks appear here after/);
console.log('Saved task list excludes failures, retains no-data results, paginates and shows full Vietnam timestamps.');
