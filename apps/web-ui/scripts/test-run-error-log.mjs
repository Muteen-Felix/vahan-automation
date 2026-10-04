import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/run-error-log.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS}}).outputText;
const exports = {};
runInNewContext(compiled, {exports});
const {recordRunOutcome, jobRunOutcome, readRunErrors, describeRunError, groupRunErrors, formatRunErrors, MAX_RUN_ERRORS} = exports;
const filters = {states: ['Assam'], rtos: ['Office AS25']};
const failure = {id: 'job:original', jobId: 'original', sessionId: 'session-1', name: 'Report AS25', filters,
  status: 'failed', detail: 'RTO_OPTIONS_TIMEOUT: options did not load', occurredAt: '2026-10-02T10:00:00Z'};
let entries = recordRunOutcome([], failure);
assert.equal(entries.length, 1);
assert.equal(recordRunOutcome(entries, failure), entries, 'socket replay must not duplicate failures');
assert.equal(recordRunOutcome(entries, {...failure, id: 'batch:case-1'}), entries, 'batch and socket logs share a job identity');
const restored = recordRunOutcome(recordRunOutcome([], {...failure, occurredAt: null}), failure);
assert.equal(restored.length, 1);
assert.equal(restored[0].occurredAt, failure.occurredAt, 'legacy errors recover time from the original job without duplication');
assert.equal(recordRunOutcome(entries, {...failure, id: 'ok', status: 'completed', sessionId: 'other-session'}), entries);
assert.equal(recordRunOutcome(entries, {...failure, id: 'ok', status: 'completed', filters: {...filters, rtos: ['Other office']}}), entries);
assert.equal(recordRunOutcome(entries, {...failure, id: 'older-result', status: 'completed', occurredAt: '2026-10-02T09:00:00Z'}), entries);
entries = recordRunOutcome(entries, {...failure, id: 'retry:ok', jobId: 'retry', status: 'completed', occurredAt: '2026-10-02T10:01:00Z'});
assert.equal(entries[0].resolution, 'completed');
assert.equal(entries[0].detail, failure.detail, 'successful retry preserves the original error');
assert.equal(entries[0].occurredAt, failure.occurredAt);
assert.equal(recordRunOutcome(entries, failure), entries, 'late failure replay cannot reopen a resolved error');
entries = recordRunOutcome(entries, {...failure, id: 'job:retry-failed', jobId: 'retry-failed', occurredAt: '2026-10-02T10:02:00Z'});
assert.equal(entries.length, 2, 'another failed attempt is a separate history row');
assert.equal(entries[0].resolution, null);
entries = recordRunOutcome(entries, {...failure, id: 'retry:no-data', status: 'no_data', occurredAt: '2026-10-02T10:03:00Z'});
assert.equal(entries[0].resolution, 'no_data');
assert.equal(entries[1].resolution, 'completed');
assert.deepEqual(JSON.parse(JSON.stringify(readRunErrors(JSON.stringify(entries)))), JSON.parse(JSON.stringify(entries)), 'account state round trip preserves recovered failures');
assert.equal(readRunErrors('{broken').length, 0);
assert.equal(readRunErrors(JSON.stringify([{status: 'failed'}])).length, 0);
const job = {id: 'job-a', sessionId: 's', scenarioName: 'A', filters, updatedAt: failure.occurredAt, error: failure.detail};
assert.equal(jobRunOutcome({...job, status: 'CANCELLED'}), null, 'user stop is not a run error');
assert.equal(jobRunOutcome({...job, status: 'WAITING_RESULT'}), null);
assert.equal(jobRunOutcome({...job, status: 'NO_DATA'}).status, 'no_data');
assert.equal(jobRunOutcome({...job, status: 'FAILED', error: 'NO_RECORD_FOUND: empty'}), null);
assert.equal(jobRunOutcome({...job, status: 'FAILED'}).detail, failure.detail);
for (const code of ['RTO_OPTIONS_TIMEOUT', 'VAHAN_RESULT_TIMEOUT', 'CAPTCHA_INVALID_LIMIT']) {
  assert.notEqual(describeRunError(code).title, 'Report error', `${code} has a specific explanation`);
}
let many = [];
for (let i = 0; i < MAX_RUN_ERRORS + 10; i++) many = recordRunOutcome(many, {...failure, id: String(i), jobId: String(i)});
assert.equal(many.length, MAX_RUN_ERRORS);
assert.equal(many[0].id, String(MAX_RUN_ERRORS + 9));
const repeated = [
  {...entries[0], detail: failure.detail, name: 'Report 1', resolution: null},
  {...entries[1], detail: `Automatic retry 1/1 failed: ${failure.detail} It will be retried automatically at the next checkpoint.`, name: 'Report 2', resolution: 'completed'},
  {...entries[0], detail: 'RTO_OPTIONS_TIMEOUT: options   did not load', name: 'Report 1'},
];
assert.equal(groupRunErrors(repeated).length, 1, 'identical messages from different offices/retries are listed once');
assert.equal(groupRunErrors([...repeated, {...entries[0], detail: 'RTO_OPTIONS_TIMEOUT: different failure'}]).length, 2,
  'same error category with a different original message must remain separate');
