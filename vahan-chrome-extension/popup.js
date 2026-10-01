const runnerConnection = document.querySelector("#runnerConnection");
const connectionDetail = document.querySelector("#connectionDetail");
const runnerServerUrl = document.querySelector("#runnerServerUrl");
const runnerName = document.querySelector("#runnerName");
const runnerToken = document.querySelector("#runnerToken");
const saveRunnerConfigButton = document.querySelector("#saveRunnerConfig");
const workflowBadge = document.querySelector("#workflowBadge");
const workflowTitle = document.querySelector("#workflowTitle");
const workflowMeta = document.querySelector("#workflowMeta");
const workflowDetail = document.querySelector("#workflowDetail");
const workflowJobId = document.querySelector("#workflowJobId");
const authGuard = document.querySelector("#authGuard");
const authGuardMessage = document.querySelector("#authGuardMessage");
const clearAuthHoldButton = document.querySelector("#clearAuthHold");
const reloadVahanTabButton = document.querySelector("#reloadVahanTab");
const status = document.querySelector("#status");
const statusTab = document.querySelector("#statusTab");
const settingsTab = document.querySelector("#settingsTab");
const statusView = document.querySelector("#statusView");
const backendSettings = document.querySelector("#backendSettings");
const successfulApplyCountElement = document.querySelector("#successfulApplyCount");
const resetApplyCountButton = document.querySelector("#resetApplyCount");
const applyCountFeedback = document.querySelector("#applyCountFeedback");

function renderSuccessfulApplyCount(value) {
  const count = Number(value);
  const safeCount = Number.isSafeInteger(count) && count > 0 ? count : 0;
  successfulApplyCountElement.textContent = new Intl.NumberFormat("en-GB").format(safeCount);
}

function setApplyCountFeedback(message = "", kind = "") {
  applyCountFeedback.className = `apply-count-feedback ${kind}`.trim();
  applyCountFeedback.textContent = message;
}

function showPopupView(view) {
  const showingSettings = view === "settings";
  statusView.hidden = showingSettings;
  backendSettings.hidden = !showingSettings;
  statusTab.classList.toggle("active", !showingSettings);
  settingsTab.classList.toggle("active", showingSettings);
  statusTab.setAttribute("aria-selected", String(!showingSettings));
  settingsTab.setAttribute("aria-selected", String(showingSettings));
}

statusTab.addEventListener("click", () => showPopupView("status"));
settingsTab.addEventListener("click", () => showPopupView("settings"));

const connectionLabels = {
  connected: "Backend connected",
  connecting: "Connecting to backend...",
  disconnected: "Backend disconnected",
  error: "Could not connect to backend",
};

const workflowStates = {
  QUEUED: { state: "running", detail: "Queued" },
  ASSIGNED: { state: "running", detail: "Assigned to extension" },
  OPENING_VAHAN: { state: "running", detail: "Opening VAHAN" },
  CAPTURING_CAPTCHA: { state: "running", detail: "Loading CAPTCHA" },
  FILLING_FILTERS: { state: "running", detail: "Filling filters" },
  WAITING_CAPTCHA: { state: "waiting", detail: "Waiting for CAPTCHA on VAHAN" },
  SUBMITTING: { state: "running", detail: "Submitting CAPTCHA to VAHAN" },
  WAITING_RESULT: { state: "running", detail: "Waiting for VAHAN results" },
  DOWNLOADING_REPORT: { state: "running", detail: "Downloading Excel" },
  UPLOADING_REPORT: { state: "running", detail: "Saving Excel" },
  COMPLETED: { state: "success", detail: "Completed" },
  FAILED: { state: "error", detail: "Job failed" },
  CANCELLED: { state: "error", detail: "Job cancelled" },
};

