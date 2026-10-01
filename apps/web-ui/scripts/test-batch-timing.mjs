import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/batch-timing.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { estimateBatchTiming } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

assert.equal(estimateBatchTiming([], 100, 0, 1000, 9000).remainingMs, null);
const samples = [{ index: 0, durationMs: 10000 }, { index: 1, durationMs: 20000 }];
const active = estimateBatchTiming(samples, 10, 2, 100000, 105000);
assert.equal(active.averageMs, 15000);
assert.equal(active.remainingMs, 115000, "ETA must subtract the current filter's elapsed time");
assert.equal(active.sampleCount, 2);
assert.equal(estimateBatchTiming(samples, 10, 2, 100000, 130000).remainingMs, 105000,
  "a slow active filter must not produce negative remaining time");
assert.equal(estimateBatchTiming(samples, 10, 2, null, 105000).remainingMs, 120000);
assert.equal(estimateBatchTiming(samples, 10, 10, null, 105000).remainingMs, 0);
assert.equal(estimateBatchTiming([], 3, 0, null, 105000).averageMs, null,
  "a new retry run must not reuse old run samples");
assert.deepEqual(estimateBatchTiming(JSON.parse(JSON.stringify(samples)), 10, 2, 100000, 105000), active,
  "restored run samples must preserve the estimate");
assert.equal(estimateBatchTiming([...samples, { index: 2, durationMs: NaN }], 10, 2, null, 0).averageMs, 15000);
console.log("Batch average, ETA, slow filters, retry runs and recovery passed.");
