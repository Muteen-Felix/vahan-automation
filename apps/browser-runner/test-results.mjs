import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import {createServer} from 'node:http';

const browser = await chromium.launch({headless: true});
const page = await browser.newPage();
await page.addInitScript({path: fileURLToPath(new URL('./page-driver.js', import.meta.url))});
const table = (heading = 'Maker', value = 'Example', id = 'report') =>
  `<table id="${id}"><thead><tr><th>${heading}</th><th>Count</th></tr></thead>` +
  `<tbody><tr><td>${value}</td><td>123</td></tr></tbody><tfoot><tr><td>Total</td><td>123</td></tr></tfoot></table>`;
const emptyTable = '<table><tbody><tr><td>Maker</td><td>Count</td></tr><tr><td colspan="2">No record found</td></tr></tbody></table>';
async function fixture(initial, next, {rto = 'PUNE-MH12', title = 'RTO (PUNE-MH12)', timeout = 1200} = {}) {
  await page.route('http://fixture.test/**', route => route.fulfill({contentType: 'text/html', body:
    `<button id="applyTrigger">Apply</button><section class="report-main-column"><h2>${title}</h2><div id="tables">${initial}</div></section>`}));
  await page.goto('http://fixture.test/');
  await page.evaluate(({timeout, rto}) => vahanDriver.prepareResult(timeout, rto), {timeout, rto});
  if (next !== null) await page.evaluate(html => { document.querySelector('#tables').innerHTML = html; }, next);
  return page.evaluate(({timeout, rto}) => vahanDriver.result(timeout, rto), {timeout, rto});
}
let passed = 0;
async function check(name, run) { await run(); passed++; console.log(`PASS ${name}`); }
try {
  await check('multiple axes, tables, exact cells and totals without Excel', async () => {
    const result = await fixture('', table('Fuel', 'PETROL', 'fuel') + table('Vehicle Class', 'MOTOR CAR', 'class'));
    assert.equal(result.type, 'DATA_READY'); assert.equal(result.downloadReady, false);
    assert.equal(result.report.tables.length, 2);
    assert.deepEqual(result.report.tables[1].rows[1].cells, ['MOTOR CAR', '123']);
    assert.equal(result.report.tables[0].rows[2].section, 'foot');
    assert.match(result.report.observedAt, /^\d{4}-\d{2}-\d{2}T/);
  });
  await check('fresh No record found with td headings', async () => {
    const result = await fixture(table(), emptyTable);
    assert.equal(result.type, 'NO_RECORD'); assert.equal(result.report.message, 'No record found');
    assert.deepEqual(result.report.tables, []);
  });
  await check('RTO names with parentheses accept confirmed no-data and populated reports', async () => {
    const rto = 'M/S DAISY MOTORS PVT LTD(F.C) - HR261';
    const title = `Maker and Month Wise Data for RTO (${rto}) in Haryana (2026)`;
    assert.equal((await fixture('', emptyTable, {rto, title})).type, 'NO_RECORD');
    assert.equal((await fixture('', table('Maker', 'BAJAJ AUTO LTD'), {rto, title})).type, 'DATA_READY');
    assert.equal((await fixture('', emptyTable, {rto: 'OTHER OFFICE - HR262', title, timeout: 100})).type, 'TIMEOUT');
  });
  await check('standalone no-data message', async () => {
    assert.equal((await fixture('', '<p>No record found</p>')).type, 'NO_RECORD');
  });
  await check('stale no-data from previous Apply is not accepted', async () => {
    assert.equal((await fixture(emptyTable, null, {timeout: 650})).type, 'TIMEOUT');
  });
  await check('stale populated table is not accepted', async () => {
    assert.equal((await fixture(table(), null, {timeout: 100})).type, 'TIMEOUT');
  });
  await check('blank timeout is distinct from no data', async () => {
    assert.equal((await fixture('', null, {timeout: 100})).type, 'TIMEOUT');
  });
  await check('wrong RTO is not accepted', async () => {
    assert.equal((await fixture('', table(), {title: 'RTO (MUMBAI-MH01)', timeout: 100})).type, 'TIMEOUT');
  });
  await check('invalid validation takes priority over data', async () => {
    assert.equal((await fixture('', '<p>Invalid CAPTCHA</p>' + table())).type, 'INVALID_CAPTCHA');
  });
  await check('hidden tables and filter tables are excluded', async () => {
    const result = await fixture('', table() + '<div hidden>' + table('Fuel') + '</div>' +
      '<table><tr><td><select><option>State</option></select></td><td>Filter</td></tr></table>');
    assert.equal(result.report.tables.length, 1);
  });
  await check('new identical no-data node is a fresh response', async () => {
    assert.equal((await fixture(emptyTable, emptyTable)).type, 'NO_RECORD');
  });
  await check('loading no-data followed by populated result saves data', async () => {
    const pending = fixture('', '<div aria-busy="true">' + emptyTable + '</div>');
    await page.waitForSelector('[aria-busy="true"]');
    await page.evaluate(html => { document.querySelector('#tables').innerHTML = html; }, table('Fuel'));
    assert.equal((await pending).type, 'DATA_READY');
  });
  await check('result reader starts during navigation before body exists', async () => {
    const server = createServer((_request, response) => {
      response.writeHead(200, {'Content-Type': 'text/html'});
      response.write('<!doctype html><html><head><title>Loading report</title>');
      setTimeout(() => response.end('</head><body><section class="report-main-column"><h2>RTO (PUNE-MH12)</h2>' + table() + '</section></body></html>'), 300);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    try {
      await page.goto(`http://127.0.0.1:${server.address().port}/`, {waitUntil: 'commit'});
      assert.equal(await page.evaluate(() => document.body), null);
      const result = await page.evaluate(() => vahanDriver.result(1500, 'PUNE-MH12'));
      assert.equal(result.type, 'DATA_READY');
      assert.deepEqual(result.report.tables[0].rows[1].cells, ['Example', '123']);
    } finally { await new Promise(resolve => server.close(resolve)); }
  });
  for (const dynamic of [false, true]) {
    await check(`category group with ${dynamic ? 'delayed' : 'unchanged'} subcategory options`, async () => {
      await fixture('', null, {timeout: 25});
      await page.evaluate(dynamic => {
        document.body.insertAdjacentHTML('beforeend', '<select multiple id="vehicleCategoryGroup"><option selected>Four Wheeler</option><option>Two Wheeler</option></select>' +
          '<select multiple id="vehicleSubCategory">' + (dynamic ? '' : '<option>TWO WHEELER(NT)</option>') + '</select>');
        if (dynamic) document.querySelector('#vehicleCategoryGroup').addEventListener('change', () => {
          setTimeout(() => { document.querySelector('#vehicleSubCategory').innerHTML = '<option>TWO WHEELER(NT)</option>'; }, 150);
        });
      }, dynamic);
      await Promise.race([
        page.evaluate(() => vahanDriver.fill({categoryGroups: 'Two Wheeler', subCategories: 'TWO WHEELER(NT)'})),
        new Promise((_resolve, reject) => setTimeout(() => reject(new Error('Valid subcategory selection did not finish.')), 1500)),
      ]);
      assert.deepEqual(await page.locator('#vehicleSubCategory').evaluate(select => [...select.selectedOptions].map(option => option.textContent)), ['TWO WHEELER(NT)']);
    });
  }
  console.log(`${passed} result-flow checks passed.`);
} finally { await browser.close(); }
