import { useCallback, useEffect, useRef, useState } from "react";

import { CaptchaPanel } from "./components/CaptchaPanel";
import { ConnectionBanner } from "./components/ConnectionBanner";
import { ExportedReportsList } from "./components/ExportedReportsList";
import { HealthCheckReports } from "./components/HealthCheckReports";
import { HealthCheckSchedule } from "./components/HealthCheckSchedule";
import { JobStatus } from "./components/JobStatus";
import { MatrixRunner } from "./components/MatrixRunner";
import { buildMatrix, currentReportYear, MATRIX_STORAGE_KEY, readMatrixPlan, updateMatrixYear, type MatrixPlan } from "./matrix-plan";
import type {
  Acknowledgement,
  CaptchaChallenge,
  ConnectionState,
  Job,
  PendingUiHealthCheck,
  Runner,
  ReportSource,
  Scenario,
  UiHealthCheckNowResponse,
  VahanFilters,
} from "./contracts";
import { AUTH_REQUIRED_EVENT, ApiError, api } from "./services/api-client";
import { uiSocket } from "./services/socket-client";
import type { FilterTiming } from "./batch-timing";

const ACTIVE_JOB_STORAGE_KEY = "vahanActiveJobId";
const BATCH_RECOVERY_STORAGE_KEY = "vahanStateRtoBatchRecoveryV1";
const UI_SOCKET_ACK_TIMEOUT_MS = 15_000;
const CAPTCHA_REFRESH_ACK_TIMEOUT_MS = 25_000;
const EMPTY_SCENARIOS: Scenario[] = [];
type AppSection = "configure" | "reports" | "settings";
type BatchStatus = "idle" | "running" | "completed" | "completed_with_errors" | "stopped" | "error";

interface BatchLogEntry {
  index: number;
  name: string;
  state?: string;
  rto?: string;
  status: "ok" | "empty" | "error";
  detail: string;
  jobId?: string;
  excelFileName?: string | null;
  noDataFileName?: string | null;
  durationMs?: number;
}

interface PersistedBatchRecovery {
  version: 1;
  status: BatchStatus;
  queueIndices: number[];
  nextPosition: number;
  currentIndex: number | null;
  activeJobId: string | null;
  stopRequested: boolean;
  hadErrors: boolean;
  log: BatchLogEntry[];
  failedAtIndex: number | null;
  progress: { done: number; total: number; current: string };
  sessionId: string;
  source?: ReportSource;
  year: number;
  startedAt?: string;
  finishedAt?: string | null;
  timings?: FilterTiming[];
  currentFilterStartedAt?: number | null;
}

