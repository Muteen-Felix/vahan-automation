import { io } from "socket.io-client";
import { normalizeJobFilters } from "./job-config.mjs";
import { uploadCapturedReport, matchesReportCapture, matchesJobPageResult } from "./report-upload.mjs";
import {
  registerUiHealthCheck,
} from "../ui-drift/health-check.mjs";
import {
  VAHAN_AUTH_HOLD_KEY,
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
} from "./vahan-auth-guard.mjs";

const DEFAULT_RUNNER_CONFIG = Object.freeze({
  serverUrl: "http://127.0.0.1:8000",
  runnerName: "VAHAN Chrome",
  token: "change-me",
});
const HEARTBEAT_INTERVAL_MS = 20_000;
const RUNNER_CONNECTION_ALARM = "runner-connection-watchdog";
const VAHAN_URL = "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en";
const VAHAN_PAGE_STALL_TIMEOUT_MS = 10_000;
const VAHAN_PAGE_STALL_CHECK_INTERVAL_MS = 1_000;
const VAHAN_PAGE_LIVENESS_PROBE_INTERVAL_MS = 2_000;
const VAHAN_PAGE_HEARTBEAT_INTERVAL_MS = 2_000;
// Monitor page responsiveness, not job progress: slow network responses and
// an attended CAPTCHA wait are safe as long as the page event loop responds.
const VAHAN_PAGE_STALL_MONITORED_STAGES = new Set([
  "OPENING_VAHAN",
  "FILLING_FILTERS",
  "CAPTURING_CAPTCHA",
  "SUBMITTING",
  "WAITING_CAPTCHA",
  "WAITING_RESULT",
  "DOWNLOADING_REPORT",
  "UPLOADING_REPORT",
]);
// Cross-border latency (e.g. Vietnam -> India) can make the initial cold load
// take much longer than a same-region load. This only applies to the first
// navigation in getVahanTab(); sendToVahan()'s reload-recovery keeps the
// tighter default timeout since it's recovering an already-loaded tab.
const INITIAL_PAGE_LOAD_TIMEOUT_MS = 75_000;
// Max idle age before an existing tab is considered stale and reloaded to guarantee
// a fresh session (JSESSIONID) and CSRF token.
const MAX_TAB_IDLE_AGE_MS = 10 * 60 * 1000;
const VAHAN_OPTION_SELECTORS = Object.freeze({
  archivedFlags: { selector: "#archivedFlags", multiple: true },
  period: { selector: "#reportType" },
  financialYears: { selector: "#financialYearSelect", multiple: true },
  reportYear: { selector: "#reportYear" },
  reportMonth: { selector: "#reportMonth" },
  states: { selector: "#stateName", multiple: true },
  rtos: { selector: "#rtoCode", multiple: true },
  emissions: { selector: "#vehicleEmission", multiple: true },
  categoryGroups: { selector: "#vehicleCategoryGroup", multiple: true },
  subCategories: { selector: "#vehicleSubCategory", multiple: true },
  classes: { selector: "#vehicleClass", multiple: true },
  fuels: { selector: "#vehicleFuel", multiple: true },
  evTypes: { selector: "#evType", multiple: true },
  statuses: { selector: "#vehicleStatus", multiple: true },
  ownerTypes: { selector: "#vehicleOwnerType", multiple: true },
  vehicleType: { selector: "#vehicleType" },
  fitness: { selector: "#fitnessCheck" },
  delhiNcr: { selector: "#delhiNcr" },
  yAxis: { selector: "#yAxis" },
  xAxis: { selector: "#xAxis" },
});

let socket;
let heartbeatTimer;
let reconnectTimer;
let runnerConnectionTask;
let runnerReconnectRequested = false;
let activeConfig;
let activeJobId;
let cancelledJobIds = new Set();
let pendingBlobResolver;
let pendingReportCapture;
let reportJobInFlight;
let vahanPageStallCheckTimer;
let vahanPageStallCheckTask;
const vahanPageHeartbeats = new Map();
const vahanPageStallRecoveryJobs = new Set();
let pendingReportUploadController;
let uiHealthCheckController;
let vahanAuthHold;
let authHoldWrite = Promise.resolve();
const authChallengeWaiters = new Set();
const authFailureReportedJobs = new Set();
const tabActivityTimestamps = new Map();
const tabLastErrors = new Map();
const vahanPageLivenessProbes = new Map();
let successfulApplyCountQueue = Promise.resolve();

function serializeSuccessfulApplyCountUpdate(operation) {
  const update = successfulApplyCountQueue.catch(() => {}).then(operation);
  successfulApplyCountQueue = update.catch(() => {});
  return update;
}

function normalizeSuccessfulApplyCount(value) {
  const count = Number(value);
  return Number.isSafeInteger(count) && count > 0 ? count : 0;
}

function recordSuccessfulApplyClick(clickId) {
  return serializeSuccessfulApplyCountUpdate(async () => {
    const stored = await chrome.storage.local.get([
      "successfulApplyCount",
      "successfulApplyClickIds",
    ]);
    const clickIds = Array.isArray(stored.successfulApplyClickIds)
      ? stored.successfulApplyClickIds.filter((id) => typeof id === "string")
      : [];
    const count = normalizeSuccessfulApplyCount(stored.successfulApplyCount);
    if (clickIds.includes(clickId)) return { count, duplicate: true };

    const nextCount = count + 1;
    clickIds.push(clickId);
    await chrome.storage.local.set({
      successfulApplyCount: nextCount,
      successfulApplyClickIds: clickIds.slice(-1024),
    });
    return { count: nextCount, duplicate: false };
  });
}

async function flushPendingSuccessfulApplyClicks() {
  if (!socket?.connected) return;
  const stored = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
  const pending = Array.isArray(stored.pendingSuccessfulApplyClicks)
    ? stored.pendingSuccessfulApplyClicks.filter((entry) => entry && typeof entry.jobId === "string" && typeof entry.clickId === "string")
    : [];
  for (const entry of pending) {
    if (!socket?.connected) return;
    let response;
    try {
      response = await socket.timeout(5_000).emitWithAck("job:apply-clicked", entry);
    } catch {
      return;
    }
    if (response?.ok !== true) {
      const latest = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
      const current = Array.isArray(latest.pendingSuccessfulApplyClicks) ? latest.pendingSuccessfulApplyClicks : [];
      await chrome.storage.local.set({
        pendingSuccessfulApplyClicks: current.filter((item) => item?.jobId !== entry.jobId || item?.clickId !== entry.clickId),
      });
      continue;
    }
    const latest = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
    const current = Array.isArray(latest.pendingSuccessfulApplyClicks) ? latest.pendingSuccessfulApplyClicks : [];
    await chrome.storage.local.set({
      pendingSuccessfulApplyClicks: current.filter((item) => item?.jobId !== entry.jobId || item?.clickId !== entry.clickId),
    });
  }
}

async function queueSuccessfulApplyClickForJob(jobId, clickId) {
  const stored = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
  const pending = Array.isArray(stored.pendingSuccessfulApplyClicks)
    ? stored.pendingSuccessfulApplyClicks.filter((entry) => entry && typeof entry.jobId === "string" && typeof entry.clickId === "string")
    : [];
  if (!pending.some((entry) => entry.jobId === jobId && entry.clickId === clickId)) {
    pending.push({ jobId, clickId });
    await chrome.storage.local.set({ pendingSuccessfulApplyClicks: pending.slice(-500) });
  }
  await flushPendingSuccessfulApplyClicks();
  const latest = await chrome.storage.local.get("pendingSuccessfulApplyClicks");
  return !Array.isArray(latest.pendingSuccessfulApplyClicks)
    || !latest.pendingSuccessfulApplyClicks.some((entry) => entry?.jobId === jobId && entry?.clickId === clickId);
}

