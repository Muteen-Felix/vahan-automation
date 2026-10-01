// ── Excel byte bridge ───────────────────────────────────────────────
// interceptor-main.js observes the page's export in the MAIN world and
// suppresses the native browser download. This isolated-world handler
// forwards the captured, non-empty bytes to the service worker, which
// uploads them to the API server as the sole copy of the report.
function sendExcelDataUrl(dataUrl, fileName, captureId) {
  if (typeof dataUrl !== "string" || !dataUrl.startsWith("data:")) {
    console.error("[VAHAN EXT] Invalid Excel data URL.");
    return;
  }
  chrome.runtime.sendMessage({
    type: "EXCEL_BLOB_CAPTURED",
    dataUrl,
    fileName: fileName || "report.xlsx",
    captureId,
  }).catch((error) => console.error("[VAHAN EXT] Send blob error:", error));
}

async function blobToDataUrl(blob, fileName, captureId) {
  if (!blob?.size) throw new Error("Excel blob was empty.");
  await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Could not read the Excel blob."));
    reader.onload = () => {
      sendExcelDataUrl(reader.result, fileName, captureId);
      resolve();
    };
    reader.readAsDataURL(blob);
  });
}

async function captureExcelDownload(href, fileName = "report.xlsx", captureId) {
  if (typeof href !== "string" || !href) throw new Error("Excel download URL is missing.");
  let lastError;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const response = await fetch(href, { credentials: "include" });
      if (!response.ok) throw new Error(`Excel download fetch failed (${response.status}).`);
      const blob = await response.blob();
      await blobToDataUrl(blob, fileName, captureId);
      return;
    } catch (error) {
      lastError = error;
      if (attempt < 3) await delay(100 * (attempt + 1));
    }
  }
  throw lastError || new Error("Excel file could not be captured.");
}

(function installDownloadInterceptor() {
  window.addEventListener("__VAHAN_EXCEL_EXPORT__", (e) => {
    const { dataUrl, href, fileName, captureId } = e.detail || {};
    if (dataUrl) sendExcelDataUrl(dataUrl, fileName, captureId);
    else if (href) captureExcelDownload(href, fileName, captureId).catch((error) => {
      console.error("[VAHAN EXT] Failed to capture Excel download:", error);
    });
  });
  window.addEventListener("__VAHAN_EXCEL_EXPORT_ERROR__", (event) => {
    chrome.runtime.sendMessage({
      type: "EXCEL_BLOB_FAILED",
      captureId: event.detail?.captureId,
      error: event.detail?.error || "VAHAN could not generate the Excel file.",
    }).catch(() => {});
  });
})();

const splitValues = (value) => String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const VAHAN_PAGE_HEARTBEAT_INTERVAL_MS = 2_000;
const VAHAN_AUTH_HOLD_KEY = "vahanAuthHold";
const VAHAN_AUTH_GUARD_VERSION = 2;
let vahanPageHeartbeatTimer;

function sendVahanPageHeartbeat() {
  chrome.runtime.sendMessage({
    type: "VAHAN_PAGE_HEARTBEAT",
    visible: document.visibilityState === "visible",
  }).catch(() => {});
}

function startVahanPageHeartbeat() {
  const refreshHeartbeatSchedule = () => {
    window.clearInterval(vahanPageHeartbeatTimer);
    vahanPageHeartbeatTimer = undefined;
    sendVahanPageHeartbeat();
    if (document.visibilityState === "visible") {
      vahanPageHeartbeatTimer = window.setInterval(sendVahanPageHeartbeat, VAHAN_PAGE_HEARTBEAT_INTERVAL_MS);
    }
  };
  refreshHeartbeatSchedule();
  document.addEventListener("visibilitychange", refreshHeartbeatSchedule);
}

async function getActiveVahanAuthHold() {
  try {
    const { [VAHAN_AUTH_HOLD_KEY]: hold } = await chrome.storage.local.get(VAHAN_AUTH_HOLD_KEY);
    if (hold?.code !== "VAHAN_AUTH_REQUIRED" || hold.guardVersion !== VAHAN_AUTH_GUARD_VERSION) return null;
    const retryAfter = Date.parse(hold.retryAfter || "");
    return Number.isFinite(retryAfter) && retryAfter > Date.now() ? hold : null;
  } catch {
    return null;
  }
}

function authHoldStatusMessage(hold) {
  const retryAfter = hold?.retryAfter
    ? new Date(hold.retryAfter).toLocaleString("en-GB")
    : "after confirmation";
  return `VAHAN requires HTTP authentication. The extension is paused to prevent repeated retries. `
    + `Close the sign-in dialog, wait until ${retryAfter}, then reload the page.`;
}


function getOptionMap(select) {
  return [...select.options].map((option) => ({
    label: normalize(option.label || option.textContent),
    value: option.value,
  }));
}

function selectOptionsSignature(selector) {
  const select = document.querySelector(selector);
  if (!select) return "";
  return [...select.options]
    .map((option) => `${option.value}\u0000${normalize(option.label || option.textContent)}`)
    .join("\u0001");
}

async function waitForSelectOptionsChange(selector, previousSignature, timeout = 15_000) {
  await waitForDomCondition(
    () => {
      const signature = selectOptionsSignature(selector);
      return Boolean(signature && signature !== previousSignature);
    },
    timeout,
    0,
    `${selector}: options did not update after the filter changed.`,
  );
}

async function waitForOptions(selector, labels, timeout = 15000, previousSignature = null) {
  const expected = labels.map(normalize);
  const isReady = () => {
    const select = document.querySelector(selector);
    if (!select) return false;
    const available = getOptionMap(select).map((option) => option.label);
    const optionsChanged = previousSignature === null
      || selectOptionsSignature(selector) !== previousSignature;
    return optionsChanged && expected.every((label) => available.includes(label));
  };
  await waitForDomCondition(
    isReady,
    timeout,
    0,
    `${selector}: dynamic options did not load within ${timeout} ms.`,
  );
}

function waitForDomCondition(check, timeout, stableMs, timeoutMessage) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let stableTimer;
    const observer = new MutationObserver(evaluate);
    const timeoutTimer = window.setTimeout(() => {
      finish(reject, new Error(timeoutMessage));
    }, timeout);

    function finish(callback, value) {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutTimer);
      window.clearTimeout(stableTimer);
      observer.disconnect();
      callback(value);
    }

    function evaluate() {
      if (settled) return;
      if (!check()) {
        window.clearTimeout(stableTimer);
        stableTimer = undefined;
        return;
      }
      if (!stableMs) {
        finish(resolve);
        return;
      }
      if (stableTimer === undefined) {
        stableTimer = window.setTimeout(() => {
          stableTimer = undefined;
          if (check()) finish(resolve);
          else evaluate();
        }, stableMs);
      }
    }

    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    evaluate();
  });
}

async function refreshXAxisOptions(yAxisLabel, { resetSelection = false } = {}) {
  const yAxis = document.querySelector("#yAxis");
  const xAxis = document.querySelector("#xAxis");
  if (!yAxis || !xAxis) throw new Error("Could not find #yAxis or #xAxis.");
  const match = getOptionMap(yAxis).find((option) => option.label === normalize(yAxisLabel));
  if (!match) throw new Error(`#yAxis: could not find "${yAxisLabel}".`);
  const previousYAxisValue = yAxis.value;
  const previousXAxisOptions = selectOptionsSignature("#xAxis");

  // VAHAN restores X-Axis from a hidden field while rebuilding its options.
  // Clear both values during job fills so a previous scenario cannot affect
  // the requested selection. Option lookups keep the page's current choice.
  const hiddenXAxis = document.querySelector("#xAxis_hidden");
  if (resetSelection) {
    xAxis.value = "";
    if (hiddenXAxis) hiddenXAxis.value = "";
  }
  if (previousYAxisValue !== match.value || resetSelection) {
    yAxis.value = match.value;
    yAxis.dispatchEvent(new Event("change", { bubbles: true }));
    yAxis.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
  }
  if (previousYAxisValue !== match.value) {
    await waitForSelectOptionsChange("#xAxis", previousXAxisOptions);
  }
  return [...xAxis.options]
    .filter((option) => option.value)
    .map((option) => (option.label || option.textContent || "").replace(/\s+/g, " ").trim());
}

