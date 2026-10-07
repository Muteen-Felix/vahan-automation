import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import ts from 'typescript';

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const start = app.indexOf('  async function continueUncoveredReports(');
const end = app.indexOf('  async function restartStoppedBatch(', start);
const compiled = ts.transpileModule(app.slice(start, end), {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
const source = readFileSync(new URL('../src/report-coverage.ts', import.meta.url), 'utf8');
const helper = ts.transpileModule(source.slice(source.indexOf('export function uncoveredScenarios(')).replace('export function', 'function'), {
  compilerOptions: {target: ts.ScriptTarget.ES2022},
}).outputText;
const select = runInNewContext(`${helper}\nuncoveredScenarios`);
const scenarios = Array.from({length: 6}, (_, i) => ({name: `Office ${i}`, filters: {states: ['ASSAM'], rtos: [`AS${i}`]}}));
const plan = {year: 2026, scenarios};
const coverage = {canContinue: true, missingIndices: [0, 3, 5]};
assert.deepEqual(Array.from(select(plan, coverage).indices), [0, 3, 5]);
assert.deepEqual(Array.from(select(plan, coverage).scenarios), [scenarios[0], scenarios[3], scenarios[5]]);
assert.throws(() => select(plan, {...coverage, missingIndices: [7]}), /office list changed/);
assert.throws(() => select(plan, {...coverage, missingIndices: [3, 3]}), /office list changed/);
assert.throws(() => select(plan, {...coverage, canContinue: false, blockedReason: 'Already running'}), /Already running/);

function harness({missing = coverage.missingIndices, busy = false, savedPlan = plan, existingJob = null, canContinue = true} = {}) {
  const calls = [];
  const context = {
    batchRunningRef: {current: busy}, creating: false, latestJobRef: {current: existingJob},
    matrixPlan: savedPlan, currentReportYear: () => 2026, isReportYear: year => year >= 1900 && year <= 2026, updateMatrixYear: (value, year) => ({...value, year}),
    setRunSettings: () => {}, runSettings: {year: 2026, workerCount: 5}, RUN_SETTINGS_STORAGE_KEY: "settings",
    prepareMatrix: async () => {calls.push('load-matrix'); return plan;},
    persistentState: {setItem: () => {}}, MATRIX_STORAGE_KEY: 'matrix', setMatrixPlan: () => {},
    loadReportCoverage: async (query, matrix) => {calls.push({query, matrix}); return {...coverage, missingIndices: missing, canContinue, blockedReason: 'Blocked'};},
    uncoveredScenarios: select,
    runScenarioQueue: async (queue, options) => {calls.push({queue, options}); context.batchRunningRef.current = true;},
    setNotice: message => calls.push(message),
  };
  const run = runInNewContext(`${compiled}\ncontinueUncoveredReports`, context);
  return {run, context, calls};
}
const query = {year: 2026, dataset: 'own-scope', state: '', rto: ''};
const normal = harness();
await normal.run(query);
assert.equal(normal.calls[0].query, query, 'coverage is re-read at the moment the user clicks');
assert.deepEqual(Array.from(normal.calls[1].options.selectedIndices), [0, 3, 5]);
assert.deepEqual(Array.from(normal.calls[1].queue), [scenarios[0], scenarios[3], scenarios[5]], 'skip all existing data and fill gaps before the last saved office');
await assert.rejects(normal.run(query), /Stop the current report/);
const complete = harness({missing: []});
await complete.run(query);
assert.equal(complete.calls.length, 2);
assert.match(complete.calls[1], /already covered/);
const unloaded = harness({savedPlan: null});
await unloaded.run(query);
assert.equal(unloaded.calls[0], 'load-matrix');
await assert.rejects(harness({busy: true}).run(query), /Stop the current report/);
await assert.rejects(harness({existingJob: {status: 'WAITING_CAPTCHA'}}).run(query), /Stop the current report/);
await assert.rejects(harness().run({...query, year: 2027}), /supported calendar year/);
const historical = harness();
await historical.run({...query, year: 2024});
assert.equal(historical.calls[1].options.planOverride.year, 2024, 'historical continuation keeps the requested year');
await assert.rejects(harness({canContinue: false}).run(query), /Blocked/);
console.log('Coverage continuation rechecks saved data, fills only missing office indices, loads absent plans and blocks active/foreign-year runs.');