function resetSuccessfulApplyCount() {
  return serializeSuccessfulApplyCountUpdate(async () => {
    await chrome.storage.local.set({ successfulApplyCount: 0 });
    return { count: 0 };
  });
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function recordTabActivity(tabId) {
  if (tabId !== undefined && tabId !== null) {
    tabActivityTimestamps.set(tabId, Date.now());
  }
}

class VahanAuthRequiredError extends Error {
  constructor(hold) {
    super(vahanAuthHoldMessage(hold));
    this.name = "VahanAuthRequiredError";
    this.code = VAHAN_AUTH_REQUIRED_CODE;
    this.hold = hold;
  }
}

class VahanSessionExpiredError extends Error {
  constructor(message = vahanSessionExpiredMessage()) {
    super(message);
    this.name = "VahanSessionExpiredError";
    this.code = VAHAN_SESSION_EXPIRED_CODE;
  }
}

class VahanUnreachableError extends Error {
  constructor(detail = "") {
    super(vahanUnreachableMessage(detail));
    this.name = "VahanUnreachableError";
    this.code = VAHAN_UNREACHABLE_CODE;
    this.detail = detail;
  }
}

class VahanServerError extends Error {
  constructor(statusCode = 500) {
    super(`VAHAN server error (HTTP ${statusCode}). The site may be under maintenance.`);
    this.name = "VahanServerError";
    this.code = VAHAN_SERVER_ERROR_CODE;
    this.statusCode = statusCode;
  }
}

async function loadVahanAuthHold() {
  const stored = await chrome.storage.local.get(VAHAN_AUTH_HOLD_KEY);
  vahanAuthHold = stored?.[VAHAN_AUTH_HOLD_KEY] || undefined;
  if (!isVahanAuthHoldActive(vahanAuthHold)) {
    if (vahanAuthHold?.code === VAHAN_AUTH_REQUIRED_CODE
      && vahanAuthHold.guardVersion !== VAHAN_AUTH_GUARD_VERSION) {
      await chrome.storage.local.remove(VAHAN_AUTH_HOLD_KEY);
    }
    vahanAuthHold = undefined;
    chrome.action.setBadgeText?.({ text: "" });
  }
  return vahanAuthHold;
}

function notifyAuthChallengeWaiters(hold) {
  for (const waiter of authChallengeWaiters) {
    if (waiter.tabId === undefined || hold.tabId === null || waiter.tabId === hold.tabId) {
      waiter.reject(new VahanAuthRequiredError(hold));
    }
  }
}

function showAuthHoldBadge(hold) {
  chrome.action.setBadgeText?.({ text: "!" });
  chrome.action.setBadgeBackgroundColor?.({ color: "#b42318" });
  chrome.action.setTitle?.({ title: "VAHAN authentication required — automation paused" });
  chrome.runtime.sendMessage({ type: "VAHAN_AUTH_REQUIRED", authHold: hold }).catch(() => {});
}

function recordVahanAuthChallenge(details) {
  const hold = createVahanAuthHold(details, vahanAuthHold);
  vahanAuthHold = hold;
  notifyAuthChallengeWaiters(hold);
  showAuthHoldBadge(hold);

  // Serialize storage writes because the server may challenge several assets
  // for the same page at almost the same time.
  authHoldWrite = authHoldWrite
    .catch(() => {})
    .then(async () => {
      await chrome.storage.local.set({ [VAHAN_AUTH_HOLD_KEY]: hold });
      return hold;
    });
  return hold;
}

async function clearVahanAuthHold() {
  vahanAuthHold = undefined;
  await chrome.storage.local.remove(VAHAN_AUTH_HOLD_KEY);
  chrome.action.setBadgeText?.({ text: "" });
  chrome.action.setTitle?.({ title: "VAHAN RPA Assistant" });
  chrome.runtime.sendMessage({ type: "VAHAN_AUTH_CLEARED" }).catch(() => {});
}

async function assertNoVahanAuthHold(tabId) {
  const hold = vahanAuthHold || await loadVahanAuthHold();
  if (isVahanAuthHoldActive(hold, Date.now(), tabId)) {
    throw new VahanAuthRequiredError(hold);
  }
}

function installVahanAuthGuard() {
  if (!chrome.webRequest?.onAuthRequired?.addListener) return;

  // The extension never guesses credentials. Cancel the challenge instead of
  // allowing Chrome's native login dialog and stop all automation retries.
  chrome.webRequest.onAuthRequired.addListener(
    (details, respond) => {
      if (details.isProxy) {
        respond({});
        return;
      }
      if (!isVahanMainFrameAuthChallenge(details)) {
        // Do not let a protected image/API asset open an HTTP auth prompt or
        // pause the otherwise usable official report page.
        respond({ cancel: true });
        return;
      }
      const hold = recordVahanAuthChallenge(details);
      respond({ cancel: true });
    },
    { urls: ["https://analytics.parivahan.gov.in/*"] },
    ["asyncBlocking"],
  );

  // A normal top-level page load is the only automatic signal that the hold
  // can be cleared. It avoids retaining a stale lock after the user has
  // manually waited/reloaded the official page.
  chrome.webRequest.onCompleted?.addListener(
    (details) => {
      if (details.type !== "main_frame") return;
      if (details.statusCode >= 500 && isVahanRequestUrl(details.url)) {
        tabLastErrors.set(details.tabId, {
          type: "SERVER_ERROR",
          statusCode: details.statusCode,
          url: details.url,
          timestamp: Date.now(),
        });
      }
      if (details.statusCode >= 200 && details.statusCode < 300) {
        if (isVahanPublicReportUrl(details.url)) {
          recordTabActivity(details.tabId);
          tabLastErrors.delete(details.tabId);
        }
        if (!isVahanRequestUrl(details.url) || !vahanAuthHold) return;
        if (vahanAuthHold.tabId !== null && vahanAuthHold.tabId !== details.tabId) return;
        try {
          const completed = new URL(details.url);
          const challenged = new URL(vahanAuthHold.url);
          if (`${completed.origin}${completed.pathname}` !== `${challenged.origin}${challenged.pathname}`) return;
        } catch {
          return;
        }
        clearVahanAuthHold().catch(() => {});
      }
    },
    { urls: ["https://analytics.parivahan.gov.in/*"] },
  );

  if (chrome.webNavigation?.onErrorOccurred) {
    chrome.webNavigation.onErrorOccurred.addListener((details) => {
      if (details.frameId === 0 && isVahanRequestUrl(details.url)) {
        tabLastErrors.set(details.tabId, {
          type: "NETWORK_ERROR",
          error: details.error,
          url: details.url,
          timestamp: Date.now(),
        });
      }
    });
  }

  chrome.tabs.onRemoved?.addListener((tabId) => {
    tabActivityTimestamps.delete(tabId);
    tabLastErrors.delete(tabId);
    vahanPageHeartbeats.delete(tabId);
    vahanPageLivenessProbes.delete(tabId);
  });
}

async function reportJobStatus(jobId, status, error) {
  if (!socket?.connected) throw new Error("Backend is disconnected.");
  const response = await socket.timeout(5_000).emitWithAck("job:status", {
    jobId,
    status,
    ...(error ? { error } : {}),
  });
  if (!response?.ok) throw new Error(response?.error || `Could not report ${status}.`);
}

async function restorePreviousJobTab(activeServerJob) {
  const previousTabId = activeServerJob?.previousTabId;
  const vahanTabId = activeServerJob?.tabId;
  if (!Number.isInteger(previousTabId) || !Number.isInteger(vahanTabId) || previousTabId === vahanTabId) return;

  try {
    const [activeTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (activeTab?.id !== vahanTabId) return;
    const previousTab = await chrome.tabs.get(previousTabId);
    if (previousTab.windowId !== activeTab.windowId) return;
    await chrome.tabs.update(previousTabId, { active: true });
  } catch {
    // The user may have closed the original tab while the job was running.
  }
}

async function finishServerJob(activeServerJob) {
  if (!activeServerJob?.jobId) return;
  const { activeServerJob: storedJob } = await chrome.storage.local.get("activeServerJob");
  if (storedJob?.jobId && storedJob.jobId !== activeServerJob.jobId) return;
  await restorePreviousJobTab(activeServerJob);
  if (activeJobId === activeServerJob.jobId) activeJobId = undefined;
  await chrome.storage.local.remove(["pendingServerJob", "activeServerJob"]);
}

async function recoverStalledVahanPage(activeServerJob, stalledForMs) {
  const jobId = activeServerJob?.jobId;
  const tabId = activeServerJob?.tabId;
  if (!jobId || !Number.isInteger(tabId) || vahanPageStallRecoveryJobs.has(jobId)) return;
  vahanPageStallRecoveryJobs.add(jobId);
  let recoveryStarted = false;

  try {
    const { activeServerJob: currentJob } = await chrome.storage.local.get("activeServerJob");
    if (currentJob?.jobId !== jobId
      || !VAHAN_PAGE_STALL_MONITORED_STAGES.has(currentJob.stage)
      || (activeJobId && activeJobId !== jobId)) return;

    const tab = await chrome.tabs.get(tabId);
    const heartbeat = vahanPageHeartbeats.get(tabId);
    if (!isVahanPublicReportUrl(tab.url)
      || tab.status !== "complete"
      || tab.discarded
      || tab.frozen
      || !heartbeat
      || Date.now() - heartbeat.receivedAt < VAHAN_PAGE_STALL_TIMEOUT_MS
      || isVahanAuthHoldActive(vahanAuthHold, Date.now(), tabId)) return;

    const { activeServerJob: latestJob } = await chrome.storage.local.get("activeServerJob");
    if (latestJob?.jobId !== jobId || !VAHAN_PAGE_STALL_MONITORED_STAGES.has(latestJob.stage)) return;

    recoveryStarted = true;
    const seconds = Math.max(10, Math.round(stalledForMs / 1000));
    const recoveringJob = { ...latestJob, stage: "PAGE_STALLED_RELOADING" };
    cancelledJobIds.add(jobId);
    await chrome.storage.local.set({ activeServerJob: recoveringJob });

    let reloadDetail = "The page was reloaded.";
    try {
      await chrome.tabs.reload(tabId);
    } catch (error) {
      reloadDetail = `Reload failed: ${error.message}`;
    }

    const errorMessage = `VAHAN page stopped responding for about ${seconds} seconds. ${reloadDetail} This job was marked failed to prevent stale results.`;
    await reportJobStatus(jobId, "FAILED", errorMessage).catch((error) => {
      console.warn("[VAHAN EXT] Could not report the stalled page job:", error.message);
    });
    await finishServerJob(recoveringJob);
  } catch (error) {
    console.warn("[VAHAN EXT] Could not recover the stalled VAHAN page:", error.message);
  } finally {
    if (!recoveryStarted) vahanPageStallRecoveryJobs.delete(jobId);
    else {
      vahanPageHeartbeats.delete(tabId);
      vahanPageLivenessProbes.delete(tabId);
    }
  }
}

function requestVahanPageLivenessProbe(tabId) {
  if (vahanPageLivenessProbes.has(tabId)) return;
  const probe = chrome.scripting.executeScript({
    target: { tabId },
    func: () => ({ url: location.href, readyState: document.readyState }),
  });
  let trackedProbe;
  trackedProbe = probe.then((results) => {
    const result = results?.[0]?.result;
    if (result?.readyState === "complete" && isVahanPublicReportUrl(result.url)) {
      vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: false });
    }
  }).catch((error) => {
    // A timeout or frozen renderer leaves the last response timestamp stale;
    // the watchdog handles it. Transient navigation errors are retried.
    console.debug("[VAHAN EXT] Background page liveness probe did not respond:", error.message);
  }).finally(() => {
    if (vahanPageLivenessProbes.get(tabId) === trackedProbe) {
      vahanPageLivenessProbes.delete(tabId);
    }
  });
  vahanPageLivenessProbes.set(tabId, trackedProbe);
}

