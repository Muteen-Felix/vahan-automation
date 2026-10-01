import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
function loadFunction(name, nextName, context) {
  const start = source.indexOf(`  async function ${name}(`);
  const end = source.indexOf(`  async function ${nextName}(`, start);
  assert.ok(start >= 0 && end > start);
  const compiled = ts.transpileModule(source.slice(start, end), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return runInNewContext(`${compiled}\n${name}`, context);
}
const created = { id: "job-a", status: "WAITING_RESULT" };
const noop = () => {};
const create = loadFunction("createJob", "submitCaptcha", {
  api: { createJob: async () => created },
  setCreating: noop, setError: noop, setNotice: noop, setCaptcha: noop,
  setJob: noop, latestJobRef: { current: null },
  localStorage: { setItem: noop }, ACTIVE_JOB_STORAGE_KEY: "test",
  batchRecoveryRef: { current: null },
  batchStopRef: { current: false },
  subscribeJob: async () => { throw new Error("operation has timed out"); },
  refreshRunners: async () => {}, isSocketTimeout: () => true,
});
assert.equal((await create("runner-a", {})).id, "job-a",
  "a successful job creation must survive a failed live subscription");

class ApiError extends Error { constructor(status) { super(); this.status = status; } }
function waiterContext(getJob) {
  const scheduled = new Map();
  let timerId = 0;
  const context = {
    api: { getJob }, ApiError,
    latestJobRef: { current: created }, terminalResolverRef: { current: null },
    setJob: noop, setCaptcha: noop, setNotice: noop, setReportsTrigger: noop,
    localStorage: { removeItem: noop }, ACTIVE_JOB_STORAGE_KEY: "test",
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
