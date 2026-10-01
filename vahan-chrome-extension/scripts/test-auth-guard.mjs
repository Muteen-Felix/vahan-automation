import assert from "node:assert/strict";
import {
  VAHAN_AUTH_HOLD_MS,
  VAHAN_AUTH_GUARD_VERSION,
  VAHAN_AUTH_REQUIRED_CODE,
  VAHAN_SESSION_EXPIRED_CODE,
  VAHAN_UNREACHABLE_CODE,
  VAHAN_SERVER_ERROR_CODE,
  createVahanAuthHold,
  isVahanAuthHoldActive,
  isVahanMainFrameAuthChallenge,
  isVahanRequestUrl,
  isVahanPublicReportUrl,
  isVahanRedirectedHomeUrl,
  isChromeErrorUrl,
  vahanAuthHoldMessage,
  vahanSessionExpiredMessage,
  vahanUnreachableMessage,
} from "../src/vahan-auth-guard.mjs";

const now = Date.parse("2026-09-18T10:00:00.000Z");
const first = createVahanAuthHold({
  tabId: 42,
  url: "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en",
  scheme: "Basic",
  realm: "VAHAN",
  statusCode: 401,
}, null, now);

assert.equal(first.code, VAHAN_AUTH_REQUIRED_CODE);
assert.equal(first.guardVersion, VAHAN_AUTH_GUARD_VERSION);
assert.equal(first.resourceType, "unknown");
assert.equal(first.url, "https://analytics.parivahan.gov.in/analytics/vahanpublicreport");
assert.equal(first.occurrences, 1);
assert.equal(isVahanAuthHoldActive(first, now + 1_000, 42), true);
assert.equal(isVahanAuthHoldActive(first, now + 1_000, 7), false);
assert.equal(isVahanAuthHoldActive(first, now + VAHAN_AUTH_HOLD_MS + 1, 42), false);

const repeated = createVahanAuthHold({ tabId: 42, url: first.url, statusCode: 401 }, first, now + 2_000);
assert.equal(repeated.occurrences, 2);
assert.equal(isVahanRequestUrl(first.url), true);
assert.equal(isVahanRequestUrl("https://example.com/analytics/vahanpublicreport"), false);
assert.equal(isVahanMainFrameAuthChallenge({
  type: "main_frame",
  url: first.url,
}), true);
assert.equal(isVahanMainFrameAuthChallenge({
  type: "image",
  url: first.url,
}), false);
assert.equal(isVahanMainFrameAuthChallenge({
  type: "sub_frame",
  url: first.url,
}), false);
assert.equal(isVahanAuthHoldActive({ ...first, guardVersion: 1 }, now + 1_000, 42), false);
assert.match(vahanAuthHoldMessage(first), /paused to prevent repeated retries/);

// Tests for new resilience functions
assert.equal(VAHAN_SESSION_EXPIRED_CODE, "VAHAN_SESSION_EXPIRED");
assert.equal(VAHAN_UNREACHABLE_CODE, "VAHAN_UNREACHABLE");
assert.equal(VAHAN_SERVER_ERROR_CODE, "VAHAN_SERVER_ERROR");

assert.equal(isVahanPublicReportUrl("https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en"), true);
assert.equal(isVahanPublicReportUrl("https://analytics.parivahan.gov.in/analytics/vahanpublicreport"), true);
assert.equal(isVahanPublicReportUrl("https://analytics.parivahan.gov.in/analytics/"), false);
assert.equal(isVahanPublicReportUrl("https://analytics.parivahan.gov.in/analytics/login"), false);

assert.equal(isVahanRedirectedHomeUrl("https://analytics.parivahan.gov.in/analytics/"), true);
assert.equal(isVahanRedirectedHomeUrl("https://analytics.parivahan.gov.in/analytics"), true);
assert.equal(isVahanRedirectedHomeUrl("https://analytics.parivahan.gov.in/analytics/login"), true);
assert.equal(isVahanRedirectedHomeUrl("https://analytics.parivahan.gov.in/"), true);
assert.equal(isVahanRedirectedHomeUrl("https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en"), false);

assert.equal(isChromeErrorUrl("chrome-error://chromewebdata/"), true);
assert.equal(isChromeErrorUrl("chrome-error://something"), true);
assert.equal(isChromeErrorUrl("https://analytics.parivahan.gov.in/analytics/vahanpublicreport"), false);

assert.match(vahanSessionExpiredMessage(), /session has expired/);
assert.match(vahanUnreachableMessage("ERR_CONNECTION_TIMED_OUT"), /ERR_CONNECTION_TIMED_OUT/);

console.log("VAHAN auth guard tests passed.");