const copiedText = formatRunErrors(repeated);
assert.equal((copiedText.match(/Message:/g) || []).length, 1);
assert.ok(copiedText.includes('Occurrences: 3'));
assert.ok(copiedText.includes('Reports: Report 1; Report 2'));
assert.ok(!copiedText.includes('Automatic retry'));
assert.ok(copiedText.includes('GMT+7'));
assert.equal(formatRunErrors([]), '');
console.log('Run errors: replay deduplication, exact office/session recovery, retry history, no-data/stop, account persistence and retention passed.');
console.log('Copy errors groups identical original messages across reports and retries without merging different failures.');

const componentSource = readFileSync(new URL('../src/components/CopyRunErrors.tsx', import.meta.url), 'utf8');
const componentCompiled = ts.transpileModule(componentSource, {compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
}}).outputText;
function copyHarness(writeText) {
  const state = [], refs = [], timers = new Map();
  let cursor = 0;
  const componentExports = {};
  const react = {
    useState(initial) {const slot = cursor++; if (!(slot in state)) state[slot] = initial;
      return [state[slot], value => {state[slot] = value;}];},
    useRef(initial) {const slot = cursor++; return refs[slot] ||= {current: initial};},
    useEffect() {},
  };
  const jsx = (type, props) => ({type, props});
  runInNewContext(componentCompiled, {
    exports: componentExports, navigator: {clipboard: {writeText}},
    require(name) {if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return {jsx, jsxs: jsx};
      if (name === '../run-error-log') return exports; throw new Error(name);},
    setTimeout(fn) {timers.set(1, fn); return 1;}, clearTimeout(id) {timers.delete(id);},
  });
  return {timers, render(entries) {cursor = 0; return componentExports.CopyRunErrors({entries});}};
}
const writes = [];
const copyUI = copyHarness(async text => {writes.push(text);});
let button = copyUI.render(repeated).props.children[0];
assert.equal(button.props.children, 'Copy errors (1)');
assert.equal(button.props.disabled, false);
button.props.onClick();
await new Promise(resolve => setImmediate(resolve));
assert.equal(writes[0], copiedText, 'copy button writes the deduplicated errors to the clipboard');
assert.equal(copyUI.render(repeated).props.children[0].props.children, 'Copied');
copyUI.timers.get(1)();
assert.equal(copyUI.render(repeated).props.children[0].props.children, 'Copy errors (1)');
assert.equal(copyUI.render([]).props.children[0].props.disabled, true);
const deniedCopy = copyHarness(async () => {throw new Error('Permission denied');});
deniedCopy.render(repeated).props.children[0].props.onClick();
await new Promise(resolve => setImmediate(resolve));
const deniedView = deniedCopy.render(repeated);
assert.equal(deniedView.props.children[0].props.children, 'Copy errors (1)');
assert.equal(deniedView.props.children[2].props.role, 'alert', 'clipboard denial must not claim success');
console.log('Copy button writes grouped errors, confirms actual success, handles denied access, and disables when empty.');
