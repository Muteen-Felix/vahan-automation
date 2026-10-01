export const VAHAN_AUTH_HOLD_KEY = "vahanAuthHold";
export const VAHAN_AUTH_REQUIRED_CODE = "VAHAN_AUTH_REQUIRED";
export const VAHAN_SESSION_EXPIRED_CODE = "VAHAN_SESSION_EXPIRED";
export const VAHAN_UNREACHABLE_CODE = "VAHAN_UNREACHABLE";
export const VAHAN_SERVER_ERROR_CODE = "VAHAN_SERVER_ERROR";
export const VAHAN_AUTH_HOLD_MS = 15 * 60 * 1000;
export const VAHAN_AUTH_GUARD_VERSION = 2;

const VAHAN_HOST = "analytics.parivahan.gov.in";

export function isVahanRequestUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" && url.hostname === VAHAN_HOST;
  } catch {
    return false;
  }
}

export function isVahanPublicReportUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:"
      && url.hostname === VAHAN_HOST
      && url.pathname.startsWith("/analytics/vahanpublicreport");
  } catch {
    return false;
  }
}

export function isVahanRedirectedHomeUrl(value) {
  try {
    const url = new URL(String(value || ""));
    if (url.hostname !== VAHAN_HOST) return false;
    const path = url.pathname.replace(/\/+$/, "") || "/";
    return path === "" || path === "/" || path === "/analytics" || path === "/analytics/login";
  } catch {
    return false;
  }
}

export function isChromeErrorUrl(value) {
  const str = String(value || "").toLowerCase();
  return str.startsWith("chrome-error://")
    || (str.startsWith("chrome-extension://") && str.includes("error"))
    || str.includes("chromewebdata");
}

// A protected image, stylesheet or API request must not lock the whole
// extension when the report page itself is still usable. Only a top-level
// VAHAN document challenge is a real authentication stop for the runner.
export function isVahanMainFrameAuthChallenge(details = {}) {
  return details.isProxy !== true
    && details.type === "main_frame"
    && isVahanRequestUrl(details.url);
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return `${url.origin}${url.pathname}`;
  } catch {
    return `https://${VAHAN_HOST}/`;
  }
}

function timestamp(value) {
  return new Date(value).toISOString();
}

export function createVahanAuthHold(details = {}, previous = null, now = Date.now()) {
  const tabId = Number.isInteger(details.tabId) && details.tabId >= 0 ? details.tabId : null;
  const sameChallenge = previous
    && previous.tabId === tabId
    && previous.code === VAHAN_AUTH_REQUIRED_CODE
    && Date.parse(previous.lastDetectedAt || "") > now - VAHAN_AUTH_HOLD_MS;

  return {
    guardVersion: VAHAN_AUTH_GUARD_VERSION,
    code: VAHAN_AUTH_REQUIRED_CODE,
    status: "AUTH_REQUIRED",
    host: VAHAN_HOST,
    resourceType: String(details.type || "unknown"),
    tabId,
    url: safeUrl(details.url),
    scheme: String(details.scheme || "Basic"),
    realm: String(details.realm || "").slice(0, 120),
    statusCode: Number(details.statusCode) || 401,
    occurrences: sameChallenge ? Number(previous.occurrences || 0) + 1 : 1,
    firstDetectedAt: sameChallenge ? previous.firstDetectedAt : timestamp(now),
    lastDetectedAt: timestamp(now),
    retryAfter: timestamp(now + VAHAN_AUTH_HOLD_MS),
  };
}

export function isVahanAuthHoldActive(hold, now = Date.now(), tabId) {
  if (!hold || hold.guardVersion !== VAHAN_AUTH_GUARD_VERSION || hold.code !== VAHAN_AUTH_REQUIRED_CODE) return false;
  if (tabId !== undefined && hold.tabId !== null && hold.tabId !== tabId) return false;
  const retryAfter = Date.parse(hold.retryAfter || "");
  return Number.isFinite(retryAfter) && retryAfter > now;
}

export function vahanAuthHoldMessage(hold = {}) {
  const retryAfter = hold.retryAfter ? new Date(hold.retryAfter).toLocaleString("en-GB") : "after confirmation";
  return `VAHAN requires HTTP authentication (${hold.statusCode || 401}). `
    + `The extension is paused to prevent repeated retries. Close the sign-in dialog, `
    + `wait until ${retryAfter}, verify that the official page is accessible, then try again.`;
}

export function vahanSessionExpiredMessage() {
  return "The VAHAN session has expired (session timeout). Reload the VAHAN page to start a new session.";
}

export function vahanUnreachableMessage(detail = "") {
  const reason = detail ? ` (${detail})` : "";
  return `Cannot reach VAHAN${reason}. The server may be under maintenance or your network may be disconnected.`;
}

