import assert from "node:assert/strict";

import {
  MAX_UI_HEALTH_CHECK_INTERVAL_DAYS,
  UI_HEALTH_CHECK_ALARM,
  UI_HEALTH_CHECK_INTERVAL_MINUTES,
  UI_HEALTH_OFFICIAL_URL,
  isUiHealthOfficialUrl,
  createUiHealthCheckController,
} from "../ui-drift/health-check.mjs";

function createEvent() {
  const listeners = [];
  return {
    addListener(listener) {
      listeners.push(listener);
    },
    removeListener(listener) {
      const index = listeners.indexOf(listener);
      if (index >= 0) listeners.splice(index, 1);
    },
    emit(...args) {
      for (const listener of listeners) listener(...args);
    },
  };
}

function createHarness(
  responses,
  {
    officialTabs = [{ id: 1, status: "complete", url: UI_HEALTH_OFFICIAL_URL, active: true }],
    activeTabs = officialTabs,
    tabUrl = UI_HEALTH_OFFICIAL_URL,
  } = {},
) {
  const storage = {};
  const calls = {
    alarms: [],
    createdTabs: [],
    removedTabs: [],
    downloads: [],
    injectedScripts: [],
    healthLogs: [],
    healthMessages: [],
  };
  let nextResponse = 0;
  const tabsOnUpdated = createEvent();

  return {
    calls,
    storage,
    chrome: {
      alarms: {
        onAlarm: createEvent(),
        async get() {
          return undefined;
        },
        async create(name, options) {
          calls.alarms.push({ name, options });
        },
      },
      storage: {
        local: {
          async get(keys) {
            const requested = Array.isArray(keys) ? keys : [keys];
            return Object.fromEntries(
              requested
                .filter((key) => Object.hasOwn(storage, key))
                .map((key) => [key, storage[key]]),
            );
          },
          async set(values) {
            Object.assign(storage, values);
          },
        },
      },
      fetch: async (url, options = {}) => {
        calls.healthLogs.push({ url, options });
        return {
          ok: true,
          async json() {
            return {
              ok: true,
              logId: calls.healthLogs.length,
              fileName: `report-backend-${calls.healthLogs.length}.csv`,
              rowCount: calls.healthLogs.length,
              fromDate: "2026-09-17",
              toDate: "2026-09-17",
              part: 1,
            };
          },
        };
      },
      tabs: {
        onUpdated: tabsOnUpdated,
        async query(queryInfo = {}) {
          if (queryInfo.active) return activeTabs;
          return officialTabs;
        },
        async create(options) {
          calls.createdTabs.push(options);
          return { id: calls.createdTabs.length, status: "complete", url: options.url };
        },
        async get(tabId) {
          return { id: tabId, status: "complete", url: tabUrl };
        },
        async sendMessage(tabId, message) {
          calls.healthMessages.push({ tabId, message });
          return responses[nextResponse++];
        },
        async remove(tabId) {
          calls.removedTabs.push(tabId);
        },
      },
      scripting: {
        async executeScript(details) {
          calls.injectedScripts.push(details);
        },
      },
      downloads: {
        async download(options) {
          calls.downloads.push(options);
          return calls.downloads.length;
        },
        async removeFile() {},
      },
    },
  };
}

function contract(dataSignature, fuelDigest = "fuel-a", fuelCount = 2) {
  return {
    contractVersion: "v1",
    signature: "controls-signature",
    path: "/analytics/vahanpublicreport",
    formAction: "/analytics/vahanpublicreport",
    controls: [
      {
        name: "form",
        selector: "#vahanPublicForm",
        tag: "form",
        id: "vahanPublicForm",
        nameAttr: "",
        multiple: false,
      },
      {
        name: "fuel",
        selector: "#vehicleFuel",
        tag: "select",
        id: "vehicleFuel",
        nameAttr: "vehicleFuels",
        multiple: true,
      },
    ],
    dataSnapshot: {
      version: "v1",
      signature: dataSignature,
      controls: {
        category: {
          selector: "#vehicleCategoryGroup",
          optionCount: 2,
          digest: "category-a",
          sample: [{ label: "Two Wheeler", value: "2" }],
        },
        fuel: {
          selector: "#vehicleFuel",
          optionCount: fuelCount,
          digest: fuelDigest,
          sample: [{ label: "Petrol", value: "P" }],
        },
      },
    },
  };
}

