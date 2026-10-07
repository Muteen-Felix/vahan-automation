import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const start = source.indexOf('  async function runSharedScenarioQueue(');
const end = source.indexOf('  async function runParallelScenarioQueue(', start);
const compiled = ts.transpileModule(source.slice(start, end), {
  compilerOptions: {target: ts.ScriptTarget.ES2022},
}).outputText;
const noop = () => {};
async function verify(workerCount, year = 2026) {
const tasks = Array.from({length: 60}, (_, position) => ({position, name: `Case ${position}`,
  status: 'PENDING', attempts: 0, failures: 0, runnerId: null, jobId: null, error: null}));
const scenarios = tasks.map(task => ({name: task.name, filters: {states: ['State'], rtos: [`RTO ${task.position}`]}}));
const jobs = new Map();
const recovery = {current: null}, log = {current: []};
const active = new Set(), claimed = new Set(), workerCounts = new Map();
let peak = 0, restReads = 0;
const errors = [];
const context = {
  currentReportYear: () => 2026, isReportYear: year => year >= 1900 && year <= 2026, TARGET_WORKER_COUNT: 10, selectedWorkerCount: workerCount,
  compareRunnerIds: (a, b) => a.localeCompare(b, undefined, {numeric: true}),
  matrixOfficeKey: scenario => scenario.name,
  runnersRef: {current: Array.from({length: 10}, (_, n) => ({id: `playwright-${n + 1}`, status: 'ONLINE', source: 'new'}))},
  ensureDockerWorkers: async () => {}, refreshRunners: async () => {}, batchRunningRef: {current: false}, batchStopRef: {current: false},
  batchLoopStartedRef: {current: false}, batchRecoveryRef: recovery, batchLogRef: log,
  persistentState: {removeItem: noop}, ACTIVE_JOB_STORAGE_KEY: 'active',
  crypto: {randomUUID: () => 'shared-fixture'},
  writeBatchRecovery: value => {recovery.current = value;}, logRunOutcome: noop, rememberJob: noop,
  setError: message => errors.push(message), setNotice: noop, setRunSettings: noop,
  sleep: () => new Promise(resolve => setTimeout(resolve, 1)),
  subscribeJob: async id => {
    if (id === 'job-7') throw new Error('Lost initial subscription');
    return jobs.get(id);
  },
  waitForExistingJob: async id => {
    const job = jobs.get(id);
    await new Promise(resolve => setTimeout(resolve, job.runnerId === 'playwright-10' ? 20 : 1));
    active.delete(job.runnerId);
    job.status = Number(id.slice(4)) % 3 === 0 ? 'NO_DATA' : 'COMPLETED';
    return {...job, mainReportSavedAt: new Date().toISOString(), mainReportSummary: {parsedRows: 3}};
  },
  api: {
    startBatchQueue: async (_id, cases, maxWorkers) => {
      assert.equal(maxWorkers, workerCount);
      return {status: 'RUNNING', maxWorkers, tasks: tasks.map(task => ({...task}))};
    },
    batchQueue: async () => ({status: 'RUNNING', tasks: tasks.map(task => ({...task}))}),
    claimBatchTask: async (_session, runnerId) => {
      assert.ok(!active.has(runnerId), 'one worker must finish its prior job before taking another');
      const task = tasks.find(task => task.status === 'PENDING');
      if (!task) return {type: active.size ? 'waiting' : 'done'};
      assert.ok(!claimed.has(task.position), 'a task must not be claimed twice');
      claimed.add(task.position); active.add(runnerId); peak = Math.max(peak, active.size);
      workerCounts.set(runnerId, (workerCounts.get(runnerId) || 0) + 1);
      Object.assign(task, {status: 'PROCESSING', runnerId, jobId: `job-${task.position}`, attempts: 1});
      jobs.set(task.jobId, {id: task.jobId, runnerId, status: 'ASSIGNED'});
      return {type: 'assigned', task: {...task}, jobId: task.jobId};
    },
    getJob: async id => {restReads++; return jobs.get(id);},
    settleBatchTask: async (_session, position) => {
      const task = tasks[position]; task.status = jobs.get(task.jobId).status;
      return {...task};
    },
  },
};
for (const name of ['setBatchLog', 'setParallelCaptchas', 'setBatchRunning', 'setBatchStatus',
  'setBatchStartedAt', 'setBatchFinishedAt', 'setBatchActiveElapsedMs', 'setBatchActiveSegmentStartedAt',
  'setBatchProgress', 'setCurrentFilterStartedAt', 'setFailedAtIndex', 'setBatchTimings', 'setJob', 'setReportsTrigger']) context[name] = noop;
const run = runInNewContext(`${compiled}\nrunSharedScenarioQueue`, context);
await run({year, scenarios});
assert.deepEqual(errors, []);
assert.equal(peak, workerCount, 'only the selected number of workers can run concurrently');
assert.equal(workerCounts.size, workerCount);
assert.equal(recovery.current.year, year);
assert.equal(claimed.size, 60);
assert.equal(log.current.length, 60);
assert.equal(restReads, 1, 'use the subscription snapshot and REST only after a lost subscription');
if (workerCount === 10) assert.ok(workerCounts.get('playwright-10') < Math.max(...workerCounts.values()), 'fast workers take more cases');
assert.equal(recovery.current.status, 'completed');
assert.equal(recovery.current.progress.done, 60);
}
for (const count of [1, 5, 10]) await verify(count, 2024);
console.log('Shared queue: configurable 1/5/10 workers, historical year, unique claims and complete progress passed.');
