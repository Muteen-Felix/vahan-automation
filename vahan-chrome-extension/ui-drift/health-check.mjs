import {
  VAHAN_AUTH_HOLD_KEY,
  isVahanAuthHoldActive,
  vahanAuthHoldMessage,
} from "../src/vahan-auth-guard.mjs";

export const UI_HEALTH_CHECK_ALARM = "vahan-ui-health-check";
export const DEFAULT_UI_HEALTH_CHECK_INTERVAL_DAYS = 3;
export const MIN_UI_HEALTH_CHECK_INTERVAL_DAYS = 1;
export const MAX_UI_HEALTH_CHECK_INTERVAL_DAYS = 365;
// Kept as a compatibility export for existing callers. The controller uses
// the configured interval at runtime and falls back to the default above.
export const UI_HEALTH_CHECK_INTERVAL_DAYS = DEFAULT_UI_HEALTH_CHECK_INTERVAL_DAYS;
export const UI_HEALTH_CHECK_INTERVAL_MINUTES = UI_HEALTH_CHECK_INTERVAL_DAYS * 24 * 60;
export const UI_HEALTH_CHECK_TIMEOUT_MS = 45_000;
export const UI_HEALTH_CHECK_TAB_READY_TIMEOUT_MS = 30_000;
export const UI_HEALTH_CHECK_MESSAGE_TIMEOUT_MS = 1_500;
export const UI_HEALTH_CHECK_MESSAGE_ATTEMPTS = 10;
export const UI_HEALTH_CHECK_MESSAGE = "RUN_SCHEDULED_UI_CHECK";
export const UI_HEALTH_CHECK_STATE_KEY = "vahanUiHealthCheck";
export const PENDING_DEV_NOTIFICATION_KEY = "vahanUiPendingDevNotification";
export const UI_HEALTH_SCHEDULE_PATH = "/api/ui-health/schedule";
export const UI_HEALTH_LOG_PATH = "/api/ui-health/logs";
export const UI_HEALTH_PENDING_LOGS_KEY = "vahanUiHealthPendingLogs";
export const UI_HEALTH_LOG_TIMEOUT_MS = 15_000;
export const UI_HEALTH_OFFICIAL_URL =
  "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en";
// Backward-compatible name for callers that used the original production URL export.
export const VAHAN_PUBLIC_REPORT_URL = UI_HEALTH_OFFICIAL_URL;
export const UI_HEALTH_OFFICIAL_HOST = "analytics.parivahan.gov.in";
export const UI_HEALTH_REPORT_PATH = "/analytics/vahanpublicreport";
export const UI_HEALTH_OFFICIAL_TAB_MATCHES = Object.freeze([
  "https://analytics.parivahan.gov.in/analytics/vahanpublicreport*",
]);

const DATA_CHANGED_STATUS = "DATA_CHANGED";

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function withTimeout(promise, timeoutMs, message) {
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => reject(new Error(message)), timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timeoutId);
        resolve(value);
      },
      (error) => {
        clearTimeout(timeoutId);
        reject(error);
      },
    );
  });
}

function now() {
  return new Date().toISOString();
}

function createCheckId() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function errorMessage(error) {
  return String(error?.message || error || "Unknown scheduled health-check error")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 300);
}

async function assertNoVahanAuthHold(chromeApi, tabId) {
  const stored = await chromeApi.storage.local.get(VAHAN_AUTH_HOLD_KEY);
  const hold = stored?.[VAHAN_AUTH_HOLD_KEY];
  if (isVahanAuthHoldActive(hold, Date.now(), tabId)) {
    throw new Error(`${hold.code}: ${vahanAuthHoldMessage(hold)}`);
  }
}

function normalizeIntervalDays(value, fallback = DEFAULT_UI_HEALTH_CHECK_INTERVAL_DAYS) {
  const numeric = Number(value);
  if (
    Number.isInteger(numeric) &&
    numeric >= MIN_UI_HEALTH_CHECK_INTERVAL_DAYS &&
    numeric <= MAX_UI_HEALTH_CHECK_INTERVAL_DAYS
  ) {
    return numeric;
  }
  return fallback;
}

function intervalMinutesForDays(intervalDays) {
  return intervalDays * 24 * 60;
}

