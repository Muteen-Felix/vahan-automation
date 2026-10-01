/*
 * VAHAN official-page DevTools test harness.
 *
 * Paste this file into the DevTools Console/Snippets of the real page:
 *   https://analytics.parivahan.gov.in/analytics/vahanpublicreport
 *
 * This file only mutates the current DOM. It never fills CAPTCHA, clicks
 * Apply, submits a form, downloads a report, or calls a production API.
 * After each mutation, use Web UI -> "Kiểm tra ngay" exactly once, inspect
 * the new report, then reload the official page before the next case.
 */
(() => {
  "use strict";

  const OFFICIAL_HOST = "analytics.parivahan.gov.in";
  const OFFICIAL_PATH = "/analytics/vahanpublicreport";
  const REQUIRED_CONTROLS = Object.freeze({
    form: "#vahanPublicForm",
    category: "#vehicleCategoryGroup",
    fuel: "#vehicleFuel",
    yaxis: "#yAxis",
    xaxis: "#xAxis",
    captcha: "#externalCaptcha",
    apply: "#applyTrigger",
  });
  const MULTISELECTS = Object.freeze({
    category: "#vehicleCategoryGroup",
    fuel: "#vehicleFuel",
  });

  const normalize = (value) => String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase();

  function assertOfficialPage() {
    const url = new URL(window.location.href);
    const path = url.pathname.replace(/\/+$/, "");
    if (
      url.protocol !== "https:" ||
      url.hostname !== OFFICIAL_HOST ||
      url.port !== "" ||
      path !== OFFICIAL_PATH
    ) {
      throw new Error(
        `Chỉ chạy trên https://${OFFICIAL_HOST}${OFFICIAL_PATH}. URL hiện tại: ${window.location.href}`,
      );
    }
  }

  function one(selector) {
    const matches = document.querySelectorAll(selector);
    if (matches.length !== 1) {
      throw new Error(`${selector}: cần đúng 1 element, hiện có ${matches.length}.`);
    }
    return matches[0];
  }

  function all(selector) {
    return [...document.querySelectorAll(selector)];
  }

  function remove(selector) {
    const element = one(selector);
    element.remove();
    return { selector, applied: true, countAfter: document.querySelectorAll(selector).length };
  }

  function duplicate(selector) {
    const element = one(selector);
    element.parentElement.appendChild(element.cloneNode(true));
    return { selector, applied: true, countAfter: document.querySelectorAll(selector).length };
  }

  function renameId(selector, nextId) {
    const element = one(selector);
    const previousId = element.id;
    element.id = nextId;
    return {
      selector,
      applied: true,
      previousId,
      nextId,
      countAfter: document.querySelectorAll(selector).length,
    };
  }

  function removeAttribute(selector, attribute) {
    const element = one(selector);
    element.removeAttribute(attribute);
    return { selector, attribute, applied: true };
  }

  function removeOption(selector, expectedLabel) {
    const select = one(selector);
    const option = [...select.options].find((item) => normalize(
      item.getAttribute("label") || item.textContent,
    ) === normalize(expectedLabel));
    if (!option) throw new Error(`${selector}: không tìm thấy option '${expectedLabel}'.`);
    option.remove();
    return {
      selector,
      expectedLabel,
      applied: true,
      optionCountAfter: select.options.length,
    };
  }

  function replaceOptions(selector, options) {
    const select = one(selector);
    select.replaceChildren(...options.map(({ label, value }) => new Option(label, value)));
    return { selector, applied: true, optionCountAfter: select.options.length };
  }

  function wrapperFor(selectSelector) {
    const select = one(selectSelector);
    const group = select.closest(".form-group");
    let wrappers = group ? [...group.querySelectorAll("div.multiselect-dropdown")] : [];
    if (wrappers.length !== 1 && select.parentElement) {
      wrappers = [...select.parentElement.querySelectorAll("div.multiselect-dropdown")];
    }
    if (wrappers.length !== 1) {
      throw new Error(`${selectSelector}: cần đúng 1 multiselect wrapper, hiện có ${wrappers.length}.`);
    }
    return wrappers[0];
  }

  function removeWrapper(selectSelector) {
    const wrapper = wrapperFor(selectSelector);
    wrapper.remove();
    return {
      selector: selectSelector,
      applied: true,
      wrapperCountAfter: document.querySelectorAll("div.multiselect-dropdown").length,
    };
  }

  function duplicateWrapper(selectSelector) {
    const wrapper = wrapperFor(selectSelector);
    wrapper.parentElement.appendChild(wrapper.cloneNode(true));
    return {
      selector: selectSelector,
      applied: true,
      wrapperCountAfter: document.querySelectorAll("div.multiselect-dropdown").length,
    };
  }

  function moveWrapper(selectSelector) {
    const wrapper = wrapperFor(selectSelector);
    document.body.appendChild(wrapper);
    return { selector: selectSelector, applied: true, movedTo: "body" };
  }

  function removeSearch(selectSelector) {
    const wrapper = wrapperFor(selectSelector);
    const search = wrapper.querySelectorAll("input.multiselect-dropdown-search");
    if (search.length !== 1) throw new Error(`${selectSelector}: search count=${search.length}.`);
    search[0].remove();
    return { selector: selectSelector, applied: true, searchCountAfter: wrapper.querySelectorAll("input.multiselect-dropdown-search").length };
  }

  function duplicateSearch(selectSelector) {
    const wrapper = wrapperFor(selectSelector);
    const search = wrapper.querySelectorAll("input.multiselect-dropdown-search");
    if (search.length !== 1) throw new Error(`${selectSelector}: search count=${search.length}.`);
    search[0].parentElement.appendChild(search[0].cloneNode(true));
    return { selector: selectSelector, applied: true, searchCountAfter: wrapper.querySelectorAll("input.multiselect-dropdown-search").length };
  }

  function removeAllCheckbox(selectSelector) {
    const wrapper = wrapperFor(selectSelector);
    const allRows = wrapper.querySelectorAll(".multiselect-dropdown-all-selector");
    if (allRows.length !== 1) throw new Error(`${selectSelector}: All count=${allRows.length}.`);
    allRows[0].remove();
    return { selector: selectSelector, applied: true, allCountAfter: wrapper.querySelectorAll(".multiselect-dropdown-all-selector").length };
  }

  function duplicateAllCheckbox(selectSelector) {
    const wrapper = wrapperFor(selectSelector);
    const allRows = wrapper.querySelectorAll(".multiselect-dropdown-all-selector");
    if (allRows.length !== 1) throw new Error(`${selectSelector}: All count=${allRows.length}.`);
    allRows[0].parentElement.appendChild(allRows[0].cloneNode(true));
    return { selector: selectSelector, applied: true, allCountAfter: wrapper.querySelectorAll(".multiselect-dropdown-all-selector").length };
  }

  function applyCase(_caseId, definition) {
    return definition.apply();
  }

  const cases = {
    baseline: {
      phase: "health-check",
      expectedStatus: "PASS",
      expectedCodes: [],
      mutation: "không thay đổi DOM",
      confirmRequired: false,
      apply: () => ({ applied: false }),
    },
    "missing-category": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "xóa #vehicleCategoryGroup",
      confirmRequired: true,
      apply: () => remove(REQUIRED_CONTROLS.category),
    },
    "missing-fuel": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "xóa #vehicleFuel",
      confirmRequired: true,
      apply: () => remove(REQUIRED_CONTROLS.fuel),
    },
    "missing-yaxis": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "xóa #yAxis",
      confirmRequired: true,
      apply: () => remove(REQUIRED_CONTROLS.yaxis),
    },
    "missing-xaxis": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "xóa #xAxis",
      confirmRequired: true,
      apply: () => remove(REQUIRED_CONTROLS.xaxis),
    },
    "missing-captcha": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "xóa #externalCaptcha",
      confirmRequired: true,
      apply: () => remove(REQUIRED_CONTROLS.captcha),
    },
    "missing-apply": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "xóa #applyTrigger",
      confirmRequired: true,
      apply: () => remove(REQUIRED_CONTROLS.apply),
    },
    "missing-form": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "xóa #vahanPublicForm; có thể tạo thêm lỗi thiếu control con",
      confirmRequired: true,
      apply: () => remove(REQUIRED_CONTROLS.form),
    },
    "renamed-category": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "đổi id #vehicleCategoryGroup thành vehicleCategoryGroupRenamed",
      confirmRequired: true,
      apply: () => renameId(REQUIRED_CONTROLS.category, "vehicleCategoryGroupRenamed"),
    },
    "renamed-fuel": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "đổi id #vehicleFuel thành vehicleFuelRenamed",
      confirmRequired: true,
      apply: () => renameId(REQUIRED_CONTROLS.fuel, "vehicleFuelRenamed"),
    },
    "duplicate-category": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "nhân đôi #vehicleCategoryGroup",
      confirmRequired: true,
      apply: () => duplicate(REQUIRED_CONTROLS.category),
    },
    "duplicate-fuel": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "nhân đôi #vehicleFuel",
      confirmRequired: true,
      apply: () => duplicate(REQUIRED_CONTROLS.fuel),
    },
    "duplicate-yaxis": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "nhân đôi #yAxis",
      confirmRequired: true,
      apply: () => duplicate(REQUIRED_CONTROLS.yaxis),
    },
    "duplicate-xaxis": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      mutation: "nhân đôi #xAxis",
      confirmRequired: true,
      apply: () => duplicate(REQUIRED_CONTROLS.xaxis),
    },
    "wrong-category-type": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_CONTROL_TYPE"],
      mutation: "xóa thuộc tính multiple của #vehicleCategoryGroup",
      confirmRequired: true,
      apply: () => removeAttribute(REQUIRED_CONTROLS.category, "multiple"),
    },
    "wrong-fuel-type": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_CONTROL_TYPE"],
      mutation: "xóa thuộc tính multiple của #vehicleFuel",
      confirmRequired: true,
      apply: () => removeAttribute(REQUIRED_CONTROLS.fuel, "multiple"),
    },
    "missing-category-option": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_OPTION"],
      mutation: "xóa option Two Wheeler khỏi #vehicleCategoryGroup",
      confirmRequired: true,
      apply: () => removeOption(REQUIRED_CONTROLS.category, "Two Wheeler"),
    },
    "missing-yaxis-option": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_OPTION"],
      mutation: "xóa option Fuel khỏi #yAxis",
      confirmRequired: true,
      apply: () => removeOption(REQUIRED_CONTROLS.yaxis, "Fuel"),
    },
    "empty-fuel-options": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_EMPTY_OPTIONS"],
      mutation: "xóa toàn bộ option của #vehicleFuel",
      confirmRequired: true,
      apply: () => replaceOptions(REQUIRED_CONTROLS.fuel, []),
    },
    "missing-category-wrapper": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_MULTISELECT_WRAPPER"],
      mutation: "xóa wrapper multiselect Category",
      confirmRequired: true,
      apply: () => removeWrapper(MULTISELECTS.category),
    },
    "duplicate-category-wrapper": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_MULTISELECT_WRAPPER"],
      mutation: "nhân đôi wrapper multiselect Category",
      confirmRequired: true,
      apply: () => duplicateWrapper(MULTISELECTS.category),
    },
    "moved-category-wrapper": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_MULTISELECT_WRAPPER"],
      mutation: "đưa wrapper Category ra body",
      confirmRequired: true,
      apply: () => moveWrapper(MULTISELECTS.category),
    },
    "missing-fuel-wrapper": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_MULTISELECT_WRAPPER"],
      mutation: "xóa wrapper multiselect Fuel",
      confirmRequired: true,
      apply: () => removeWrapper(MULTISELECTS.fuel),
    },
    "duplicate-fuel-wrapper": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_MULTISELECT_WRAPPER"],
      mutation: "nhân đôi wrapper multiselect Fuel",
      confirmRequired: true,
      apply: () => duplicateWrapper(MULTISELECTS.fuel),
    },
    "moved-fuel-wrapper": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_MULTISELECT_WRAPPER"],
      mutation: "đưa wrapper Fuel ra body",
      confirmRequired: true,
      apply: () => moveWrapper(MULTISELECTS.fuel),
    },
    "missing-fuel-search": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_SEARCH_INPUT"],
      mutation: "xóa ô search trong wrapper Fuel",
      confirmRequired: true,
      apply: () => removeSearch(MULTISELECTS.fuel),
    },
    "duplicate-fuel-search": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_SEARCH_INPUT"],
      mutation: "nhân đôi ô search trong wrapper Fuel",
      confirmRequired: true,
      apply: () => duplicateSearch(MULTISELECTS.fuel),
    },
    "missing-fuel-all": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_ALL_OPTION_NOT_FOUND"],
      mutation: "xóa checkbox All trong wrapper Fuel",
      confirmRequired: true,
      apply: () => removeAllCheckbox(MULTISELECTS.fuel),
    },
    "duplicate-fuel-all": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_ALL_OPTION_NOT_FOUND"],
      mutation: "nhân đôi checkbox All trong wrapper Fuel",
      confirmRequired: true,
      apply: () => duplicateAllCheckbox(MULTISELECTS.fuel),
    },
    "two-drift": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      expectedErrorCount: 2,
      mutation: "xóa #vehicleCategoryGroup và #vehicleFuel trong cùng một lượt",
      confirmRequired: true,
      apply: () => ({
        results: [remove(REQUIRED_CONTROLS.category), remove(REQUIRED_CONTROLS.fuel)],
        applied: true,
      }),
    },
    "multi-drift": {
      phase: "health-check",
      expectedStatus: "UI_DRIFT",
      expectedCodes: ["UI_DRIFT_REQUIRED_CONTROL"],
      expectedErrorCount: 6,
      mutation: "xóa Category, Fuel, Y-Axis, X-Axis, CAPTCHA và Apply trong cùng một lượt",
      confirmRequired: true,
      apply: () => ({
        results: [
          remove(REQUIRED_CONTROLS.category),
          remove(REQUIRED_CONTROLS.fuel),
          remove(REQUIRED_CONTROLS.yaxis),
          remove(REQUIRED_CONTROLS.xaxis),
          remove(REQUIRED_CONTROLS.captcha),
          remove(REQUIRED_CONTROLS.apply),
        ],
        applied: true,
      }),
    },
    "data-changed-fuel": {
      phase: "health-check",
      expectedStatus: "DATA_CHANGED",
      expectedCodes: ["UI_DRIFT_OPTION_DATA_CHANGED"],
      mutation: "thay dataset option của #vehicleFuel; cần chạy baseline trước",
      confirmRequired: true,
      apply: () => replaceOptions(REQUIRED_CONTROLS.fuel, [
        { label: "DevTools Test Fuel", value: "DEVTOOLS_TEST_FUEL" },
        { label: "DevTools Test Hybrid", value: "DEVTOOLS_TEST_HYBRID" },
      ]),
    },
    "data-changed-category": {
      phase: "health-check",
      expectedStatus: "DATA_CHANGED",
      expectedCodes: ["UI_DRIFT_OPTION_DATA_CHANGED"],
      mutation: "thay dataset option của #vehicleCategoryGroup; cần chạy baseline trước",
      confirmRequired: true,
      apply: () => replaceOptions(REQUIRED_CONTROLS.category, [
        { label: "Two Wheeler", value: "Two Wheeler" },
      ]),
    },
    "data-changed-yaxis": {
      phase: "health-check",
      expectedStatus: "DATA_CHANGED",
      expectedCodes: ["UI_DRIFT_OPTION_DATA_CHANGED"],
      mutation: "thay dataset option của #yAxis; cần chạy baseline trước",
      confirmRequired: true,
      apply: () => replaceOptions(REQUIRED_CONTROLS.yaxis, [
        { label: "Fuel", value: "vehicleFuel" },
      ]),
    },
    "data-changed-xaxis": {
      phase: "health-check",
      expectedStatus: "DATA_CHANGED",
      expectedCodes: ["UI_DRIFT_OPTION_DATA_CHANGED"],
      mutation: "thay dataset option của #xAxis; cần chạy baseline trước",
      confirmRequired: true,
      apply: () => replaceOptions(REQUIRED_CONTROLS.xaxis, [
        { label: "State Wise", value: "stateCode" },
      ]),
    },
    "data-changed-category-and-fuel": {
      phase: "health-check",
      expectedStatus: "DATA_CHANGED",
      expectedCodes: ["UI_DRIFT_OPTION_DATA_CHANGED"],
      expectedDataChangeCount: 2,
      mutation: "thay dataset option của Category và Fuel cùng một lượt; cần chạy baseline trước",
      confirmRequired: true,
      apply: () => ({
        results: [
          replaceOptions(REQUIRED_CONTROLS.category, [
            { label: "Two Wheeler", value: "Two Wheeler" },
          ]),
          replaceOptions(REQUIRED_CONTROLS.fuel, [
            { label: "DevTools Test Fuel", value: "DEVTOOLS_TEST_FUEL" },
          ]),
        ],
        applied: true,
      }),
    },
    "visual-only": {
      phase: "health-check",
      expectedStatus: "PASS",
      expectedCodes: [],
      mutation: "đổi style/data attribute, không đổi DOM contract",
      confirmRequired: true,
      apply: () => {
        document.documentElement.dataset.vahanDevtoolsVisualTest = "1";
        document.body.style.outline = "6px solid magenta";
        return { applied: true, note: "reload để khôi phục style" };
      },
    },
  };

  function snapshot() {
    assertOfficialPage();
    const controls = Object.fromEntries(Object.entries(REQUIRED_CONTROLS).map(([name, selector]) => [
      name,
      document.querySelectorAll(selector).length,
    ]));
    const wrappers = Object.fromEntries(Object.entries(MULTISELECTS).map(([name, selector]) => [
      name,
      (() => {
        try {
          return wrapperFor(selector).parentElement?.querySelectorAll("div.multiselect-dropdown").length || 0;
        } catch {
          return 0;
        }
      })(),
    ]));
    return {
      url: window.location.href,
      controls,
      wrappers,
      fuelOptionCount: document.querySelector(REQUIRED_CONTROLS.fuel)?.options.length || 0,
      categoryOptionCount: document.querySelector(REQUIRED_CONTROLS.category)?.options.length || 0,
      yaxisOptionCount: document.querySelector(REQUIRED_CONTROLS.yaxis)?.options.length || 0,
    };
  }

  function list() {
    return Object.entries(cases).map(([caseId, definition]) => ({
      caseId,
      phase: definition.phase,
      expectedStatus: definition.expectedStatus,
      expectedCodes: definition.expectedCodes,
      expectedErrorCount: definition.expectedErrorCount || 1,
      expectedDataChangeCount: definition.expectedDataChangeCount || 0,
      mutation: definition.mutation,
    }));
  }

  function run(caseId, options = {}) {
    assertOfficialPage();
    const definition = cases[caseId];
    if (!definition) throw new Error(`Case không tồn tại: ${caseId}`);
    if (definition.confirmRequired && options.confirm !== true) {
      throw new Error(
        `Case '${caseId}' thay đổi DOM thật. Gọi VahanOfficialDevTools.run('${caseId}', { confirm: true }).`,
      );
    }
    const details = applyCase(caseId, { ...definition, confirmRequired: false });
    const entry = {
      source: "vahan-official-devtools",
      caseId,
      phase: definition.phase,
      expectedStatus: definition.expectedStatus,
      expectedCodes: definition.expectedCodes,
      expectedErrorCount: definition.expectedErrorCount || 1,
      expectedDataChangeCount: definition.expectedDataChangeCount || 0,
      mutation: definition.mutation,
      details,
      timestamp: new Date().toISOString(),
      nextStep: "Mở Web UI -> Kiểm tra ngay đúng một lần, xem reports[]/errorCount, rồi reload trang official.",
    };
    console.warn(`[VAHAN OFFICIAL DEVTOOLS][${caseId}]`, entry);
    console.table({
      caseId: entry.caseId,
      expectedStatus: entry.expectedStatus,
      expectedCodes: entry.expectedCodes.join(", "),
      expectedErrorCount: entry.expectedErrorCount,
      expectedDataChangeCount: entry.expectedDataChangeCount,
      mutation: entry.mutation,
    });
    return entry;
  }

  function restore() {
    assertOfficialPage();
    window.location.reload();
  }

  const api = Object.freeze({
    list,
    restore,
    run,
    snapshot,
    help: () => console.table({
      list: "VahanOfficialDevTools.list()",
      snapshot: "VahanOfficialDevTools.snapshot()",
      run: "VahanOfficialDevTools.run('two-drift', { confirm: true })",
      restore: "VahanOfficialDevTools.restore()",
      workflow: "run case -> Web UI #configure -> Kiểm tra ngay -> xem reports[]/errorCount -> reload",
    }),
  });

  assertOfficialPage();
  globalThis.VahanOfficialDevTools = api;
  console.info(
    "[VAHAN OFFICIAL DEVTOOLS] Harness loaded. Chỉ đọc/mutate DOM; không CAPTCHA, không Apply.",
  );
  console.info("Gõ VahanOfficialDevTools.help() hoặc console.table(VahanOfficialDevTools.list())");
})();