async function checkVahanPageStall() {
  const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
  if (!activeServerJob?.jobId
    || !VAHAN_PAGE_STALL_MONITORED_STAGES.has(activeServerJob.stage)
    || !Number.isInteger(activeServerJob.tabId)) return;

  const tabId = activeServerJob.tabId;
  let tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch {
    return;
  }
  if (!isVahanPublicReportUrl(tab.url) || tab.status !== "complete" || tab.discarded || tab.frozen) return;

  let heartbeat = vahanPageHeartbeats.get(tabId);
  if (!heartbeat) {
    heartbeat = { receivedAt: Date.now(), visible: Boolean(tab.active) };
    vahanPageHeartbeats.set(tabId, heartbeat);
    return;
  }
  if (!tab.active && Date.now() - heartbeat.receivedAt >= VAHAN_PAGE_LIVENESS_PROBE_INTERVAL_MS) {
    requestVahanPageLivenessProbe(tabId);
  }
  const stalledForMs = Date.now() - heartbeat.receivedAt;
  if (stalledForMs < VAHAN_PAGE_STALL_TIMEOUT_MS) return;
  await recoverStalledVahanPage(activeServerJob, stalledForMs);
}

function startVahanPageStallWatchdog() {
  if (vahanPageStallCheckTimer) return;
  vahanPageStallCheckTimer = setInterval(() => {
    if (vahanPageStallCheckTask) return;
    vahanPageStallCheckTask = checkVahanPageStall()
      .catch((error) => console.warn("[VAHAN EXT] Page responsiveness check failed:", error.message))
      .finally(() => { vahanPageStallCheckTask = undefined; });
  }, VAHAN_PAGE_STALL_CHECK_INTERVAL_MS);
}

async function publishCaptcha(jobId, captcha) {
  if (!socket?.connected) throw new Error("Backend is disconnected.");
  const response = await socket.timeout(5_000).emitWithAck("captcha:required", {
    jobId,
    captchaId: captcha.captchaId,
    imageDataUrl: captcha.imageDataUrl,
  });
  if (!response?.ok) throw new Error(response?.error || "Could not publish CAPTCHA.");
}

async function publishCaptchaChange(activeServerJob, captcha, event) {
  if (!captcha?.captchaId || !captcha?.imageDataUrl) {
    throw new Error("VAHAN did not return a valid fresh CAPTCHA.");
  }
  if (captcha.captchaId === activeServerJob.captchaId) {
    throw new Error("VAHAN returned the previous CAPTCHA image. Please try again.");
  }

  const updatedJob = {
    ...activeServerJob,
    captchaId: captcha.captchaId,
    stage: "WAITING_CAPTCHA",
  };
  // Persist first so the mutation observer cannot republish the same image
  // while the backend is delivering the event to the Web UI.
  await chrome.storage.local.set({ activeServerJob: updatedJob });
  await emitWithRetry(event, {
    jobId: activeServerJob.jobId,
    captchaId: captcha.captchaId,
    imageDataUrl: captcha.imageDataUrl,
  });
  return captcha;
}

