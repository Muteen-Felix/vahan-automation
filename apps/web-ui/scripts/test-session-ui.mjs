import assert from 'node:assert/strict';
import {chromium} from '../../browser-runner/node_modules/playwright/index.mjs';

const browser = await chromium.launch({headless: true});
const origin = process.env.NAV_UI_URL || 'http://127.0.0.1:5184/';
try {
  const context = await browser.newContext();
  const requests = [];
  let deadline = Date.now() / 1000 + 8;
  let token = 'session-fixture';
  await context.addCookies([{name:'vahan_session_fixture',value:token,url:new URL(origin).origin,
    httpOnly:true,sameSite:'Strict'}]);
  await context.addInitScript(() => {
    if (!localStorage.getItem('session-fixture-seeded')) {
      localStorage.setItem('vahanUiAccessToken', 'session-fixture');
      localStorage.setItem('vahanUiSessionMarker', 'fixture-marker');
      localStorage.setItem('session-fixture-seeded', 'yes');
    }
  });
  await context.route('https://fonts.googleapis.com/**', route => route.abort());
  await context.route('https://fonts.gstatic.com/**', route => route.abort());
  await context.routeWebSocket('**/socket.io/**', socket => {
    socket.send('0' + JSON.stringify({sid: 'session-fixture', upgrades: [], pingInterval: 60000, pingTimeout: 60000}));
    socket.onMessage(message => {
      if (String(message).startsWith('40/ui,')) socket.send('40/ui,' + JSON.stringify({sid: 'session-ui'}));
    });
  });
  await context.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push(path);
    let body = [];
    if (path === '/api/auth/status') body = {configured: true, tokenTtlSeconds: 43200, idleTimeoutSeconds: 3600};
    else if (path === '/api/auth/login') {
      token = `session-fixture-${Date.now()}`;
      deadline = Date.now() / 1000 + 3600;
      body = {accessToken: null, sessionMarker:`marker-${Date.now()}`,csrfToken:'fixture-csrf',username: 'fixture', tokenType: 'Cookie', expiresIn: 43200};
      return route.fulfill({json:body,headers:{'Set-Cookie':`vahan_session_fixture=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200`}});
    } else if (path === '/api/auth/me' || path === '/api/auth/activity') {
      assert.equal(request.headers().authorization,undefined,'UI never sends an exposed bearer token');
      if (!request.headers().cookie?.includes(`vahan_session_fixture=${token}`) || Date.now() / 1000 >= deadline) {
        return route.fulfill({status: 401, json: {detail: 'Session expired'}});
      }
      body = {username: 'fixture', role: 'admin', csrfToken:'fixture-csrf',expiresAt: Math.floor(Date.now() / 1000 + 43200), idleExpiresAt: Math.floor(deadline)};
    } else if (path === '/api/user-state') body = {};
    else if (path === '/api/network/status') body = {online: true};
    else if (path === '/api/ui-health/status') body = {blocked: false, latestPreflight: null};
    else if (path === '/api/annual-reports') body = {year: 2026, datasets: [], years: [2026], states: [], rtos: [], rows: [], coverage: [], summary: {rows: 0, makers: 0, offices: 0}};
    await route.fulfill({json: body});
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin);
  await page.getByRole('navigation', {name: 'Main navigation'}).waitFor();
  await page.getByRole('heading', {name: 'Welcome back', exact: true}).waitFor({timeout: 15000});
  assert.ok(requests.filter(path => path === '/api/network/status').length >= 2, 'Background polling continues during idle period');
  assert.ok(requests.filter(path => path === '/api/auth/activity').length <= 2, 'Polling never generates periodic activity');
  assert.equal(requests.includes('/api/auth/renew'), false, 'Retired renew endpoint is never called');
  assert.equal(await page.evaluate(() => localStorage.getItem('vahanUiAccessToken')), null);

  await page.getByLabel('Username', {exact: true}).fill('fixture');
  await page.getByLabel('Password', {exact: true}).fill('Fixture password');
  await page.getByRole('button', {name: 'Sign in', exact: true}).click();
  await page.getByRole('navigation', {name: 'Main navigation'}).waitFor();
  const second = await context.newPage();
  await second.goto(origin);
  await second.getByRole('navigation', {name: 'Main navigation'}).waitFor();
  await page.evaluate(() => localStorage.removeItem('vahanUiSessionMarker'));
  await second.getByRole('heading', {name: 'Welcome back', exact: true}).waitFor();
  assert.deepEqual(errors, []);
  await context.close();
  console.log('Session UI: idle logout despite polling, no renewal, login recovery and shared-tab logout passed.');
} finally {
  await browser.close();
}