function isReportPath(value) {
  return String(value || "").replace(/\/+$/, "") === UI_HEALTH_REPORT_PATH;
}

export function isUiHealthOfficialUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return (
      url.protocol === "https:" &&
      url.hostname === UI_HEALTH_OFFICIAL_HOST &&
      url.port === "" &&
      isReportPath(url.pathname)
    );
  } catch {
    return false;
  }
}

async function findUiHealthOfficialTab(chromeApi) {
  if (typeof chromeApi.tabs?.query !== "function") return null;
  const tabs = await chromeApi.tabs.query({ url: UI_HEALTH_OFFICIAL_TAB_MATCHES });
  const validTabs = (tabs || []).filter(
    (tab) => tab?.id !== undefined && isUiHealthOfficialUrl(tab.url),
  );
  return validTabs.find((tab) => tab.active) || validTabs[0] || null;
}

async function findUiHealthActiveTab(chromeApi) {
  if (typeof chromeApi.tabs?.query !== "function") return null;
  const tabs = await chromeApi.tabs.query({ active: true, lastFocusedWindow: true });
  return tabs?.[0] || null;
}

async function getVerifiedUiHealthTab(chromeApi, tabId) {
  const tab = await chromeApi.tabs.get(tabId);
  if (isUiHealthOfficialUrl(tab?.url)) return tab;
  throw new Error(
    "Health checks can run only on the official VAHAN page " +
    `${UI_HEALTH_OFFICIAL_URL}. Current URL: ${tab?.url || "unknown"}.`,
  );
}

function healthCheckPageUrl(tab, fallback = UI_HEALTH_OFFICIAL_URL) {
  const value = String(tab?.url || "").trim();
  return value || fallback;
}

function missingOfficialTabError() {
  return (
    "No official VAHAN tab is open, or the URL is incorrect. Open " +
    `${UI_HEALTH_OFFICIAL_URL} and try again.`
  );
}

function noOfficialTabWithActivePageError(tab) {
  return (
    "No official VAHAN tab is open. The current tab URL is " +
    `${tab?.url || "unknown"}. Open ${UI_HEALTH_OFFICIAL_URL} and try again.`
  );
}

async function loadBackendSchedule(chromeApi, fetchImpl) {
  if (typeof fetchImpl !== "function") return null;

  const stored = await chromeApi.storage.local.get("runnerConfig");
  const runnerConfig = stored?.runnerConfig || {};
  const serverUrl = String(runnerConfig.serverUrl || "").trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(serverUrl)) return null;

  const response = await fetchImpl(`${serverUrl}${UI_HEALTH_SCHEDULE_PATH}`, {
    headers: {
      "X-VAHAN-RUNNER-TOKEN": String(runnerConfig.token || ""),
      "X-VAHAN-RUNNER-ID": String(runnerConfig.runnerId || ""),
    },
  });
  if (!response?.ok) {
    throw new Error(`Could not load the check schedule from the backend (${response?.status || "unknown"}).`);
  }
  const payload = await response.json();
  const intervalDays = normalizeIntervalDays(payload?.intervalDays, null);
  if (intervalDays === null) {
    throw new Error("The backend returned an invalid check interval.");
  }
  return intervalDays;
}