async function requestFreshCaptcha(activeServerJob) {
  const captcha = await sendToVahan(activeServerJob.tabId, {
    type: "REFRESH_CAPTCHA",
    previousCaptchaId: activeServerJob.captchaId,
  });
  if (!captcha?.ok) throw new Error(captcha?.error || "Could not refresh the official VAHAN CAPTCHA.");
  return captcha;
}

async function emitWithRetry(event, payload, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      if (!socket?.connected) throw new Error("Backend is disconnected.");
      const response = await socket.timeout(5_000).emitWithAck(event, payload);
      if (!response?.ok) throw new Error(response?.error || `${event} was rejected.`);
      return response;
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await delay(500 * attempt);
    }
  }
  throw lastError;
}

function assertJobActive(jobId) {
  if (cancelledJobIds.has(jobId)) throw new Error("Job was cancelled.");
}

async function verifyTabUrl(tabId) {
  const tab = await chrome.tabs.get(tabId);
  const url = tab?.url || "";
  if (isChromeErrorUrl(url)) {
    const lastError = tabLastErrors.get(tabId);
    throw new VahanUnreachableError(lastError?.error || "Connection error");
  }
  const lastError = tabLastErrors.get(tabId);
  if (lastError && lastError.type === "SERVER_ERROR" && Date.now() - lastError.timestamp < 15_000) {
    throw new VahanServerError(lastError.statusCode);
  }
  if (isVahanRedirectedHomeUrl(url)) {
    throw new VahanSessionExpiredError();
  }
  return tab;
}

