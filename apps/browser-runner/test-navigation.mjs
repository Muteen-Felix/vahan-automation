import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {runInNewContext} from 'node:vm';
import {createServer} from 'node:http';
import {chromium} from 'playwright';

const source = readFileSync(new URL('./runner.mjs', import.meta.url), 'utf8');
const start = source.indexOf('async function finalizeResult(');
const end = source.indexOf("socket.on('connect'", start);
const workerCode = `${source.slice(start, end)}\nwaitForResult`;
const official = 'https://analytics.parivahan.gov.in/analytics/vahanpublicreport';
function fixture({results, advance = 100, cancelAfterRead = false, loadingError} = {}) {
  let now = 0, reads = 0;
  const job = {jobId: 'test-job', filters: {rtos: ['Test Office - AN206']}};
  const context = {
    globalThis: {URL}, target: new URL(official), active: job, authRequired: false, RESULT_TIMEOUT: 1000,
    Date: {now: () => now},
    setTimeout: callback => {now += advance; queueMicrotask(callback);},
    assertCurrent: candidate => {if (candidate !== context.active || candidate.cancelled) throw new Error('Job was cancelled.');},
    page: {url: () => official,
      waitForLoadState: async () => {if (loadingError) throw new Error(loadingError);},
      evaluate: async (_fn, args) => {
        reads++;
        assert.ok(args.timeout > 0 && args.timeout <= 1000);
        if (cancelAfterRead) job.cancelled = true;
        const result = results?.[reads - 1] || new Error('page.evaluate: Execution context was destroyed, most likely because of a navigation');
        if (result instanceof Error) throw result;
        return result;
      }},
  };
  const run = runInNewContext(workerCode, context);
  return {context, job, reads: () => reads, run: () => run(job)};
}
const many = fixture({results: [new Error('Execution context was destroyed'), new Error('Cannot find context with specified id'), {type: 'TIMEOUT'}]});
await assert.rejects(many.run(), /VAHAN_RESULT_TIMEOUT/);
assert.equal(many.reads(), 3, 'more than one navigation must reattach the result reader');
const forever = fixture();
await assert.rejects(forever.run(), /VAHAN_RESULT_TIMEOUT/);
assert.equal(forever.reads(), 10, 'navigation retries share one deadline');
const cancelled = fixture({cancelAfterRead: true});
await assert.rejects(cancelled.run(), /Job was cancelled/);
assert.equal(cancelled.reads(), 1);
const scriptError = fixture({results: [new Error('Unexpected parser error')]});
await assert.rejects(scriptError.run(), /Unexpected parser error/);
assert.equal(scriptError.reads(), 1, 'non-navigation errors must not be hidden');
const blockedDocument = fixture({loadingError: 'page.waitForLoadState: Timeout 1000ms exceeded.'});
await assert.rejects(blockedDocument.run(), /VAHAN_RESULT_TIMEOUT/);
assert.equal(blockedDocument.reads(), 0);
const unauthenticated = fixture(); unauthenticated.context.authRequired = true;
await assert.rejects(unauthenticated.run(), /VAHAN_AUTH_REQUIRED/);
assert.equal(unauthenticated.reads(), 0);

// Reproduce a form POST, two further document navigations and streamed HTML.
// This fixture has no security challenge or external network requests.
let posts = 0;
const server = createServer((request, response) => {
  const stage = new URL(request.url, 'http://fixture.test').searchParams.get('stage');
  response.writeHead(200, {'Content-Type': 'text/html'});
  if (request.method === 'POST') {
    posts++;
    response.end('<html><head><script>setTimeout(()=>location.replace("?stage=1"),160)</script></head><body>Loading report</body></html>');
  } else if (stage === '1') {
    response.end('<html><head><script>setTimeout(()=>location.replace("?stage=2"),160)</script></head><body>Redirecting report</body></html>');
  } else if (stage === '2') {
    response.write('<!doctype html><html><head><title>Report loading</title>');
    setTimeout(() => response.end('</head><body><section class="report-main-column"><h2>RTO (Test Office - AN206)</h2><p>No record found</p></section></body></html>'), 150);
  } else {
    response.end('<form method="POST"><button id="applyTrigger">Apply</button></form><section class="report-main-column"><h2>RTO (Test Office - AN206)</h2></section>');
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage();
  await page.addInitScript({path: fileURLToPath(new URL('./page-driver.js', import.meta.url))});
  const url = `http://127.0.0.1:${server.address().port}/analytics/vahanpublicreport`;
  await page.goto(url);
  await page.evaluate(() => vahanDriver.prepareResult(5000, 'Test Office - AN206'));
  const saved = [], job = {jobId: 'fixture-report', filters: {rtos: ['Test Office - AN206']}};
  let lostContexts = 0;
  const context = {
    globalThis: {URL}, target: new URL(url), active: job, authRequired: false, RESULT_TIMEOUT: 5000, setTimeout,
    assertCurrent: candidate => assert.equal(candidate, context.active),
    page: {url: () => page.url(), waitForLoadState: (...args) => page.waitForLoadState(...args),
      evaluate: async (...args) => {try {return await page.evaluate(...args);} catch (error) {
        if (/context was destroyed/i.test(error.message)) lostContexts++;
        throw error;
      }}},
    http: async (_path, options) => {saved.push(JSON.parse(options.body)); return {status: 'NO_DATA'};},
    saveState: async () => {},
  };
  const run = runInNewContext(workerCode, context);
  await page.locator('#applyTrigger').click({noWaitAfter: true});
  await run(job);
  assert.equal(posts, 1, 'navigation recovery must not resubmit Apply');
  assert.equal(saved.length, 1, 'the final document is saved exactly once');
  assert.equal(saved[0].result, 'NO_RECORD');
  assert.equal(context.active, null);
  assert.ok(lostContexts >= 2, 'the real fixture must exercise repeated destroyed contexts');
  console.log(`Chromium POST/navigation recovery passed: ${posts} Apply, ${lostContexts} destroyed contexts, 1 confirmed saved result.`);
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
console.log('Navigation checks passed: repeated context loss, shared timeout, cancellation, parser errors, loading timeout and authentication.');