async function postHealthCheck(chromeApi, healthCheck, fetchImpl) {
  if (typeof fetchImpl !== "function") {
    throw new Error("Backend log upload is unavailable in this extension runtime.");
  }

  const stored = await chromeApi.storage.local.get("runnerConfig");
  const runnerConfig = stored?.runnerConfig || {};
  const serverUrl = String(runnerConfig.serverUrl || "").trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(serverUrl)) {
    throw new Error("Configure the backend address before uploading UI health logs.");
  }

  const response = await withTimeout(
    fetchImpl(`${serverUrl}${UI_HEALTH_LOG_PATH}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-VAHAN-RUNNER-TOKEN": String(runnerConfig.token || ""),
        "X-VAHAN-RUNNER-ID": String(runnerConfig.runnerId || ""),
      },
      body: JSON.stringify({
        healthCheck,
        pageUrl: healthCheck.pageUrl || UI_HEALTH_OFFICIAL_URL,
        runnerId: runnerConfig.runnerId || null,
      }),
    }),
    UI_HEALTH_LOG_TIMEOUT_MS,
    "Timed out while sending the UI health log to the backend.",
  );
  if (!response?.ok) {
    throw new Error(`Could not upload the UI health log to the backend (${response?.status || "unknown"}).`);
  }
  return response.json();
}

function normalizeControl(control = {}) {
  return {
    name: String(control.name || ""),
    selector: String(control.selector || ""),
    tag: String(control.tag || ""),
    id: String(control.id || ""),
    nameAttr: String(control.nameAttr ?? control.name_attr ?? ""),
    multiple: Boolean(control.multiple),
  };
}

function normalizeDataSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return null;
  const controls = {};
  for (const [name, control] of Object.entries(snapshot.controls || {})) {
    controls[name] = {
      selector: String(control?.selector || ""),
      optionCount: Number.isFinite(Number(control?.optionCount))
        ? Number(control.optionCount)
        : 0,
      digest: String(control?.digest || ""),
      sample: Array.isArray(control?.sample)
        ? control.sample.slice(0, 8).map((option) => ({
          label: String(option?.label || ""),
          value: String(option?.value || ""),
        }))
        : [],
    };
  }
  return {
    version: String(snapshot.version || "v1"),
    signature: String(snapshot.signature || ""),
    controls,
  };
}

function normalizeContract(contract = {}) {
  return {
    contractVersion: String(contract.contractVersion || ""),
    signature: String(contract.signature || ""),
    path: String(contract.path || contract.urlPath || ""),
    formAction: String(contract.formAction || ""),
    controls: Array.isArray(contract.controls)
      ? contract.controls.map(normalizeControl)
      : [],
    dataSnapshot: normalizeDataSnapshot(contract.dataSnapshot),
  };
}

export function compareDataSnapshots(previous, current) {
  if (!previous?.signature || !current?.signature) return [];
  const previousControls = previous?.controls || {};
  const currentControls = current?.controls || {};
  const names = new Set([
    ...Object.keys(previousControls),
    ...Object.keys(currentControls),
  ]);
  return [...names]
    .sort()
    .filter((name) => {
      const before = previousControls[name];
      const after = currentControls[name];
      if (!before || !after) return Boolean(before || after);
      return before.optionCount !== after.optionCount || before.digest !== after.digest;
    })
    .map((name) => ({
      name,
      selector: currentControls[name]?.selector || previousControls[name]?.selector || "",
      previous: previousControls[name] || null,
      current: currentControls[name] || null,
    }));
}

function summarizeContract(contract) {
  const normalized = normalizeContract(contract);
  return {
    ...normalized,
    controls: normalized.controls,
    dataSnapshot: normalized.dataSnapshot,
  };
}

function normalizeUiDriftReport(report = {}) {
  return {
    code: String(report.code || "UI_DRIFT"),
    step: String(report.step || "scheduled-health-check"),
    title: String(report.title || "UI structure does not match the contract"),
    target: String(report.target || "VAHAN Public Report page"),
    expected: String(report.expected || "no data"),
    actual: String(report.actual || "no data"),
    action: String(report.action || "A developer should review the UI contract."),
    message: String(report.message || "A change was detected on the VAHAN Public Report page."),
    diagnostics: report.diagnostics && typeof report.diagnostics === "object"
      ? report.diagnostics
      : {},
  };
}

function normalizeUiDriftReports(response = {}) {
  const reports = Array.isArray(response.uiDrifts) && response.uiDrifts.length > 0
    ? response.uiDrifts
    : response.uiDrift
      ? [response.uiDrift]
      : [];
  return reports.map((report) => normalizeUiDriftReport(report));
}

function dataChangedReport(changes, previousContract, currentContract) {
  const target = changes.length === 1
    ? changes[0].name
    : `${changes.length} controls containing option data`;
  const actual = changes.map((change) => {
    const before = change.previous;
    const after = change.current;
    return `${change.name}: ${before?.optionCount ?? 0} option/${before?.digest || "missing"}` +
      ` → ${after?.optionCount ?? 0} option/${after?.digest || "missing"}`;
  }).join("; ");
  return {
    code: "UI_DRIFT_OPTION_DATA_CHANGED",
    step: "scheduled-health-check",
    title: "Option data on the VAHAN Public Report page has changed",
    target,
    expected: "The option data matches the previous check",
    actual,
    action: "A developer should verify the data change, update the adapter if needed, and rerun the UI checks.",
    message: `A data change was detected at ${target}. The tool logged it for review.`,
    diagnostics: {
      previousDataSignature: previousContract?.dataSnapshot?.signature || "",
      currentDataSignature: currentContract?.dataSnapshot?.signature || "",
      changes,
    },
  };
}

async function queueDevNotification(chromeApi, healthCheck) {
  if (!["UI_DRIFT", DATA_CHANGED_STATUS].includes(healthCheck.status)) return null;

  const stored = await chromeApi.storage.local.get(PENDING_DEV_NOTIFICATION_KEY);
  const previous = stored[PENDING_DEV_NOTIFICATION_KEY];
  const reports = Array.isArray(healthCheck.reports) && healthCheck.reports.length > 0
    ? healthCheck.reports
    : healthCheck.report
      ? [healthCheck.report]
      : [];
  const primaryReport = healthCheck.report || reports[0] || null;
  const sameAlert = previous?.report?.code === primaryReport?.code &&
    previous?.report?.target === primaryReport?.target;
  const notification = {
    schemaVersion: "v1",
    type: healthCheck.status === DATA_CHANGED_STATUS
      ? "VAHAN_UI_DATA_CHANGED"
      : "VAHAN_UI_DRIFT",
    alertType: healthCheck.status,
    delivery: "PENDING_CONFIGURATION",
    firstDetectedAt: sameAlert ? previous.firstDetectedAt : healthCheck.checkedAt,
    lastDetectedAt: healthCheck.checkedAt,
    occurrences: sameAlert ? Number(previous.occurrences || 0) + 1 : 1,
    errorCount: Number(healthCheck.errorCount || reports.length || 0),
    report: primaryReport,
    reports,
  };

  // This is intentionally only a local queue. A future website/webhook/email
  // connector can read this payload without changing the health-check flow.
  await chromeApi.storage.local.set({ [PENDING_DEV_NOTIFICATION_KEY]: notification });
  return notification;
}

async function flushPendingHealthLogs(chromeApi, fetchImpl) {
  const stored = await chromeApi.storage.local.get(UI_HEALTH_PENDING_LOGS_KEY);
  const pending = Array.isArray(stored[UI_HEALTH_PENDING_LOGS_KEY])
    ? stored[UI_HEALTH_PENDING_LOGS_KEY].filter((item) => item && typeof item === "object")
    : [];
  let lastResult = null;
  let lastError = null;

  while (pending.length > 0) {
    try {
      lastResult = await postHealthCheck(chromeApi, pending[0], fetchImpl);
      pending.shift();
    } catch (error) {
      lastError = errorMessage(error);
      break;
    }
  }
  await chromeApi.storage.local.set({ [UI_HEALTH_PENDING_LOGS_KEY]: pending });
  return {
    ok: pending.length === 0,
    pendingCount: pending.length,
    lastResult,
    error: lastError,
  };
}

async function deliverHealthLog(chromeApi, healthCheck, fetchImpl) {
  await flushPendingHealthLogs(chromeApi, fetchImpl);
  try {
    const result = await postHealthCheck(chromeApi, healthCheck, fetchImpl);
    const pending = await chromeApi.storage.local.get(UI_HEALTH_PENDING_LOGS_KEY);
    return {
      ...(result || {}),
      ok: true,
      pendingCount: Array.isArray(pending[UI_HEALTH_PENDING_LOGS_KEY])
        ? pending[UI_HEALTH_PENDING_LOGS_KEY].length
        : 0,
    };
  } catch (error) {
    const stored = await chromeApi.storage.local.get(UI_HEALTH_PENDING_LOGS_KEY);
    const pending = Array.isArray(stored[UI_HEALTH_PENDING_LOGS_KEY])
      ? stored[UI_HEALTH_PENDING_LOGS_KEY]
      : [];
    pending.push(healthCheck);
    await chromeApi.storage.local.set({ [UI_HEALTH_PENDING_LOGS_KEY]: pending });
    return {
      ok: false,
      queued: true,
      pendingCount: pending.length,
      error: errorMessage(error),
    };
  }
}

async function persistUiHealthCheck(chromeApi, healthCheck, fetchImpl) {
  const identifiedHealthCheck = {
    ...healthCheck,
    checkId: healthCheck.checkId || createCheckId(),
  };
  const notification = await queueDevNotification(chromeApi, identifiedHealthCheck);
  await chromeApi.storage.local.set({
    [UI_HEALTH_CHECK_STATE_KEY]: identifiedHealthCheck,
    ...(notification ? { [PENDING_DEV_NOTIFICATION_KEY]: notification } : {}),
  });

  const saved = {
    ...identifiedHealthCheck,
    backendLog: await deliverHealthLog(chromeApi, identifiedHealthCheck, fetchImpl),
  };
  await chromeApi.storage.local.set({ [UI_HEALTH_CHECK_STATE_KEY]: saved });
  return saved;
}

function waitForTabReady(chromeApi, tabId, timeoutMs = UI_HEALTH_CHECK_TAB_READY_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const onUpdated = (updatedTabId, changeInfo) => {
      if (updatedTabId === tabId && changeInfo.status === "complete") finish(resolve);
    };
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      chromeApi.tabs.onUpdated?.removeListener(onUpdated);
      callback(value);
    };
    const timeoutId = setTimeout(
      () => finish(reject, new Error("Timed out while loading the VAHAN Public Report health-check tab.")),
      timeoutMs,
    );

    chromeApi.tabs.onUpdated?.addListener(onUpdated);
    chromeApi.tabs.get(tabId)
      .then((tab) => {
        if (tab.status === "complete") finish(resolve);
      })
      .catch(() => {});
  });
}

async function requestUiHealthCheck(
  chromeApi,
  tabId,
  retryDelayMs = 500,
  requireOfficial = true,
) {
  let lastError;
  let recoveryAttempted = false;
  for (let attempt = 0; attempt < UI_HEALTH_CHECK_MESSAGE_ATTEMPTS; attempt += 1) {
    try {
      await assertNoVahanAuthHold(chromeApi, tabId);
      return await withTimeout(
        chromeApi.tabs.sendMessage(tabId, {
          type: UI_HEALTH_CHECK_MESSAGE,
          requireOfficial,
        }),
        UI_HEALTH_CHECK_MESSAGE_TIMEOUT_MS,
        "Timed out while waiting for the VAHAN UI health-check content script.",
      );
    } catch (error) {
      lastError = error;

      // An HTTP authentication challenge is a hard stop. Do not reinject the
      // content script or spend the remaining attempts while Chrome/server is
      // waiting for credentials.
      try {
        await assertNoVahanAuthHold(chromeApi, tabId);
      } catch (authError) {
        throw authError;
      }

      // A content script is not automatically re-injected into an already
      // open tab after chrome://extensions reloads the extension. Recover the
      // read-only health-check pair in that exact official tab before retrying.
      if (!recoveryAttempted && typeof chromeApi.scripting?.executeScript === "function") {
        recoveryAttempted = true;
        try {
          await chromeApi.scripting.executeScript({
            target: { tabId },
            files: ["ui-drift/guard.js", "ui-drift/health-check-content.js"],
          });
        } catch (recoveryError) {
          lastError = recoveryError;
        }
      }
      await wait(retryDelayMs);
    }
  }
  throw lastError || new Error("VAHAN Public Report health-check content script did not respond.");
}

export function createUiHealthCheckController(chromeApi, options = {}) {
  const fallbackIntervalDays = normalizeIntervalDays(
    options.intervalDays,
    normalizeIntervalDays(
      Number(options.intervalMinutes) / (24 * 60),
      DEFAULT_UI_HEALTH_CHECK_INTERVAL_DAYS,
    ),
  );
  let intervalDays = fallbackIntervalDays;
  const checkTimeoutMs = options.checkTimeoutMs || UI_HEALTH_CHECK_TIMEOUT_MS;
  const tabReadyTimeoutMs = options.tabReadyTimeoutMs || UI_HEALTH_CHECK_TAB_READY_TIMEOUT_MS;
  const retryDelayMs = options.retryDelayMs ?? 500;
  const fetchImpl = options.fetch || globalThis.fetch;
  let activeHealthCheck = null;

  async function ensureAlarm({ force = false, requestedIntervalDays } = {}) {
    if (!chromeApi.alarms?.get || !chromeApi.alarms?.create) {
      return { ok: false, reason: "Chrome alarms API is unavailable." };
    }
    if (requestedIntervalDays !== undefined) {
      const normalized = normalizeIntervalDays(requestedIntervalDays, null);
      if (normalized === null) {
        return {
          ok: false,
          reason: `The check interval must be between ${MIN_UI_HEALTH_CHECK_INTERVAL_DAYS} and ${MAX_UI_HEALTH_CHECK_INTERVAL_DAYS} days.`,
          intervalDays,
        };
      }
      intervalDays = normalized;
    }
    const intervalMinutes = intervalMinutesForDays(intervalDays);
    const existing = await chromeApi.alarms.get(UI_HEALTH_CHECK_ALARM);
    if (!force && existing && Number(existing.periodInMinutes) === intervalMinutes) {
      return { ok: true, created: false, intervalDays, alarm: existing };
    }
    await chromeApi.alarms.create(UI_HEALTH_CHECK_ALARM, {
      delayInMinutes: intervalMinutes,
      periodInMinutes: intervalMinutes,
    });
    return {
      ok: true,
      created: !existing,
      updated: Boolean(existing),
      intervalDays,
    };
  }

  async function updateSchedule(requestedIntervalDays) {
    return ensureAlarm({ force: true, requestedIntervalDays });
  }

  async function refreshScheduleFromBackend() {
    try {
      const configuredIntervalDays = await loadBackendSchedule(chromeApi, fetchImpl);
      if (configuredIntervalDays === null) {
        return {
          ok: false,
          reason: "Backend schedule is unavailable; keeping the current extension schedule.",
          intervalDays,
        };
      }
      return updateSchedule(configuredIntervalDays);
    } catch (error) {
      return { ok: false, reason: errorMessage(error), intervalDays };
    }
  }

  async function execute(trigger, requestedTabId) {
    const startedAt = now();
    const previousState = await chromeApi.storage.local.get(UI_HEALTH_CHECK_STATE_KEY);
    const previousHealthCheck = previousState[UI_HEALTH_CHECK_STATE_KEY];
    const tabId = requestedTabId;
    let pageUrl = UI_HEALTH_OFFICIAL_URL;

    try {
      if (!tabId) throw new Error("Chrome did not return a health-check tab ID.");
      const candidate = await chromeApi.tabs.get(tabId);
      pageUrl = healthCheckPageUrl(candidate);
      const tab = await getVerifiedUiHealthTab(chromeApi, tabId);
      pageUrl = healthCheckPageUrl(tab, pageUrl);
      await assertNoVahanAuthHold(chromeApi, tabId);

      await waitForTabReady(chromeApi, tabId, tabReadyTimeoutMs);
      const readyTab = await getVerifiedUiHealthTab(chromeApi, tabId);
      pageUrl = healthCheckPageUrl(readyTab, pageUrl);
      await assertNoVahanAuthHold(chromeApi, tabId);
      const response = await withTimeout(
        requestUiHealthCheck(chromeApi, tabId, retryDelayMs, true),
        checkTimeoutMs,
        "Timed out while checking the VAHAN UI contract.",
      );
      const checkedAt = now();

      if (response?.ok && response.contract) {
        const contract = summarizeContract(response.contract);
        const changes = compareDataSnapshots(
          previousHealthCheck?.contract?.dataSnapshot,
          contract.dataSnapshot,
        );
        if (changes.length > 0) {
          const report = dataChangedReport(
            changes,
            previousHealthCheck?.contract,
            contract,
          );
          return persistUiHealthCheck(chromeApi, {
            status: DATA_CHANGED_STATUS,
            trigger,
            startedAt,
            checkedAt,
            pageUrl,
            contract,
            report,
            reports: [report],
            errorCount: 1,
          }, fetchImpl);
        }
        return persistUiHealthCheck(chromeApi, {
          status: "PASS",
          trigger,
          startedAt,
          checkedAt,
          pageUrl,
          contract,
          reports: [],
          errorCount: 0,
        }, fetchImpl);
      }

      const reports = normalizeUiDriftReports(response);
      if (reports.length > 0) {
        return persistUiHealthCheck(chromeApi, {
          status: "UI_DRIFT",
          trigger,
          startedAt,
          checkedAt,
          pageUrl,
          report: reports[0],
          reports,
          errorCount: Number(response.errorCount) || reports.length,
        }, fetchImpl);
      }

      return persistUiHealthCheck(chromeApi, {
        status: "CHECK_ERROR",
        trigger,
        startedAt,
        checkedAt,
        pageUrl,
        error: errorMessage(response?.error || "The VAHAN Public Report health check returned no result."),
      }, fetchImpl);
    } catch (error) {
      return persistUiHealthCheck(chromeApi, {
        status: "CHECK_ERROR",
        trigger,
        startedAt,
        checkedAt: now(),
        pageUrl,
        error: errorMessage(error),
      }, fetchImpl);
    }
  }

  async function runOnOfficialTab(trigger = "alarm") {
    let tab;
    try {
      tab = await findUiHealthOfficialTab(chromeApi);
    } catch (error) {
      return persistUiHealthCheck(chromeApi, {
        status: "CHECK_ERROR",
        trigger,
        startedAt: now(),
        checkedAt: now(),
        pageUrl: UI_HEALTH_OFFICIAL_URL,
        error: errorMessage(error),
      }, fetchImpl);
    }

    if (!tab?.id) {
      // The Web UI is normally the active tab when the user clicks
      // "Kiểm tra ngay". Keep that tab's URL in the diagnostic when no
      // official tab exists, but never inspect it as a production page.
      let activeTab = null;
      try {
        activeTab = await findUiHealthActiveTab(chromeApi);
      } catch {
        // The active-tab lookup is diagnostic-only.
      }
      return persistUiHealthCheck(chromeApi, {
        status: "CHECK_ERROR",
        trigger,
        startedAt: now(),
        checkedAt: now(),
        pageUrl: healthCheckPageUrl(activeTab),
        error: activeTab
          ? noOfficialTabWithActivePageError(activeTab)
          : missingOfficialTabError(),
      }, fetchImpl);
    }

    return execute(trigger, tab.id);
  }

  async function getState() {
    return chromeApi.storage.local.get([
      UI_HEALTH_CHECK_STATE_KEY,
      PENDING_DEV_NOTIFICATION_KEY,
      UI_HEALTH_PENDING_LOGS_KEY,
    ]);
  }

  function run(trigger = "alarm") {
    if (!activeHealthCheck) {
      activeHealthCheck = runOnOfficialTab(trigger).finally(() => {
        activeHealthCheck = null;
      });
    }
    return activeHealthCheck;
  }

  return Object.freeze({
    ensureAlarm,
    getState,
    refreshScheduleFromBackend,
    run,
    updateSchedule,
  });
}

export function registerUiHealthCheck(chromeApi, options = {}) {
  const controller = createUiHealthCheckController(chromeApi, options);
  const ensure = () => {
    controller.ensureAlarm().catch((error) => {
      console.error("[VAHAN UI HEALTH] Could not create the check schedule:", errorMessage(error));
    });
  };

  chromeApi.runtime?.onInstalled?.addListener(ensure);
  chromeApi.runtime?.onStartup?.addListener(ensure);
  chromeApi.alarms?.onAlarm?.addListener((alarm) => {
    if (alarm.name === UI_HEALTH_CHECK_ALARM) void controller.run("alarm");
  });
  chromeApi.runtime?.onMessage?.addListener((message, _sender, sendResponse) => {
    if (message?.type === "GET_UI_HEALTH_CHECK") {
      controller.getState()
        .then(sendResponse)
        .catch((error) => sendResponse({ error: errorMessage(error) }));
      return true;
    }
    if (message?.type === "RUN_UI_HEALTH_CHECK_NOW") {
      controller.run("manual")
        .then((healthCheck) => sendResponse({
          ok: healthCheck.status === "PASS",
          healthCheck,
        }))
        .catch((error) => sendResponse({ ok: false, error: errorMessage(error) }));
      return true;
    }
    return undefined;
  });
  ensure();
  return controller;
}