async function waitForXAxisOptions(yAxisLabel, labels, timeout = 15000) {
  const expected = labels.map(normalize);
  let available = [];
  const isReady = () => {
    const xAxis = document.querySelector("#xAxis");
    if (xAxis) {
      available = [...xAxis.options]
        .filter((option) => option.value)
        .map((option) => (option.label || option.textContent || "").replace(/\s+/g, " ").trim());
      const availableNormalized = available.map(normalize);
      return expected.every((label) => availableNormalized.includes(label));
    }
    return false;
  };
  try {
    // Keep the requested option present briefly so an old list is not
    // mistaken for the options VAHAN is rebuilding after the Y-Axis change.
    await waitForDomCondition(isReady, timeout, 400, "X-Axis options did not settle.");
    return;
  } catch {
    // Keep the existing, detailed selector error for the caller.
  }
  const missing = labels.filter((label, index) => !available.map(normalize).includes(expected[index]));
  throw new Error(
    `#xAxis: requested option(s) "${missing.join(", ")}" did not load for Y-Axis "${yAxisLabel}" `
    + `within ${timeout} ms. Available X-Axis options: ${available.join(", ") || "(none)"}.`,
  );
}

async function selectLabels(selector, rawValue) {
  const labels = splitValues(rawValue);
  const select = document.querySelector(selector);
  if (!select) throw new Error(`Could not find ${selector}.`);
  const options = getOptionMap(select);
  if (!labels.length && !select.multiple) return;
  const values = labels.map((label) => options.find((option) => option.label === normalize(label))?.value);
  if (values.some((value) => value === undefined)) throw new Error(`${selector}: could not find "${labels.join(", ")}".`);
  const selected = [...select.selectedOptions].map((option) => option.value);
  if (selected.length === values.length && values.every((value) => selected.includes(value))) return false;

  // Write to the native select first. The VAHAN multi-select widget can omit
  // filtered/lazy rows from its DOM, so clicking visible widget rows is not a
  // reliable way to update RTO and other dynamic multi-selects.
  for (const option of select.options) option.selected = values.includes(option.value);
  select.dispatchEvent(new Event("change", { bubbles: true }));
  if (typeof select.loadOptions === "function") select.loadOptions();
  // Native selection and event handlers are synchronous; yield to widget
  // microtasks without a timer that Chrome may heavily throttle in a hidden tab.
  await Promise.resolve();

  const actual = [...select.selectedOptions].map((option) => normalize(option.label || option.textContent));
  const expected = labels.map(normalize);
  if (actual.length !== expected.length || expected.some((label) => !actual.includes(label))) {
    throw new Error(`${selector}: VAHAN widget did not apply the requested selection.`);
  }
  return true;
}

async function clearSelect(selector) {
  const select = document.querySelector(selector);
  if (!select) return;
  if (![...select.options].some((option) => option.selected)) return;
  for (const option of select.options) option.selected = false;
  select.dispatchEvent(new Event("change", { bubbles: true }));
  if (typeof select.loadOptions === "function") select.loadOptions();
  await Promise.resolve();
}

async function loadMakerOptions(rawValue) {
  const makers = splitValues(rawValue);
  const select = document.querySelector("#vehicleMaker");
  if (!makers.length || !select) return;
  for (const maker of makers) {
    if ([...select.options].some((option) => normalize(option.label || option.textContent) === normalize(maker))) continue;
    const values = await fetchMakers(maker);
    for (const value of values) {
      if (![...select.options].some((option) => option.value === value)) select.add(new Option(value, value));
    }
  }
  if (typeof select.loadOptions === "function") select.loadOptions();
}

function readOptions(selectors) {
  return Object.fromEntries(Object.entries(selectors).map(([id, definition]) => {
    const select = document.querySelector(definition.selector);
    const labels = select
      ? [...select.options].map((option) => (option.label || option.textContent || "").replace(/\s+/g, " ").trim()).filter(Boolean)
      : [];
    return [id, labels];
  }));
}

async function fetchRtos(stateLabels) {
  const labels = splitValues(stateLabels);
  if (labels.length !== 1) return [];
  const state = [...document.querySelectorAll("#stateName option")]
    .find((option) => normalize(option.label || option.textContent) === normalize(labels[0]));
  if (!state) return [];
  const url = new URL("/analytics/json_rtos", location.origin);
  url.searchParams.set("stateCode", state.value);
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) throw new Error(`Could not load RTO options (${response.status}).`);
  return (await response.json()).map((rto) => rto.rtoName);
}

async function fetchMakers(search) {
  const url = new URL("/analytics/vahanpublicreport/lazy/vehicle-makers", location.origin);
  url.search = new URLSearchParams({ page: "0", size: "20", search }).toString();
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) throw new Error(`Could not search Maker options (${response.status}).`);
  const payload = await response.json();
  const rows = Array.isArray(payload)
    ? payload
    : payload.content || payload.results || payload.data || payload.items || [];
  return rows.map((item) => typeof item === "string"
    ? item
    : item.label || item.name || item.value || item.makerName,
  ).filter(Boolean);
}

async function getXAxisOptions(yAxisLabel) {
  if (!yAxisLabel) return [];
  return refreshXAxisOptions(yAxisLabel);
}

async function getStateOptions(delhiNcrLabel) {
  const previousStateOptions = selectOptionsSignature("#stateName");
  const delhiNcrChanged = await selectLabels("#delhiNcr", delhiNcrLabel);
  if (delhiNcrChanged) {
    await waitForSelectOptionsChange("#stateName", previousStateOptions);
  }
  const state = document.querySelector("#stateName");
  return state
    ? [...state.options]
        .map((option) => (option.label || option.textContent || "").replace(/\s+/g, " ").trim())
        .filter(Boolean)
    : [];
}

