import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

function moduleUrl(file, dependencies = {}) {
  let source = readFileSync(new URL(file, import.meta.url), 'utf8');
  for (const [name, url] of Object.entries(dependencies)) source = source.replace(`'${name}'`, `'${url}'`);
  const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext}}).outputText;
  return `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`;
}
const {observeScheduleTiming, estimateScheduleTiming, formatScheduleDuration} = await import(
  moduleUrl('../src/schedule-timing.ts', {'./batch-timing': moduleUrl('../src/batch-timing.ts')}));
const {formatScheduledTime} = await import(moduleUrl('../src/run-schedules.ts'));
const start = Date.parse('2026-10-07T16:18:00Z');
const schedule = {status:'RUNNING', sessionId:'run-1', lastRunAt:new Date(start).toISOString(),
  total:100, done:20, workerCount:7};
let observation = observeScheduleTiming(null, schedule, start + 120_000);
const initial = estimateScheduleTiming(schedule, observation, start + 120_000);
assert.equal(initial.remainingMs, 480_000, 'Reload uses the actual start, rather than the planned schedule time.');
assert.equal(initial.casesPerMinute, 10);
assert.equal(initial.finishesAt, '2026-10-07T16:28:00.000Z');
assert.equal(formatScheduledTime(initial.finishesAt), '07 Oct 2026, 23:28', 'Finish uses Vietnam time.');
assert.equal(estimateScheduleTiming({...schedule, workerCount:1}, observation, start + 120_000).remainingMs,
  initial.remainingMs, 'Observed system throughput already accounts for parallel workers.');
assert.equal(estimateScheduleTiming(schedule, null, start + 120_000).remainingMs, initial.remainingMs);
assert.equal(estimateScheduleTiming({...schedule, done:0}, null, start + 120_000).remainingMs, null);
assert.equal(estimateScheduleTiming({...schedule, lastRunAt:null}, null, start + 120_000).remainingMs, null);
assert.equal(estimateScheduleTiming({...schedule, lastRunAt:'invalid'}, null, start + 120_000).finishesAt, null);
assert.equal(estimateScheduleTiming(schedule, null, start - 1).remainingMs, null);
for (const status of ['WAITING', 'PREPARING', 'COMPLETED', 'COMPLETED_WITH_ERRORS', 'STOPPED', 'ERROR']) {
  assert.equal(estimateScheduleTiming({...schedule, status}, observation, start + 120_000).remainingMs, null);
}
const stale = estimateScheduleTiming(schedule, observation, start + 136_000);
assert.equal(stale.stale, true);
assert.equal(stale.finishesAt, null, 'A lost polling connection hides the outdated forecast.');
observation = observeScheduleTiming(observation, schedule, start + 241_000);
assert.equal(estimateScheduleTiming(schedule, observation, start + 241_000).stalled, true,
  'Fresh polls without completions for two minutes hide the estimate.');
assert.equal(observation.samples.length, 1, 'Unchanged polling data is not a completion checkpoint.');
const resumed = {...schedule, done:26};
observation = observeScheduleTiming(observation, resumed, start + 245_000);
const slowed = estimateScheduleTiming(resumed, observation, start + 245_000);
assert.ok(slowed.remainingMs > initial.remainingMs, 'The recent output window follows slower processing.');
assert.equal(slowed.stalled, false);
const newRun = {...schedule, sessionId:'run-2', lastRunAt:new Date(start + 300_000).toISOString(), done:1};
assert.equal(estimateScheduleTiming(newRun, observation, start + 310_000).remainingMs, 990_000);
observation = observeScheduleTiming(observation, newRun, start + 310_000);
assert.equal(observation.samples.length, 1, 'Daily executions discard the previous run checkpoints.');
observation = observeScheduleTiming(observation, {...newRun, done:0}, start + 311_000);
assert.equal(observation.samples.length, 1, 'Counter rollback resets observed throughput.');
assert.equal(estimateScheduleTiming({...newRun, done:100}, null, start + 310_000).remainingMs, 0);
assert.equal(formatScheduleDuration(480_000), '8m');
assert.equal(formatScheduleDuration(3_601_000), '1h 1m');
assert.equal(formatScheduleDuration(90_000_000), '1d 1h');
const resumedClock = {...schedule, executionEpoch:3, activeElapsedMs:120_000,
  activeSegmentStartedAt:new Date(start+3_600_000).toISOString()};
const afterPause = estimateScheduleTiming(resumedClock,null,start+3_600_000);
assert.equal(afterPause.remainingMs,initial.remainingMs,'An hour paused is excluded from processing throughput and ETA.');
assert.equal(afterPause.casesPerMinute,initial.casesPerMinute);
const reset = observeScheduleTiming(observation,resumedClock,start+3_601_000);
assert.equal(reset.samples.length,1,'A resumed execution segment clears stalled previous observations.');
console.log('Schedule ETA: reload, system throughput, Vietnam finish time, slowdown, stalls, stale polls and run reset passed.');
