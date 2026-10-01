// Shared fail-closed UI contract and diagnostics for the production extension.
// Keep this file before content.js in manifest.json.
(function installVahanUiDrift(global) {
  "use strict";

  const UI_CONTRACT_VERSION = "v1";
  const REPORT_PATH_FRAGMENT = "/analytics/vahanpublicreport";
  const BASE_REQUIRED_CONTROLS = {
    form: "#vahanPublicForm",
    category: "#vehicleCategoryGroup",
    fuel: "#vehicleFuel",
    yaxis: "#yAxis",
    xaxis: "#xAxis",
    captcha: "#externalCaptcha",
    apply: "#applyTrigger",
  };

  const CONTROL_LABELS = {
    form: "form VAHAN Public Report (#vahanPublicForm)",
    category: "Category Group (#vehicleCategoryGroup)",
    vehicleCategoryGroup: "Category Group (#vehicleCategoryGroup)",
    vehicleSubCategory: "Sub-category (#vehicleSubCategory)",
    vehicleClass: "Class (#vehicleClass)",
    fuel: "Fuel (#vehicleFuel)",
    vehicleFuel: "Fuel (#vehicleFuel)",
    yaxis: "Y-Axis (#yAxis)",
    yAxis: "Y-Axis (#yAxis)",
    xaxis: "X-Axis (#xAxis)",
    xAxis: "X-Axis (#xAxis)",
    captcha: "CAPTCHA field (#externalCaptcha)",
    externalCaptcha: "CAPTCHA field (#externalCaptcha)",
    apply: "Apply button (#applyTrigger)",
    applyTrigger: "Apply button (#applyTrigger)",
    archivedFlags: "Archived Flag (#archivedFlags)",
    reportType: "Report Type (#reportType)",
    financialYearSelect: "Financial Year (#financialYearSelect)",
    reportYear: "Report Year (#reportYear)",
    reportMonth: "Report Month (#reportMonth)",
    delhiNcr: "Delhi NCR (#delhiNcr)",
    stateName: "State (#stateName)",
    rtoCode: "RTO (#rtoCode)",
    vehicleEmission: "Emission (#vehicleEmission)",
    vehicleMaker: "Maker (#vehicleMaker)",
    evType: "EV Type (#evType)",
    vehicleStatus: "Status (#vehicleStatus)",
    vehicleOwnerType: "Owner Type (#vehicleOwnerType)",
    vehicleType: "Vehicle Type (#vehicleType)",
    fitnessCheck: "Fitness (#fitnessCheck)",
  };

  class UiDriftError extends Error {
    constructor(code, message, step = "preflight", details = {}) {
      super(message);
      this.name = "UiDriftError";
      this.code = code;
      this.step = step;
      this.details = details;
    }
  }

  function displayDiagnosticValue(value, maxLength = 180) {
    if (value === null || value === undefined || value === "") {
      return "no data";
    }
    const raw = Array.isArray(value) ? value.join(", ") : String(value);
    const text = raw.replace(/\s+/g, " ").trim();
    if (!text) return "no data";
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
  }

  function diagnosticTarget(details = {}, step = "preflight") {
    const key = details.control || details.name;
    if (CONTROL_LABELS[key]) return CONTROL_LABELS[key];

    const selector = details.selector;
    if (selector) {
      const cleanSelector = String(selector).replace(/^#/, "");
      if (CONTROL_LABELS[cleanSelector]) return CONTROL_LABELS[cleanSelector];
      return `control ${displayDiagnosticValue(selector)}`;
    }

    const hiddenSelectId = details.hiddenSelectId || details.hidden_select_id;
    if (hiddenSelectId) {
      const cleanId = String(hiddenSelectId).replace(/^#/, "");
      return CONTROL_LABELS[cleanId] || `control #${cleanId}`;
    }

    if (details.label) return displayDiagnosticValue(details.label);
    return step || "preflight";
  }

  function normalizeControlFingerprint(control) {
    if (!control) return null;
    return {
      tag: control.tag || null,
      id: control.id || null,
      nameAttr: control.nameAttr || null,
      multiple: Boolean(control.multiple),
    };
  }

  function describeControlFingerprint(control) {
    if (!control) return "control does not exist";
    const fingerprint = normalizeControlFingerprint(control);
    return `tag=${fingerprint.tag}; id=${fingerprint.id}; name=${fingerprint.nameAttr}; multiple=${fingerprint.multiple}`;
  }

  function diffControlFingerprints(expectedContract, actualContract) {
    if (!Array.isArray(expectedContract?.controls)) return [];
    const expected = new Map(expectedContract.controls.map((control) => [control.name, control]));
    const actual = new Map((actualContract?.controls || []).map((control) => [control.name, control]));
    const names = new Set([...expected.keys(), ...actual.keys()]);
    return [...names]
      .filter((name) => {
        const expectedControl = normalizeControlFingerprint(expected.get(name));
        const actualControl = normalizeControlFingerprint(actual.get(name));
        return JSON.stringify(expectedControl) !== JSON.stringify(actualControl);
      })
      .map((name) => ({
        name,
        selector: expected.get(name)?.selector || actual.get(name)?.selector || "",
        expected: expected.get(name) || null,
        actual: actual.get(name) || null,
      }));
  }

  function formatUiDrift(error) {
    const details = error?.details || {};
    const code = error?.code || "UI_DRIFT";
    const count = details.count;
    let target = diagnosticTarget(details, error?.step);
    let title;
    let expected;
    let actual;

    if (code === "UI_DRIFT_REQUIRED_CONTROL") {
      title = "Required control is missing or duplicated";
      expected = "The DOM must contain exactly one control";
      actual = `The DOM contains ${count === undefined ? "an unknown number of" : count} control(s)`;
    } else if (code === "UI_DRIFT_CONTROL_TYPE") {
      title = "Control type changed";
      expected = displayDiagnosticValue(details.expected, 100);
      actual = displayDiagnosticValue(
        details.actual || "control is no longer a multi-select (the multiple attribute is missing)"
      );
    } else if (code === "UI_DRIFT_REQUIRED_OPTION") {
      const option = displayDiagnosticValue(
        details.expectedOption || details.expected_option || details.option
      );
      title = "Required option is missing";
      expected = `option '${option}' must exist`;
      actual = displayDiagnosticValue(
        details.actual || "option was removed, renamed, or has not loaded"
      );
    } else if (code === "UI_DRIFT_EMPTY_OPTIONS") {
      title = "Options list is empty";
      expected = "At least one option must be available to continue";
      actual = `The DOM contains ${details.optionCount ?? details.option_count ?? 0} option(s)`;
    } else if (code === "UI_DRIFT_MULTISELECT_WRAPPER") {
      title = "Multi-select wrapper position or count changed";
      expected = "Exactly one wrapper must be in the same form group as the native select";
      actual = `Found ${details.wrapperCount ?? details.wrapper_count ?? "an unknown number of"} wrapper(s)`;
    } else if (code === "UI_DRIFT_WRONG_PAGE") {
      target = "VAHAN Public Report page";
      title = "Wrong page is open";
      expected = displayDiagnosticValue(
        details.expectedUrl || details.expected_url || `URL must include ${REPORT_PATH_FRAGMENT}`,
      );
      actual = displayDiagnosticValue(details.url);
    } else if (code === "UI_DRIFT_CHANGED_DURING_RUN") {
      const change = details.changedControls?.[0] || details.changed_controls?.[0];
      if (change) {
        target = diagnosticTarget({ control: change.name, selector: change.selector }, error?.step);
        title = "Control changed between checks";
        expected = describeControlFingerprint(change.expected);
        actual = describeControlFingerprint(change.actual);
        const totalChanges = (details.changedControls || details.changed_controls || []).length;
        if (totalChanges > 1) actual += `; ${totalChanges - 1} other control(s) also changed`;
      } else {
        target = "UI structure during the workflow";
        title = "UI changed between checks";
        expected = `signature=${displayDiagnosticValue(
          details.expectedSignature || details.expected_signature
        )}`;
        actual = `signature=${displayDiagnosticValue(
          details.actualSignature || details.actual_signature
        )}`;
      }
    } else if (code === "UI_DRIFT_OPTION_NOT_UNIQUE") {
      target = `${displayDiagnosticValue(details.label)} > option '${displayDiagnosticValue(
        details.target || details.targetText
      )}'`;
      title = "Option is no longer unique";
      expected = "Exactly one matching option must be found";
      actual = `Found ${count === undefined ? "an unknown number of" : count} match(es)`;
    } else if (code === "UI_DRIFT_ALL_OPTION_NOT_FOUND") {
      target = `${displayDiagnosticValue(details.label)} > checkbox All`;
      title = "Select All checkbox changed or is missing";
      expected = "Exactly one Select All checkbox must exist";
      actual = `Found ${count === undefined ? "an unknown number of" : count} checkbox(es)`;
    } else if (code === "UI_DRIFT_SEARCH_INPUT") {
      target = `search field for ${displayDiagnosticValue(details.label)}`;
      title = "Multi-select search field is invalid";
      expected = "Exactly one search field must exist";
      actual = `Found ${count === undefined ? "an unknown number of" : count} field(s)`;
    } else if (code === "UI_DRIFT_OPTION_CONTROL") {
      target = `option '${displayDiagnosticValue(details.option)}' trong ${displayDiagnosticValue(
        details.label
      )}`;
      title = "Option control changed";
      expected = "Exactly one checkbox must exist for the option";
      actual = `Found ${details.checkboxCount ?? details.checkbox_count ?? "an unknown number of"} checkbox(es)`;
    } else if (code === "UI_DRIFT_SELECTION_NOT_SYNCED") {
      target = `${displayDiagnosticValue(details.label)} > option '${displayDiagnosticValue(
        details.option
      )}'`;
      title = "Widget and native select are out of sync";
      expected = "The checkbox and native option must both be selected";
      actual = `Current native select value: ${displayDiagnosticValue(
        details.selectedOptions || details.selected
      )}`;
    } else if (code === "UI_DRIFT_AXIS_NOT_SYNCED") {
      target = "Y-Axis/X-Axis and hidden fields";
      title = "Report axis values are out of sync";
      expected = "Hidden fields must match the displayed values";
      actual = `Expected=${displayDiagnosticValue(details.expected)}; Actual=${displayDiagnosticValue(
        details.actual
      )}`;
    } else if (code === "UI_DRIFT_STALE_FLOW_STATE") {
      target = "saved workflow state";
      title = "Saved workflow state has an incomplete contract";
      expected = "A valid UI contract signature must be present";
      actual = "No signature was found";
    } else if (code === "UI_DRIFT_DYNAMIC_CONTROL_TIMEOUT") {
      title = "Dynamic control did not appear in time";
      expected = "Required controls and options must appear within the allowed time";
      actual = `Timed out at step ${displayDiagnosticValue(error?.step)}`;
    } else {
      title = "UI structure does not match the contract";
      expected = "The page must match the tested UI contract";
      actual = `Error code ${code}`;
    }

    const message = `A change was detected at ${target}: ${title}. The tool stopped to avoid incorrect data entry.`;
    const action =
      "A developer should review this area, update the selector or adapter, and rerun the approved UI checks. " +
      "The user does not need to re-enter data until the tool is updated.";
    return {
      code,
      step: error?.step || "preflight",
      title,
      target,
      expected,
      actual,
      action,
      message,
    };
  }

  function requireOne(selector, name, step = "preflight") {
    const matches = document.querySelectorAll(selector);
    if (matches.length !== 1) {
      throw new UiDriftError(
        "UI_DRIFT_REQUIRED_CONTROL",
        `Could not find exactly one required control "${name}".`,
        step,
        { name, selector, count: matches.length }
      );
    }
    return matches[0];
  }

  function getDropdownContainer(hiddenSelectId, step = "filter") {
    const cleanId = String(hiddenSelectId).replace(/^#/, "");
    const hidden = requireOne(`#${cleanId}`, cleanId, step);
    const group = hidden.closest(".form-group");
    let candidates = group ? group.querySelectorAll("div.multiselect-dropdown") : [];
    if (candidates.length !== 1 && hidden.parentElement) {
      candidates = hidden.parentElement.querySelectorAll("div.multiselect-dropdown");
    }
    if (candidates.length !== 1) {
      throw new UiDriftError(
        "UI_DRIFT_MULTISELECT_WRAPPER",
        `Could not identify exactly one multi-select widget for #${cleanId}.`,
        step,
        { hiddenSelectId: cleanId, wrapperCount: candidates.length }
      );
    }
    const wrapper = candidates[0];
    const label = wrapper.getAttribute("aria-label") || cleanId;
    const searchInputs = wrapper.querySelectorAll("input.multiselect-dropdown-search");
    if (searchInputs.length !== 1) {
      throw new UiDriftError(
        "UI_DRIFT_SEARCH_INPUT",
        `Could not identify exactly one search field for #${cleanId}.`,
        step,
        { label, count: searchInputs.length }
      );
    }
    if (hidden.hasAttribute("multiselect-select-all")) {
      const allCheckboxes = wrapper.querySelectorAll(
        ".multiselect-dropdown-all-selector input[type=checkbox]"
      );
      if (allCheckboxes.length !== 1) {
        throw new UiDriftError(
          "UI_DRIFT_ALL_OPTION_NOT_FOUND",
          `Could not identify exactly one Select All checkbox for #${cleanId}.`,
          step,
          { label, count: allCheckboxes.length }
        );
      }
    }
    return wrapper;
  }

  function stableSignature(fingerprint) {
    const canonical = JSON.stringify(fingerprint);
    return Array.from(canonical)
      .reduce((hash, character) => ((hash * 31 + character.charCodeAt(0)) >>> 0), 7)
      .toString(16);
  }

  function collectUiContractErrors(step = "preflight", additionalControls = {}, multiSelectNames = []) {
    if (!window.location.pathname.includes(REPORT_PATH_FRAGMENT)) {
      return {
        contract: null,
        errors: [new UiDriftError(
          "UI_DRIFT_WRONG_PAGE",
          "The current page is not VAHAN Public Report.",
          step,
          { url: window.location.href },
        )],
      };
    }

    const controls = { ...BASE_REQUIRED_CONTROLS, ...additionalControls };
    const fingerprint = [];
    const elements = new Map();
    const errors = [];
    for (const [name, selector] of Object.entries(controls)) {
      let element;
      try {
        element = requireOne(selector, name, step);
      } catch (error) {
        errors.push(error);
        continue;
      }
      elements.set(name, element);
      fingerprint.push({
        name,
        selector,
        tag: element.tagName.toLowerCase(),
        id: element.id,
        nameAttr: element.getAttribute("name"),
        multiple: element.hasAttribute("multiple"),
      });
    }

    const multiNames = multiSelectNames.length ? multiSelectNames : ["category", "fuel"];
    for (const name of multiNames) {
      const selector = controls[name];
      if (!selector) continue;
      const element = elements.get(name);
      if (!element) continue;
      if (!element?.hasAttribute("multiple")) {
        errors.push(new UiDriftError(
          "UI_DRIFT_CONTROL_TYPE",
          `Control ${name} is no longer a multi-select as required by contract ${UI_CONTRACT_VERSION}.`,
          step,
          {
            name,
            expected: "multiple select",
            actual: "control no longer has the multiple attribute",
          }
        ));
        continue;
      }
      try {
        getDropdownContainer(element.id, step);
      } catch (error) {
        errors.push(error);
      }
    }

    return {
      contract: {
        contractVersion: UI_CONTRACT_VERSION,
        signature: stableSignature(fingerprint),
        path: window.location.pathname,
        formAction: elements.get("form")?.getAttribute("action") || "",
        controls: fingerprint,
      },
      errors,
    };
  }

  function getUiContract(step = "preflight", additionalControls = {}, multiSelectNames = []) {
    const validation = collectUiContractErrors(step, additionalControls, multiSelectNames);
    if (validation.errors.length > 0) throw validation.errors[0];
    return validation.contract;
  }

  function assertUiContract(
    step = "preflight",
    expectedSignature = null,
    additionalControls = {},
    multiSelectNames = [],
    expectedContract = null
  ) {
    const contract = getUiContract(step, additionalControls, multiSelectNames);
    if (expectedSignature && expectedSignature !== contract.signature) {
      const changedControls = diffControlFingerprints(expectedContract, contract);
      throw new UiDriftError(
        "UI_DRIFT_CHANGED_DURING_RUN",
        "The UI structure changed while the workflow was running; the data has not been verified.",
        step,
        { expectedSignature, actualSignature: contract.signature, changedControls }
      );
    }
    return contract;
  }

  async function waitForUiContract(
    step = "preflight",
    expectedSignature = null,
    additionalControls = {},
    multiSelectNames = [],
    timeoutMs = 10000,
    expectedContract = null
  ) {
    const startedAt = Date.now();
    let lastError = null;
    while (Date.now() - startedAt < timeoutMs) {
      try {
        return assertUiContract(
          step,
          expectedSignature,
          additionalControls,
          multiSelectNames,
          expectedContract
        );
      } catch (error) {
        lastError = error;
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
    }
    throw lastError || new UiDriftError(
      "UI_DRIFT_DYNAMIC_CONTROL_TIMEOUT",
      "The UI contract was not ready in time.",
      step
    );
  }

  // The repair policy is deliberately small.  A repair is allowed only when
  // the original control is absent and there is exactly one semantic match
  // with the expected tag, name or label.  It never guesses an option, a
  // changed control type, a duplicate element, or a submit/CAPTCHA change.
  const SAFE_CONTROL_IDENTITIES = Object.freeze({
    category: { tag: "select", names: ["vehicleCategoryGroup"], labels: ["category group"] },
    vehicleCategoryGroup: { tag: "select", names: ["vehicleCategoryGroup"], labels: ["category group"] },
    fuel: { tag: "select", names: ["vehicleFuels"], labels: ["fuel"] },
    vehicleFuel: { tag: "select", names: ["vehicleFuels"], labels: ["fuel"] },
    yaxis: { tag: "select", labels: ["y-axis"] },
    yAxis: { tag: "select", labels: ["y-axis"] },
    xaxis: { tag: "select", labels: ["x-axis"] },
    xAxis: { tag: "select", labels: ["x-axis"] },
    captcha: { tag: "input", names: ["externalCaptcha"], labels: ["captcha"] },
    externalCaptcha: { tag: "input", names: ["externalCaptcha"], labels: ["captcha"] },
    apply: { tag: "button", labels: ["apply"] },
    applyTrigger: { tag: "button", labels: ["apply"] },
    archivedFlags: { tag: "select", names: ["archivedFlags"], labels: ["archived flag"] },
    reportType: { tag: "select", names: ["timePeriod"], labels: ["year type"] },
    financialYearSelect: { tag: "select", names: ["financialYearList"], labels: ["financial year"] },
    reportYear: { tag: "select", names: ["reportYear"], labels: ["month / year"] },
    reportMonth: { tag: "select", names: ["reportMonth"], labels: ["month / year"] },
    fromYear: { tag: "input", names: ["fromYear"] },
    toYear: { tag: "input", names: ["toYear"] },
    fromDate: { tag: "input", names: ["fromDate"] },
    toDate: { tag: "input", names: ["toDate"] },
    delhiNcr: { tag: "select", names: ["delhiNcr"], labels: ["delhi ncr"] },
    stateName: { tag: "select", names: ["stateMultiple"], labels: ["state"] },
    rtoCode: { tag: "select", names: ["rtoCodeMultiple"], labels: ["rto"] },
    vehicleEmission: { tag: "select", names: ["vehicleEmissions"], labels: ["emission"] },
    vehicleMaker: { tag: "select", names: ["vehicleMakers"], labels: ["maker"] },
    vehicleSubCategory: { tag: "select", names: ["vehicleSubCategories"], labels: ["sub-category"] },
    vehicleClass: { tag: "select", names: ["vehicleClasses"], labels: ["class"] },
    evType: { tag: "select", names: ["evType"], labels: ["ev type"] },
    vehicleStatus: { tag: "select", names: ["vehicleStatus"], labels: ["status"] },
    vehicleOwnerType: { tag: "select", names: ["vehicleOwnerType"], labels: ["owner type"] },
    vehicleType: { tag: "select", names: ["vehicleType"], labels: ["type"] },
    fitnessCheck: { tag: "select", names: ["fitnessCheck"], labels: ["fitness valid as on date"] },
    yAxisHidden: { tag: "input", names: ["yAxis"] },
    xAxisHidden: { tag: "input", names: ["xAxis"] },
  });

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
  }

  function controlNameFromSelector(selector) {
    return String(selector || "").replace(/^#/, "");
  }

  function safeControlIdentity(name, selector) {
    return SAFE_CONTROL_IDENTITIES[name] ||
      SAFE_CONTROL_IDENTITIES[controlNameFromSelector(selector)] ||
      null;
  }

  function findSemanticControl(name, selector) {
    const identity = safeControlIdentity(name, selector);
    if (!identity) return null;
    const candidates = [...document.querySelectorAll(identity.tag)];
    const byName = candidates.filter((element) => identity.names?.includes(element.getAttribute("name")));
    if (byName.length === 1) return byName[0];
    if (byName.length > 1) return null;

    const expectedLabels = (identity.labels || []).map(normalizeText);
    if (!expectedLabels.length) return null;
    const byLabel = [...document.querySelectorAll("label")]
      .filter((label) => {
        const labelText = normalizeText(label.textContent);
        return expectedLabels.some((expected) => labelText === expected || labelText.includes(expected));
      })
      .map((label) => label.control || (label.htmlFor ? document.getElementById(label.htmlFor) : null))
      .filter((element, index, elements) => element && elements.indexOf(element) === index)
      .filter((element) => candidates.includes(element));
    if (byLabel.length === 1) return byLabel[0];

    if (identity.tag === "button") {
      const byText = candidates.filter((element) => expectedLabels.some((expected) => {
        const text = normalizeText(element.textContent);
        return text === expected || text.includes(expected);
      }));
      if (byText.length === 1) return byText[0];
    }
    return null;
  }

  function repairControlIdentity(name, selector) {
    if (!selector || document.querySelectorAll(selector).length !== 0) return null;
    const candidate = findSemanticControl(name, selector);
    const expectedId = controlNameFromSelector(selector);
    if (!candidate || document.getElementById(expectedId)) return null;

    const previousId = candidate.id;
    const labels = [...document.querySelectorAll("label")].filter((label) =>
      label.control === candidate || (previousId && label.htmlFor === previousId)
    );
    const wrappers = [...document.querySelectorAll("[data-for-select]")].filter((wrapper) =>
      [previousId, candidate.getAttribute("name"), expectedId].filter(Boolean).includes(
        wrapper.getAttribute("data-for-select")
      )
    );

    candidate.id = expectedId;
    labels.forEach((label) => { label.htmlFor = expectedId; });
    wrappers.forEach((wrapper) => { wrapper.dataset.forSelect = expectedId; });
    return {
      target: `#${expectedId}`,
      message: `Restored control detection using ${candidate.getAttribute("name") || "label"}`,
    };
  }

  function repairMovedMultiselectWrapper(hiddenSelectId) {
    const cleanId = controlNameFromSelector(hiddenSelectId);
    if (!cleanId) return null;
    const selects = document.querySelectorAll(`#${cleanId}`);
    if (selects.length !== 1) return null;
    const select = selects[0];
    const target = select.closest(".field-control");
    const group = select.closest(".form-group");
    if (!target || !group) return null;

    const wrappers = [...document.querySelectorAll("[data-for-select]")].filter((wrapper) =>
      wrapper.getAttribute("data-for-select") === cleanId ||
      wrapper.getAttribute("data-for-select") === select.getAttribute("name")
    );
    if (wrappers.length !== 1) return null;
    const wrapper = wrappers[0];
    const ownerGroup = wrapper.closest(".form-group");
    if (ownerGroup && group && ownerGroup !== group) return null;

    const needsClass = !wrapper.classList.contains("multiselect-dropdown");
    const needsMove = wrapper.parentElement !== target;
    if (!needsClass && !needsMove) return null;
    wrapper.classList.add("multiselect-dropdown");
    target.appendChild(wrapper);
    return {
      target: `#${cleanId}`,
      message: "Moved the multi-select wrapper back to the correct form group",
    };
  }

  function trySafeUiRepair(error) {
    if (!error?.code?.startsWith("UI_DRIFT")) return { repaired: false, retry: false };
    const details = error.details || {};

    if (error.code === "UI_DRIFT_REQUIRED_CONTROL") {
      const selector = details.selector;
      const count = details.count ?? (selector ? document.querySelectorAll(selector).length : undefined);
      if (count > 1) return { repaired: false, retry: false };
      const repair = repairControlIdentity(details.name || details.control, selector);
      if (repair) return { repaired: true, ...repair };
      return {
        repaired: false,
        retry: Boolean(safeControlIdentity(details.name || details.control, selector)) && count === 0,
      };
    }

    if (error.code === "UI_DRIFT_MULTISELECT_WRAPPER") {
      const repair = repairMovedMultiselectWrapper(details.hiddenSelectId || details.hidden_select_id);
      if (repair) return { repaired: true, ...repair };
    }
    return { repaired: false, retry: false };
  }

  function createSafeContractGuard({ onRepair = () => {}, maxRepairAttempts = 8 } = {}) {
    let repairNotices = [];

    function recordRepair(repair) {
      const notice = `Safely repaired a UI change at ${repair.target}.`;
      if (!repairNotices.includes(notice)) repairNotices.push(notice);
      onRepair({ ...repair, notice });
    }

    function assertWithSafeRepair(
      step,
      expectedSignature,
      additionalControls,
      multiSelectNames,
      expectedContract
    ) {
      let lastError;
      for (let attempt = 0; attempt < maxRepairAttempts; attempt += 1) {
        try {
          return assertUiContract(
            step,
            expectedSignature,
            additionalControls,
            multiSelectNames,
            expectedContract
          );
        } catch (error) {
          lastError = error;
          const repair = trySafeUiRepair(error);
          if (!repair.repaired) throw error;
          recordRepair(repair);
        }
      }
      throw lastError;
    }

    async function waitForContractWithSafeRepair(
      step = "preflight",
      expectedSignature = null,
      additionalControls = {},
      multiSelectNames = [],
      timeoutMs = 10000,
      expectedContract = null
    ) {
      const deadline = Date.now() + timeoutMs;
      let lastError = null;
      while (Date.now() < deadline) {
        try {
          return assertUiContract(
            step,
            expectedSignature,
            additionalControls,
            multiSelectNames,
            expectedContract
          );
        } catch (error) {
          lastError = error;
          const repair = trySafeUiRepair(error);
          if (repair.repaired) {
            recordRepair(repair);
            await new Promise((resolve) => setTimeout(resolve, 50));
            continue;
          }
          if (!repair.retry) throw error;
          await new Promise((resolve) => setTimeout(resolve, 200));
        }
      }
      throw lastError || new UiDriftError(
        "UI_DRIFT_DYNAMIC_CONTROL_TIMEOUT",
        "The UI contract was not ready in time.",
        step
      );
    }

    return Object.freeze({
      assertWithSafeRepair,
      consumeRepairNotices: () => {
        const notice = repairNotices.join(" ");
        repairNotices = [];
        return notice;
      },
      reset: () => { repairNotices = []; },
      waitForContractWithSafeRepair,
    });
  }

  global.VahanUiDrift = Object.freeze({
    UiDriftError,
    assertUiContract,
    createSafeContractGuard,
    collectUiContractErrors,
    formatUiDrift,
    getDropdownContainer,
    getUiContract,
    isUiDriftError: (error) => Boolean(error?.code?.startsWith("UI_DRIFT")),
    requireOne,
    waitForUiContract,
  });
})(globalThis);