function fill(selector, value) {
  if (value === undefined || value === null) return;
  const input = document.querySelector(selector);
  if (!input) throw new Error(`Could not find ${selector}.`);
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

async function fillVahan(config) {
  const has = (key) => Object.prototype.hasOwnProperty.call(config, key);

  // These controls are independent. Dispatch their change events together;
  // dependent option waits below use DOM changes instead of a fixed sleep.
  await Promise.all([
    ...(has("archivedFlags") ? [selectLabels("#archivedFlags", config.archivedFlags)] : []),
    ...(has("period") ? [selectLabels("#reportType", config.period)] : []),
  ]);
  await Promise.all([
    ...(has("financialYears") ? [selectLabels("#financialYearSelect", config.financialYears)] : []),
    ...(has("reportYear") ? [selectLabels("#reportYear", config.reportYear)] : []),
    ...(has("reportMonth") ? [selectLabels("#reportMonth", config.reportMonth)] : []),
  ]);
  if (has("fromYear")) fill("#fromYear", config.fromYear);
  if (has("toYear")) fill("#toYear", config.toYear);
  if (has("fromDate")) fill("#fromDate", config.fromDate);
  if (has("toDate")) fill("#toDate", config.toDate);

  // VAHAN rebuilds the State options whenever Delhi NCR changes. Apply this
  // first so the State selection below is not cleared by the page script.
  let stateOptionsBeforeDelhiChange = null;
  let delhiNcrChanged = false;
  if (has("delhiNcr")) {
    stateOptionsBeforeDelhiChange = selectOptionsSignature("#stateName");
    delhiNcrChanged = await selectLabels("#delhiNcr", config.delhiNcr);
  }
  const geographyTask = (async () => {
    if (has("states")) {
      const states = splitValues(config.states);
      if (states.length) {
        if (delhiNcrChanged) {
          await waitForOptions("#stateName", states, 5_000, stateOptionsBeforeDelhiChange);
        } else {
          await waitForOptions("#stateName", states, 5_000);
        }
      }
      const previousRtoOptions = selectOptionsSignature("#rtoCode");
      const stateChanged = await selectLabels("#stateName", config.states);
      if (has("rtos") && splitValues(config.rtos).length) {
        await waitForOptions(
          "#rtoCode",
          splitValues(config.rtos),
          15_000,
          stateChanged ? previousRtoOptions : null,
        );
        await selectLabels("#rtoCode", config.rtos);
      }
      return;
    }
    if (has("rtos") && splitValues(config.rtos).length) {
      await waitForOptions("#rtoCode", splitValues(config.rtos));
      await selectLabels("#rtoCode", config.rtos);
    }
    return;
  })();
  const optionalSelects = {
    categoryGroups: "#vehicleCategoryGroup", subCategories: "#vehicleSubCategory",
    classes: "#vehicleClass", fuels: "#vehicleFuel", evTypes: "#evType",
    statuses: "#vehicleStatus", ownerTypes: "#vehicleOwnerType",
    vehicleType: "#vehicleType", fitness: "#fitnessCheck",
  };
  // Clear fields the new scenario omits *before* setting the fields it
  // specifies. VAHAN's dropdowns are mutually dependent (e.g. a stale
  // #evType selection restricts #vehicleFuel's option list), so a value left
  // over from the previous scenario can make an otherwise-valid label in
  // this scenario appear "not found".
  const dependentOptionalKeys = new Set([
    "categoryGroups", "subCategories", "classes", "fuels", "evTypes", "vehicleType",
  ]);
  await Promise.all(Object.entries(optionalSelects)
    .filter(([key]) => !has(key) && !dependentOptionalKeys.has(key))
    .map(([, selector]) => clearSelect(selector)));
  for (const key of dependentOptionalKeys) {
    if (!has(key)) await clearSelect(optionalSelects[key]);
  }

  const independentVehicleTasks = [];
  if (has("emissions")) independentVehicleTasks.push(selectLabels("#vehicleEmission", config.emissions));
  if (has("makers")) {
    independentVehicleTasks.push((async () => {
      await loadMakerOptions(config.makers);
      await selectLabels("#vehicleMaker", config.makers);
    })());
  }
  for (const key of ["statuses", "ownerTypes", "fitness"]) {
    const selector = optionalSelects[key];
    if (has(key)) independentVehicleTasks.push(selectLabels(selector, config[key]));
  }

  const dependentVehicleTask = (async () => {
    // These filters rebuild one another's option lists, so keep this chain in
    // order and wait for each requested option to appear.
    if (has("categoryGroups")) {
      const previousSubCategoryOptions = selectOptionsSignature(optionalSelects.subCategories);
      const changed = await selectLabels(optionalSelects.categoryGroups, config.categoryGroups);
      if (splitValues(config.subCategories).length) {
        await waitForOptions(optionalSelects.subCategories, splitValues(config.subCategories), 15_000,
          changed ? previousSubCategoryOptions : null);
      }
    }
    if (has("subCategories")) {
      const previousClassOptions = selectOptionsSignature(optionalSelects.classes);
      const changed = await selectLabels(optionalSelects.subCategories, config.subCategories);
      if (splitValues(config.classes).length) {
        await waitForOptions(optionalSelects.classes, splitValues(config.classes), 15_000,
          changed ? previousClassOptions : null);
      }
    }
    if (has("classes")) {
      await selectLabels(optionalSelects.classes, config.classes);
    }
    // The EV selection can constrain Fuel, so preserve that dependency order.
    if (has("evTypes")) {
      const previousFuelOptions = selectOptionsSignature(optionalSelects.fuels);
      const changed = await selectLabels(optionalSelects.evTypes, config.evTypes);
      if (splitValues(config.fuels).length) {
        await waitForOptions(optionalSelects.fuels, splitValues(config.fuels), 15_000,
          changed ? previousFuelOptions : null);
      }
    }
    if (has("fuels")) {
      await selectLabels(optionalSelects.fuels, config.fuels);
    }
  })();

  const axisTask = (async () => {
    if (has("yAxis")) {
      const changed = await selectLabels("#yAxis", config.yAxis);
      const xAxis = document.querySelector("#xAxis");
      const available = xAxis ? getOptionMap(xAxis).map((option) => option.label) : [];
      if (changed || splitValues(config.xAxis).some((label) => !available.includes(normalize(label)))) {
        await refreshXAxisOptions(splitValues(config.yAxis)[0], { resetSelection: true });
      }
    }
    if (has("xAxis") && splitValues(config.xAxis).length) {
      const yAxis = document.querySelector("#yAxis");
      const selectedYAxis = yAxis && [...yAxis.options].find((option) => option.value === yAxis.value);
      const yAxisLabel = splitValues(config.yAxis)[0]
        || selectedYAxis?.label
        || selectedYAxis?.textContent?.trim();
      const currentLabels = document.querySelector("#xAxis")?.selectedOptions;
      const alreadySelected = currentLabels && [...currentLabels].map((option) => normalize(option.label || option.textContent));
      if (!alreadySelected || alreadySelected.length !== splitValues(config.xAxis).length
        || splitValues(config.xAxis).some((label) => !alreadySelected.includes(normalize(label)))) {
        await waitForXAxisOptions(yAxisLabel || "(current selection)", splitValues(config.xAxis));
      }
      await selectLabels("#xAxis", config.xAxis);
    }
  })();

  // Run independent controls and the separate axis chain together. The
  // category/subcategory/class and EV/fuel chains remain ordered by dependency.
  await Promise.all([geographyTask, ...independentVehicleTasks, dependentVehicleTask, axisTask]);
  if (has("vehicleType")) await selectLabels(optionalSelects.vehicleType, config.vehicleType);
  // Dependent page handlers can reset controls that were correct earlier.
  // Verify the complete requested selection before publishing the CAPTCHA.
  const selectors = {
    ...optionalSelects, archivedFlags: "#archivedFlags", period: "#reportType",
    financialYears: "#financialYearSelect", reportYear: "#reportYear", reportMonth: "#reportMonth",
    delhiNcr: "#delhiNcr", states: "#stateName", rtos: "#rtoCode",
    emissions: "#vehicleEmission", makers: "#vehicleMaker", yAxis: "#yAxis", xAxis: "#xAxis",
  };
  for (const [key, selector] of Object.entries(selectors)) {
    if (!has(key)) continue;
    const select = document.querySelector(selector);
    const expected = splitValues(config[key]).map(normalize);
    if (!expected.length && !select?.multiple) continue;
    const actual = select ? [...select.selectedOptions].map((option) => normalize(option.label || option.textContent)) : [];
    if (!select || actual.length !== expected.length || expected.some((label) => !actual.includes(label))) {
      throw new Error(`${selector}: final filter selection does not match the requested case.`);
    }
  }
  if (has("autoApply")) configureAutoApply(config.autoApply);
}

async function captureCaptcha(timeout = 15000) {
  const deadline = Date.now() + timeout;
  let image;
  while (Date.now() < deadline) {
    image = document.querySelector("#captchaImage");
    if (image?.complete && image.naturalWidth > 0 && image.naturalHeight > 0) break;
    await delay(200);
  }
  if (!image?.complete || !image.naturalWidth || !image.naturalHeight) {
    throw new Error("CAPTCHA image did not load within the allowed time.");
  }

  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Could not create a canvas for the CAPTCHA image.");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  const sourceUrl = image.currentSrc || image.src || image.getAttribute("src");
  if (!sourceUrl) throw new Error("The CAPTCHA image has no identifier.");
  const imageDataUrl = canvas.toDataURL("image/png");
  let hash = 2166136261;
  for (let index = 0; index < imageDataUrl.length; index += 1) {
    hash ^= imageDataUrl.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return {
    captchaId: `${sourceUrl}#${(hash >>> 0).toString(16)}`,
    imageDataUrl,
  };
}

let isRefreshingCaptcha = false;

async function refreshCaptcha(previousCaptchaId, timeout = 15000) {
  const refreshButton = document.querySelector("#captchaImg");
  if (!refreshButton || !isVisible(refreshButton)) {
    throw new Error("Could not find the official VAHAN CAPTCHA refresh button.");
  }

  // The official page owns CAPTCHA generation through #captchaImg. Do not
  // synthesize an image URL: clicking this control keeps the request in the
  // user's authenticated VAHAN session and clears the old CAPTCHA value.
  isRefreshingCaptcha = true;
  try {
    refreshButton.click();

    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      try {
        const captcha = await captureCaptcha(1_000);
        if (!previousCaptchaId || captcha.captchaId !== previousCaptchaId) return captcha;
      } catch (_error) {
        // The image is briefly unavailable while the official page replaces it.
      }
      await delay(150);
    }
    throw new Error("VAHAN did not provide a new CAPTCHA image in time.");
  } finally {
    // Settle window so DOM load and mutation observer events from this refresh don't re-trigger.
    setTimeout(() => {
      isRefreshingCaptcha = false;
    }, 500);
  }
}

let captchaRefreshTimer;
async function notifyCaptchaRefresh() {
  clearTimeout(captchaRefreshTimer);
  captchaRefreshTimer = setTimeout(async () => {
    try {
      if (isRefreshingCaptcha) return;
      const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
      if (!activeServerJob || activeServerJob.stage !== "WAITING_CAPTCHA") return;
      // Passively capture the new CAPTCHA image if it changed out-of-band on VAHAN;
      // never trigger an active refresh click from this observer.
      const captcha = await captureCaptcha();
      if (captcha.captchaId === activeServerJob.captchaId) return;
      await chrome.runtime.sendMessage({ type: "SERVER_CAPTCHA_CHANGED", captcha });
    } catch (_error) {
      // A transient image load is expected while VAHAN swaps CAPTCHA pixels.
    }
  }, 150);
}

function observeCaptchaChanges() {
  document.addEventListener("load", (event) => {
    if (event.target?.id === "captchaImage") notifyCaptchaRefresh();
  }, true);
  const observer = new MutationObserver((mutations) => {
    if (mutations.some((mutation) =>
      mutation.target?.id === "captchaImage" ||
      [...mutation.addedNodes].some((node) => node.nodeType === Node.ELEMENT_NODE && (
        node.id === "captchaImage" || node.querySelector?.("#captchaImage")
      )),
    )) notifyCaptchaRefresh();
  });
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ["src"],
  });
}

