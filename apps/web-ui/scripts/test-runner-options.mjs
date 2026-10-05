import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/services/runner-options.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ESNext}}).outputText.replaceAll('export ', '');
function fixture(ack, {advanceTimers = false} = {}) {
  let now = 0, attempts = 0;
  const timers = new Map(), progress = [];
  const socket = {connected: true, get volatile() {return this;}, timeout(ms) {
    assert.equal(ms, 125_000); return this;
  }, emitWithAck: async (event, payload) => {
    attempts++;
    assert.equal(event, 'ui:runner-options');
    assert.equal(payload.runnerId, 'fixture-worker');
    return ack(attempts);
  }};
  const context = {Date: {now: () => now}, setInterval: callback => {timers.set(1, callback); return 1;},
    clearInterval: id => timers.delete(id), setTimeout: (callback, ms) => {if (advanceTimers) now += ms; queueMicrotask(callback);}};
  const request = runInNewContext(`${compiled}\nrequestRunnerOptions`, context);
  return {socket, timers, progress, attempts: () => attempts,
    tick: seconds => {now = seconds * 1000; timers.get(1)?.();},
    run: () => request(socket, 'fixture-worker', {type: 'GET_ALL_OPTIONS'}, 'Checking fixed filter options…', message => progress.push(message))};
}
let acknowledge;
const delayed = fixture(() => new Promise(resolve => {acknowledge = resolve;}));
const pending = delayed.run();
delayed.tick(40);
assert.match(delayed.progress.at(-1), /attempt 1\/3 · 40s \/ 125s/);
acknowledge({ok: true, options: {states: ['Fixture State']}});
assert.deepEqual(await pending, {states: ['Fixture State']}, 'a response after the old 20-second deadline succeeds');
assert.equal(delayed.timers.size, 0);

const offline = fixture(() => {throw new Error('must not send');});
offline.socket.connected = false;
await assert.rejects(offline.run(), /Connection lost/);
assert.equal(offline.attempts(), 0);

const retries = fixture(attempt => attempt < 3 ? {ok: false, error: 'VAHAN_OPTIONS_TIMEOUT'} : {ok: true, options: []});
assert.deepEqual(await retries.run(), []);
assert.equal(retries.attempts(), 3);
assert.equal(retries.timers.size, 0);

const exhausted = fixture(() => {throw new Error('operation has timed out');});
await assert.rejects(exhausted.run(), /timed out/);
assert.equal(exhausted.attempts(), 3);
assert.equal(exhausted.timers.size, 0);

const auth = fixture(() => ({ok: false, error: 'VAHAN_AUTH_REQUIRED: operator authentication is required.'}));
await assert.rejects(auth.run(), /VAHAN_AUTH_REQUIRED/);
assert.equal(auth.attempts(), 1);
assert.equal(auth.timers.size, 0);

const disconnect = fixture(() => {disconnect.socket.connected = false; throw new Error('connection closed');});
await assert.rejects(disconnect.run(), /Connection lost/);
assert.equal(disconnect.attempts(), 1, 'preparation must not replay commands across a disconnect');
assert.equal(disconnect.timers.size, 0);

const busy = fixture(attempt => attempt <= 8 ? {ok: false, error: 'Worker is busy.', code: 'RUNNER_BUSY', retryAfterMs: 1000}
  : {ok: true, options: ['Ready']}, {advanceTimers: true});
assert.deepEqual(await busy.run(), ['Ready']);
assert.equal(busy.attempts(), 9, 'busy replies must not exhaust the three real options attempts');
assert.ok(busy.progress.some(message => message.startsWith('Waiting for the browser worker')));
assert.equal(busy.timers.size, 0);
const busyForever = fixture(() => ({ok: false, error: 'Worker is busy.'}), {advanceTimers: true});
await assert.rejects(busyForever.run(), /RUNNER_BUSY_TIMEOUT/);
assert.equal(busyForever.attempts(), 126);
assert.equal(busyForever.timers.size, 0);

const runner = readFileSync(new URL('../../browser-runner/runner.mjs', import.meta.url), 'utf8');
const api = readFileSync(new URL('../../api-server/app/realtime/ui_events.py', import.meta.url), 'utf8');
const runnerTimeout = Number(runner.match(/const OPTIONS_TIMEOUT = ([\d_]+)/)[1].replaceAll('_', ''));
const apiTimeout = Number(api.match(/RUNNER_OPTIONS_TIMEOUT_SECONDS = (\d+)/)[1]) * 1000;
const uiTimeout = Number(source.match(/RUNNER_OPTIONS_ACK_TIMEOUT_MS = ([\d_]+)/)[1].replaceAll('_', ''));
assert.ok(runnerTimeout < apiTimeout && apiTimeout < uiTimeout, 'each layer must outlast the underlying operation');
assert.ok(api.includes('timeout=RUNNER_OPTIONS_TIMEOUT_SECONDS'));
console.log('Options UI checks passed: delayed acknowledgement, live progress, offline connection, recovery, bounded retries, authentication and aligned deadlines.');