async function waitForTabComplete(tabId, timeout = 30_000) {
  await assertNoVahanAuthHold(tabId);
  const current = await chrome.tabs.get(tabId);
  if (current.status === "complete") {
    await verifyTabUrl(tabId);
    return;
  }
  await new Promise((resolve, reject) => {
    let settled = false;
    const authWaiter = {
      tabId,
      reject: (error) => finish(reject, error),
    };
    const authPoll = setInterval(() => {
      assertNoVahanAuthHold(tabId).catch((error) => finish(reject, error));
    }, 250);
    const timer = setTimeout(() => {
      finish(reject, new Error("VAHAN page did not finish loading in time."));
    }, timeout);
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      clearInterval(authPoll);
      chrome.tabs.onUpdated.removeListener(listener);
      authChallengeWaiters.delete(authWaiter);
      callback(value);
    };
    const listener = (updatedId, changeInfo) => {
      if (updatedId !== tabId || changeInfo.status !== "complete") return;
      verifyTabUrl(tabId)
        .then(() => finish(resolve))
        .catch((error) => finish(reject, error));
    };
    authChallengeWaiters.add(authWaiter);
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function getVahanTab() {
  await assertNoVahanAuthHold();
  const tabs = await chrome.tabs.query({ url: "https://analytics.parivahan.gov.in/analytics/vahanpublicreport*" });
  // Prefer a warm, inactive page so starting a report never steals the user's
  // current tab when another VAHAN page is already open.
  let tab = tabs.find((candidate) => !candidate.discarded && !candidate.active)
    || tabs.find((candidate) => !candidate.discarded)
    || tabs[0];
  let forceReload = Boolean(tab?.discarded);

  if (tab?.id) {
    const lastActive = tabActivityTimestamps.get(tab.id) || 0;
    const isStale = (Date.now() - lastActive) > MAX_TAB_IDLE_AGE_MS;
    if (isStale || !isVahanPublicReportUrl(tab.url)) {
      forceReload = true;
    }
  } else {
    tab = await chrome.tabs.create({ url: VAHAN_URL, active: false });
  }

  if (!tab.id) throw new Error("Chrome did not return a VAHAN tab id.");

  // Keep Chrome's memory manager from discarding the warm DOM between cases.
  // The page stays inactive; selectors/results are observed with DOM events.
  if (tab.autoDiscardable !== false) {
    await chrome.tabs.update(tab.id, { autoDiscardable: false });
  }

  if (forceReload) {
    await chrome.tabs.update(tab.id, { url: VAHAN_URL });
  }

  try {
    await waitForTabComplete(tab.id, INITIAL_PAGE_LOAD_TIMEOUT_MS);
  } catch (error) {
    // An auth-hold or resilience rejection is surfaced immediately
    if (error instanceof VahanAuthRequiredError
      || error instanceof VahanUnreachableError
      || error instanceof VahanServerError
      || error instanceof VahanSessionExpiredError) {
      throw error;
    }
    if (!String(error?.message).includes("did not finish loading")) {
      throw error;
    }
    // Cross-border network slowness is transient: reload once and give the
    // page one more chance before giving up.
    await chrome.tabs.reload(tab.id);
    try {
      await waitForTabComplete(tab.id, INITIAL_PAGE_LOAD_TIMEOUT_MS);
    } catch (retryError) {
      if (retryError instanceof VahanUnreachableError
        || retryError instanceof VahanServerError
        || retryError instanceof VahanSessionExpiredError) {
        throw retryError;
      }
      throw new Error("VAHAN page did not finish loading after a retry — the site may be down or extremely slow.");
    }
  }

  await assertNoVahanAuthHold(tab.id);
  recordTabActivity(tab.id);
  return tab.id;
}

async function getOptionsTab() {
  return getVahanTab();
}

async function sendToVahan(tabId, message) {
  let reloadAttempted = false;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    try {
      await assertNoVahanAuthHold(tabId);
      return await chrome.tabs.sendMessage(tabId, message);
    } catch (error) {
      await assertNoVahanAuthHold(tabId);
      if (String(error?.message).includes("Receiving end")) {
        try {
          const currentTab = await chrome.tabs.get(tabId);
          if (isChromeErrorUrl(currentTab?.url)) {
            const lastError = tabLastErrors.get(tabId);
            throw new VahanUnreachableError(lastError?.error || "Connection error");
          }
          if (isVahanRedirectedHomeUrl(currentTab?.url)) {
            throw new VahanSessionExpiredError();
          }
        } catch (inspectError) {
          if (inspectError instanceof VahanUnreachableError || inspectError instanceof VahanSessionExpiredError) {
            throw inspectError;
          }
        }
      }
      if (attempt === 0 && String(error?.message).includes("Receiving end")) {
        reloadAttempted = true;
        await chrome.tabs.reload(tabId);
        await waitForTabComplete(tabId);
      }
      if (attempt === 5 || (reloadAttempted && attempt > 0)) {
        try {
          const finalTab = await chrome.tabs.get(tabId);
          if (isChromeErrorUrl(finalTab?.url)) {
            throw new VahanUnreachableError();
          }
          if (isVahanRedirectedHomeUrl(finalTab?.url)) {
            throw new VahanSessionExpiredError();
          }
        } catch (finalInspectError) {
          if (finalInspectError instanceof VahanUnreachableError || finalInspectError instanceof VahanSessionExpiredError) {
            throw finalInspectError;
          }
        }
        throw error;
      }
      await delay(500);
    }
  }
}

function isLikelyExcelDownload(item, tabId) {
  if (!item || item.id === undefined) return false;
  if (Number.isInteger(item.tabId) && item.tabId >= 0 && item.tabId !== tabId) return false;
  const url = String(item.url || "").toLocaleLowerCase();
  if (!url.startsWith("blob:https://analytics.parivahan.gov.in/")
    && !isVahanRequestUrl(url)) return false;
  if (url.startsWith("blob:")) return true;
  const source = `${url} ${item.filename || ""}`;
  return /(?:\.xlsx?(?:$|[?#])|\.xlsm(?:$|[?#])|excel|spreadsheet|export)/i.test(source);
}

async function triggerAndWaitForExcelDownload(activeServerJob) {
  const { tabId, jobId } = activeServerJob;
  const captureId = crypto.randomUUID();
  // The page-level bridge (interceptor-main.js / content.js) suppresses the
  // native browser download and hands us the exact bytes instead. The only
  // copy of the report is the one this function uploads to the API server.
  // The listeners below are a secondary defense: if suppression ever fails
  // (e.g. a VAHAN change bypasses the patched click path), cancel and erase
  // any Excel-looking download that slips through so it never lands as a
  // second, unmanaged copy on the user's machine.
  let resolveBlob;
  let rejectBlob;
  let blobTimer;

  const blobPromise = new Promise((resolve, reject) => {
    resolveBlob = resolve;
    rejectBlob = reject;
    blobTimer = setTimeout(() => {
      reject(new Error("Excel file bytes were not captured within 60 seconds."));
    }, 60_000);
  });

  const onCreated = (item) => {
    if (!isLikelyExcelDownload(item, tabId)) return;
    try {
      chrome.downloads.cancel(item.id, () => {
        chrome.downloads.erase({ id: item.id }, () => {});
      });
    } catch (e) {}

    // If the page used a download URL rather than the URL.createObjectURL
    // path, ask the tab to copy that source into the same upload bridge so we
    // still capture the bytes despite the suppression having missed it.
    if (item.url) {
      sendToVahan(tabId, {
        type: "CAPTURE_EXCEL_DOWNLOAD",
        href: item.url,
        fileName: item.filename?.split(/[\\/]/).pop() || "report.xlsx",
        captureId,
      }).catch(() => {});
    }
  };

  const blobResolver = (data) => {
    clearTimeout(blobTimer);
    if (data?.error || !data?.dataUrl || !String(data.dataUrl).startsWith("data:")) {
      rejectBlob(new Error(data?.error || "Excel file bytes were not captured correctly."));
    } else {
      resolveBlob(data);
    }
    if (pendingBlobResolver === blobResolver) pendingBlobResolver = undefined;
    resolveBlob = () => {};
    rejectBlob = () => {};
  };
  pendingBlobResolver = blobResolver;
  pendingReportCapture = { tabId, captureId };
  chrome.downloads.onCreated.addListener(onCreated);

  try {
    const response = await sendToVahan(tabId, { type: "CLICK_EXCEL_DOWNLOAD", captureId });
    if (!response?.ok) {
      rejectBlob(new Error(response?.error || "Could not click the Excel download button."));
    }

    const { dataUrl, fileName } = await blobPromise;

    // Upload to API server.
    const { activeServerJob: currentJob } = await chrome.storage.local.get("activeServerJob");
    if (currentJob?.jobId !== jobId) throw new Error("The active job changed before the Excel upload.");
    assertJobActive(jobId);
    await chrome.storage.local.set({
      activeServerJob: { ...activeServerJob, stage: "UPLOADING_REPORT" },
    });

    const config = await loadRunnerConfig();
    const serverUrl = config.serverUrl || "http://127.0.0.1:8000";

    // Convert data URL to Blob for upload.
    const blobResponse = await fetch(dataUrl);
    if (!blobResponse.ok) {
      throw new Error(`Could not decode the captured Excel file (${blobResponse.status}).`);
    }
    const blob = await blobResponse.blob();
    if (!blob.size) throw new Error("The captured Excel file is empty.");
    const uploadFileName = activeServerJob?.scenarioName
      ? `${activeServerJob.scenarioName.replace(/[\\/*?:"<>|\r\n\t]/g, "_").trim()}.xlsx`
      : (fileName || "report.xlsx");
    const uploadController = new AbortController();
    pendingReportUploadController = uploadController;
    try {
      assertJobActive(jobId);
      const result = await uploadCapturedReport({
        serverUrl, jobId, runnerId: config.runnerId, token: config.token,
        blob, fileName: uploadFileName,
        signal: uploadController.signal,
      });
      assertJobActive(jobId);
      return result;
    } finally {
      if (pendingReportUploadController === uploadController) pendingReportUploadController = undefined;
    }
  } finally {
    clearTimeout(blobTimer);
    chrome.downloads.onCreated.removeListener(onCreated);
    if (pendingBlobResolver === blobResolver) pendingBlobResolver = undefined;
    if (pendingReportCapture?.captureId === captureId) pendingReportCapture = undefined;
    await chrome.tabs.sendMessage(tabId, { type: "END_EXCEL_CAPTURE", captureId }).catch(() => {});
  }
}


async function executeJob(job) {
  const jobId = String(job?.jobId || "");
  if (!jobId) return;
  if (activeJobId === jobId) return;
  if (activeJobId) {
    console.warn(`[VAHAN EXT] Preempting stale job ${activeJobId} with new job ${jobId}`);
    const staleJobId = activeJobId;
    cancelledJobIds.add(staleJobId);
    const { activeServerJob: staleServerJob } = await chrome.storage.local.get("activeServerJob");
    if (staleServerJob?.jobId === staleJobId) await finishServerJob(staleServerJob);
    else {
      activeJobId = undefined;
      await chrome.storage.local.remove(["pendingServerJob", "activeServerJob"]);
    }
  }

  activeJobId = jobId;
  cancelledJobIds.delete(jobId);
  await chrome.storage.local.set({ pendingServerJob: job });
  chrome.runtime.sendMessage({ type: "SERVER_JOB_ASSIGNED", job }).catch(() => {});

  let tabId;
  try {
    await reportJobStatus(jobId, "OPENING_VAHAN");
    tabId = await getVahanTab();
    assertJobActive(jobId);
    const vahanTab = await chrome.tabs.get(tabId);
    vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: Boolean(vahanTab.active) });
    await chrome.storage.local.set({ pendingServerJob: { ...job, tabId } });

    const config = normalizeJobFilters(job.filters);
    await chrome.storage.local.set({
      pendingServerJob: { ...job, tabId },
      activeServerJob: { ...job, tabId, config, stage: "FILLING_FILTERS", executionMode: "background" },
    });

    // Configure the inactive page before publishing the CAPTCHA so the user
    // only has to enter it in the Web UI, without switching to the official site.
    await reportJobStatus(jobId, "FILLING_FILTERS");
    let fillResponse = await sendToVahan(tabId, { type: "FILL_VAHAN", config });
    if (!fillResponse?.ok && String(fillResponse?.error || "").startsWith("#stateName:")) {
      // VAHAN can retain the previous case's regional State option list after
      // switching to ALL STATES. Open the report URL afresh once, then fill
      // the entire case again so no stale dependent filter can survive.
      await chrome.tabs.update(tabId, { url: VAHAN_URL });
      await waitForTabComplete(tabId, INITIAL_PAGE_LOAD_TIMEOUT_MS);
      assertJobActive(jobId);
      fillResponse = await sendToVahan(tabId, { type: "FILL_VAHAN", config });
    }
    if (!fillResponse?.ok) throw new Error(fillResponse?.error || "VAHAN did not accept the filters.");
    assertJobActive(jobId);
    const { vahanConfig = {} } = await chrome.storage.local.get("vahanConfig");
    await chrome.storage.local.set({ vahanConfig: { ...vahanConfig, ...config } });

    await chrome.storage.local.set({
      activeServerJob: { ...job, tabId, config, filtersFilled: true, stage: "CAPTURING_CAPTCHA", executionMode: "background" },
    });
    await reportJobStatus(jobId, "CAPTURING_CAPTCHA");
    const captcha = await sendToVahan(tabId, { type: "CAPTURE_CAPTCHA" });
    if (!captcha?.ok) throw new Error(captcha?.error || "Could not capture the CAPTCHA.");
    assertJobActive(jobId);
    await chrome.storage.local.set({
      activeServerJob: {
        ...job, tabId, config, filtersFilled: true, executionMode: "background",
        captchaId: captcha.captchaId, stage: "WAITING_CAPTCHA", attempts: 0,
      },
    });
    await publishCaptcha(jobId, captcha);
  } catch (error) {
    if (!cancelledJobIds.has(jobId)) {
      const authHeld = isVahanAuthHoldActive(vahanAuthHold, Date.now(), tabId);
      if (!(authHeld && authFailureReportedJobs.has(jobId))) {
        let errorMessage = error.message;
        if (authHeld) {
          errorMessage = `${VAHAN_AUTH_REQUIRED_CODE}: ${vahanAuthHoldMessage(vahanAuthHold)}`;
        } else if (error.code) {
          errorMessage = `${error.code}: ${error.message}`;
        }
        await reportJobStatus(
          jobId,
          "FAILED",
          errorMessage,
        ).catch(() => {});
        if (authHeld) authFailureReportedJobs.add(jobId);
      }
    }
    await finishServerJob({ jobId, tabId });
  }
}

async function loadRunnerConfig() {
  const { runnerConfig = {} } = await chrome.storage.local.get("runnerConfig");
  const normalized = {
    ...DEFAULT_RUNNER_CONFIG,
    ...runnerConfig,
    runnerId: runnerConfig.runnerId || crypto.randomUUID(),
  };
  if (JSON.stringify(normalized) !== JSON.stringify(runnerConfig)) {
    await chrome.storage.local.set({ runnerConfig: normalized });
  }
  return normalized;
}

async function publishConnection(status, detail = "") {
  const connection = {
    status,
    detail,
    runnerId: activeConfig?.runnerId || null,
    serverUrl: activeConfig?.serverUrl || null,
    updatedAt: new Date().toISOString(),
  };
  await chrome.storage.local.set({ runnerConnection: connection });
  chrome.runtime.sendMessage({ type: "RUNNER_CONNECTION_CHANGED", connection }).catch(() => {});
}

function stopHeartbeat() {
  clearInterval(heartbeatTimer);
  heartbeatTimer = undefined;
}

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (!socket?.connected) return;
    socket.timeout(5_000).emit("runner:heartbeat", { timestamp: Date.now() }, (error, response) => {
      if (error || !response?.ok) {
        const detail = error?.message || response?.error || "Heartbeat failed.";
        publishConnection("error", detail);
        if (!error && response?.ok === false && /not registered/i.test(response.error || "")) {
          void connectRunner({ force: true }).catch(() => {});
        }
      }
    });
  }, HEARTBEAT_INTERVAL_MS);
}