function submitRemoteCaptcha(value, autoApply) {
  autoApply = true;
  if (typeof value === "string" && value.trim().length === 5) {
    value = value.trim() + "H";
  }
  const input = document.querySelector("#externalCaptcha");
  if (!input) throw new Error("Could not find the CAPTCHA input on VAHAN.");
  input.focus();
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  updateFloatingStep("captcha", "done");

  if (!autoApply) {
    setFloatingStatus("waiting", "CAPTCHA entered. Review it and click Apply on VAHAN.");
    return { applied: false };
  }

  // configureAutoApply owns the delayed click and prevents duplicate submits.
  configureAutoApply(true);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return { applied: true };
}

let autoApplyCleanup;
let applyResultWatcherButton;

// Watch an accepted Apply on the real form button. This also covers AJAX
// responses; after a full form navigation the content script resumes watcher
// startup on the returned report page.
function watchApplyButton(button) {
  if (!button || applyResultWatcherButton === button) return;
  applyResultWatcherButton = button;
  button.addEventListener("click", () => {
    const resultBaseline = captureVahanResultBaseline();
    const wasEnabled = !button.disabled;
    queueMicrotask(() => {
      // The official Apply handler disables the button only after accepting
      // the submit. Do not watch a stale result after client-side rejection.
      if (!wasEnabled || !button.disabled) return;
      const clickId = globalThis.crypto?.randomUUID?.()
        || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      chrome.runtime.sendMessage({ type: "COUNT_SUCCESSFUL_APPLY_CLICK", clickId })
        .then((response) => {
          if (!response?.ok) console.warn("Could not save successful Apply count:", response?.error);
          else if (response.serverRecorded === false) console.warn("Apply count is saved locally, but could not be synced to run analysis.");
        })
        .catch((error) => console.warn("Could not save successful Apply count:", error));
      startServerResultWatcher(resultBaseline).catch((error) => console.error("[VAHAN EXT] Result watcher failed:", error));
    });
  }, true);
}

function configureAutoApply(enabled) {
  enabled = true;
  autoApplyCleanup?.();
  autoApplyCleanup = undefined;

  const applyLabel = floatingWidget?.shadowRoot?.querySelector('[data-role="apply-label"]');
  if (applyLabel) {
    applyLabel.textContent = enabled ? "5. Auto-click Apply" : "5. Click Apply on VAHAN";
  }

  const captcha = document.querySelector("#externalCaptcha");
  const applyButton = document.querySelector("#applyTrigger");
  watchApplyButton(applyButton);
  if (!enabled || !captcha || !applyButton) return;

  let submitted = false;
  const cleanup = () => {
    captcha.removeEventListener("input", onInput);
  };
  const submit = () => {
    if (submitted || captcha.value.trim().length < 6) return;
    submitted = true;
    cleanup();
    updateFloatingStep("captcha", "done");
    updateFloatingStep("apply", "running");
    setFloatingStatus("running", "CAPTCHA complete. Clicking Apply...");
    applyButton.scrollIntoView({ behavior: "smooth", block: "center" });
    applyButton.click();
  };
  const onInput = () => {
    const length = captcha.value.trim().length;
    if (length >= 6) queueMicrotask(submit);
    else if (length === 5) setFloatingStatus("waiting", "5 of 6 CAPTCHA characters entered. Enter the final character shown in the image.");
  };

  captcha.addEventListener("input", onInput);
  autoApplyCleanup = cleanup;
  onInput();
}

async function initializeAutoApplyPreference() {
  const { vahanConfig } = await chrome.storage.local.get("vahanConfig");
  configureAutoApply(vahanConfig?.autoApply);
}

let exportClicked = false;
let exportWatcherTimer;
let exportWatcherTimeout;
async function startAutoExportWatcher() {
  const { vahanConfig, activeServerJob } = await chrome.storage.local.get(["vahanConfig", "activeServerJob"]);
  clearInterval(exportWatcherTimer);
  clearTimeout(exportWatcherTimeout);
  exportWatcherTimer = undefined;
  exportWatcherTimeout = undefined;
  if (activeServerJob || !(vahanConfig?.autoExport ?? true) || exportClicked) return;
  exportWatcherTimer = setInterval(() => {
    const button = findExcelDownloadButton();
    if (!exportClicked && readMakerReportResult().type === "DATA" && isUsableExcelButton(button)) {
      exportClicked = true;
      clearInterval(exportWatcherTimer);
      updateFloatingStep("captcha", "done");
      updateFloatingStep("apply", "done");
      updateFloatingStep("export", "done");
      setFloatingStatus("success", "Results found. Downloading the Excel file.");
      button.click();
    }
  }, 500);
  exportWatcherTimeout = setTimeout(() => clearInterval(exportWatcherTimer), 120000);
}