function readBatchRecovery(): PersistedBatchRecovery | null {
  try {
    const raw = localStorage.getItem(BATCH_RECOVERY_STORAGE_KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as PersistedBatchRecovery;
    if (stored.source === "old") {
      localStorage.removeItem(BATCH_RECOVERY_STORAGE_KEY);
      localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
      localStorage.removeItem("vahanHundredSessionsV1");
      return null;
    }
    const validStatuses: BatchStatus[] = ["idle", "running", "completed", "completed_with_errors", "stopped", "error"];
    if (
      stored.version !== 1
      || !validStatuses.includes(stored.status)
      || !Array.isArray(stored.queueIndices)
      || !stored.queueIndices.every((index) => Number.isInteger(index) && index >= 0)
      || !Number.isInteger(stored.nextPosition)
      || stored.nextPosition < 0
      || stored.nextPosition > stored.queueIndices.length
      || !Array.isArray(stored.log)
      || typeof stored.stopRequested !== "boolean"
      || typeof stored.hadErrors !== "boolean"
      || !stored.progress
      || !Number.isFinite(stored.progress.done)
      || !Number.isFinite(stored.progress.total)
      || typeof stored.progress.current !== "string"
      || typeof stored.sessionId !== "string"
      || !Number.isInteger(stored.year)
    ) return null;
    return {
      ...stored,
      timings: Array.isArray(stored.timings) ? stored.timings.filter((sample) =>
        sample && Number.isInteger(sample.index) && Number.isFinite(sample.durationMs) && sample.durationMs >= 0) : [],
      currentFilterStartedAt: Number.isFinite(stored.currentFilterStartedAt) ? stored.currentFilterStartedAt : null,
    };
  } catch {
    return null;
  }
}

function isSocketTimeout(reason: unknown): boolean {
  const message = reason instanceof Error ? reason.message : String(reason || "");
  return /operation has timed out|timed out|timeout/i.test(message);
}

function sectionFromHash(): AppSection {
  const hash = window.location.hash.replace(/^#/, "").split("?")[0];
  if (hash === "reports") return "reports";
  if (hash === "settings") return "settings";
  return "configure";
}

function matrixOfficeKey(scenario: Scenario): string {
  return `${scenario.filters.states[0]?.trim().toLocaleLowerCase() || ""}\u0000${scenario.filters.rtos[0]?.trim().toLocaleLowerCase() || ""}`;
}

function findMatrixOfficeIndex(plan: MatrixPlan, target: Scenario): number {
  const key = matrixOfficeKey(target);
  return plan.scenarios.findIndex((scenario) => matrixOfficeKey(scenario) === key);
}

export default function App() {
  const [activeSection, setActiveSection] = useState<AppSection>(() => sectionFromHash());
  const view = activeSection;
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [runners, setRunners] = useState<Runner[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [captcha, setCaptcha] = useState<CaptchaChallenge | null>(null);
  const [creating, setCreating] = useState(false);
  const [submittingCaptcha, setSubmittingCaptcha] = useState(false);
  const [refreshingCaptcha, setRefreshingCaptcha] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [matrixPlan, setMatrixPlan] = useState<MatrixPlan | null>(readMatrixPlan);
  const scenarios = matrixPlan?.scenarios || EMPTY_SCENARIOS;
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [matrixProgress, setMatrixProgress] = useState("");
  const [initialBatchRecovery] = useState(readBatchRecovery);
  const [batchRunning, setBatchRunning] = useState(initialBatchRecovery?.status === "running");
  const [batchStatus, setBatchStatus] = useState<BatchStatus>(initialBatchRecovery?.status || "idle");
  const [failedAtIndex, setFailedAtIndex] = useState<number | null>(initialBatchRecovery?.failedAtIndex ?? null);
  const [reportsTrigger, setReportsTrigger] = useState(0);
  const [batchProgress, setBatchProgress] = useState(initialBatchRecovery?.progress || { done: 0, total: 0, current: "" });
  const [batchLog, setBatchLog] = useState<BatchLogEntry[]>(initialBatchRecovery?.log || []);
  const [batchStartedAt, setBatchStartedAt] = useState<string | null>(initialBatchRecovery?.startedAt || null);
  const [batchFinishedAt, setBatchFinishedAt] = useState<string | null>(initialBatchRecovery?.finishedAt || null);
  const [batchTimings, setBatchTimings] = useState<FilterTiming[]>(initialBatchRecovery?.timings || []);
  const [currentFilterStartedAt, setCurrentFilterStartedAt] = useState<number | null>(initialBatchRecovery?.currentFilterStartedAt ?? null);
  const [healthReportsRefreshToken, setHealthReportsRefreshToken] = useState(0);
  const [pendingManualCheck, setPendingManualCheck] = useState<PendingUiHealthCheck | null>(null);
  const [jobRestoreReady, setJobRestoreReady] = useState(false);

  const runnersRef = useRef<Runner[]>([]);
  useEffect(() => { runnersRef.current = runners; }, [runners]);
  const terminalResolverRef = useRef<((job: Job) => void) | null>(null);
  const latestJobRef = useRef<Job | null>(null);
  const batchStopRef = useRef(false);
  const batchRunningRef = useRef(initialBatchRecovery?.status === "running");
  const batchLoopStartedRef = useRef(false);
  const batchRecoveryRef = useRef<PersistedBatchRecovery | null>(initialBatchRecovery);
  const batchLogRef = useRef<BatchLogEntry[]>(initialBatchRecovery?.log || []);
  const failedAtIndexRef = useRef<number | null>(initialBatchRecovery?.failedAtIndex ?? null);
  const matrixLoadInFlightRef = useRef(false);
  const pendingManualCheckRef = useRef<PendingUiHealthCheck | null>(null);

  function writeBatchRecovery(next: PersistedBatchRecovery | null) {
    batchRecoveryRef.current = next;
    try {
      if (next) localStorage.setItem(BATCH_RECOVERY_STORAGE_KEY, JSON.stringify(next));
      else localStorage.removeItem(BATCH_RECOVERY_STORAGE_KEY);
    } catch {
      setNotice("Could not save batch progress in this browser. Keep this page open to let the batch continue.");
    }
  }

  function updateBatchRecovery(patch: Partial<PersistedBatchRecovery>) {
    const current = batchRecoveryRef.current;
    if (current) writeBatchRecovery({ ...current, ...patch });
  }

  function updateBatchProgress(next: { done: number; total: number; current: string }) {
    setBatchProgress(next);
    updateBatchRecovery({ progress: next });
  }

  useEffect(() => {
    const onHashChange = () => setActiveSection(sectionFromHash());
    window.addEventListener("hashchange", onHashChange);
    onHashChange();
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    document.title = view === "settings"
      ? "VAHAN · Settings"
      : view === "reports" ? "VAHAN · Exported Reports" : "VAHAN · Report Automation";
  }, [view]);

  const onHealthCheckRequested = useCallback((request: UiHealthCheckNowResponse) => {
    const pending = {
      requestId: request.requestId,
      requestedAt: request.requestedAt,
    };
    pendingManualCheckRef.current = pending;
    setPendingManualCheck(pending);
  }, []);

  const onManualCheckSettled = useCallback(() => {
    pendingManualCheckRef.current = null;
    setPendingManualCheck(null);
  }, []);

  async function prepareMatrix(): Promise<MatrixPlan | null> {
    if (batchRunningRef.current || matrixLoadInFlightRef.current) return null;
    matrixLoadInFlightRef.current = true;
    setMatrixLoading(true);
    setError("");
    setNotice("");
    setMatrixProgress("Connecting to VAHAN before this session…");
    const year = currentReportYear();
    try {
      const runnerId = await pickAvailableRunnerWithRetry();
      if (!runnerId) throw new Error("No online extension runner is available.");
      const requestPayload = async (request: Record<string, unknown>): Promise<unknown> => {
        let lastError = "VAHAN did not return options.";
        for (let attempt = 0; attempt < 3; attempt += 1) {
          try {
            const response = await uiSocket.timeout(30_000).emitWithAck("ui:runner-options", {
              runnerId, request,
            }) as Acknowledgement & { options?: unknown };
            if (response.ok && response.options) return response.options;
            lastError = response.error || lastError;
          } catch (reason) {
            lastError = reason instanceof Error ? reason.message : String(reason);
          }
          if (attempt < 2) await sleep(1000 * (attempt + 1));
        }
        throw new Error(lastError);
      };
      const requestOptions = async (request: Record<string, unknown>): Promise<string[]> => {
        const options = await requestPayload(request);
        if (!Array.isArray(options) || !options.every((item) => typeof item === "string")) {
          throw new Error("VAHAN returned an invalid options list.");
        }
        return options;
      };
      setMatrixProgress("Checking fixed filter options…");
      const available = await requestPayload({ type: "GET_ALL_OPTIONS" }) as Record<string, string[]>;
      const expected: Record<string, string[]> = {
        archivedFlags: ["ACTIVE_COMPLIANT", "ACTIVE_NON_COMPLIANT", "PERMANENT_ARCHIVE", "TEMPORARY_ARCHIVE"],
        period: ["CALENDAR YEAR"],
        categoryGroups: ["Two Wheeler"],
        subCategories: ["TWO WHEELER (Invalid Carriage)", "TWO WHEELER(NT)", "TWO WHEELER(T)"],
        fuels: ["ELECTRIC(BOV)", "PURE EV"],
        yAxis: ["Maker"],
      };
      for (const [field, values] of Object.entries(expected)) {
        const options = available[field] || [];
        const missing = values.filter((value) => !options.some((option) => option.trim().toLowerCase() === value.toLowerCase()));
        if (missing.length) throw new Error(`VAHAN is missing ${field}: ${missing.join(", ")}.`);
      }
      const xAxis = await requestOptions({ type: "GET_X_AXIS_OPTIONS", yAxis: "Maker" });
      if (!xAxis.some((option) => option.trim().toLowerCase() === "month wise")) {
        throw new Error("VAHAN is missing X-Axis Month Wise for Y-Axis Maker.");
      }
      setMatrixProgress("Loading State list from VAHAN…");
      const states = [...new Set((await requestOptions({ type: "GET_STATE_OPTIONS", delhiNcr: "ALL STATES" }))
        .map((name) => name.trim()).filter((name) => name && !/^(-+\s*select|all states)/i.test(name)))];
      if (!states.length) throw new Error("VAHAN returned no State options.");
      const rtosByState: Record<string, string[]> = {};
      for (const [index, state] of states.entries()) {
        setMatrixProgress(`Loading RTO ${index + 1}/${states.length}: ${state}`);
        const rtos = (await requestOptions({ type: "GET_RTO_OPTIONS", stateLabels: state }))
          .map((name) => name.trim()).filter((name) => name && !/^(-+\s*select|all rto)/i.test(name));
        if (!rtos.length) throw new Error(`VAHAN returned no RTO offices for ${state}. Matrix was not saved.`);
        if (new Set(rtos).size !== rtos.length) {
          throw new Error(`VAHAN returned duplicate RTO names for ${state}. Matrix was not saved because offices would be missed.`);
        }
        rtosByState[state] = rtos;
      }
      const plan = buildMatrix(states, rtosByState, year);
      localStorage.setItem(MATRIX_STORAGE_KEY, JSON.stringify(plan));
      setMatrixPlan(plan);
      return plan;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load the State–RTO matrix.");
      return null;
    } finally {
      matrixLoadInFlightRef.current = false;
      setMatrixLoading(false);
      setMatrixProgress("");
    }
  }

  async function refreshRunners() {
    try {
      setRunners(await api.runners());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load the runner list.");
    }
  }

  function resolveTerminal(finishedJob: Job) {
    latestJobRef.current = finishedJob;
    const resolve = terminalResolverRef.current;
    if (!resolve) return;
    resolve(finishedJob);
  }

  async function subscribeJob(jobId: string) {
    const acknowledgement = await uiSocket.timeout(UI_SOCKET_ACK_TIMEOUT_MS).emitWithAck(
      "ui:subscribe-job", { jobId },
    ) as Acknowledgement;
    if (!acknowledgement.ok) throw new Error(acknowledgement.error || "Could not subscribe to the job.");
    if (acknowledgement.job) {
      if (acknowledgement.job.source === "old") {
        localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
        setCaptcha(null);
        return;
      }
      latestJobRef.current = acknowledgement.job;
      setJob(acknowledgement.job);
      if (["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(acknowledgement.job.status)) {
        localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
        await refreshRunners();
        resolveTerminal(acknowledgement.job);
      }
    }
    if (acknowledgement.captcha) setCaptcha({ ...acknowledgement.captcha, invalid: false });
  }

  useEffect(() => {
    const ensureUiSocket = () => {
      if (!uiSocket.connected && !uiSocket.active) uiSocket.connect();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") ensureUiSocket();
    };
    const onConnect = () => {
      setConnection("connected");
      setJobRestoreReady(false);
      refreshRunners();
      const activeJobId = (batchRecoveryRef.current?.status === "running" ? batchRecoveryRef.current.activeJobId : null)
        || localStorage.getItem(ACTIVE_JOB_STORAGE_KEY);
      if (activeJobId) {
        localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, activeJobId);
        subscribeJob(activeJobId)
          .catch((reason) => {
            if (isSocketTimeout(reason)) {
              setNotice("The connection is slow. Job status will continue syncing with the extension.");
            } else {
              setError(reason instanceof Error ? reason.message : "Could not restore the job.");
            }
          })
          .finally(() => setJobRestoreReady(true));
      } else {
        setJobRestoreReady(true);
      }
    };
    const onDisconnect = (reason: string) => {
      setConnection("disconnected");
      setJobRestoreReady(false);
      if (reason === "io server disconnect") window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
    };
    const onConnectError = (reason: Error) => {
      setConnection("error");
      if (/rejected|unauthorized|authentication required|token expired/i.test(reason.message)) {
        window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
      }
    };
    const onRunnerChange = () => refreshRunners();
    const onJobStatus = async (updated: Job) => {
      latestJobRef.current = updated;
      setJob(updated);
      if (updated.status === "SUBMITTING" || updated.status === "WAITING_RESULT") {
        setCaptcha(null);
        setNotice("");
      }
      if (["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(updated.status)) {
        localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
        setCaptcha(null);
        if (updated.status === "COMPLETED") {
          setReportsTrigger((c) => c + 1);
        }
        // Đợi danh sách runner cập nhật xong TRƯỚC KHI resolve — nếu không, batch runner
        // (runScenarioQueue) sẽ đọc runnersRef.current lúc còn stale (runner vẫn hiện "đang
        // bận") và báo nhầm "không còn runner rảnh" ngay sau job đầu tiên.
        await refreshRunners();
        resolveTerminal(updated);
      }
    };
    const onCaptcha = (challenge: CaptchaChallenge) => setCaptcha({ ...challenge, invalid: false });
    const onCaptchaInvalid = (challenge: CaptchaChallenge) => setCaptcha({ ...challenge, invalid: true });
    const onCaptchaRefreshed = (challenge: CaptchaChallenge) => setCaptcha({ ...challenge, invalid: false, refreshed: true });
    const onUiHealthLogReceived = (payload: { trigger?: string; checkedAt?: string }) => {
      setHealthReportsRefreshToken((value) => value + 1);
      const pending = pendingManualCheckRef.current;
      if (!pending || payload.trigger !== "manual-web") return;
      const checkedAt = Date.parse(payload.checkedAt || "");
      const requestedAt = Date.parse(pending.requestedAt);
      if (Number.isFinite(checkedAt) && Number.isFinite(requestedAt) && checkedAt >= requestedAt) {
        onManualCheckSettled();
      }
    };

    uiSocket.on("connect", onConnect);
    uiSocket.on("disconnect", onDisconnect);
    uiSocket.on("connect_error", onConnectError);
    uiSocket.on("runner:online", onRunnerChange);
    uiSocket.on("runner:offline", onRunnerChange);
    uiSocket.on("job:status", onJobStatus);
    uiSocket.on("captcha:required", onCaptcha);
    uiSocket.on("captcha:invalid", onCaptchaInvalid);
    uiSocket.on("captcha:refreshed", onCaptchaRefreshed);
    uiSocket.on("ui-health:log-received", onUiHealthLogReceived);
    uiSocket.connect();
    window.addEventListener("online", ensureUiSocket);
    window.addEventListener("pageshow", ensureUiSocket);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      window.removeEventListener("online", ensureUiSocket);
      window.removeEventListener("pageshow", ensureUiSocket);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      uiSocket.off("connect", onConnect);
      uiSocket.off("disconnect", onDisconnect);
      uiSocket.off("connect_error", onConnectError);
      uiSocket.off("runner:online", onRunnerChange);
      uiSocket.off("runner:offline", onRunnerChange);
      uiSocket.off("job:status", onJobStatus);
      uiSocket.off("captcha:required", onCaptcha);
      uiSocket.off("captcha:invalid", onCaptchaInvalid);
      uiSocket.off("captcha:refreshed", onCaptchaRefreshed);
      uiSocket.off("ui-health:log-received", onUiHealthLogReceived);
      uiSocket.disconnect();
    };
  }, []);

  async function createJob(runnerId: string, filters: VahanFilters, scenarioName?: string, sessionId?: string) {
    setCreating(true);
    setError("");
    setNotice("");
    setCaptcha(null);
    try {
      const created = await api.createJob(runnerId, filters, scenarioName, sessionId);
      latestJobRef.current = created;
      setJob(created);
      localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, created.id);
      if (batchRecoveryRef.current?.status === "running") {
        updateBatchRecovery({ activeJobId: created.id });
      }
      if (sessionId && batchStopRef.current) {
        const cancelled = await api.cancelJob(created.id);
        latestJobRef.current = cancelled;
        setJob(cancelled);
        localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
        resolveTerminal(cancelled);
        return;
      }
      try {
        await subscribeJob(created.id);
        await refreshRunners();
      } catch {
        // Creation already succeeded. A subscription/refresh error must not
        // skip this case or start a second job while the runner is still busy.
        setNotice("Job created. Reconnecting to live updates; this case remains active.");
      }
      return created;
    } catch (reason) {
      if (isSocketTimeout(reason)) {
        const message = "The connection is slow. The job was created and the extension is still being monitored.";
        setNotice(message);
        throw new Error(message);
      }
      const message = reason instanceof Error ? reason.message : "Could not create the job.";
      setError(message);
      throw new Error(message);
    } finally {
      setCreating(false);
    }
  }

  async function submitCaptcha(text1: string) {
    if (!job || !captcha) return;
    setSubmittingCaptcha(true);
    setError("");
    setNotice("");
    try {
      const acknowledgement = await uiSocket.timeout(UI_SOCKET_ACK_TIMEOUT_MS).emitWithAck(
        "captcha:submitted",
        { jobId: job.id, captchaId: captcha.captchaId, text1 },
      ) as Acknowledgement;
      if (!acknowledgement.ok) throw new Error(acknowledgement.error || "Could not submit the CAPTCHA.");
      setCaptcha(null);
    } catch (reason) {
      if (isSocketTimeout(reason)) {
        // The server accepts this command before the extension performs the
        // slow DOM work. Keep this as a non-blocking notice for old servers or
        // a temporarily slow socket; a real job failure is shown by JobStatus.
        setNotice("CAPTCHA received. The extension is continuing to fill in the VAHAN filters.");
      } else {
        setError(reason instanceof Error ? reason.message : "Could not submit the CAPTCHA.");
      }
    } finally {
      setSubmittingCaptcha(false);
    }
  }

  async function refreshCaptcha() {
    if (!job || !captcha) return;
    setRefreshingCaptcha(true);
    setError("");
    setNotice("");
    try {
      const acknowledgement = await uiSocket.timeout(CAPTCHA_REFRESH_ACK_TIMEOUT_MS).emitWithAck(
        "captcha:refresh",
        { jobId: job.id, captchaId: captcha.captchaId },
      ) as Acknowledgement & { captcha?: CaptchaChallenge };
      if (!acknowledgement.ok) throw new Error(acknowledgement.error || "Could not load a new CAPTCHA.");
      if (acknowledgement.captcha) {
        setCaptcha({ ...acknowledgement.captcha, invalid: false, refreshed: true });
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load a new CAPTCHA.");
    } finally {
      setRefreshingCaptcha(false);
    }
  }

  function pickAvailableRunner(): string | null {
    const runner = runnersRef.current.find((candidate) => (candidate.source || "new") === "new"
      && candidate.status === "ONLINE" && !candidate.currentJobId);
    return runner ? runner.id : null;
  }

  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  // pickAvailableRunner() nên đã thấy đúng runner rảnh ngay (onJobStatus giờ await
  // refreshRunners() trước khi cho batch đi tiếp) — vòng retry này chỉ là lớp phòng hộ
  // cho race condition còn sót lại (vd. REST list chậm hơn dự kiến), không phải cơ chế
  // chính để đồng bộ trạng thái runner.
  async function pickAvailableRunnerWithRetry(attempts = 3, delayMs = 1000): Promise<string | null> {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const runnerId = pickAvailableRunner();
      if (runnerId) return runnerId;
      if (attempt < attempts - 1) {
        await sleep(delayMs);
        await refreshRunners();
      }
    }
    return null;
  }

  async function runOneScenarioJob(runnerId: string, filters: VahanFilters, scenarioName?: string, sessionId?: string): Promise<Job> {
    try {
      const created = await createJob(runnerId, filters, scenarioName, sessionId);
      const id = created?.id || latestJobRef.current?.id;
      if (!id) throw new Error("The created job has no identifier.");
      return await waitForExistingJob(id);
    } catch (reason) {
      terminalResolverRef.current = null;
      throw reason;
    }
  }

  async function waitForExistingJob(jobId: string): Promise<Job> {
    const isTerminal = (candidate: Job | null): candidate is Job =>
      Boolean(candidate && ["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(candidate.status));
    const known = latestJobRef.current;
    if (known?.id === jobId && isTerminal(known)) return known;

    // Socket.IO gives immediate completion; REST is a fallback for missed
    // terminal events while the browser or socket was disconnected.
    return new Promise((resolve, reject) => {
      let settled = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const finish = (completed: Job) => {
        if (settled || completed.id !== jobId) return;
        settled = true;
        clearTimeout(timer);
        if (terminalResolverRef.current === finish) terminalResolverRef.current = null;
        resolve(completed);
      };
      terminalResolverRef.current = finish;
      const poll = async () => {
        if (settled) return;
        try {
          const snapshot = await api.getJob(jobId);
          if (settled) return;
          latestJobRef.current = snapshot;
          setJob(snapshot);
          if (isTerminal(snapshot)) {
            localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
            setCaptcha(null);
            if (snapshot.status === "COMPLETED") setReportsTrigger((value) => value + 1);
            await refreshRunners().catch(() => {});
            finish(snapshot);
            return;
          }
          if (uiSocket.connected) await subscribeJob(jobId).catch(() => {});
        } catch (reason) {
          if (reason instanceof ApiError && reason.status === 404) {
            settled = true;
            if (terminalResolverRef.current === finish) terminalResolverRef.current = null;
            reject(new Error("The backend no longer has this job. It may have restarted; retry this filter."));
            return;
          }
          setNotice("Connection interrupted. Waiting for the current filter's confirmed result.");
        }
        if (!settled) timer = setTimeout(() => void poll(), 3_000);
      };
      const latest = latestJobRef.current;
      if (latest?.id === jobId && isTerminal(latest)) finish(latest);
      else timer = setTimeout(() => void poll(), known?.id === jobId ? 3_000 : 0);
    });
  }

  async function runScenarioQueue(
    queue: Scenario[],
    {
      startIndex = 0,
      clearLog = true,
      resumeState,
      selectedIndices,
      planOverride,
    }: { startIndex?: number; clearLog?: boolean; resumeState?: PersistedBatchRecovery; selectedIndices?: number[]; planOverride?: MatrixPlan } = {},
  ) {
    if ((!queue.length && !resumeState) || (batchRunningRef.current && !resumeState)) return;
    const sourcePlan = planOverride || matrixPlan;
    if (!sourcePlan) {
      setError("The State–RTO office list could not be loaded. Start a new session to refresh it.");
      return;
    }
    if (resumeState && resumeState.year !== currentReportYear()) {
      setError("The saved batch belongs to a previous calendar year. Start a new run for the current year.");
      if (resumeState) {
        batchRunningRef.current = false;
        setBatchRunning(false);
        setBatchStatus("error");
        writeBatchRecovery({ ...resumeState, status: "error" });
      }
      return;
    }
    const activePlan = updateMatrixYear(sourcePlan, currentReportYear());
    if (activePlan !== sourcePlan) {
      localStorage.setItem(MATRIX_STORAGE_KEY, JSON.stringify(activePlan));
      setMatrixPlan(activePlan);
      batchLogRef.current = [];
      setBatchLog([]);
      failedAtIndexRef.current = null;
      setFailedAtIndex(null);
    }
    const activeScenarios = activePlan.scenarios;
    batchLoopStartedRef.current = true;
    batchRunningRef.current = true;
    setBatchRunning(true);
    setBatchStatus("running");

    const queueIndices = resumeState?.queueIndices || selectedIndices || queue.map((_, index) => startIndex + index);
    const sessionId = resumeState?.sessionId || crypto.randomUUID();
    const startPosition = resumeState?.nextPosition || 0;
    const total = queueIndices.length;
    let done = resumeState ? Math.min(resumeState.progress.done, total) : 0;
    const startedAt = resumeState?.startedAt || new Date().toISOString();
    let timings = resumeState?.timings || [];
    setBatchTimings(timings);
    setCurrentFilterStartedAt(resumeState?.currentFilterStartedAt ?? null);
    setBatchStartedAt(startedAt);
    setBatchFinishedAt(null);
    let current = resumeState?.progress.current
      || activeScenarios[queueIndices[startPosition]]?.name
      || queue[0]?.name
      || "";

    if (clearLog) {
      batchLogRef.current = [];
      setBatchLog([]);
      failedAtIndexRef.current = null;
      setFailedAtIndex(null);
    }
    if (resumeState) {
      batchStopRef.current = resumeState.stopRequested;
      updateBatchRecovery({ status: "running", startedAt, finishedAt: null });
    } else {
      batchStopRef.current = false;
      const initialProgress = { done: 0, total, current };
      writeBatchRecovery({
        version: 1,
        status: "running",
        queueIndices,
        nextPosition: 0,
        currentIndex: queueIndices[0] ?? null,
        activeJobId: null,
        stopRequested: false,
        hadErrors: false,
        log: batchLogRef.current,
        failedAtIndex: failedAtIndexRef.current,
        progress: initialProgress,
        sessionId,
        year: activePlan.year,
        startedAt,
        finishedAt: null,
        timings: [],
        currentFilterStartedAt: null,
      });
      done = 0;
    }
    updateBatchProgress({ done, total, current });

    let outcome: BatchStatus = "completed";
    let hadErrors = resumeState?.hadErrors || false;

    let filterStartedAt = Date.now();
    function recordScenario(entry: BatchLogEntry) {
      entry.durationMs = Math.max(0, Date.now() - filterStartedAt);
      timings = [...timings.filter((sample) => sample.index !== entry.index), { index: entry.index, durationMs: entry.durationMs }];
      setBatchTimings(timings);
      const currentLog = batchLogRef.current;
      const existingIndex = currentLog.findIndex((item) => item.index === entry.index);
      const nextLog = existingIndex < 0
        ? [...currentLog, entry]
        : currentLog.map((item, index) => index === existingIndex ? entry : item);
      batchLogRef.current = nextLog;
      setBatchLog(nextLog);
      if (entry.status === "error") hadErrors = true;
      updateBatchRecovery({ log: nextLog, hadErrors, timings });
    }

    function recordFailedIndex(index: number | null) {
      failedAtIndexRef.current = index;
      setFailedAtIndex(index);
      updateBatchRecovery({ failedAtIndex: index });
    }

    for (let position = startPosition; position < queueIndices.length; position += 1) {
      if (currentReportYear() !== activePlan.year) {
        outcome = "error";
        setError("Calendar year changed during the batch. Reload the matrix to use the new year.");
        break;
      }
      const activeJobId = resumeState && position === startPosition ? resumeState.activeJobId : null;
      if (batchStopRef.current) {
        if (activeJobId) {
          try {
            const stoppedJob = await api.cancelJob(activeJobId);
            latestJobRef.current = stoppedJob;
            setJob(stoppedJob);
            resolveTerminal(stoppedJob);
          } catch {
            // The job may already have reached a terminal state before recovery.
          }
        }
        outcome = "stopped";
        break;
      }
      const scenarioIndex = queueIndices[position];
      const scenario = activeScenarios[scenarioIndex];
      if (!scenario) {
        outcome = "error";
        setError(`Could not find case ${scenarioIndex + 1} while restoring the batch.`);
        break;
      }
      current = scenario.name;
      filterStartedAt = resumeState && position === startPosition
        ? resumeState.currentFilterStartedAt ?? Date.now() : Date.now();
      setCurrentFilterStartedAt(filterStartedAt);
      updateBatchProgress({ done, total, current });
      updateBatchRecovery({
        status: "running",
        nextPosition: position,
        currentIndex: scenarioIndex,
        activeJobId,
        stopRequested: batchStopRef.current,
        currentFilterStartedAt: filterStartedAt,
      });

      try {
        let result: Job;
        if (activeJobId) {
          result = await waitForExistingJob(activeJobId);
        } else {
          const runnerId = await pickAvailableRunnerWithRetry();
          if (!runnerId) throw new Error("No online VAHAN extension runner is available.");
          if (batchStopRef.current) {
            outcome = "stopped";
            break;
          }
          result = await runOneScenarioJob(runnerId, scenario.filters, scenario.name, sessionId);
        }
        if (batchStopRef.current && result.status === "CANCELLED") {
          outcome = "stopped";
          break;
        }
        if (result.status === "NO_DATA" || (result.error || "").startsWith("NO_RECORD_FOUND")) {
          recordScenario({
            index: scenarioIndex,
            name: `${scenario.filters.states[0]} · ${scenario.filters.rtos[0]}`,
            state: scenario.filters.states[0],
            rto: scenario.filters.rtos[0],
            status: "empty",
            detail: "No record found. State and RTO saved in a text file.",
            jobId: result.id,
            noDataFileName: result.noDataFileName,
          });
        } else if (result.status === "COMPLETED") {
          recordScenario({
            index: scenarioIndex,
            name: scenario.name,
            status: "ok",
            detail: "Job " + result.id + " completed.",
            jobId: result.id,
            excelFileName: result.excelFileName,
          });
          if (failedAtIndexRef.current === scenarioIndex) recordFailedIndex(null);
        } else {
          hadErrors = true;
          recordScenario({
            index: scenarioIndex,
            name: scenario.name, status: "error",
            state: scenario.filters.states[0],
            rto: scenario.filters.rtos[0],
            jobId: result.id,
            detail: (result.error || ("Job ended with status " + result.status + ".")) + " This case was skipped; continuing with the next case.",
          });
          recordFailedIndex(scenarioIndex);
        }
      } catch (reason) {
        if (batchStopRef.current) {
          outcome = "stopped";
          break;
        }
        hadErrors = true;
        recordScenario({
          index: scenarioIndex,
          name: scenario.name, status: "error",
          state: scenario.filters.states[0],
          rto: scenario.filters.rtos[0],
          detail: (reason instanceof Error ? reason.message : "An unknown error occurred while creating the job.") + " This case was skipped; continuing with the next case.",
        });
        recordFailedIndex(scenarioIndex);
      }
      done = position + 1;
      setCurrentFilterStartedAt(null);
      updateBatchProgress({ done, total, current: scenario.name });
      updateBatchRecovery({
        nextPosition: position + 1,
        currentIndex: null,
        activeJobId: null,
        currentFilterStartedAt: null,
        hadErrors,
      });
      if (batchStopRef.current) {
        outcome = "stopped";
        break;
      }
    }

    const finalStatus = outcome === "completed" && hadErrors ? "completed_with_errors" : outcome;
    const finishedAt = new Date().toISOString();
    updateBatchProgress({ done, total, current });
    setBatchStatus(finalStatus);
    setBatchFinishedAt(finishedAt);
    setCurrentFilterStartedAt(null);
    updateBatchRecovery({
      status: finalStatus,
      currentIndex: null,
      activeJobId: null,
      stopRequested: false,
      hadErrors,
      finishedAt,
      currentFilterStartedAt: null,
    });
    batchRunningRef.current = false;
    setBatchRunning(false);
  }

  async function stopBatch() {
    batchStopRef.current = true;
    updateBatchRecovery({ stopRequested: true });
    const current = latestJobRef.current;
    const activeJobId = batchRecoveryRef.current?.activeJobId
      || (current && !["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(current.status) ? current.id : null);
    if (!activeJobId) return;
    try {
      const cancelled = await api.cancelJob(activeJobId);
      latestJobRef.current = cancelled;
      setJob(cancelled);
      localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
      setCaptcha(null);
      resolveTerminal(cancelled);
      await refreshRunners();
    } catch (reason) {
      const latest = await api.getJob(activeJobId).catch(() => null);
      if (latest && ["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(latest.status)) {
        resolveTerminal(latest);
      } else {
        setError(reason instanceof Error ? reason.message : "Could not stop the current job.");
      }
    }
  }

  async function runAllScenarios() {
    if (batchRunningRef.current) return;
    const freshPlan = await prepareMatrix();
    if (!freshPlan) return;
    await runScenarioQueue(freshPlan.scenarios, { planOverride: freshPlan });
  }

  async function runFromScenarioIndex(index: number) {
    const selectedScenario = scenarios[index];
    if (!Number.isInteger(index) || index < 0 || !selectedScenario) return;
    const freshPlan = await prepareMatrix();
    if (!freshPlan) return;
    const freshIndex = findMatrixOfficeIndex(freshPlan, selectedScenario);
    if (freshIndex < 0) {
      setError("The selected office is no longer available in VAHAN. Select an office from the refreshed list and try again.");
      return;
    }
    await runScenarioQueue(freshPlan.scenarios.slice(freshIndex), {
      startIndex: freshIndex, clearLog: true, planOverride: freshPlan,
    });
  }

  async function runSingleScenarioIndex(index: number) {
    const selectedScenario = scenarios[index];
    if (!Number.isInteger(index) || index < 0 || !selectedScenario) return;
    const freshPlan = await prepareMatrix();
    if (!freshPlan) return;
    const freshIndex = findMatrixOfficeIndex(freshPlan, selectedScenario);
    if (freshIndex < 0) {
      setError("The selected office is no longer available in VAHAN. Select an office from the refreshed list and try again.");
      return;
    }
    await runScenarioQueue([freshPlan.scenarios[freshIndex]], {
      startIndex: freshIndex, clearLog: true, planOverride: freshPlan,
    });
  }

  async function retryFailedScenario() {
    const failedOffices = batchLogRef.current.filter((entry) => entry.status === "error")
      .map((entry) => {
        const scenario = scenarios[entry.index];
        return {
          state: entry.state || scenario?.filters.states[0],
          rto: entry.rto || scenario?.filters.rtos[0],
        };
      })
      .filter((office): office is { state: string; rto: string } => Boolean(office.state && office.rto));
    if (!failedOffices.length) return;
    const freshPlan = await prepareMatrix();
    if (!freshPlan) return;
    const failedIndices = [...new Set(failedOffices.map((office) => freshPlan.scenarios.findIndex((scenario) =>
      scenario.filters.states[0].trim().toLocaleLowerCase() === office.state.trim().toLocaleLowerCase()
      && scenario.filters.rtos[0].trim().toLocaleLowerCase() === office.rto.trim().toLocaleLowerCase())))];
    if (failedIndices.some((index) => index < 0)) {
      setError("One or more failed offices are no longer available in VAHAN. Review Exported Reports before retrying.");
      return;
    }
    await runScenarioQueue(failedIndices.map((index) => freshPlan.scenarios[index]), {
      selectedIndices: failedIndices,
      startIndex: failedIndices[0],
      clearLog: true,
      planOverride: freshPlan,
    });
  }

  useEffect(() => {
    if (!jobRestoreReady || batchLoopStartedRef.current) return;
    const recovery = batchRecoveryRef.current;
    if (recovery?.status !== "running") return;
    if (!scenarios.length) {
      setError("Batch progress was restored, but the saved State–RTO matrix could not be found.");
      batchRunningRef.current = false;
      setBatchRunning(false);
      writeBatchRecovery({ ...recovery, status: "error", activeJobId: null });
      return;
    }

    const activeJobId = recovery.activeJobId || localStorage.getItem(ACTIVE_JOB_STORAGE_KEY);
    if (activeJobId) localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, activeJobId);
    void runScenarioQueue(scenarios, {
      clearLog: false,
      resumeState: { ...recovery, activeJobId },
    });
  }, [jobRestoreReady, scenarios]);

  async function cancelJob() {
    if (!job) return;
    try {
      setJob(await api.cancelJob(job.id));
      localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
      setCaptcha(null);
      await refreshRunners();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not cancel the job.");
    }
  }

  const busy = creating || batchRunning || Boolean(job && !["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(job.status));

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand-lockup" href="#configure" aria-label="VAHAN Report Automation">
          <span className="brand-symbol" aria-hidden="true">V</span>
          <span className="brand-copy"><strong>VAHAN</strong><small>REPORT AUTOMATION</small></span>
        </a>
        <nav className="main-nav" aria-label="Main navigation">
          <a className={activeSection === "configure" ? "active" : undefined} aria-current={activeSection === "configure" ? "page" : undefined} href="#configure">Create Report</a>
          <a className={activeSection === "reports" ? "active" : undefined} aria-current={activeSection === "reports" ? "page" : undefined} href="#reports">Exported Reports</a>
          <a className={activeSection === "settings" ? "active" : undefined} aria-current={activeSection === "settings" ? "page" : undefined} href="#settings">Settings</a>
        </nav>
        <div className="header-actions">
          <ConnectionBanner backend={connection} runners={runners.length} />
          <button className="logout-button" type="button" onClick={api.logout}>Log out</button>
        </div>
      </header>

      <div className="app-layout">
        <div className="app-main">
          {view === "settings" ? (
            <main className="page-content settings-page" id="settings">
              <div className="section-intro settings-intro">
                <h2>Settings</h2>
              </div>

              <HealthCheckSchedule
                pendingManualCheck={pendingManualCheck}
                onCheckRequested={onHealthCheckRequested}
              />
              <HealthCheckReports
                refreshToken={healthReportsRefreshToken}
                pendingManualCheck={pendingManualCheck}
                onManualCheckSettled={onManualCheckSettled}
              />
            </main>
          ) : view === "reports" ? (
            <main className="page-content exported-reports-page" id="reports">
              <div className="section-intro reports-intro">
                <h2>Exported Reports</h2>
              </div>
              <ExportedReportsList refreshTrigger={reportsTrigger} />
            </main>
          ) : (
              <main className="page-content report-page-content">
                <div className="section-intro report-intro" id="configure">
                  <div className="report-intro-copy">
                    <p className="report-eyebrow"><span aria-hidden="true" />REPORTING WORKSPACE</p>
                    <h2>Create Report</h2>
                    <p>Run the standard VAHAN Maker report across State and RTO offices.</p>
                  </div>
                  <div className="report-period-summary">
                    <span className="report-period-icon" aria-hidden="true">FY</span>
                    <span><small>REPORTING PERIOD</small><strong>Calendar year {currentReportYear()}</strong></span>
                  </div>
                </div>

                {error && <div className="global-error" role="alert">{error}<button onClick={() => setError("")}>×</button></div>}
                {notice && <div className="global-notice" role="status">{notice}<button onClick={() => setNotice("")}>×</button></div>}

                <div className="workspace">
                  <div className="left-column">
                    <MatrixRunner
                      plan={matrixPlan}
                      loading={matrixLoading}
                      loadingMessage={matrixProgress}
                      scenarios={scenarios}
                      onRunAll={runAllScenarios}
                      onRunFrom={runFromScenarioIndex}
                      onRunOne={runSingleScenarioIndex}
                      onRetryFailed={retryFailedScenario}
                      onStop={stopBatch}
                      running={batchRunning}
                      progress={batchProgress}
                      batchStatus={batchStatus}
                      startedAt={batchStartedAt}
                      timings={batchTimings}
                      currentFilterStartedAt={currentFilterStartedAt}
                      finishedAt={batchFinishedAt}
                      log={batchLog}
                      failedAtIndex={failedAtIndex}
                      disabled={busy}
                    />
                  </div>
                  <div className="right-column">
                    {job && (
                      <div className="job-status-area" id="activity">
                        <JobStatus job={job} onCancel={cancelJob} />
                      </div>
                    )}
                    <CaptchaPanel
                      challenge={captcha}
                      submitting={submittingCaptcha}
                      refreshing={refreshingCaptcha}
                      onSubmit={submitCaptcha}
                      onRefresh={refreshCaptcha}
                    />
                    {!job && <section className="empty-state" data-running={batchRunning}>
                      <span className="empty-state-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none"><path d="M4.5 18.5V12m5 6.5V6m5 12.5v-9m5 9V9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
                      </span>
                      <span className="empty-state-kicker">SESSION ACTIVITY</span>
                      <h2>{batchRunning ? "Connecting to VAHAN" : "Ready to run"}</h2>
                      <p>{batchRunning
                        ? "The next report is being prepared. Activity and CAPTCHA requests will appear here."
                        : "Report progress and CAPTCHA requests will appear here after you start a session."}</p>
                      <span className="empty-state-status"><i />{batchRunning ? "Session in progress" : "Waiting for a session"}</span>
                    </section>}
                  </div>
                </div>

              </main>
          )}
        </div>
      </div>
    </div>
  );
}