async function connectRunnerOnce() {
  clearTimeout(reconnectTimer);
  activeConfig = await loadRunnerConfig();
  void uiHealthCheckController?.refreshScheduleFromBackend();
  socket?.removeAllListeners();
  socket?.disconnect();

  await publishConnection("connecting", "Connecting to backend...");
  socket = io(`${activeConfig.serverUrl}/runner`, {
    transports: ["websocket"],
    auth: {
      runnerId: activeConfig.runnerId,
      runnerName: activeConfig.runnerName,
      source: "new",
      token: activeConfig.token,
      version: chrome.runtime.getManifest().version,
    },
    reconnection: true,
    reconnectionAttempts: Infinity,
    reconnectionDelay: 1_000,
    reconnectionDelayMax: 10_000,
    timeout: 10_000,
  });

  socket.on("connect", async () => {
    publishConnection("connected", "Backend connected.");
    startHeartbeat();
    await flushPendingSuccessfulApplyClicks();
    const { activeServerJob, pendingServerJob } = await chrome.storage.local.get([
      "activeServerJob",
      "pendingServerJob",
    ]);
    if (activeServerJob?.jobId) {
      // A temporary socket reconnect does not restart the running workflow.
      // Keep the captured bytes/upload retry and its job association alive.
      if (activeJobId === activeServerJob.jobId && !cancelledJobIds.has(activeJobId)) return;
      await reportJobStatus(activeServerJob.jobId, "FAILED", "Extension reconnected or restarted.").catch(() => {});
      await restorePreviousJobTab(activeServerJob);
    } else if (pendingServerJob?.jobId) {
      if (activeJobId === pendingServerJob.jobId && !cancelledJobIds.has(activeJobId)) return;
      await restorePreviousJobTab(pendingServerJob);
    }
    activeJobId = undefined;
    await chrome.storage.local.remove(["pendingServerJob", "activeServerJob"]);
  });

  socket.on("disconnect", (reason) => {
    stopHeartbeat();
    publishConnection("disconnected", `Disconnected: ${reason}`);
  });

  socket.on("connect_error", (error) => {
    stopHeartbeat();
    publishConnection("error", error.message || "Could not connect to backend.");
  });

  socket.on("ui-health:schedule-updated", (schedule) => {
    uiHealthCheckController?.updateSchedule(schedule?.intervalDays).catch((error) => {
      console.warn("[VAHAN UI HEALTH] Could not update the check schedule:", error.message);
    });
  });

  socket.on("ui-health:run-now", (request = {}) => {
    uiHealthCheckController?.run("manual-web").then((healthCheck) => {
      console.info(
        "[VAHAN UI HEALTH] Immediate official-tab check completed:",
        request.requestId || "unknown-request",
        healthCheck.status,
      );
    }).catch((error) => {
      console.warn("[VAHAN UI HEALTH] Immediate check failed:", error.message);
    });
  });

  socket.io.on("reconnect_attempt", () => {
    publishConnection("connecting", "Reconnecting to backend...");
  });

  socket.on("job:assigned", (job) => executeJob(job).catch(async (error) => {
    const jobId = String(job?.jobId || "");
    if (jobId) await reportJobStatus(jobId, "FAILED", error.message).catch(() => {});
    if (activeJobId === jobId) activeJobId = undefined;
  }));
  socket.on("job:cancelled", async ({ jobId }) => {
    const id = String(jobId);
    cancelledJobIds.add(id);
    if (pendingBlobResolver) pendingBlobResolver(null);
    pendingReportUploadController?.abort();
    const { activeServerJob, pendingServerJob } = await chrome.storage.local.get([
      "activeServerJob",
      "pendingServerJob",
    ]);
    if (activeServerJob?.jobId === id) await finishServerJob(activeServerJob);
    else if (pendingServerJob?.jobId === id) {
      await restorePreviousJobTab(pendingServerJob);
      await chrome.storage.local.remove("pendingServerJob");
    }
    if (activeJobId === id) activeJobId = undefined;
  });
  socket.on("captcha:submit", async (payload, acknowledge) => {
    const jobId = String(payload?.jobId || "");
    let activeServerJob;
    try {
      ({ activeServerJob } = await chrome.storage.local.get("activeServerJob"));
      if (!activeServerJob
        || activeServerJob.jobId !== jobId
        || activeServerJob.stage !== "WAITING_CAPTCHA"
        || (activeJobId && activeJobId !== jobId)) {
        throw new Error("The active VAHAN job no longer matches this CAPTCHA.");
      }
      activeJobId = jobId;
      if (activeServerJob.captchaId !== payload.captchaId) {
        throw new Error("The CAPTCHA has changed or expired.");
      }
      assertJobActive(jobId);
      const attempts = (activeServerJob.attempts || 0) + 1;
      await chrome.storage.local.set({
        activeServerJob: {
          ...activeServerJob,
          stage: "SUBMITTING",
          attempts,
        },
      });

      if (!activeServerJob.filtersFilled) throw new Error("VAHAN filters are not ready yet.");
      assertJobActive(jobId);

      // Confirm the final CAPTCHA identity before forwarding the recognized or
      // user-entered text to VAHAN.
      const currentCaptcha = await sendToVahan(activeServerJob.tabId, { type: "CAPTURE_CAPTCHA" });
      if (!currentCaptcha?.ok) {
        throw new Error(currentCaptcha?.error || "Could not verify the current CAPTCHA.");
      }
      if (currentCaptcha.captchaId !== activeServerJob.captchaId) {
        await chrome.storage.local.set({
          activeServerJob: {
            ...activeServerJob,
            captchaId: currentCaptcha.captchaId,
            stage: "WAITING_CAPTCHA",
            attempts: attempts - 1,
          },
        });
        await reportJobStatus(jobId, "WAITING_CAPTCHA");
        await publishCaptcha(jobId, currentCaptcha);
        acknowledge({ ok: true, refreshed: true });
        return;
      }

      const response = await sendToVahan(activeServerJob.tabId, {
        type: "SUBMIT_REMOTE_CAPTCHA",
        value: String(payload.value || ""),
        autoApply: activeServerJob.config.autoApply ?? false,
      });
      if (!response?.ok) throw new Error(response?.error || "Could not fill the CAPTCHA on VAHAN.");
      await chrome.storage.local.set({
        activeServerJob: {
          ...activeServerJob,
          stage: "WAITING_RESULT",
          attempts,
        },
      });
      await reportJobStatus(jobId, "WAITING_RESULT");
      acknowledge({ ok: true });
    } catch (error) {
      await reportJobStatus(jobId, "FAILED", error.message).catch(() => {});
      if (activeServerJob?.jobId === jobId) await finishServerJob(activeServerJob);
      acknowledge({ ok: false, error: error.message });
    }
  });
  socket.on("captcha:refresh", async (payload, acknowledge) => {
    const jobId = String(payload?.jobId || "");
    try {
      const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
      if (!activeServerJob || activeServerJob.jobId !== jobId || activeServerJob.stage !== "WAITING_CAPTCHA") {
        throw new Error("The job is not waiting for a CAPTCHA refresh.");
      }
      if (activeServerJob.captchaId !== payload?.captchaId) {
        throw new Error("The CAPTCHA has changed or expired.");
      }
      assertJobActive(jobId);
      const captcha = await requestFreshCaptcha(activeServerJob);
      await publishCaptchaChange(activeServerJob, captcha, "captcha:refreshed");
      acknowledge({ ok: true, captcha: {
        jobId,
        captchaId: captcha.captchaId,
        imageDataUrl: captcha.imageDataUrl,
      } });
    } catch (error) {
      acknowledge({ ok: false, error: error.message });
    }
  });
  socket.on("runner:options", async (request, acknowledge) => {
    try {
      const tabId = await getOptionsTab();
      const messageByType = {
        GET_ALL_OPTIONS: {
          type: "GET_VAHAN_OPTIONS",
          selectors: VAHAN_OPTION_SELECTORS,
        },
        GET_STATE_OPTIONS: { type: "GET_STATE_OPTIONS", delhiNcr: request.delhiNcr },
        GET_RTO_OPTIONS: { type: "GET_RTO_OPTIONS", stateLabels: request.stateLabels },
        GET_X_AXIS_OPTIONS: { type: "GET_X_AXIS_OPTIONS", yAxis: request.yAxis },
        SEARCH_MAKERS: { type: "SEARCH_MAKERS", search: request.search },
      };
      const message = messageByType[request.type];
      if (!message) throw new Error("Unsupported VAHAN options request.");
      acknowledge(await sendToVahan(tabId, message));
    } catch (error) {
      acknowledge({ ok: false, error: error.message });
    }
  });
}