// Floating controller shown directly on the VAHAN page. A shadow root keeps
// the extension UI isolated from the website's Bootstrap/theme styles.
let floatingWidget;

function updateFloatingStep(name, state) {
  const row = floatingWidget?.shadowRoot?.querySelector(`[data-step="${name}"]`);
  if (!row) return;
  const icons = { idle: "○", running: "◌", done: "✓", waiting: "→", error: "×" };
  row.dataset.state = state;
  row.querySelector(".step-icon").textContent = icons[state] || icons.idle;
}

function setFloatingStatus(state, message) {
  const root = floatingWidget?.shadowRoot;
  if (!root) return;
  const badge = root.querySelector(".badge");
  const status = root.querySelector(".status");
  const labels = {
    ready: "Ready",
    running: "Processing...",
    waiting: "Waiting for CAPTCHA",
    success: "Success",
    error: "An error occurred",
  };
  badge.dataset.state = state;
  badge.textContent = labels[state] || labels.ready;
  status.textContent = message;
}

function resetFloatingSteps() {
  for (const name of ["time", "vehicle", "axes", "captcha", "apply", "export"]) {
    updateFloatingStep(name, "idle");
  }
}

// VAHAN trả các thông báo này trong DOM sau khi xử lý form. Không được tìm
// chuỗi trên toàn bộ body: DOM có thể giữ thông báo cũ/ẩn trong template.
// Chỉ nhận diện một node đang hiển thị, có nội dung ngắn và thực sự chứa thông báo.
const NO_RECORD_TEXT = /\bno\s+record\s+found\b/i;
const INVALID_CAPTCHA_TEXT = /\binvalid\s+captcha\b/i;
// The export controls remain visible for an empty Maker report. The Maker
// table, rather than a button, decides whether a file can be downloaded.
const NO_RECORD_CONFIRMATION_MS = 500;
const EXCEL_BUTTON_SELECTOR = "#downloadMakerAllExcel, #downloadBtn1";
const compactText = (value) => String(value || "").replace(/\s+/g, " ").trim();
const isVisible = (element) => {
  if (!element || element.getClientRects().length === 0) return false;
  if (element.getAttribute?.("aria-hidden") === "true") return false;
  if (element.closest?.('[aria-hidden="true"]')) return false;
  const style = window.getComputedStyle(element);
  return style.display !== "none"
    && style.visibility !== "hidden"
    && style.opacity !== "0";
};
const getResultRegion = () => document.querySelector(".report-main-column") || document.body;
const findExcelDownloadButton = () => {
  const buttons = [...document.querySelectorAll(EXCEL_BUTTON_SELECTOR)];
  const named = buttons.find(isVisible);
  if (named) return named;
  return [...getResultRegion().querySelectorAll("button, a")].find((element) =>
    isVisible(element) && /download\s+all\s+records\s+excel/i.test(compactText(element.textContent))) || buttons[0] || null;
};
const isUsableExcelButton = (button) => isVisible(button)
  && !button.disabled && button.getAttribute("aria-disabled") !== "true";
function readMakerReportResult() {
  const tables = [...getResultRegion().querySelectorAll("table")].filter((candidate) => {
    if (!isVisible(candidate)) return false;
    const headings = [...candidate.querySelectorAll("thead th, thead td, tr:first-child th, tr:first-child td")]
      .map((cell) => compactText(cell.textContent));
    return headings.some((heading) => /^maker$/i.test(heading));
  });
  const table = tables.at(-1);
  if (!table) return { type: null, table: null, fingerprint: "" };
  const rows = [...table.querySelectorAll("tbody tr")].filter(isVisible);
  const makerRows = rows.filter((row) => {
    const cells = [...row.querySelectorAll("th, td")].map((cell) => compactText(cell.textContent));
    return cells.length > 1 && Boolean(cells[0])
      && !/^(?:maker|page\s+total|grand\s+total|total)$/i.test(cells[0])
      && !NO_RECORD_TEXT.test(cells[0]);
  });
  const noRecord = rows.some((row) => NO_RECORD_TEXT.test(compactText(row.textContent)));
  return {
    type: makerRows.length ? "DATA" : noRecord ? "NO_RECORD" : null,
    table,
    fingerprint: compactText(table.textContent),
  };
}
const findVisiblePageMessages = (pattern, root = getResultRegion()) => [...root.querySelectorAll("*")]
  .filter(isVisible)
  .filter((element) => {
    const text = compactText(element.textContent);
    if (!pattern.test(text) || text.length > 240) return false;
    // If a parent contains the same message through a child, let the leaf
    // node decide. This avoids matching the whole result page/container.
    return ![...element.children].some((child) =>
      isVisible(child) && pattern.test(compactText(child.textContent)));
  });
function captureVahanResultBaseline() {
  const result = readMakerReportResult();
  return {
    invalidCaptchaNodes: new Set(findVisiblePageMessages(INVALID_CAPTCHA_TEXT)),
    resultTable: result.table,
    resultFingerprint: result.fingerprint,
    regionFingerprint: compactText(getResultRegion().textContent),
  };
}
const RESULT_LOADING_SELECTOR = [
  '[aria-busy="true"]', '[role="progressbar"]', ".spinner-border", ".spinner-grow",
  ".loading-spinner", ".loading-overlay", ".chart-loading", ".fa-spinner.fa-spin",
  ".loader", "#applyTrigger:disabled",
].join(", ");
const isResultLoading = () => {
  const root = getResultRegion();
  if (document.readyState === "loading" || document.querySelector("#applyTrigger")?.disabled) return true;
  const loadingIndicators = root.querySelectorAll(RESULT_LOADING_SELECTOR);
  if (root.matches?.(RESULT_LOADING_SELECTOR) && isVisible(root)) return true;
  return [...loadingIndicators].some(isVisible);
};
const isApplyPending = () => document.readyState === "loading"
  || Boolean(document.querySelector("#applyTrigger")?.disabled);
const mutationCanChangeResult = (mutation) => {
  const nodes = [mutation.target, ...mutation.addedNodes, ...mutation.removedNodes];
  return nodes.some((node) => {
    const target = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    if (!target || target.nodeType !== Node.ELEMENT_NODE) return false;
    if (mutation.type === "attributes") {
      if (target.id === "applyTrigger" && mutation.attributeName === "disabled") return true;
      if (
        mutation.attributeName === "class"
        && /(?:^|\s)(?:spinner-border|spinner-grow|loading-spinner|loading-overlay|chart-loading|fa-spinner|fa-spin|loader)(?:\s|$)/i.test(mutation.oldValue || "")
      ) return true;
      if (mutation.attributeName === "aria-busy" && mutation.oldValue === "true") return true;
      if (mutation.attributeName === "role" && mutation.oldValue === "progressbar") return true;
    }
    if (target.matches?.("table") || target.closest?.("table") || target.querySelector?.("table")) return true;
    if (target.matches?.(EXCEL_BUTTON_SELECTOR) || target.closest?.(EXCEL_BUTTON_SELECTOR) || target.querySelector?.(EXCEL_BUTTON_SELECTOR)) return true;
    if (mutation.type !== "attributes" && target.closest?.(".report-main-column")) return true;
    if (
      target.matches?.(RESULT_LOADING_SELECTOR)
      || target.closest?.(RESULT_LOADING_SELECTOR)
      || target.querySelector?.(RESULT_LOADING_SELECTOR)
    ) return true;
    const text = compactText(target.textContent);
    return text.length <= 240 && (NO_RECORD_TEXT.test(text) || INVALID_CAPTCHA_TEXT.test(text));
  });
};