async function run() {
  const harness = createHarness([
    { ok: true, contract: contract("data-a") },
    { ok: true, contract: contract("data-b", "fuel-b", 3) },
    {
      ok: false,
      uiDrift: {
        code: "UI_DRIFT_REQUIRED_CONTROL",
        step: "scheduled-health-check",
        title: "Control bắt buộc bị thiếu hoặc bị trùng",
        message: "Phát hiện thay đổi tại Fuel (#vehicleFuel): ID đã bị đổi.",
        target: "Fuel (#vehicleFuel)",
        expected: "DOM phải có đúng 1 control",
        actual: "DOM đang có 0 control",
        diagnostics: { selector: "#vehicleFuel", name: "fuel", count: 0 },
        action: "Dev cần kiểm tra selector Fuel.",
      },
    },
  ]);
  harness.storage.runnerConfig = {
    serverUrl: "http://127.0.0.1:8000",
    runnerId: "test-runner",
  };
  const controller = createUiHealthCheckController(harness.chrome, {
    retryDelayMs: 1,
    fetch: harness.chrome.fetch,
  });

  const alarm = await controller.ensureAlarm();
  assert.equal(alarm.created, true);
  assert.deepEqual(harness.calls.alarms, [{
    name: UI_HEALTH_CHECK_ALARM,
    options: {
      delayInMinutes: UI_HEALTH_CHECK_INTERVAL_MINUTES,
      periodInMinutes: UI_HEALTH_CHECK_INTERVAL_MINUTES,
    },
  }]);

  const updatedAlarm = await controller.updateSchedule(5);
  assert.equal(updatedAlarm.ok, true);
  assert.equal(updatedAlarm.intervalDays, 5);
  assert.deepEqual(harness.calls.alarms[1], {
    name: UI_HEALTH_CHECK_ALARM,
    options: {
      delayInMinutes: 5 * 24 * 60,
      periodInMinutes: 5 * 24 * 60,
    },
  });
  const invalidAlarm = await controller.updateSchedule(MAX_UI_HEALTH_CHECK_INTERVAL_DAYS + 1);
  assert.equal(invalidAlarm.ok, false);
  assert.equal(invalidAlarm.intervalDays, 5);

  const backendHarness = createHarness([]);
  backendHarness.storage.runnerConfig = { serverUrl: "http://127.0.0.1:8000" };
  const backendController = createUiHealthCheckController(backendHarness.chrome, {
    fetch: async (url) => {
      assert.equal(url, "http://127.0.0.1:8000/api/ui-health/schedule");
      return { ok: true, async json() { return { intervalDays: 7 }; } };
    },
  });
  const refreshed = await backendController.refreshScheduleFromBackend();
  assert.equal(refreshed.ok, true);
  assert.equal(refreshed.intervalDays, 7);
  assert.equal(backendHarness.calls.alarms[0].options.periodInMinutes, 7 * 24 * 60);

  const first = await controller.run("manual");
  assert.equal(first.status, "PASS");
  assert.equal(first.backendLog.ok, true);
  assert.equal(first.pageUrl, UI_HEALTH_OFFICIAL_URL);
  assert.equal(harness.storage.vahanUiHealthCheck.contract.dataSnapshot.signature, "data-a");

  assert.equal(isUiHealthOfficialUrl(UI_HEALTH_OFFICIAL_URL), true);
  assert.equal(
    isUiHealthOfficialUrl("https://analytics.parivahan.gov.in/analytics/other"),
    false,
  );

  const changed = await controller.run("alarm");
  assert.equal(changed.status, "DATA_CHANGED");
  assert.equal(changed.report.code, "UI_DRIFT_OPTION_DATA_CHANGED");
  assert.match(changed.report.actual, /fuel: 2 option\/fuel-a/);
  assert.equal(harness.storage.vahanUiPendingDevNotification.type, "VAHAN_UI_DATA_CHANGED");
  assert.equal(harness.storage.vahanUiPendingDevNotification.occurrences, 1);

  const drift = await controller.run("alarm");
  assert.equal(drift.status, "UI_DRIFT");
  assert.equal(drift.report.code, "UI_DRIFT_REQUIRED_CONTROL");
  assert.equal(drift.report.diagnostics.count, 0);
  assert.deepEqual(harness.calls.createdTabs, []);
  assert.deepEqual(harness.calls.removedTabs, []);

  const state = await controller.getState();
  assert.equal(state.vahanUiHealthCheck.status, "UI_DRIFT");
  assert.equal(state.vahanUiPendingDevNotification.type, "VAHAN_UI_DRIFT");
  assert.deepEqual(state.vahanUiHealthPendingLogs, []);
  assert.equal(harness.calls.healthLogs.length, 3);
  assert.match(harness.calls.healthLogs[0].url, /\/api\/ui-health\/logs$/);
  const driftPayload = JSON.parse(harness.calls.healthLogs[2].options.body);
  assert.equal(driftPayload.healthCheck.status, "UI_DRIFT");
  assert.equal(driftPayload.healthCheck.report.code, "UI_DRIFT_REQUIRED_CONTROL");
  assert.equal(driftPayload.healthCheck.report.diagnostics.selector, "#vehicleFuel");
  assert.equal(driftPayload.healthCheck.report.diagnostics.count, 0);

  const multiReports = [
    ["#vehicleCategoryGroup", "category"],
    ["#vehicleFuel", "fuel"],
    ["#yAxis", "yaxis"],
    ["#xAxis", "xaxis"],
    ["#externalCaptcha", "captcha"],
    ["#applyTrigger", "apply"],
    ["#archivedFlags", "archivedFlags"],
    ["#reportType", "reportType"],
    ["#financialYearSelect", "financialYearSelect"],
    ["#reportYear", "reportYear"],
  ].map(([selector, name]) => ({
    code: "UI_DRIFT_REQUIRED_CONTROL",
    step: "scheduled-health-check",
    title: "Control bắt buộc bị thiếu hoặc bị trùng",
    message: `Phát hiện thay đổi tại ${selector}.`,
    target: selector,
    expected: "DOM phải có đúng 1 control",
    actual: "DOM đang có 0 control",
    diagnostics: { selector, name, count: 0 },
    action: "Dev cần kiểm tra selector.",
  }));
  const multiHarness = createHarness([
    {
      ok: false,
      uiDrift: multiReports[0],
      uiDrifts: multiReports,
      errorCount: multiReports.length,
    },
  ]);
  multiHarness.storage.runnerConfig = { serverUrl: "http://127.0.0.1:8000" };
  const multiController = createUiHealthCheckController(multiHarness.chrome, {
    retryDelayMs: 1,
    fetch: multiHarness.chrome.fetch,
  });
  const multi = await multiController.run("manual");
  assert.equal(multi.status, "UI_DRIFT");
  assert.equal(multi.errorCount, 10);
  assert.equal(multi.reports.length, 10);
  assert.equal(multi.report.code, "UI_DRIFT_REQUIRED_CONTROL");
  assert.equal(multi.reports[1].diagnostics.selector, "#vehicleFuel");
  assert.equal(multi.backendLog.ok, true);
  assert.equal(multiHarness.storage.vahanUiPendingDevNotification.errorCount, 10);
  const multiPayload = JSON.parse(multiHarness.calls.healthLogs[0].options.body);
  assert.equal(multiPayload.healthCheck.errorCount, 10);
  assert.equal(multiPayload.healthCheck.reports.length, 10);

  const offlineHarness = createHarness([{ ok: true, contract: contract("offline") }]);
  offlineHarness.storage.runnerConfig = { serverUrl: "http://127.0.0.1:8000" };
  const offlineController = createUiHealthCheckController(offlineHarness.chrome, {
    retryDelayMs: 1,
    fetch: async () => { throw new Error("backend unavailable"); },
  });
  const queued = await offlineController.run("alarm");
  assert.equal(queued.backendLog.ok, false);
  assert.equal(queued.backendLog.queued, true);
  assert.equal(offlineHarness.storage.vahanUiHealthPendingLogs.length, 1);

  const noOfficialHarness = createHarness([], { officialTabs: [] });
  noOfficialHarness.storage.runnerConfig = { serverUrl: "http://127.0.0.1:8000" };
  const noOfficialController = createUiHealthCheckController(noOfficialHarness.chrome, {
    retryDelayMs: 1,
    fetch: noOfficialHarness.chrome.fetch,
  });
  const noOfficial = await noOfficialController.run("manual-web");
  assert.equal(noOfficial.status, "CHECK_ERROR");
  assert.match(noOfficial.error, /Không có tab VAHAN chính thức/);
  assert.equal(noOfficial.pageUrl, UI_HEALTH_OFFICIAL_URL);
  assert.deepEqual(noOfficialHarness.calls.createdTabs, []);
  assert.deepEqual(noOfficialHarness.calls.removedTabs, []);

  const scheduledWithoutOfficial = await noOfficialController.run("alarm");
  assert.equal(scheduledWithoutOfficial.status, "CHECK_ERROR");
  assert.match(scheduledWithoutOfficial.error, /Không có tab VAHAN chính thức/);
  assert.equal(noOfficialHarness.calls.healthLogs.length, 2);

  const backgroundOfficialHarness = createHarness([
    { ok: true, contract: contract("background-official") },
  ], {
    officialTabs: [{ id: 1, status: "complete", url: UI_HEALTH_OFFICIAL_URL, active: false }],
    activeTabs: [{ id: 9, status: "complete", url: "http://127.0.0.1:5173/#configure", active: true }],
    tabUrl: UI_HEALTH_OFFICIAL_URL,
  });
  backgroundOfficialHarness.storage.runnerConfig = { serverUrl: "http://127.0.0.1:8000" };
  const officialTabController = createUiHealthCheckController(backgroundOfficialHarness.chrome, {
    retryDelayMs: 1,
    fetch: backgroundOfficialHarness.chrome.fetch,
  });
  const backgroundManual = await officialTabController.run("manual-web");
  assert.equal(backgroundManual.status, "PASS");
  assert.equal(backgroundManual.pageUrl, UI_HEALTH_OFFICIAL_URL);
  assert.equal(backgroundOfficialHarness.calls.healthMessages[0].tabId, 1);
  assert.equal(backgroundOfficialHarness.calls.healthMessages[0].message.requireOfficial, true);
  assert.deepEqual(backgroundOfficialHarness.calls.createdTabs, []);
  assert.equal(backgroundOfficialHarness.calls.healthLogs.length, 1);

  const recoveryHarness = createHarness([
    { ok: true, contract: contract("recovered-after-injection") },
  ]);
  recoveryHarness.storage.runnerConfig = { serverUrl: "http://127.0.0.1:8000" };
  let recovered = false;
  const originalSendMessage = recoveryHarness.chrome.tabs.sendMessage;
  recoveryHarness.chrome.tabs.sendMessage = async (...args) => {
    if (!recovered) throw new Error("Could not establish connection. Receiving end does not exist.");
    return originalSendMessage(...args);
  };
  recoveryHarness.chrome.scripting.executeScript = async (details) => {
    recoveryHarness.calls.injectedScripts.push(details);
    recovered = true;
  };
  const recoveryController = createUiHealthCheckController(recoveryHarness.chrome, {
    retryDelayMs: 1,
    fetch: recoveryHarness.chrome.fetch,
  });
  const recoveredCheck = await recoveryController.run("manual");
  assert.equal(recoveredCheck.status, "PASS");
  assert.deepEqual(recoveryHarness.calls.injectedScripts, [{
    target: { tabId: 1 },
    files: ["ui-drift/guard.js", "ui-drift/health-check-content.js"],
  }]);

  console.log("SCHEDULED HEALTH PASS official_tab_verified=True manual_web_prefers_official_tab=True exact_url_guard=True no_official_tab_logged=True data_change_detected=True multi_error_reports=True backend_csv=True offline_queue=True health_content_recovery=True");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