function connectRunner({ force = false } = {}) {
  if (runnerConnectionTask) {
    runnerReconnectRequested ||= force;
    return runnerConnectionTask;
  }

  const task = (async () => {
    do {
      runnerReconnectRequested = false;
      await connectRunnerOnce();
    } while (runnerReconnectRequested);
  })()
    .catch(async (error) => {
      stopHeartbeat();
      await publishConnection("error", error?.message || "Could not start the backend connection.").catch(() => {});
      throw error;
    })
    .finally(() => {
      if (runnerConnectionTask === task) runnerConnectionTask = undefined;
    });
  runnerConnectionTask = task;
  return task;
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== RUNNER_CONNECTION_ALARM || socket?.active) return;
  void connectRunner().catch(() => {});
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "loading") {
    vahanPageHeartbeats.delete(tabId);
    vahanPageLivenessProbes.delete(tabId);
    return;
  }
  if (changeInfo.status === "complete" && isVahanPublicReportUrl(tab.url)) {
    vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: Boolean(tab.active) });
  }
});

function refreshVahanHeartbeatAfterFocus(tabId) {
  chrome.tabs.get(tabId).then((tab) => {
    if (isVahanPublicReportUrl(tab.url)) {
      vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: true });
    }
  }).catch(() => {});
}

chrome.tabs.onActivated.addListener(({ tabId }) => refreshVahanHeartbeatAfterFocus(tabId));
chrome.windows.onFocusChanged.addListener((windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) return;
  chrome.tabs.query({ active: true, windowId }).then((tabs) => {
    const tab = tabs[0];
    if (tab?.id && isVahanPublicReportUrl(tab.url)) {
      vahanPageHeartbeats.set(tab.id, { receivedAt: Date.now(), visible: true });
    }
  }).catch(() => {});
});