let resultWatcherJobId;
async function startServerResultWatcher(resultBaseline) {
  const { activeServerJob } = await chrome.storage.local.get("activeServerJob");
  if (!activeServerJob || activeServerJob.stage !== "WAITING_RESULT") return;
  if (resultWatcherJobId === activeServerJob.jobId) return;

  resultWatcherJobId = activeServerJob.jobId;
  try {
    await resumeServerJobAfterApply(activeServerJob, resultBaseline);
  } catch (error) {
    await chrome.runtime.sendMessage({
      type: "SERVER_JOB_PAGE_RESULT", jobId: activeServerJob.jobId,
      result: "FAILED", error: error.message,
    }).catch(() => {});
  } finally {
    if (resultWatcherJobId === activeServerJob.jobId) resultWatcherJobId = undefined;
  }
}

function waitForVahanResult(timeoutMs = 90_000, baseline = null, expectedRto = "") {
  return new Promise((resolve) => {
    let settled = false;
    let checkQueued = false;
    let noRecordTimer;
    let timeoutTimer;
    let observer;
    const baselineInvalidNodes = baseline?.invalidCaptchaNodes || new Set();
    let invalidCaptchaWasCleared = !baseline || baselineInvalidNodes.size === 0;

    const refreshResultTransitions = () => {
      if ([...baselineInvalidNodes].some((node) =>
        !node.isConnected || !isVisible(node) || !INVALID_CAPTCHA_TEXT.test(compactText(node.textContent)))) {
        invalidCaptchaWasCleared = true;
      }
    };
    const hasFreshMessage = (pattern, initialNodes, wasCleared) => {
      const currentNodes = findVisiblePageMessages(pattern);
      if (!baseline) return currentNodes.length > 0;
      return currentNodes.some((node) => !initialNodes.has(node)) || (wasCleared && currentNodes.length > 0);
    };
    const tableChanged = (result) => !baseline || Boolean(result.table && (
      result.table !== baseline.resultTable
      || result.fingerprint !== baseline.resultFingerprint
    ));
    const matchesExpectedRto = () => {
      if (!expectedRto) return true;
      const reportText = compactText(getResultRegion().textContent);
      const displayedRto = reportText.match(/\bRTO\s*\(([^)]*)\)/i)?.[1];
      if (!displayedRto) return false;
      const normalizeRto = (value) => compactText(value).toLocaleLowerCase()
        .replace(/[‐‑‒–—]/g, "-").replace(/\s*[-,]\s*/g, "-");
      const expectedCode = compactText(expectedRto).match(/-\s*([a-z]{1,3}\d+)\s*$/i)?.[1];
      return normalizeRto(displayedRto) === normalizeRto(expectedRto)
        || Boolean(expectedCode && new RegExp(`\\b${expectedCode}\\b`, "i").test(displayedRto));
    };
    const hasFreshReport = (result) => matchesExpectedRto() && (tableChanged(result) || Boolean(
      result.table && baseline
      && compactText(getResultRegion().textContent) !== baseline.regionFingerprint
      && matchesExpectedRto()
    ));

    const finish = (result) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(noRecordTimer);
      window.clearTimeout(timeoutTimer);
      observer?.disconnect();
      chrome.storage.onChanged?.removeListener(onStorageChanged);
      resolve(result);
    };

    const checkDom = () => {
      if (settled) return;
      refreshResultTransitions();
      if (hasFreshMessage(INVALID_CAPTCHA_TEXT, baselineInvalidNodes, invalidCaptchaWasCleared)) {
        finish({ type: "INVALID_CAPTCHA" });
        return;
      }
      const report = readMakerReportResult();
      const fresh = hasFreshReport(report);
      if (fresh && report.type === "DATA" && !isApplyPending() && (tableChanged(report) || !isResultLoading())
        && isUsableExcelButton(findExcelDownloadButton())) {
        finish({ type: "DOWNLOAD_READY" });
        return;
      }
      if (fresh && report.type === "NO_RECORD") {
        if (isResultLoading()) {
          window.clearTimeout(noRecordTimer);
          noRecordTimer = undefined;
          return;
        }
        if (noRecordTimer === undefined) {
          // Confirm only after the current report area is idle. The short
          // window remains, while an active render can no longer create a
          // premature no-data result.
          noRecordTimer = window.setTimeout(() => {
            noRecordTimer = undefined;
            refreshResultTransitions();
            const confirmed = readMakerReportResult();
            if (hasFreshReport(confirmed) && confirmed.type === "DATA"
              && !isApplyPending()
              && (tableChanged(confirmed) || !isResultLoading())
              && isUsableExcelButton(findExcelDownloadButton())) {
              finish({ type: "DOWNLOAD_READY" });
            } else if (hasFreshReport(confirmed) && confirmed.type === "NO_RECORD" && !isResultLoading()) {
              finish({ type: "NO_RECORD" });
            } else {
              queueCheck();
            }
          }, NO_RECORD_CONFIRMATION_MS);
        }
        return;
      }
      window.clearTimeout(noRecordTimer);
      noRecordTimer = undefined;
    };

    const queueCheck = () => {
      if (settled || checkQueued) return;
      checkQueued = true;
      queueMicrotask(() => {
        checkQueued = false;
        checkDom();
      });
    };

    const checkAuthHold = () => {
      getActiveVahanAuthHold().then((hold) => {
        if (hold) finish({ type: "AUTH_REQUIRED", hold });
      }).catch(() => {});
    };

    const onStorageChanged = (changes, areaName) => {
      if (areaName !== "local") return;
      if (changes[VAHAN_AUTH_HOLD_KEY]) checkAuthHold();
      if (changes.activeServerJob && !changes.activeServerJob.newValue) finish({ type: "CANCELLED" });
    };

    observer = new MutationObserver((mutations) => {
      if (mutations.some(mutationCanChangeResult)) queueCheck();
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeOldValue: true,
      attributeFilter: ["class", "style", "hidden", "aria-hidden", "aria-busy", "disabled", "href", "download", "aria-label", "role"],
    });
    chrome.storage.onChanged?.addListener(onStorageChanged);
    timeoutTimer = window.setTimeout(() => finish({ type: "TIMEOUT" }), timeoutMs);
    checkAuthHold();
    checkDom();
  });
}