function renderWorkflowScenario(scenarioName, fallbackTitle) {
  workflowMeta.replaceChildren();
  workflowMeta.hidden = true;

  const fullName = typeof scenarioName === "string" ? scenarioName.trim() : "";
  const parts = fullName.split(/\s*\|\s*/).filter(Boolean);
  if (parts.length < 2) {
    workflowTitle.textContent = fullName || fallbackTitle;
    workflowTitle.title = fullName;
    return;
  }

  const caseMatch = parts[0].match(/^(?:case\s*)?(\d+)$/i);
  const categoryIndex = caseMatch ? 1 : 0;
  workflowTitle.textContent = caseMatch
    ? `Case ${caseMatch[1]} · ${parts[categoryIndex]}`
    : parts[categoryIndex];
  workflowTitle.title = fullName;

  const filterParts = parts.slice(categoryIndex + 1);
  for (const filter of filterParts) {
    const axisMatch = filter.match(/^([YX])\s*=\s*(.+)$/i);
    const axisPairMatch = filter.match(/^Y\s*=\s*(.+?)\s*\/\s*X\s*=\s*(.+)$/i);
    if (axisPairMatch) {
      addWorkflowChip(`Y · ${axisPairMatch[1]}`);
      addWorkflowChip(`X · ${axisPairMatch[2]}`);
    } else if (axisMatch) {
      addWorkflowChip(`${axisMatch[1].toUpperCase()} · ${axisMatch[2]}`);
    } else {
      addWorkflowChip(filter);
    }
  }
  workflowMeta.hidden = workflowMeta.childElementCount === 0;
}

function addWorkflowChip(label) {
  const chip = document.createElement("span");
  chip.className = "workflow-chip";
  chip.textContent = label;
  workflowMeta.append(chip);
}

function renderRunnerConnection(connection = {}) {
  const connectionState = connection.status || "disconnected";
  runnerConnection.dataset.state = connectionState;
  runnerConnection.querySelector(".connection-text").textContent =
    connectionLabels[connectionState] || connectionLabels.disconnected;
  connectionDetail.textContent = connection.detail || "No recent connection details.";
}

function renderWorkflow(job) {
  if (!job?.jobId) {
    workflowBadge.dataset.state = "idle";
    workflowBadge.textContent = "Ready";
    workflowTitle.textContent = "No job yet";
    workflowTitle.removeAttribute("title");
    workflowMeta.replaceChildren();
    workflowMeta.hidden = true;
    workflowDetail.textContent = "Create a report in the Web UI to get started.";
    workflowDetail.dataset.state = "idle";
    workflowJobId.hidden = true;
    return;
  }

  const stage = workflowStates[job.stage] || { state: "running", detail: "Processing" };
  workflowBadge.dataset.state = stage.state;
  workflowBadge.textContent = stage.state === "waiting"
    ? "Action required"
    : stage.state === "success"
      ? "Completed"
      : stage.state === "error"
        ? "Error"
        : "Processing";
  renderWorkflowScenario(job.scenarioName, stage.detail);
  workflowDetail.textContent = stage.detail;
  workflowDetail.dataset.state = stage.state;
  workflowJobId.hidden = false;
  workflowJobId.textContent = `Job ${job.jobId}`;
  workflowJobId.title = job.jobId;
}

function renderAuthHold(hold) {
  const active = Boolean(hold?.code === "VAHAN_AUTH_REQUIRED");
  authGuard.hidden = !active;
  if (!active) {
    authGuardMessage.textContent = "";
    return;
  }
  const retryAfter = hold.retryAfter ? new Date(hold.retryAfter).toLocaleString("en-GB") : "after confirmation";
  authGuardMessage.textContent = `VAHAN returned HTTP 401. The extension is paused to prevent repeated retries. Close the dialog and wait until ${retryAfter}.`;
}

function setStatus(message = "", kind = "") {
  status.className = `form-status ${kind}`.trim();
  status.textContent = message;
}

async function loadRunnerConfig() {
  const { runnerConfig = {} } = await chrome.storage.local.get("runnerConfig");
  runnerServerUrl.value = runnerConfig.serverUrl || "http://127.0.0.1:8000";
  runnerName.value = runnerConfig.runnerName || "VAHAN Chrome";
  runnerToken.value = runnerConfig.token || "change-me";
}