async function handlePageResult(message, sender) {
  const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
  if (!activeServerJob
    || activeServerJob.stage === "PAGE_STALLED_RELOADING"
    || (activeJobId && activeServerJob.jobId !== activeJobId)) return;
  if (!matchesJobPageResult(message, sender, activeServerJob)) return;
  activeJobId = activeServerJob.jobId;
  if (sender.tab?.id !== activeServerJob.tabId) return;
  const jobId = activeServerJob.jobId;

  if (message.result === "AUTH_REQUIRED") {
    const hold = vahanAuthHold || await loadVahanAuthHold();
    await reportJobStatus(
      jobId,
      "FAILED",
      `${VAHAN_AUTH_REQUIRED_CODE}: ${vahanAuthHoldMessage(hold || {})}`,
    ).catch(() => {});
    await finishServerJob(activeServerJob);
    return;
  }

  if (message.result === "INVALID_CAPTCHA") {
    if ((activeServerJob.attempts || 0) >= 3) {
      await reportJobStatus(jobId, "FAILED", "CAPTCHA was invalid 3 consecutive times.").catch(() => {});
      await finishServerJob(activeServerJob);
      return;
    }
    // A VAHAN invalid-message node can arrive before it swaps the image. Never
    // return that old image to the FE: force an official refresh if needed.
    let captcha = message.captcha;
    if (!captcha?.captchaId || !captcha?.imageDataUrl || captcha.captchaId === activeServerJob.captchaId) {
      captcha = await requestFreshCaptcha(activeServerJob);
    }
    await publishCaptchaChange(activeServerJob, captcha, "captcha:invalid");
    return;
  }

  if (message.result === "DOWNLOAD_READY") {
    if (reportJobInFlight === jobId || ["DOWNLOADING_REPORT", "UPLOADING_REPORT"].includes(activeServerJob.stage)) return;
    reportJobInFlight = jobId;
    try {
      assertJobActive(jobId);
      await chrome.storage.local.set({
        activeServerJob: { ...activeServerJob, stage: "DOWNLOADING_REPORT" },
      });
      await triggerAndWaitForExcelDownload(activeServerJob);
      assertJobActive(jobId);
      await emitWithRetry("job:status", { jobId, status: "COMPLETED" });
    } catch (error) {
      if (!cancelledJobIds.has(jobId)) {
        await reportJobStatus(jobId, "FAILED", error.message).catch(() => {});
      }
    } finally {
      if (reportJobInFlight === jobId) reportJobInFlight = undefined;
    }
    await finishServerJob(activeServerJob);
    return;
  }

  if (message.result === "COMPLETED") {
    await reportJobStatus(jobId, "FAILED", "The page did not provide a captured Excel report.").catch(() => {});
    await finishServerJob(activeServerJob);
    return;
  }

  if (message.result === "NO_RECORD") {
    await reportJobStatus(jobId, "NO_DATA");
    await finishServerJob(activeServerJob);
    return;
  }

  if (message.result === "FAILED") {
    await reportJobStatus(jobId, "FAILED", message.error || "VAHAN did not return a result.").catch(() => {});
    await finishServerJob(activeServerJob);
  }
}

async function handleCaptchaChanged(message, sender) {
  const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
  if (!activeServerJob || activeServerJob.stage !== "WAITING_CAPTCHA") return;
  if (sender.tab?.id !== activeServerJob.tabId) return;
  const captcha = message.captcha;
  if (!captcha?.captchaId || !captcha?.imageDataUrl || captcha.captchaId === activeServerJob.captchaId) return;
  await publishCaptchaChange(activeServerJob, captcha, "captcha:refreshed");
}

chrome.runtime.onInstalled.addListener(() => { void connectRunner().catch(() => {}); });
chrome.runtime.onStartup.addListener(() => { void connectRunner().catch(() => {}); });

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local" || !changes.runnerConfig) return;
  const nextConfig = changes.runnerConfig.newValue;
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    if (JSON.stringify(nextConfig) !== JSON.stringify(activeConfig)) {
      void connectRunner({ force: true }).catch(() => {});
    }
  }, 250);
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "VAHAN_PAGE_HEARTBEAT") {
    const tabId = sender?.tab?.id;
    if (sender?.id !== chrome.runtime.id
      || !Number.isInteger(tabId)
      || !isVahanPublicReportUrl(sender.url)
      || typeof message.visible !== "boolean") {
      sendResponse({ ok: false, error: "Invalid VAHAN page heartbeat." });
      return;
    }
    vahanPageHeartbeats.set(tabId, { receivedAt: Date.now(), visible: message.visible });
    sendResponse({ ok: true });
    return;
  }

  if (message?.type === "COUNT_SUCCESSFUL_APPLY_CLICK") {
    if (!isVahanPublicReportUrl(sender?.url) || typeof message.clickId !== "string" || !message.clickId) {
      sendResponse({ ok: false, error: "Invalid VAHAN Apply click." });
      return;
    }
    Promise.all([
      recordSuccessfulApplyClick(message.clickId),
      chrome.storage.local.get("activeServerJob"),
    ])
      .then(async ([{ count, duplicate }, { activeServerJob }]) => {
        const jobId = typeof activeServerJob?.jobId === "string" ? activeServerJob.jobId : "";
        const serverRecorded = jobId ? await queueSuccessfulApplyClickForJob(jobId, message.clickId).catch(() => false) : null;
        sendResponse({ ok: true, count, duplicate, serverRecorded });
      })
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "RESET_SUCCESSFUL_APPLY_COUNT") {
    resetSuccessfulApplyCount()
      .then(({ count }) => sendResponse({ ok: true, count }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "SERVER_CAPTCHA_CHANGED") {
    handleCaptchaChanged(message, sender)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message?.type === "EXCEL_BLOB_CAPTURED") {
    if (!matchesReportCapture(message, sender, pendingReportCapture)) {
      sendResponse({ ok: false, error: "Excel capture does not match the active report." });
      return;
    }
    if (pendingBlobResolver) {
      pendingBlobResolver({ dataUrl: message.dataUrl, fileName: message.fileName });
    }
    sendResponse({ ok: true });
    return true;
  }

  if (message?.type === "EXCEL_BLOB_FAILED") {
    if (!matchesReportCapture(message, sender, pendingReportCapture)) {
      sendResponse({ ok: false, error: "Excel capture does not match the active report." });
      return;
    }
    if (pendingBlobResolver) pendingBlobResolver({ error: message.error });
    sendResponse({ ok: true });
    return true;
  }

  if (message?.type === "SERVER_JOB_PAGE_RESULT") {
    handlePageResult(message, sender)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "OPEN_ACTION_POPUP") {
    if (typeof chrome.action.openPopup !== "function") {
      sendResponse({ ok: false, error: "This feature requires Google Chrome 127 or later." });
      return;
    }
    chrome.action.openPopup()
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "GET_RUNNER_CONNECTION") {
    chrome.storage.local.get("runnerConnection").then(({ runnerConnection }) => {
      sendResponse({ ok: true, connection: runnerConnection || { status: "disconnected" } });
    });
    return true;
  }

  if (message?.type === "GET_VAHAN_AUTH_HOLD") {
    (async () => {
      const hold = vahanAuthHold || await loadVahanAuthHold();
      sendResponse({ ok: true, authHold: isVahanAuthHoldActive(hold) ? hold : null });
    })().catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "CLEAR_VAHAN_AUTH_HOLD") {
    clearVahanAuthHold()
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "RELOAD_VAHAN_PAGE") {
    (async () => {
      await clearVahanAuthHold();
      const tabs = await chrome.tabs.query({ url: "https://analytics.parivahan.gov.in/*" });
      if (tabs[0]?.id) {
        await chrome.tabs.update(tabs[0].id, { url: VAHAN_URL });
        return { ok: true };
      }
      await chrome.tabs.create({ url: VAHAN_URL });
      return { ok: true };
    })()
      .then(sendResponse)
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "RECONNECT_RUNNER") {
    connectRunner({ force: true })
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
});

startVahanPageStallWatchdog();

// UI Drift Guard is registered as an isolated listener. It owns only the
// configured read-only health check, backend CSV delivery and pending Dev
// alert; the MVP runner/job flow above remains unchanged.
uiHealthCheckController = registerUiHealthCheck(chrome);
installVahanAuthGuard();
void loadVahanAuthHold();
chrome.alarms.create(RUNNER_CONNECTION_ALARM, { periodInMinutes: 0.5 });
void connectRunner().catch(() => {});