async function resumeServerJobAfterApply(activeServerJob, resultBaseline = null) {

  updateFloatingStep("captcha", "done");
  updateFloatingStep("apply", "done");
  updateFloatingStep("export", "running");
  setFloatingStatus("running", "Checking for VAHAN results...");

  const outcome = await waitForVahanResult(90_000, resultBaseline, activeServerJob.filters?.rtos?.[0]);
  if (outcome.type === "CANCELLED") return;
  if (outcome.type === "AUTH_REQUIRED") {
    updateFloatingStep("export", "error");
    setFloatingStatus("error", authHoldStatusMessage(outcome.hold));
    await chrome.runtime.sendMessage({ type: "SERVER_JOB_PAGE_RESULT", jobId: activeServerJob.jobId, result: "AUTH_REQUIRED" });
    return;
  }

  if (outcome.type === "INVALID_CAPTCHA") {
    updateFloatingStep("captcha", "error");
    updateFloatingStep("export", "idle");
    setFloatingStatus("waiting", "Incorrect CAPTCHA. Sending the new image to the Web UI...");
    const captcha = await captureCaptcha();
    await chrome.runtime.sendMessage({
      type: "SERVER_JOB_PAGE_RESULT",
      jobId: activeServerJob.jobId,
      result: "INVALID_CAPTCHA",
      captcha,
    });
    return;
  }

  if (outcome.type === "DOWNLOAD_READY") {
    // Every server batch case requires a stored Excel file. The page's
    // autoExport preference only applies to standalone/manual use.
    setFloatingStatus("running", "Report ready. Downloading and verifying the Excel file...");
    await chrome.runtime.sendMessage({ type: "SERVER_JOB_PAGE_RESULT", jobId: activeServerJob.jobId, result: "DOWNLOAD_READY" });
    updateFloatingStep("export", "done");
    return;
  }

  if (outcome.type === "NO_RECORD") {
    updateFloatingStep("export", "idle");
    setFloatingStatus("success", "No record found. Recording State and RTO; skipping Excel.");
    await chrome.runtime.sendMessage({ type: "SERVER_JOB_PAGE_RESULT", jobId: activeServerJob.jobId, result: "NO_RECORD" });
    return;
  }

  updateFloatingStep("export", "error");
  setFloatingStatus("error", "Timed out while waiting for VAHAN results.");
  await chrome.runtime.sendMessage({
    type: "SERVER_JOB_PAGE_RESULT",
    jobId: activeServerJob.jobId,
    result: "FAILED",
    error: "Timed out waiting for the VAHAN result after 90 seconds.",
  });
}

function renderFloatingRunnerConnection(connection = {}) {
  const element = floatingWidget?.shadowRoot?.querySelector(".backend-connection");
  if (!element) return;
  const labels = {
    connected: "Backend connected",
    connecting: "Connecting to backend...",
    disconnected: "Backend disconnected",
    error: "Could not connect to backend",
  };
  element.dataset.state = connection.status || "disconnected";
  element.querySelector("span:last-child").textContent =
    labels[connection.status] || labels.disconnected;
  element.title = connection.detail || "";
}

async function runFromFloatingWidget() {
  const root = floatingWidget.shadowRoot;
  const button = root.querySelector(".start");
  button.disabled = true;
  resetFloatingSteps();
  setFloatingStatus("running", "Loading saved configuration...");
  updateFloatingStep("time", "running");

  try {
    const authHold = await getActiveVahanAuthHold();
    if (authHold) throw new Error(authHoldStatusMessage(authHold));
    const { vahanConfig } = await chrome.storage.local.get("vahanConfig");
    if (!vahanConfig) {
      throw new Error("No configuration found. Open the extension popup and choose filters first.");
    }

    await fillVahan(vahanConfig);
    updateFloatingStep("time", "done");
    updateFloatingStep("vehicle", "done");
    updateFloatingStep("axes", "done");
    updateFloatingStep("captcha", "waiting");
    setFloatingStatus(
      "waiting",
      vahanConfig.autoApply
        ? "Filters filled. Apply will run automatically after you enter the CAPTCHA."
        : "Filters filled. Enter the CAPTCHA and click Apply on VAHAN.",
    );
    button.textContent = "↻ Refill filters";
  } catch (error) {
    updateFloatingStep("time", "error");
    setFloatingStatus("error", error.message);
    button.textContent = "↻ Try again";
  } finally {
    button.disabled = false;
  }
}

