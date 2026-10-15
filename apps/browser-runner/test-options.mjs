import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {retireReportPage, stableDocumentRead} from './page-recovery.mjs';
import {chromium} from 'playwright';

const source = readFileSync(new URL('./runner.mjs', import.meta.url), 'utf8');
const start = source.indexOf('async function runnerOptions(');
const end = source.indexOf("socket.on('runner:options', runnerOptions)", start);
function fixture() {
  const timers = new Map(), replies = [], calls = [];
  let rejectEvaluation;
  const context = {
    retireReportPage:async p=>p?.close(), pageNeedsReset:false,
    active: null, optionsBusy: false, OPTIONS_TIMEOUT: 110_000,
    VAHAN_OPTION_SELECTORS: {states: {selector: '#stateName'}},
    approvedSelectors: {states: {selector: '#stateName'}},
    ensurePage: async () => calls.push('ready'),
    page: {
      evaluate: async () => new Promise((_, reject) => {rejectEvaluation = reject;}),
      close: async () => {calls.push('close'); rejectEvaluation?.(new Error('Page closed'));},
    },
    setTimeout: (callback, ms) => {assert.equal(ms, 110_000); timers.set(1, callback); return 1;},
    clearTimeout: id => timers.delete(id),
  };
  const run = runInNewContext(`${source.slice(start, end)}\nrunnerOptions`, context);
  return {context, timers, replies, calls, run: () => run({type: 'GET_ALL_OPTIONS'}, value => replies.push(value))};
}
const hung = fixture();
const pending = hung.run();
await new Promise(resolve => setImmediate(resolve));
assert.equal(hung.context.optionsBusy, true);
await hung.run();
assert.equal(hung.replies[0].error, 'Worker is busy.');
hung.timers.get(1)();
await pending;
assert.match(hung.replies[1].error, /VAHAN_OPTIONS_TIMEOUT/);
assert.deepEqual(hung.calls, ['ready', 'close']);
assert.equal(hung.context.optionsBusy, false);
assert.equal(hung.timers.size, 0);
hung.context.page.evaluate = async () => ({states: ['Test State']});
await hung.run();
assert.equal(hung.replies[2].ok, true, 'the next request succeeds after a hung evaluation');

const opening = fixture();
let finishOpening;
opening.context.ensurePage = async cancelled => {
  await new Promise(resolve => {finishOpening = resolve;});
  assert.equal(cancelled(), true);
};
const openingPending = opening.run();
opening.timers.get(1)();
await openingPending;
finishOpening();
await new Promise(resolve => setImmediate(resolve));
assert.equal(opening.replies.length, 1, 'late page initialization must not acknowledge success');
assert.equal(opening.context.optionsBusy, false);

const failed = fixture();
failed.context.ensurePage = async () => {throw new Error('VAHAN_PAGE_NOT_READY');};
await failed.run();
assert.equal(failed.replies[0].ok, false);
assert.deepEqual(failed.calls, ['close']);
assert.equal(failed.context.optionsBusy, false);

const finishing = fixture();
let releaseSave;
finishing.context.active = {finishing: true, finishPromise: new Promise(resolve => {releaseSave = resolve;})};
finishing.context.page.evaluate = async () => ({states: ['Ready after SQL save']});
const waitingForSave = finishing.run();
assert.equal(finishing.replies.length, 0, 'a released backend worker may still be finishing its local save');
finishing.context.active = null;
releaseSave();
await waitingForSave;
assert.equal(finishing.replies[0].ok, true, 'options must wait for SQL finalization rather than report busy');

const cancelled = fixture();
const pendingCancellation = cancelled.run();
await new Promise(resolve => setImmediate(resolve));
await cancelled.context.optionsCancellation.cancel();
await pendingCancellation;
assert.equal(cancelled.context.optionsBusy,false,'an acknowledged preview cancellation releases the browser immediately');
assert.equal(cancelled.context.optionsCancellation,null);
assert.ok(cancelled.calls.includes('close'));

// A real Chromium DOM reproduces VAHAN's hidden native select. No report is
// submitted and no CAPTCHA is read or solved by this fixture.
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage();
  const url = 'http://options.test/analytics/vahanpublicreport';
  await page.route('http://options.test/**', route => route.fulfill({contentType: 'text/html',
    body: '<select id="stateName" style="display:none"><option>Test State</option></select><button>State proxy</button>'}));
  const openingStart = source.indexOf('async function ensurePage(');
  const openingEnd = source.indexOf('async function saveState(', openingStart);
  const ensure = runInNewContext(`${source.slice(openingStart, openingEnd)}\nensurePage`, {
    pageNeedsReset:false, retireReportPage, stableDocumentRead,
    globalThis: {URL}, URL: url, target: new URL(url), page,
    http:async()=>({blocked:false,versionId:'fixture',revision:1,controls:[]}),
    VAHAN_OPTION_SELECTORS:{states:{selector:'#stateName'}},selectorOverrides:()=>({}),approvedSelectors:{},contractRevision:0,
    launch: async () => {}, newPage: async () => {}, authRequired: false,
  });
  await ensure();
  assert.equal(await page.locator('#stateName').isVisible(), false);
  assert.deepEqual(await page.locator('#stateName option').allTextContents(), ['Test State']);
} finally {await browser.close();}
console.log('Options checks passed: hidden State readiness, bounded waits, busy lock, page cleanup, retry and late initialization.');
