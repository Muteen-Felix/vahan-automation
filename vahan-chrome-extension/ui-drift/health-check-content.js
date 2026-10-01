(function installVahanUiHealthCheckContent(global) {
  "use strict";
  if (global.__vahanUiHealthCheckContentInstalled) return;
  global.__vahanUiHealthCheckContentInstalled = true;

  const HEALTH_CHECK_STEP = "scheduled-health-check";
  const DATA_CONTRACT_VERSION = "v1";
  const OFFICIAL_HOST = "analytics.parivahan.gov.in";
  const OFFICIAL_PATH = "/analytics/vahanpublicreport";
  const DATA_CONTROLS = Object.freeze({
    category: "#vehicleCategoryGroup",
    fuel: "#vehicleFuel",
    yAxis: "#yAxis",
    xAxis: "#xAxis",
  });

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
  }

  function hash(value) {
    let result = 2166136261;
    for (const character of String(value)) {
      result ^= character.charCodeAt(0);
      result = Math.imul(result, 16777619);
    }
    return (result >>> 0).toString(16);
  }

  function optionRecords(select) {
    return [...select.options].map((option) => ({
      label: String(option.label || option.textContent || "").replace(/\s+/g, " ").trim(),
      value: String(option.value || ""),
    }));
  }

  function isOfficialReportPage(value = global.location?.href) {
    try {
      const url = new URL(String(value || ""));
      return url.protocol === "https:"
        && url.hostname === OFFICIAL_HOST
        && url.port === ""
        && url.pathname.replace(/\/+$/, "") === OFFICIAL_PATH;
    } catch {
      return false;
    }
  }

  function dataSnapshot() {
    const controls = {};
    for (const [name, selector] of Object.entries(DATA_CONTROLS)) {
      const select = document.querySelector(selector);
      if (!select) continue;
      const options = optionRecords(select);
      controls[name] = {
        selector,
        optionCount: options.length,
        digest: hash(JSON.stringify(options)),
        sample: options.slice(0, 8),
      };
    }
    return {
      version: DATA_CONTRACT_VERSION,
      signature: hash(JSON.stringify(controls)),
      controls,
    };
  }

  function requireOption(api, selector, control, expectedOption) {
    const select = document.querySelector(selector);
    const options = select ? optionRecords(select) : [];
    if (options.some((option) => normalize(option.label) === normalize(expectedOption))) return;
    throw new api.UiDriftError(
      "UI_DRIFT_REQUIRED_OPTION",
      `Could not find the ${control} option '${expectedOption}'.`,
      HEALTH_CHECK_STEP,
      {
        control,
        selector,
        expectedOption,
        optionCount: options.length,
        actualOptions: options.slice(0, 20).map((option) => option.label),
      },
    );
  }

  function requireOptions(api, selector, control) {
    const select = document.querySelector(selector);
    const optionCount = select ? select.options.length : 0;
    if (optionCount > 0) return;
    throw new api.UiDriftError(
      "UI_DRIFT_EMPTY_OPTIONS",
      `The ${control} option list is empty or has not loaded yet.`,
      HEALTH_CHECK_STEP,
      { control, selector, optionCount },
    );
  }

  function collectUiDriftReports(errors, api) {
    return errors
      .map((error) => reportFor(error, api))
      .filter(Boolean);
  }

  function inspectAll({ requireOfficial = false } = {}) {
    const api = global.VahanUiDrift;
    if (!api) throw new Error("VAHAN UI drift contract is not available.");

    if (requireOfficial && !isOfficialReportPage()) {
      const error = new api.UiDriftError(
        "UI_DRIFT_WRONG_PAGE",
        "The current tab is not the official VAHAN Public Report page.",
        HEALTH_CHECK_STEP,
        {
          expectedUrl: `https://${OFFICIAL_HOST}${OFFICIAL_PATH}`,
          url: global.location?.href || "",
        },
      );
      const uiDrift = reportFor(error, api);
      return {
        ok: false,
        uiDrift,
        uiDrifts: uiDrift ? [uiDrift] : [],
        errorCount: uiDrift ? 1 : 0,
      };
    }

    const validation = typeof api.collectUiContractErrors === "function"
      ? api.collectUiContractErrors(HEALTH_CHECK_STEP)
      : { contract: null, errors: [] };
    const errors = [...validation.errors];

    if (errors.some((error) => error?.code === "UI_DRIFT_WRONG_PAGE")) {
      const reports = collectUiDriftReports(errors, api);
      return {
        ok: false,
        uiDrift: reports[0],
        uiDrifts: reports,
        errorCount: reports.length,
      };
    }

    const collectOptionError = (check, selector) => {
      if (!document.querySelector(selector)) return;
      try {
        check();
      } catch (error) {
        errors.push(error);
      }
    };

    collectOptionError(
      () => requireOption(api, DATA_CONTROLS.category, "category", "Two Wheeler"),
      DATA_CONTROLS.category,
    );
    collectOptionError(
      () => requireOptions(api, DATA_CONTROLS.fuel, "fuel"),
      DATA_CONTROLS.fuel,
    );
    collectOptionError(
      () => requireOption(api, DATA_CONTROLS.yAxis, "yaxis", "Fuel"),
      DATA_CONTROLS.yAxis,
    );

    const reports = collectUiDriftReports(errors, api);
    if (reports.length > 0) {
      return {
        ok: false,
        uiDrift: reports[0],
        uiDrifts: reports,
        errorCount: reports.length,
      };
    }

    const contract = {
      ...(validation.contract || {}),
      dataSnapshot: dataSnapshot(),
    };
    return { ok: true, contract };
  }

  function inspect(options = {}) {
    const result = inspectAll(options);
    if (!result.ok) {
      const first = result.uiDrift;
      const api = global.VahanUiDrift;
      throw new api.UiDriftError(
        first?.code || "UI_DRIFT",
        first?.message || "A change was detected on the VAHAN Public Report page.",
        first?.step || HEALTH_CHECK_STEP,
        first?.diagnostics || {},
      );
    }
    return result.contract;
  }

  function errorText(error) {
    return String(error?.message || error || "Unknown UI health-check error")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 300);
  }

  function reportFor(error, api = global.VahanUiDrift) {
    if (!api?.isUiDriftError(error)) return null;
    return {
      ...api.formatUiDrift(error),
      diagnostics: error.details || {},
    };
  }

  function inspectForBackground(requireOfficial) {
    try {
      return Promise.resolve(inspectAll({ requireOfficial }));
    } catch (error) {
      const uiDrift = reportFor(error);
      return Promise.resolve(uiDrift
        ? { ok: false, uiDrift, uiDrifts: [uiDrift], errorCount: 1 }
        : { ok: false, error: errorText(error) });
    }
  }

  global.VahanUiHealthCheckContent = Object.freeze({ inspect, inspectAll });

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "RUN_SCHEDULED_UI_CHECK") return;
    inspectForBackground(message.requireOfficial !== false).then(sendResponse);
    return true;
  });
})(globalThis);