function injectFloatingWidget() {
  if (document.getElementById("vahan-rpa-floating-root")) return;

  floatingWidget = document.createElement("div");
  floatingWidget.id = "vahan-rpa-floating-root";
  const root = floatingWidget.attachShadow({ mode: "open" });
  root.innerHTML = `
    <style>
      :host { all: initial; }
      .card {
        position: fixed; right: 16px; bottom: 16px; z-index: 2147483647;
        width: min(340px, calc(100vw - 24px)); overflow: hidden; border: 1px solid #e2e6ec;
        border-radius: 16px; background: #fff; color: #172033;
        box-shadow: 0 8px 24px rgba(15,23,42,.14);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }
      .header {
        display: flex; align-items: center; gap: 8px;
        padding: 11px 14px; border-bottom: 1px solid #eef0f3; color: #172033;
        background: #fff;
      }
      .title { font-size: 13px; font-weight: 600; }
      .toggle {
        width: 28px; height: 28px; margin-left: auto; padding: 0; border: 0; border-radius: 50%;
        background: #f2f4f7; color: #475467; font-size: 16px;
        line-height: 1; cursor: pointer;
      }
      .toggle:hover { background: #e8ecf2; }
      .body { padding: 12px 14px 14px; }
      .body[hidden] { display: none; }
      .backend-connection {
        display: flex; align-items: center; gap: 8px; margin: 0 0 10px;
        color: #596579; font-size: 11px;
      }
      .backend-dot {
        width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%;
        background: #bf8700; box-shadow: 0 0 0 3px rgba(191,135,0,.12);
      }
      .backend-connection[data-state="connected"] .backend-dot {
        background: #2ea44f; box-shadow: 0 0 0 3px rgba(46,164,79,.14);
      }
      .backend-connection[data-state="disconnected"] .backend-dot,
      .backend-connection[data-state="error"] .backend-dot {
        background: #cb2431; box-shadow: 0 0 0 3px rgba(203,36,49,.12);
      }
      .badge {
        display: inline-block; margin-left: auto; padding: 5px 9px;
        border: 1px solid #e4e8ee; border-radius: 999px;
        background: #f7f8fa; color: #475467; font-size: 10px; font-weight: 600;
      }
      .badge[data-state="running"], .badge[data-state="waiting"] {
        border-color: #f4dda6; background: #fff8e8; color: #946200;
      }
      .badge[data-state="success"] { border-color: #c9e9d5; background: #eef8f1; color: #137a37; }
      .badge[data-state="error"] { border-color: #f1c6c6; background: #fff2f2; color: #b42318; }
      .steps { display: flex; flex-direction: column; gap: 7px; margin-bottom: 12px; font-size: 11px; }
      .step { display: flex; align-items: center; gap: 8px; color: #667085; line-height: 1.4; }
      .step-icon { width: 14px; color: #98a2b3; font-size: 14px; font-weight: 600; text-align: center; }
      .step[data-state="running"] { color: #175cd3; font-weight: 600; }
      .step[data-state="waiting"] { color: #946200; font-weight: 600; }
      .step[data-state="done"] { color: #137a37; }
      .step[data-state="error"] { color: #b42318; font-weight: 600; }
      .start {
        width: 100%; min-height: 38px; padding: 9px 14px; border: 0; border-radius: 999px;
        background: #2165d5; color: #fff; font-size: 12px; font-weight: 600;
        cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,.1);
      }
      .start:hover { background: #174ea6; }
      .start:disabled { opacity: .6; cursor: wait; }
      .preferences {
        display: block; margin: 0 0 10px;
        padding: 10px 11px; border: 1px solid #e7eaf0; border-radius: 12px;
        background: #fafbfc;
      }
      .preferences summary { color: #475467; font-size: 11px; font-weight: 600; cursor: pointer; }
      .preferences[open] summary { margin-bottom: 8px; padding-bottom: 7px; border-bottom: 1px solid #e7eaf0; }
      .preference {
        display: flex; align-items: center; gap: 8px; margin-top: 7px; color: #475467;
        font-size: 11px; line-height: 1.4; cursor: pointer;
      }
      .preference input { width: 14px; height: 14px; margin: 0; accent-color: #2165d5; }
      .open-popup {
        width: 100%; min-height: 36px; margin-top: 8px; padding: 8px 12px; border: 1px solid #d7dce4;
        border-radius: 999px; background: #fff; color: #344054; font-size: 11px;
        font-weight: 600; cursor: pointer;
      }
      .open-popup:hover { background: #f7f8fa; border-color: #bfc7d2; }
      .status { min-height: 18px; margin-top: 8px; color: #667085; font-size: 11px; line-height: 1.45; }
    </style>
    <section class="card" aria-label="VAHAN extension">
      <header class="header">
        <div class="title">VAHAN Extension</div>
        <div class="badge" data-state="ready">Ready</div>
        <button class="toggle" type="button" aria-label="Collapse widget" aria-expanded="true">−</button>
      </header>
      <div class="body">
        <div class="backend-connection" data-state="connecting"><span class="backend-dot"></span><span>Connecting to backend...</span></div>
        <div class="steps">
          <div class="step" data-step="time" data-state="idle"><span class="step-icon">○</span><span>Time and region</span></div>
          <div class="step" data-step="vehicle" data-state="idle"><span class="step-icon">○</span><span>Vehicle filters</span></div>
          <div class="step" data-step="axes" data-state="idle"><span class="step-icon">○</span><span>Report axes</span></div>
          <div class="step" data-step="captcha" data-state="idle"><span class="step-icon">○</span><span>Enter CAPTCHA in the Web UI</span></div>
          <div class="step" data-step="apply" data-state="idle"><span class="step-icon">○</span><span data-role="apply-label">Apply</span></div>
          <div class="step" data-step="export" data-state="idle"><span class="step-icon">○</span><span>Download Excel</span></div>
        </div>
        <button class="start" type="button">Fill filters</button>
        <details class="preferences">
          <summary>Quick settings</summary>
          <label class="preference"><input data-setting="autoExport" type="checkbox"><span>Download Excel automatically when results are ready</span></label>
        </details>
        <button class="open-popup" type="button">Connection settings</button>
        <div class="status" role="status">Ready.</div>
      </div>
    </section>`;

  document.body.appendChild(floatingWidget);
  const body = root.querySelector(".body");
  const toggle = root.querySelector(".toggle");
  toggle.addEventListener("click", () => {
    const expanded = toggle.getAttribute("aria-expanded") === "true";
    body.hidden = expanded;
    toggle.textContent = expanded ? "+" : "−";
    toggle.setAttribute("aria-expanded", String(!expanded));
    toggle.setAttribute("aria-label", expanded ? "Expand widget" : "Collapse widget");
  });
  root.querySelector(".start").addEventListener("click", runFromFloatingWidget);
  for (const checkbox of root.querySelectorAll("[data-setting]")) {
    checkbox.addEventListener("change", async () => {
      const { vahanConfig = {} } = await chrome.storage.local.get("vahanConfig");
      vahanConfig[checkbox.dataset.setting] = checkbox.checked;
      await chrome.storage.local.set({ vahanConfig });
    });
  }
  root.querySelector(".open-popup").addEventListener("click", async () => {
    try {
      const response = await chrome.runtime.sendMessage({ type: "OPEN_ACTION_POPUP" });
      if (!response?.ok) throw new Error(response?.error || "Chrome could not open the popup.");
    } catch (error) {
      setFloatingStatus("error", `Could not open settings: ${error.message}`);
    }
  });
  chrome.storage.local.get(["vahanConfig", "runnerConnection"]).then(({ vahanConfig, runnerConnection }) => {
    renderFloatingRunnerConnection(runnerConnection);
    root.querySelector('[data-setting="autoExport"]').checked = vahanConfig?.autoExport ?? true;
    root.querySelector('[data-role="apply-label"]').textContent = "Auto-click Apply";
  });
}

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;
  if (changes.activeServerJob?.newValue) {
    clearInterval(exportWatcherTimer);
    clearTimeout(exportWatcherTimeout);
    exportWatcherTimer = undefined;
    exportWatcherTimeout = undefined;
  }
  if (changes.runnerConnection) {
    renderFloatingRunnerConnection(changes.runnerConnection.newValue);
  }
  if (!changes.vahanConfig) return;
  const previous = changes.vahanConfig.oldValue || {};
  const current = changes.vahanConfig.newValue || {};
  const autoApply = current.autoApply ?? false;
  const autoExport = current.autoExport ?? true;
  const root = floatingWidget?.shadowRoot;

  if (root) {
    root.querySelector('[data-setting="autoExport"]').checked = autoExport;
  }
  if ((previous.autoApply ?? false) !== autoApply) configureAutoApply(autoApply);
  if ((previous.autoExport ?? true) !== autoExport) startAutoExportWatcher();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  let operation;
  if (message?.type === "FILL_VAHAN") operation = fillVahan(message.config).then(() => ({ ok: true }));
  else if (message?.type === "CAPTURE_CAPTCHA") operation = captureCaptcha().then((captcha) => ({ ok: true, ...captcha }));
  else if (message?.type === "REFRESH_CAPTCHA") {
    operation = refreshCaptcha(message.previousCaptchaId).then((captcha) => ({ ok: true, ...captcha }));
  }
  else if (message?.type === "SUBMIT_REMOTE_CAPTCHA") {
    operation = Promise.resolve({ ok: true, ...submitRemoteCaptcha(message.value, message.autoApply) });
  }
  else if (message?.type === "CLICK_EXCEL_DOWNLOAD") {
    const button = findExcelDownloadButton();
    if (readMakerReportResult().type !== "DATA") operation = Promise.resolve({ ok: false, error: "Maker report has no data rows; Excel download skipped." });
    else if (!isUsableExcelButton(button)) operation = Promise.resolve({ ok: false, error: "Excel download button is not available." });
    else {
      window.dispatchEvent(new CustomEvent("__VAHAN_EXCEL_CAPTURE_REQUEST__", { detail: { captureId: message.captureId } }));
      button.click(); operation = Promise.resolve({ ok: true });
    }
  }
  else if (message?.type === "END_EXCEL_CAPTURE") {
    window.dispatchEvent(new CustomEvent("__VAHAN_EXCEL_CAPTURE_REQUEST__", { detail: { captureId: null, previousCaptureId: message.captureId } }));
    operation = Promise.resolve({ ok: true });
  }
  else if (message?.type === "CAPTURE_EXCEL_DOWNLOAD") {
    operation = captureExcelDownload(message.href, message.fileName || "report.xlsx", message.captureId)
      .then(() => ({ ok: true }));
  }
  else if (message?.type === "GET_VAHAN_OPTIONS") operation = Promise.resolve({ ok: true, options: readOptions(message.selectors) });
  else if (message?.type === "GET_STATE_OPTIONS") operation = getStateOptions(message.delhiNcr).then((options) => ({ ok: true, options }));
  else if (message?.type === "GET_RTO_OPTIONS") operation = fetchRtos(message.stateLabels).then((options) => ({ ok: true, options }));
  else if (message?.type === "GET_X_AXIS_OPTIONS") operation = getXAxisOptions(message.yAxis).then((options) => ({ ok: true, options }));
  else if (message?.type === "SEARCH_MAKERS") operation = fetchMakers(message.search).then((options) => ({ ok: true, options }));
  else return;

  operation
    .then(sendResponse)
    .catch((error) => sendResponse({ ok: false, error: error.message }));
  return true;
});

// All extension controls now live in the toolbar popup. Do not inject a
// floating card into the official VAHAN page: it can obscure the result table
// and duplicates the Web UI workflow.
startVahanPageHeartbeat();
initializeAutoApplyPreference();
startAutoExportWatcher();
observeCaptchaChanges();
startServerResultWatcher().catch((error) => console.error("[VAHAN EXT] Result watcher failed:", error));
