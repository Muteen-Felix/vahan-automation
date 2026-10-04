import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/batch-timing.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { estimateBatchTiming } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

assert.equal(estimateBatchTiming([], 100, 0, 1000, 9000, 0, 1000).remainingMs, null);
const samples = [{ index: 0, durationMs: 10000 }, { index: 1, durationMs: 20000 }];
const active = estimateBatchTiming(samples, 10, 2, 100000, 105000, 40000, 100000);
assert.equal(active.pace, "session");
assert.equal(active.reportsPerHour, 180);
assert.equal(active.remainingMs, 155000, "session pace must account for active time and the current report");
assert.equal(estimateBatchTiming(samples, 10, 2, 100000, 130000, 40000, 100000).remainingMs, 140000,
  "an overdue current report must not make future work disappear");
assert.equal(estimateBatchTiming(samples, 10, 2, null, 105000, 40000, 100000).remainingMs, 180000);
assert.equal(estimateBatchTiming(samples, 10, 10, null, 105000, 40000, 100000).remainingMs, 0);
assert.equal(estimateBatchTiming([], 3, 0, null, 105000, 0, 105000).remainingMs, null,
  "a new run without completed reports has no measurable throughput");
assert.deepEqual(estimateBatchTiming(JSON.parse(JSON.stringify(samples)), 10, 2, 100000, 105000, 40000, 100000), active,
  "restored run samples must preserve the estimate");
const recentSamples = [10, 20, 30, 40, 50].map((activeElapsedMs, offset) => ({
  index: offset,
  durationMs: 10000,
  completedCount: offset + 1,
  activeElapsedMs: activeElapsedMs * 1000,
}));
const recent = estimateBatchTiming(recentSamples, 10, 5, 50000, 52000, 50000, 50000);
assert.equal(recent.pace, "recent");
assert.equal(recent.reportsPerHour, 360);
assert.equal(recent.remainingMs, 48000, "recent progress checkpoints must take over after five completed reports");
console.log("Batch session throughput, recent pace, ETA and recovery passed.");