async function loadPopupState() {
  const {
    runnerConnection,
    activeServerJob,
    vahanAuthHold,
    successfulApplyCount,
  } = await chrome.storage.local.get([
    "runnerConnection", "activeServerJob", "vahanAuthHold", "successfulApplyCount",
  ]);
  renderRunnerConnection(runnerConnection);
  renderWorkflow(activeServerJob);
  renderAuthHold(vahanAuthHold);
  renderSuccessfulApplyCount(successfulApplyCount);
}

resetApplyCountButton.addEventListener("click", async () => {
  resetApplyCountButton.disabled = true;
  setApplyCountFeedback();
  try {
    const response = await chrome.runtime.sendMessage({ type: "RESET_SUCCESSFUL_APPLY_COUNT" });
    if (!response?.ok) throw new Error(response?.error || "Could not reset the counter.");
    renderSuccessfulApplyCount(response.count);
    setApplyCountFeedback("Counter reset.", "success");
  } catch (error) {
    setApplyCountFeedback(error.message || "Could not reset the counter.", "error");
  } finally {
    resetApplyCountButton.disabled = false;
  }
});

saveRunnerConfigButton.addEventListener("click", async () => {
  const serverUrl = runnerServerUrl.value.trim().replace(/\/$/, "");
  if (!/^https?:\/\//i.test(serverUrl)) {
    setStatus("Server URL must start with http:// or https://", "error");
    return;
  }

  saveRunnerConfigButton.disabled = true;
  try {
    const { runnerConfig = {} } = await chrome.storage.local.get("runnerConfig");
    await chrome.storage.local.set({
      runnerConfig: {
        ...runnerConfig,
        serverUrl,
        runnerName: runnerName.value.trim() || "VAHAN Chrome",
        token: runnerToken.value,
      },
    });
    renderRunnerConnection({ status: "connecting", detail: "Reconnecting to backend..." });
    setStatus("Settings saved. Reconnecting the extension...", "success");
  } catch (error) {
    setStatus(error.message || "Could not save backend settings.", "error");
  } finally {
    saveRunnerConfigButton.disabled = false;
  }
});

clearAuthHoldButton.addEventListener("click", async () => {
  clearAuthHoldButton.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "CLEAR_VAHAN_AUTH_HOLD" });
    if (!response?.ok) throw new Error(response?.error || "Could not clear the pause.");
    renderAuthHold(null);
    setStatus("Pause cleared. Reload the VAHAN tab before starting a new job.", "success");
  } catch (error) {
    setStatus(error.message || "Could not clear the pause.", "error");
  } finally {
    clearAuthHoldButton.disabled = false;
  }
});

reloadVahanTabButton?.addEventListener("click", async () => {
  reloadVahanTabButton.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "RELOAD_VAHAN_PAGE" });
    if (!response?.ok) throw new Error(response?.error || "Could not reload the VAHAN page.");
    renderAuthHold(null);
    setStatus("Reloading the VAHAN page...", "success");
  } catch (error) {
    setStatus(error.message || "Could not reload the VAHAN page.", "error");
  } finally {
    reloadVahanTabButton.disabled = false;
  }
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "RUNNER_CONNECTION_CHANGED") renderRunnerConnection(message.connection);
  if (message?.type === "VAHAN_AUTH_REQUIRED") renderAuthHold(message.authHold);
  if (message?.type === "VAHAN_AUTH_CLEARED") renderAuthHold(null);
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;
  if (changes.runnerConnection) renderRunnerConnection(changes.runnerConnection.newValue);
  if (changes.activeServerJob) renderWorkflow(changes.activeServerJob.newValue);
  if (changes.vahanAuthHold) renderAuthHold(changes.vahanAuthHold.newValue);
  if (changes.successfulApplyCount) renderSuccessfulApplyCount(changes.successfulApplyCount.newValue);
});

document.addEventListener("DOMContentLoaded", async () => {
  await loadRunnerConfig();
  await loadPopupState();
});
