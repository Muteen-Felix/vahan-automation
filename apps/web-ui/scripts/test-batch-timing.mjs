import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/batch-timing.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext}}).outputText;
const {estimateBatchTiming} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

assert.equal(estimateBatchTiming([], 1600, 0, null, 4000, 0, 0).remainingMs, null);
const checkpoints = Array.from({length: 100}, (_, index) => ({
  index, durationMs: index % 2 ? 3000 : 5000,
  completedCount: index + 1, activeElapsedMs: (Math.floor(index / 10) + 1) * 4000,
}));
const steady = estimateBatchTiming(checkpoints, 1600, 100, null, 40_000, 0, 0);
assert.equal(steady.pace, 'recent');
assert.equal(steady.reportsPerHour, 9000);
assert.equal(steady.remainingMs, 600_000,
  'Ten workers completing 100 cases in 40 seconds imply 10 minutes for 1,500 more cases.');
assert.equal(estimateBatchTiming(checkpoints.map((item) => ({...item, durationMs: 600_000})),
  1600, 100, null, 40_000, 0, 0).remainingMs, steady.remainingMs,
  'Individual filter durations must not affect the aggregate-throughput forecast.');
assert.equal(estimateBatchTiming(checkpoints, 1600, 100, null, 161_000, 0, 0).remainingMs, null,
  'A stalled queue must stop presenting an optimistic ETA.');
const early = estimateBatchTiming([], 10, 2, 100_000, 105_000, 40_000, 100_000);
assert.equal(early.pace, 'session');
assert.equal(early.remainingMs, 180_000, 'Initial forecast uses completed output per active wall time.');
assert.equal(estimateBatchTiming([], 10, 2, null, 0, 45_000, null).remainingMs, early.remainingMs,
  'Paused time must not change the forecast after restoring a session.');
assert.equal(estimateBatchTiming(checkpoints, 1600, 1600, null, 40_000, 0, 0).remainingMs, 0);
console.log('Aggregate throughput ETA, ten-worker pace, stalled queue and pause recovery passed.');
