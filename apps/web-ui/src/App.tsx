import { persistentState, flushPersistentState } from './services/persistent-state';
import { useCallback, useEffect, useRef, useState } from "react";

import { CaptchaInbox, type CaptchaInboxItem } from './components/CaptchaInbox';
import { UserManagement, StateSyncStatus } from './components/DataManagement';
import { ConnectionBanner } from "./components/ConnectionBanner";
import { AnnualReports } from './components/AnnualReports';
import { HealthCheckReports } from "./components/HealthCheckReports";
import { HealthCheckSchedule } from "./components/HealthCheckSchedule";
import { JobStatus } from "./components/JobStatus";
import { CopyRunErrors } from './components/CopyRunErrors';
import { jobRunOutcome, readRunErrors, recordRunOutcome, RUN_ERROR_STORAGE_KEY, type RunOutcome } from './run-error-log';
import { MatrixRunner } from "./components/MatrixRunner";
import { WorkerDashboard } from "./components/WorkerDashboard";
import { RunControls } from './components/RunControls';
import {FilterProfiles} from './components/FilterProfiles';
import {FILTER_PROFILE_STORAGE_KEY, previewFilterProfile, type FilterProfile} from './filter-profiles';
import { readRunSettings, RUN_SETTINGS_STORAGE_KEY, type RunSettings } from './run-settings';
import { buildMatrix, isReportYear, fixedFilters, MATRIX_STORAGE_KEY, readMatrixPlan, updateMatrixYear, type MatrixPlan } from "./matrix-plan";
import type {
  Acknowledgement,
  CaptchaChallenge,
  ConnectionState,
  Job,
  MakerUpdateRun,
  MakerUpdateTask,
  PendingUiHealthCheck,
  Runner,
  ReportSource,
  Scenario,
  UiHealthCheckNowResponse,
  VahanFilters,
} from "./contracts";
import { AUTH_REQUIRED_EVENT, ApiError, api, type BatchQueueTask } from "./services/api-client";
import { uiSocket } from "./services/socket-client";
import { requestRunnerOptions } from './services/runner-options';
import type { FilterTiming } from "./batch-timing";
import { TARGET_WORKER_COUNT, compareRunnerIds } from "./worker-settings";
import { loadReportCoverage, uncoveredScenarios, type CoverageContext } from './report-coverage';

const ACTIVE_JOB_STORAGE_KEY = "vahanActiveJobId";
const BATCH_RECOVERY_STORAGE_KEY = "vahanStateRtoBatchRecoveryV1";
const UI_SOCKET_ACK_TIMEOUT_MS = 15_000;
const CAPTCHA_REFRESH_ACK_TIMEOUT_MS = 25_000;
const AUTO_RETRY_CHECKPOINT_SIZE = 10;
const MAX_AUTO_RETRY_ATTEMPTS = 1;
const JOB_SNAPSHOT_LIMIT = Math.max(32, TARGET_WORKER_COUNT * 3);
const EMPTY_SCENARIOS: Scenario[] = [];
type AppSection = "configure" | "reports" | "settings" | "filters";
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
  autoRetryCount?: number;
  completedAt?: string;
  savedAt?: string;
  rowCount?: number;
}

interface PersistedBatchRecovery {
  version: 1 | 2 | 3;
  status: BatchStatus;
  queueIndices: number[];
  queueOfficeKeys?: string[];
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
  lastRetryCheckpoint?: number;
  retryQueueIndices?: number[];
  retryIndex?: number | null;
  currentFilterStartedAt?: number | null;
  activeElapsedMs?: number;
  activeSegmentStartedAt?: number | null;
  lanes?: ParallelLaneRecovery[];
}

interface ParallelLaneRecovery {
  runnerId: string;
  indices: number[];
  nextPosition: number;
  currentIndex: number | null;
  activeJobId: string | null;
  lastJobId: string | null;
  retryQueueIndices: number[];
  retryIndex: number | null;
  lastRetryCheckpoint: number;
  currentFilterStartedAt: number | null;
}

function splitParallelLanes(indices: number[], runnerIds: string[]): ParallelLaneRecovery[] {
  if (!runnerIds.length || new Set(runnerIds).size !== runnerIds.length) {
    throw new Error('Every worker needs a distinct runner ID.');
  }
  const base = Math.floor(indices.length / runnerIds.length);
  const extra = indices.length % runnerIds.length;
  let offset = 0;
  return runnerIds.map((runnerId, lane) => {
    const size = base + (lane < extra ? 1 : 0);
    const part = indices.slice(offset, offset + size);
    offset += size;
    return {
      runnerId, indices: part, nextPosition: 0,
      currentIndex: null, activeJobId: null, lastJobId: null,
      retryQueueIndices: [], retryIndex: null, lastRetryCheckpoint: 0,
      currentFilterStartedAt: null,
    };
  });
}

function validParallelLanes(lanes: unknown, queueIndices: number[]): lanes is ParallelLaneRecovery[] {
  if (!Array.isArray(lanes) || (lanes.length !== 2 && lanes.length !== TARGET_WORKER_COUNT)
    || new Set(lanes.map((lane) => lane?.runnerId)).size !== lanes.length) return false;
  if (!lanes.every((lane) => lane && typeof lane.runnerId === 'string' && lane.runnerId.length > 0
    && Array.isArray(lane.indices) && lane.indices.every((index: unknown) => Number.isInteger(index) && (index as number) >= 0)
    && Number.isInteger(lane.nextPosition) && lane.nextPosition >= 0 && lane.nextPosition <= lane.indices.length
    && (lane.currentIndex === null || Number.isInteger(lane.currentIndex))
    && (lane.activeJobId === null || typeof lane.activeJobId === 'string')
    && Array.isArray(lane.retryQueueIndices) && lane.retryQueueIndices.every((index: unknown) => lane.indices.includes(index))
    && (lane.retryIndex === null || lane.indices.includes(lane.retryIndex))
    && Number.isInteger(lane.lastRetryCheckpoint) && lane.lastRetryCheckpoint >= 0
    && lane.lastRetryCheckpoint <= lane.nextPosition)) return false;
  return lanes.flatMap((lane) => lane.indices).join(',') === queueIndices.join(',');
}

function validSharedLanes(lanes: unknown, queueIndices: number[]): lanes is ParallelLaneRecovery[] {
  if (!Array.isArray(lanes) || lanes.length < 1 || lanes.length > TARGET_WORKER_COUNT
    || new Set(lanes.map((lane) => lane?.runnerId)).size !== lanes.length) return false;
  const allowed = new Set(queueIndices);
  const claimed = lanes.flatMap((lane) => lane?.indices || []);
  return new Set(claimed).size === claimed.length && claimed.every((index) => allowed.has(index))
    && lanes.every((lane) => typeof lane.runnerId === 'string' && lane.runnerId.length > 0
      && Array.isArray(lane.indices) && Number.isInteger(lane.nextPosition)
      && lane.nextPosition >= 0 && lane.nextPosition <= lane.indices.length
      && (lane.currentIndex === null || allowed.has(lane.currentIndex))
      && (lane.activeJobId === null || typeof lane.activeJobId === 'string')
      && Array.isArray(lane.retryQueueIndices) && lane.retryQueueIndices.every((index: number) => allowed.has(index))
      && (lane.retryIndex === null || allowed.has(lane.retryIndex)));
}

function readBatchRecovery(): PersistedBatchRecovery | null {
  try {
    const raw = persistentState.getItem(BATCH_RECOVERY_STORAGE_KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as PersistedBatchRecovery;
    if (stored.source === "old") {
      persistentState.removeItem(BATCH_RECOVERY_STORAGE_KEY);
      persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
      persistentState.removeItem("vahanHundredSessionsV1");
      return null;
    }
    const validStatuses: BatchStatus[] = ["idle", "running", "completed", "completed_with_errors", "stopped", "error"];
    if (
      (stored.version !== 1 && stored.version !== 2 && stored.version !== 3)
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
      || (stored.version === 2 && !validParallelLanes(stored.lanes, stored.queueIndices))
      || (stored.version === 3 && !validSharedLanes(stored.lanes, stored.queueIndices))
    ) return null;
    const timings = Array.isArray(stored.timings) ? stored.timings.filter((sample) =>
      sample && Number.isInteger(sample.index) && Number.isFinite(sample.durationMs) && sample.durationMs >= 0) : [];
    return {
      ...stored,
      status: stored.version === 3 && stored.stopRequested && stored.status === 'running'
        ? 'stopped' : stored.status,
      timings,
      lastRetryCheckpoint: Number.isInteger(stored.lastRetryCheckpoint) && stored.lastRetryCheckpoint! >= 0
        ? stored.lastRetryCheckpoint : 0,
      retryQueueIndices: Array.isArray(stored.retryQueueIndices)
        ? stored.retryQueueIndices.filter((index) => Number.isInteger(index) && index >= 0) : [],
      retryIndex: Number.isInteger(stored.retryIndex) ? stored.retryIndex! : null,
      currentFilterStartedAt: Number.isFinite(stored.currentFilterStartedAt) ? stored.currentFilterStartedAt : null,
      activeElapsedMs: Number.isFinite(stored.activeElapsedMs)
        ? Math.max(0, stored.activeElapsedMs!)
        : timings.reduce((sum, sample) => sum + sample.durationMs, 0),
      activeSegmentStartedAt: Number.isFinite(stored.activeSegmentStartedAt)
        ? stored.activeSegmentStartedAt!
        : stored.status === "running" ? Date.now() : null,
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
  if (hash === "filters") return "filters";
  return "configure";
}

function matrixOfficeKey(scenario: Scenario): string {
  const office = `${scenario.filters.states[0]?.trim().toLocaleLowerCase() || ""}\u0000${scenario.filters.rtos[0]?.trim().toLocaleLowerCase() || ""}`;
  return scenario.caseKey ? `${office}\u0000${scenario.caseKey}` : office;
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
  const [selectedCaptchaJobId, setSelectedCaptchaJobId] = useState<string | null>(null);
  const [jobSnapshots, setJobSnapshots] = useState<Record<string, Job>>({});
  const [parallelCaptchas, setParallelCaptchas] = useState<Record<string, CaptchaChallenge>>({});
  const [creating, setCreating] = useState(false);
  const [submittingCaptcha, setSubmittingCaptcha] = useState(false);
  const [refreshingCaptcha, setRefreshingCaptcha] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [matrixPlan, setMatrixPlan] = useState<MatrixPlan | null>(readMatrixPlan);
  const scenarios = matrixPlan?.scenarios || EMPTY_SCENARIOS;
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [matrixProgress, setMatrixProgress] = useState("");
  const [filterProfiles,setFilterProfiles]=useState<FilterProfile[]>([]);
  const [selectedProfileId,setSelectedProfileId]=useState<string>(()=>{
    const stored=persistentState.getItem(FILTER_PROFILE_STORAGE_KEY)||'';
    return /^[0-9a-f-]{36}$/i.test(stored)?stored:'';
  });
  const [makerUpdate, setMakerUpdate] = useState<MakerUpdateRun | null>(null);
  const [makerUpdateRunning, setMakerUpdateRunning] = useState(false);
  const [makerUpdateProgress, setMakerUpdateProgress] = useState("");
  const [initialBatchRecovery] = useState(readBatchRecovery);
  const [runSettings, setRunSettings] = useState<RunSettings>(() => {
    const saved = readRunSettings(matrixPlan?.year, initialBatchRecovery?.lanes?.length || TARGET_WORKER_COUNT);
    return initialBatchRecovery?.status === 'running'
      ? {year: initialBatchRecovery.year, workerCount: initialBatchRecovery.lanes?.length || 1} : saved;
  });
  const selectedWorkerCount = runSettings.workerCount;
  const [poolChanging, setPoolChanging] = useState(false);
  const [poolRunningCount, setPoolRunningCount] = useState<number | null>(null);
  const [batchRunning, setBatchRunning] = useState(initialBatchRecovery?.status === "running");
  const [batchStatus, setBatchStatus] = useState<BatchStatus>(initialBatchRecovery?.status || "idle");
  const selectedYear = ((batchRunning||batchStatus==='stopped')&&matrixPlan?matrixPlan.year:filterProfiles.find(profile=>profile.id===selectedProfileId)?.definition.report?.year) ?? runSettings.year;
  const [failedAtIndex, setFailedAtIndex] = useState<number | null>(initialBatchRecovery?.failedAtIndex ?? null);
  const [reportsTrigger, setReportsTrigger] = useState(0);
  const [batchProgress, setBatchProgress] = useState(initialBatchRecovery?.progress || { done: 0, total: 0, current: "" });
  const [batchLog, setBatchLog] = useState<BatchLogEntry[]>(initialBatchRecovery?.log || []);
  const [runErrors, setRunErrors] = useState(() => {
    let entries = readRunErrors(persistentState.getItem(RUN_ERROR_STORAGE_KEY));
    for (const entry of initialBatchRecovery?.log || []) {
      if (entry.status !== 'error' || /Stopped during this case/.test(entry.detail)) continue;
      const filters = matrixPlan?.scenarios[entry.index]?.filters;
      entries = recordRunOutcome(entries, {id: entry.jobId ? `job:${entry.jobId}` : `restored:${initialBatchRecovery!.sessionId}:${entry.index}`,
        jobId: entry.jobId, sessionId: initialBatchRecovery!.sessionId, name: entry.name,
        filters: filters || {states: entry.state ? [entry.state] : [], rtos: entry.rto ? [entry.rto] : []},
        status: 'failed', detail: entry.detail, occurredAt: entry.completedAt || null, attempt: entry.autoRetryCount});
    }
    return entries;
  });
  const [batchStartedAt, setBatchStartedAt] = useState<string | null>(initialBatchRecovery?.startedAt || null);
  const [batchFinishedAt, setBatchFinishedAt] = useState<string | null>(initialBatchRecovery?.finishedAt || null);
  const [batchTimings, setBatchTimings] = useState<FilterTiming[]>(initialBatchRecovery?.timings || []);
  const [currentFilterStartedAt, setCurrentFilterStartedAt] = useState<number | null>(initialBatchRecovery?.currentFilterStartedAt ?? null);
  const [batchActiveElapsedMs, setBatchActiveElapsedMs] = useState(initialBatchRecovery?.activeElapsedMs || 0);
  const [batchActiveSegmentStartedAt, setBatchActiveSegmentStartedAt] = useState<number | null>(
    initialBatchRecovery?.activeSegmentStartedAt ?? null,
  );
  const [healthReportsRefreshToken, setHealthReportsRefreshToken] = useState(0);
  const [pendingManualCheck, setPendingManualCheck] = useState<PendingUiHealthCheck | null>(null);
  const [jobRestoreReady, setJobRestoreReady] = useState(false);

  const runnersRef = useRef<Runner[]>([]);
  useEffect(() => { runnersRef.current = runners; }, [runners]);
  const terminalResolverRef = useRef<Map<string, (job: Job) => void>>(new Map());
  const jobSnapshotsRef = useRef<Map<string, Job>>(new Map());
  const latestJobRef = useRef<Job | null>(null);
  const batchStopRef = useRef(false);
  const batchRunningRef = useRef(initialBatchRecovery?.status === "running");
  const batchLoopStartedRef = useRef(false);
  const batchRecoveryRef = useRef<PersistedBatchRecovery | null>(initialBatchRecovery);
  const sharedQueuePersistedAtRef = useRef(0);
  const sharedQueuePersistedSessionRef = useRef<string | null>(null);
  const runnerRefreshRef = useRef<Promise<void> | null>(null);
  const batchLogRef = useRef<BatchLogEntry[]>(initialBatchRecovery?.log || []);
  const failedAtIndexRef = useRef<number | null>(initialBatchRecovery?.failedAtIndex ?? null);
  const matrixLoadInFlightRef = useRef(false);
  const makerUpdateStopRef = useRef(false);
  const makerUpdateRunningRef = useRef(false);
  const makerUpdateJobRef = useRef<string | null>(null);
  const pendingManualCheckRef = useRef<PendingUiHealthCheck | null>(null);
  const runErrorsRef = useRef(runErrors);

  function rememberJob(snapshot: Job) {
    const stored = jobSnapshotsRef.current;
    stored.delete(snapshot.id);
    stored.set(snapshot.id, snapshot);
    while (stored.size > JOB_SNAPSHOT_LIMIT) stored.delete(stored.keys().next().value!);
    setJobSnapshots((current) => {
      const next = {...current};
      delete next[snapshot.id];
      next[snapshot.id] = snapshot;
      const ids = Object.keys(next);
      for (const id of ids.slice(0, Math.max(0, ids.length - JOB_SNAPSHOT_LIMIT))) delete next[id];
      return next;
    });
  }

  function logRunOutcome(outcome: RunOutcome) {
    const next = recordRunOutcome(runErrorsRef.current, outcome);
    if (next === runErrorsRef.current) return;
    runErrorsRef.current = next;
    setRunErrors(next);
    persistentState.setItem(RUN_ERROR_STORAGE_KEY, JSON.stringify(next));
  }

  useEffect(() => {
    persistentState.setItem(RUN_ERROR_STORAGE_KEY, JSON.stringify(runErrorsRef.current));
    let active = true;
    const restoreErrorTimes = async () => {
      for (const entry of runErrorsRef.current.filter(item => !item.occurredAt && item.jobId)) {
        if (!active) break;
        try {
          const previousJob = await api.getJob(entry.jobId!);
          const outcome = jobRunOutcome(previousJob);
          if (active && outcome) logRunOutcome(outcome);
        } catch { /* Old jobs can be unavailable; keep their saved error message. */ }
      }
    };
    void restoreErrorTimes();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!job) return;
    const outcome = jobRunOutcome(job);
    if (outcome) logRunOutcome(outcome);
  }, [job]);

  useEffect(() => {
    if (!error || batchRunningRef.current) return;
    logRunOutcome({id: `control:${crypto.randomUUID()}`, sessionId: 'run-controls', name: 'Run controls',
      status: 'failed', detail: error, occurredAt: new Date().toISOString()});
  }, [error]);

  function writeBatchRecovery(next: PersistedBatchRecovery | null) {
    const previous = batchRecoveryRef.current;
    const changed = previous?.status !== next?.status || previous?.year !== next?.year
      || previous?.lanes?.length !== next?.lanes?.length;
    batchRecoveryRef.current = next;
    // Queue tasks already live durably in PostgreSQL. Limit large dashboard
    // checkpoint writes while workers are finishing cases in parallel.
    if (!changed && next?.version === 3 && next.status === 'running' && !next.stopRequested
      && sharedQueuePersistedSessionRef.current === next.sessionId && sharedQueuePersistedAtRef.current
      && Date.now() - sharedQueuePersistedAtRef.current < 10_000) return;
    try {
      if (next) persistentState.setItem(BATCH_RECOVERY_STORAGE_KEY, JSON.stringify(next));
      else persistentState.removeItem(BATCH_RECOVERY_STORAGE_KEY);
      if (next?.version === 3) {
        sharedQueuePersistedAtRef.current = Date.now();
        sharedQueuePersistedSessionRef.current = next.sessionId;
      }
    } catch {
      setNotice("Could not save batch progress in this browser. Keep this page open to let the batch continue.");
    }
  }

  function updateBatchRecovery(patch: Partial<PersistedBatchRecovery>) {
    const current = batchRecoveryRef.current;
    if (current) writeBatchRecovery({ ...current, ...patch });
  }

  async function ensureDockerWorkers(count: number) {
    setPoolChanging(true);
    try {
      const pool = await api.setWorkerPool(count);
      setPoolRunningCount(pool.enabled ? pool.runningCount : null);
      await refreshRunners();
      return pool;
    } finally {setPoolChanging(false);}
  }

  async function configureRun(patch: Partial<RunSettings>) {
    if (busy || matrixLoading || poolChanging) return;
    const next = {...runSettings, ...patch};
    if (!isReportYear(next.year) || !Number.isInteger(next.workerCount)
      || next.workerCount < 1 || next.workerCount > TARGET_WORKER_COUNT) return;
    if (patch.workerCount !== undefined) {
      try {await ensureDockerWorkers(next.workerCount);}
      catch (reason) {setError(reason instanceof Error ? reason.message : 'Could not update Docker workers.'); return;}
    }
    setRunSettings(next);
    persistentState.setItem(RUN_SETTINGS_STORAGE_KEY, JSON.stringify(next));
    if (matrixPlan && matrixPlan.year !== next.year) {
      const plan = updateMatrixYear(matrixPlan, next.year);
      setMatrixPlan(plan);
      persistentState.setItem(MATRIX_STORAGE_KEY, JSON.stringify(plan));
    }
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
    if (!jobRestoreReady) return;
    let current = true;
    api.makerUpdates(selectedYear).then((runs) => {
      if (current && runs.length) api.makerUpdate(runs[0].id).then((run) => {
        if (current) setMakerUpdate(run);
      }).catch(() => {});
    }).catch(() => {});
    return () => { current = false; };
  }, [jobRestoreReady, selectedYear]);

  useEffect(() => {
    if (!jobRestoreReady) return;
    let active = true;
    const refresh = () => api.workerPool().then(pool => {
      if (active) setPoolRunningCount(pool.enabled ? pool.runningCount : null);
    }).catch(() => {});
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10_000);
    return () => {active = false; window.clearInterval(timer);};
  }, [jobRestoreReady]);

  useEffect(() => {
    if (!batchRunningRef.current && !matrixLoading && matrixPlan && matrixPlan.year !== selectedYear) {
      const plan = updateMatrixYear(matrixPlan, selectedYear);
      setMatrixPlan(plan);
      persistentState.setItem(MATRIX_STORAGE_KEY, JSON.stringify(plan));
    }
  }, [matrixPlan, selectedYear, batchRunning, matrixLoading]);

  useEffect(() => {
    document.title = view === "settings"
      ? "VAHAN · Settings"
      : view === 'filters' ? 'VAHAN · Filters' : view === "reports" ? "VAHAN · Exported Reports" : "VAHAN · Report Automation";
  }, [view]);

  async function refreshFilterProfiles(){
    const profiles=await api.filterProfiles();
    if(!Array.isArray(profiles))throw new Error('The filter profile list was invalid. Retry loading profiles.');
    setFilterProfiles(profiles);
  }
  useEffect(()=>{if(jobRestoreReady)void refreshFilterProfiles().catch(reason=>setError(reason.message));},[jobRestoreReady]);
  function selectFilterProfile(id:string){
    setSelectedProfileId(id);persistentState.setItem(FILTER_PROFILE_STORAGE_KEY,JSON.stringify(id));
  }

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
    const year = filterProfiles.find(profile=>profile.id===selectedProfileId)?.definition.report?.year ?? selectedYear;
    try {
      if(!selectedProfileId)throw new Error('Choose a saved filter profile. Create and save one on the Filters page first.');
      const profile=filterProfiles.find(item=>item.id===selectedProfileId);
      if(!profile)throw new Error('The selected filter profile is unavailable. Reload the saved profiles.');
      if(!profile.definition.report)throw new Error('Open this profile on the Filters page, choose its reporting year and save it before running.');
      setMatrixProgress(`Starting ${selectedWorkerCount} Docker workers…`);
      await ensureDockerWorkers(selectedWorkerCount);
      const runnerId = await pickAvailableRunnerWithRetry();
      if (!runnerId) throw new Error("No online browser runner is available.");
      if(selectedProfileId){
        const plan=await previewFilterProfile(selectedProfileId,runnerId,year,setMatrixProgress);
        persistentState.setItem(MATRIX_STORAGE_KEY,JSON.stringify(plan));setMatrixPlan(plan);return plan;
      }
      const requestPayload = (request: Record<string, unknown>, message: string) =>
        requestRunnerOptions(uiSocket, runnerId, request, message, setMatrixProgress);
      const requestOptions = async (request: Record<string, unknown>, message: string): Promise<string[]> => {
        const options = await requestPayload(request, message);
        if (!Array.isArray(options) || !options.every((item) => typeof item === "string")) {
          throw new Error("VAHAN returned an invalid options list.");
        }
        return options;
      };
      const available = await requestPayload({ type: "GET_ALL_OPTIONS" }, "Checking fixed filter options…") as Record<string, string[]>;
      if (!available || typeof available !== 'object' || Array.isArray(available)
          || !Object.values(available).every(options => Array.isArray(options) && options.every(option => typeof option === 'string'))) {
        throw new Error('VAHAN returned invalid fixed filter options. Please retry.');
      }
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
      const xAxis = await requestOptions({ type: "GET_X_AXIS_OPTIONS", yAxis: "Maker" }, "Checking Maker / Month Wise options…");
      if (!xAxis.some((option) => option.trim().toLowerCase() === "month wise")) {
        throw new Error("VAHAN is missing X-Axis Month Wise for Y-Axis Maker.");
      }
      const states = [...new Set((await requestOptions({ type: "GET_STATE_OPTIONS", delhiNcr: "ALL STATES" }, "Loading State list from VAHAN…"))
        .map((name) => name.trim()).filter((name) => name && !/^(-+\s*select|all states)/i.test(name)))];
      if (!states.length) throw new Error("VAHAN returned no State options.");
      const rtosByState: Record<string, string[]> = {};
      for (const [index, state] of states.entries()) {
        const rtos = (await requestOptions({ type: "GET_RTO_OPTIONS", stateLabels: state }, `Loading RTO ${index + 1}/${states.length}: ${state}`))
          .map((name) => name.trim()).filter((name) => name && !/^(-+\s*select|all rto)/i.test(name));
        if (!rtos.length) throw new Error(`VAHAN returned no RTO offices for ${state}. Matrix was not saved.`);
        if (new Set(rtos).size !== rtos.length) {
          throw new Error(`VAHAN returned duplicate RTO names for ${state}. Matrix was not saved because offices would be missed.`);
        }
        rtosByState[state] = rtos;
      }
      const plan = buildMatrix(states, rtosByState, year);
      persistentState.setItem(MATRIX_STORAGE_KEY, JSON.stringify(plan));
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
    if (runnerRefreshRef.current) return runnerRefreshRef.current;
    const refresh = (async () => {
      try {
        const available = await api.runners();
        runnersRef.current = available;
        setRunners(available);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not load the runner list.");
      }
    })();
    runnerRefreshRef.current = refresh;
    try { await refresh; }
    finally { runnerRefreshRef.current = null; }
  }

  function resolveTerminal(finishedJob: Job) {
    latestJobRef.current = finishedJob;
    rememberJob(finishedJob);
    const resolve = terminalResolverRef.current.get(finishedJob.id);
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
        persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
        setCaptcha(null);
        return;
      }
      latestJobRef.current = acknowledgement.job;
      rememberJob(acknowledgement.job);
      setJob(acknowledgement.job);
      if (["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(acknowledgement.job.status)) {
        if (persistentState.getItem(ACTIVE_JOB_STORAGE_KEY) === acknowledgement.job.id) persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
        setParallelCaptchas((current) => { const next = {...current}; delete next[acknowledgement.job!.id]; return next; });
        if (batchRecoveryRef.current?.version === 3 && batchRunningRef.current) void refreshRunners();
        else await refreshRunners();
        resolveTerminal(acknowledgement.job);
      }
    }
    if (acknowledgement.captcha) {
      const challenge = { ...acknowledgement.captcha, invalid: false };
      setCaptcha(challenge);
      setParallelCaptchas((current) => ({...current, [challenge.jobId]: challenge}));
    }
    return acknowledgement.job;
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
      const parallelIds = batchRecoveryRef.current?.status === 'running' &&
        (batchRecoveryRef.current.version === 2 || batchRecoveryRef.current.version === 3)
        ? batchRecoveryRef.current.lanes?.map((lane) => lane.activeJobId).filter((id): id is string => Boolean(id)) || [] : [];
      if (parallelIds.length) {
        void Promise.allSettled(parallelIds.map((id) => subscribeJob(id))).finally(() => setJobRestoreReady(true));
        return;
      }
      const activeJobId = (batchRecoveryRef.current?.status === "running" ? batchRecoveryRef.current.activeJobId : null)
        || persistentState.getItem(ACTIVE_JOB_STORAGE_KEY);
      if (activeJobId) {
        persistentState.setItem(ACTIVE_JOB_STORAGE_KEY, activeJobId);
        subscribeJob(activeJobId)
          .catch((reason) => {
            if (isSocketTimeout(reason)) {
              setNotice("The connection is slow. Job status will continue syncing with the browser worker.");
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
      rememberJob(updated);
      setJob(updated);
      if (updated.status === "SUBMITTING" || updated.status === "WAITING_RESULT") {
        setCaptcha((current) => current?.jobId === updated.id ? null : current);
        setParallelCaptchas((current) => { const next = {...current}; delete next[updated.id]; return next; });
        setNotice("");
      }
      if (["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(updated.status)) {
        if (persistentState.getItem(ACTIVE_JOB_STORAGE_KEY) === updated.id) persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
        setCaptcha((current) => current?.jobId === updated.id ? null : current);
        setParallelCaptchas((current) => { const next = {...current}; delete next[updated.id]; return next; });
        setReportsTrigger((c) => c + 1);
        // Đợi danh sách runner cập nhật xong TRƯỚC KHI resolve — nếu không, batch runner
        // (runScenarioQueue) sẽ đọc runnersRef.current lúc còn stale (runner vẫn hiện "đang
        // bận") và báo nhầm "không còn runner rảnh" ngay sau job đầu tiên.
        // The shared queue checks availability transactionally in SQL. Its next
        // claim can start immediately after the committed terminal event.
        if (batchRecoveryRef.current?.version === 3 && batchRunningRef.current) void refreshRunners();
        else await refreshRunners();
        resolveTerminal(updated);
      }
    };
    const saveCaptcha = (challenge: CaptchaChallenge) => {
      setCaptcha(challenge);
      setSelectedCaptchaJobId(challenge.jobId);
      setParallelCaptchas((current) => ({...current, [challenge.jobId]: challenge}));
    };
    const onCaptcha = (challenge: CaptchaChallenge) => saveCaptcha({ ...challenge, invalid: false });
    const onCaptchaInvalid = (challenge: CaptchaChallenge) => saveCaptcha({ ...challenge, invalid: true });
    const onCaptchaRefreshed = (challenge: CaptchaChallenge) => saveCaptcha({ ...challenge, invalid: false, refreshed: true });
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

  async function createJob(runnerId: string, filters: VahanFilters, scenarioName?: string, sessionId?: string,
    retryOfJobId?: string, update?: {updateKind: "GLOBAL" | "DISCOVER" | "REFRESH"; updateRunId?: string; updateTaskId?: string}) {
    setCreating(true);
    setError("");
    setNotice("");
    setCaptcha(null);
    try {
      const created = await api.createJob(runnerId, filters, scenarioName, sessionId, retryOfJobId, update);
      latestJobRef.current = created;
      rememberJob(created);
      setJob(created);
      setReportsTrigger((count) => count + 1);
      persistentState.setItem(ACTIVE_JOB_STORAGE_KEY, created.id);
      if (batchRecoveryRef.current?.status === "running") {
        updateBatchRecovery({ activeJobId: created.id });
      }
      if (sessionId && batchStopRef.current) {
        const cancelled = await api.cancelJob(created.id);
        latestJobRef.current = cancelled;
        setJob(cancelled);
        persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
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
        const message = "The connection is slow. The job was created and the browser worker is still being monitored.";
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

  async function submitCaptcha(text1: string, target = captcha) {
    if (!target) return;
    setSubmittingCaptcha(true);
    setError("");
    setNotice("");
    try {
      const acknowledgement = await uiSocket.timeout(UI_SOCKET_ACK_TIMEOUT_MS).emitWithAck(
        "captcha:submitted",
        { jobId: target.jobId, captchaId: target.captchaId, text1 },
      ) as Acknowledgement;
      if (!acknowledgement.ok) throw new Error(acknowledgement.error || "Could not submit the CAPTCHA.");
      setCaptcha((current) => current?.jobId === target.jobId ? null : current);
      setParallelCaptchas((current) => { const next = {...current}; delete next[target.jobId]; return next; });
    } catch (reason) {
      if (isSocketTimeout(reason)) {
        // The server accepts this command before the browser worker performs the
        // slow DOM work. Keep this as a non-blocking notice for old servers or
        // a temporarily slow socket; a real job failure is shown by JobStatus.
        setNotice("CAPTCHA received. The browser worker is continuing to fill in the VAHAN filters.");
      } else {
        setError(reason instanceof Error ? reason.message : "Could not submit the CAPTCHA.");
      }
    } finally {
      setSubmittingCaptcha(false);
    }
  }

  async function refreshCaptcha(target = captcha) {
    if (!target) return;
    setRefreshingCaptcha(true);
    setError("");
    setNotice("");
    try {
      const acknowledgement = await uiSocket.timeout(CAPTCHA_REFRESH_ACK_TIMEOUT_MS).emitWithAck(
        "captcha:refresh",
        { jobId: target.jobId, captchaId: target.captchaId },
      ) as Acknowledgement & { captcha?: CaptchaChallenge };
      if (!acknowledgement.ok) throw new Error(acknowledgement.error || "Could not load a new CAPTCHA.");
      if (acknowledgement.captcha) {
        const refreshed = { ...acknowledgement.captcha, invalid: false, refreshed: true };
        setCaptcha(refreshed);
        setParallelCaptchas((current) => ({...current, [refreshed.jobId]: refreshed}));
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

  // A single report has a bounded wait. A running batch waits until its worker
  // reconnects or the operator presses Stop, retaining the current filter.
  async function pickAvailableRunnerWithRetry(attempts = 30, delayMs = 1000): Promise<string | null> {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      if (attempts === Infinity && batchStopRef.current) return null;
      const runnerId = pickAvailableRunner();
      if (runnerId) return runnerId;
      if (attempt < attempts - 1) {
        await sleep(delayMs);
        await refreshRunners();
      }
    }
    return null;
  }

  async function runOneScenarioJob(runnerId: string, filters: VahanFilters, scenarioName?: string, sessionId?: string, retryOfJobId?: string): Promise<Job> {
    try {
      let selectedRunnerId = runnerId;
      let created: Job | undefined;
      for (let attempt = 0; ; attempt += 1) {
        if (batchStopRef.current) throw new Error('The batch was stopped.');
        try {
          created = await createJob(selectedRunnerId, filters, scenarioName, sessionId, retryOfJobId);
          break;
        } catch (reason) {
          const message = reason instanceof Error ? reason.message : String(reason || '');
          if (batchStopRef.current || (attempt === 9 && !batchRunningRef.current)
            || !/Runner is reconnecting|Runner is offline or does not exist/i.test(message)) {
            throw reason;
          }
          if (batchRunningRef.current) setNotice('The browser worker is reconnecting. Waiting at this filter.');
          await sleep(1000);
          await refreshRunners();
          selectedRunnerId = pickAvailableRunner() || selectedRunnerId;
        }
      }
      if (!created) throw new Error('Could not create the report job after the runner reconnected.');
      const id = created?.id || latestJobRef.current?.id;
      if (!id) throw new Error("The created job has no identifier.");
      return await waitForExistingJob(id);
    } catch (reason) {
      throw reason;
    }
  }

  async function waitForExistingJob(jobId: string): Promise<Job> {
    const isTerminal = (candidate: Job | null): candidate is Job =>
      Boolean(candidate && ["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(candidate.status));
    const known = jobSnapshotsRef.current.get(jobId) || latestJobRef.current;
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
        if (terminalResolverRef.current.get(jobId) === finish) terminalResolverRef.current.delete(jobId);
        resolve(completed);
      };
      terminalResolverRef.current.set(jobId, finish);
      const poll = async () => {
        if (settled) return;
        try {
          const snapshot = await api.getJob(jobId);
          if (settled) return;
          latestJobRef.current = snapshot;
          rememberJob(snapshot);
          setJob(snapshot);
          if (isTerminal(snapshot)) {
            if (persistentState.getItem(ACTIVE_JOB_STORAGE_KEY) === jobId) persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
            setCaptcha((current) => current?.jobId === jobId ? null : current);
            setParallelCaptchas((current) => { const next = {...current}; delete next[jobId]; return next; });
            if (["COMPLETED", "NO_DATA"].includes(snapshot.status)) setReportsTrigger((value) => value + 1);
            if (batchRecoveryRef.current?.version === 3 && batchRunningRef.current) void refreshRunners();
            else await refreshRunners().catch(() => {});
            finish(snapshot);
            return;
          }
          // Retry a lost initial subscription as well as missed terminal events.
          if (uiSocket.connected) await subscribeJob(jobId).catch(() => {});
        } catch (reason) {
          if (reason instanceof ApiError && reason.status === 404) {
            settled = true;
            if (terminalResolverRef.current.get(jobId) === finish) terminalResolverRef.current.delete(jobId);
            reject(new Error("The backend no longer has this job. It may have restarted; retry this filter."));
            return;
          }
          setNotice("Connection interrupted. Waiting for the current filter's confirmed result.");
        }
        if (!settled) timer = setTimeout(() => void poll(), uiSocket.connected ? 10_000 : 3_000);
      };
      const latest = jobSnapshotsRef.current.get(jobId) || latestJobRef.current;
      if (latest?.id === jobId && isTerminal(latest)) finish(latest);
      else timer = setTimeout(() => void poll(), known?.id === jobId ? (uiSocket.connected ? 10_000 : 3_000) : 0);
    });
  }

  async function runMakerUpdateTask(runId: string, task: MakerUpdateTask, year: number): Promise<void> {
    if (makerUpdateStopRef.current) return;
    if (task.status === "RUNNING" && task.jobId) {
      makerUpdateJobRef.current = task.jobId;
      const existing = await waitForExistingJob(task.jobId);
      makerUpdateJobRef.current = null;
      if (existing.status !== "COMPLETED" && existing.status !== "NO_DATA") {
        throw new Error(existing.error || `${task.kind} failed for ${task.maker} / ${task.state}.`);
      }
      return;
    }
    const runnerId = await pickAvailableRunnerWithRetry();
    if (!runnerId) throw new Error("No online browser runner is available for Maker update.");
    if (makerUpdateStopRef.current) return;
    const filters = fixedFilters(task.state, task.rto, year);
    filters.makers = [task.maker];
    if (task.kind === "DISCOVER") {
      filters.rtos = [];
      filters.yAxis = "RTO Wise";
    }
    setMakerUpdateProgress(`${task.kind === "DISCOVER" ? "Dò RTO" : "Cập nhật"}: ${task.maker} · ${task.state}${task.rto ? ` · ${task.rto}` : ""}`);
    const created = await createJob(runnerId, filters, `${task.kind} ${task.maker} / ${task.state}${task.rto ? ` / ${task.rto}` : ""}`,
      undefined, undefined, {updateKind: task.kind, updateRunId: runId, updateTaskId: task.id});
    if (!created) throw new Error("Could not create Maker update job.");
    makerUpdateJobRef.current = created.id;
    const finished = await waitForExistingJob(created.id);
    makerUpdateJobRef.current = null;
    if (finished.status !== "COMPLETED" && finished.status !== "NO_DATA") {
      throw new Error(finished.error || `${task.kind} failed for ${task.maker} / ${task.state}.`);
    }
  }

  async function continueMakerUpdate(runId: string): Promise<void> {
    let checkedRtoAxis = false;
    for (;;) {
      if (makerUpdateStopRef.current) return;
      const run = await api.makerUpdate(runId);
      setMakerUpdate(run);
      if (run.status !== "RUNNING") {
        setMakerUpdateProgress(run.status === "BASELINE" ? "Đã lưu mốc dữ liệu Maker đầu tiên."
          : run.status === "UNCHANGED" ? "Không có Maker thay đổi."
            : "Đã cập nhật các RTO thay đổi vào bảng chính.");
        setReportsTrigger((value) => value + 1);
        return;
      }
      const tasks = run.tasks || [];
      const discovery = tasks.filter((task) => task.kind === "DISCOVER" && task.status !== "DONE");
      const task = (discovery.length ? discovery : tasks.filter((item) => item.kind === "REFRESH" && item.status !== "DONE"))[0];
      if (!task) throw new Error("Maker update has no remaining tasks but is still marked running.");
      if (task.kind === "DISCOVER" && !checkedRtoAxis && task.status !== "RUNNING") {
        const runnerId = await pickAvailableRunnerWithRetry();
        if (!runnerId) throw new Error("No online browser runner is available for RTO discovery.");
        const available = await requestRunnerOptions(uiSocket, runnerId, {type: "GET_ALL_OPTIONS"},
          "Checking RTO report axis…", setMakerUpdateProgress) as Record<string, string[]>;
        if (!available?.yAxis?.some((label) => label.trim().toLowerCase() === "rto wise")) {
          throw new Error("VAHAN does not offer the RTO Y-Axis needed to locate changed offices.");
        }
        const xAxis = await requestRunnerOptions(uiSocket, runnerId,
          {type: "GET_X_AXIS_OPTIONS", yAxis: "RTO Wise"}, "Checking RTO / Month Wise…", setMakerUpdateProgress) as string[];
        if (!Array.isArray(xAxis) || !xAxis.some((label) => label.trim().toLowerCase() === "month wise")) {
          throw new Error("VAHAN does not offer RTO / Month Wise; focused update cannot continue safely.");
        }
        if (makerUpdateStopRef.current) return;
        checkedRtoAxis = true;
      }
      await runMakerUpdateTask(runId, task, run.year);
    }
  }

  async function startMakerUpdate(): Promise<void> {
    if (makerUpdateRunningRef.current || batchRunningRef.current || creating) return;
    makerUpdateRunningRef.current = true;
    makerUpdateStopRef.current = false;
    setMakerUpdateRunning(true);
    setError("");
    try {
      const year = selectedYear;
      const previous = await api.makerUpdates(year);
      const active = previous.find((run) => run.status === "RUNNING");
      if (active) {
        await continueMakerUpdate(active.id);
        return;
      }
      const runnerId = await pickAvailableRunnerWithRetry();
      if (!runnerId) throw new Error("No online browser runner is available for the all-State scan.");
      const states = [...new Set((await requestRunnerOptions(uiSocket, runnerId,
        {type: "GET_STATE_OPTIONS", delhiNcr: "ALL STATES"}, "Loading all States…", setMakerUpdateProgress) as string[])
        .map((name) => name.trim()).filter((name) => name && !/^(-+\s*select|all states)/i.test(name)))];
      if (states.length < 30) throw new Error("VAHAN did not return the full State list.");
      if (makerUpdateStopRef.current) return;
      const filters = fixedFilters("", "", year);
      filters.states = states;
      filters.rtos = [];
      setMakerUpdateProgress(`Tải báo cáo Maker của ${states.length} State…`);
      const created = await createJob(runnerId, filters, `Maker Month Wise / All States (${year})`,
        undefined, undefined, {updateKind: "GLOBAL"});
      if (!created) throw new Error("Could not create the all-State Maker job.");
      makerUpdateJobRef.current = created.id;
      const finished = await waitForExistingJob(created.id);
      makerUpdateJobRef.current = null;
      if (finished.status !== "COMPLETED") {
        throw new Error(finished.error || "The all-State Maker report did not complete.");
      }
      await continueMakerUpdate(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Maker update failed.");
    } finally {
      makerUpdateRunningRef.current = false;
      makerUpdateJobRef.current = null;
      setMakerUpdateRunning(false);
    }
  }

  async function stopMakerUpdate(): Promise<void> {
    makerUpdateStopRef.current = true;
    const jobId = makerUpdateJobRef.current;
    if (jobId) await api.cancelJob(jobId).catch(() => {});
    setMakerUpdateProgress("Đã dừng. Bấm Update để tiếp tục các việc chưa hoàn tất.");
  }

  async function runScenarioQueue(
    queue: Scenario[],
    {
      startIndex = 0,
      clearLog = true,
      resumeState,
      selectedIndices,
      planOverride,
      sessionIdOverride,
    }: { startIndex?: number; clearLog?: boolean; resumeState?: PersistedBatchRecovery; selectedIndices?: number[]; planOverride?: MatrixPlan; sessionIdOverride?: string } = {},
  ) {
    if ((!queue.length && !resumeState) || (batchRunningRef.current && !resumeState)) return;
    const sourcePlan = planOverride || matrixPlan;
    if (!sourcePlan) {
      setError("The State–RTO office list could not be loaded. Start a new session to refresh it.");
      return;
    }
    if (resumeState && resumeState.year !== sourcePlan.year) {
      setError("The saved batch belongs to another report year. Restore its original year to continue.");
      if (resumeState) {
        batchRunningRef.current = false;
        setBatchRunning(false);
        setBatchStatus("error");
        writeBatchRecovery({ ...resumeState, status: "error" });
      }
      return;
    }
    const activePlan = sourcePlan;
    const activeScenarios = activePlan.scenarios;
    batchLoopStartedRef.current = true;
    batchRunningRef.current = true;
    setBatchRunning(true);
    setBatchStatus("running");

    const queueIndices = resumeState?.queueIndices || selectedIndices || queue.map((_, index) => startIndex + index);
    const sessionId = resumeState?.sessionId || sessionIdOverride || crypto.randomUUID();
    const startPosition = resumeState?.nextPosition || 0;
    const total = queueIndices.length;
    let done = resumeState ? Math.min(resumeState.progress.done, total) : 0;
    const startedAt = resumeState?.startedAt || new Date().toISOString();
    let activeElapsedMs = resumeState?.activeElapsedMs ?? 0;
    let activeSegmentStartedAt: number | null = resumeState?.status === "running" && resumeState.activeSegmentStartedAt != null
      ? resumeState.activeSegmentStartedAt : Date.now();
    let retryQueueIndices = [...(resumeState?.retryQueueIndices || [])];
    let lastRetryCheckpoint = resumeState?.lastRetryCheckpoint || 0;
    let recoveredRetryIndex = resumeState?.retryIndex ?? null;
    let recoveredRetryJobId = recoveredRetryIndex === null ? null : resumeState?.activeJobId || null;
    if (recoveredRetryIndex !== null && !retryQueueIndices.includes(recoveredRetryIndex)) {
      retryQueueIndices.unshift(recoveredRetryIndex);
    }
    const activeElapsedAt = (timestamp: number) => activeElapsedMs
      + (activeSegmentStartedAt === null ? 0 : Math.max(0, timestamp - activeSegmentStartedAt));
    let timings = resumeState?.timings || [];
    setBatchTimings(timings);
    setCurrentFilterStartedAt(resumeState?.currentFilterStartedAt ?? null);
    setBatchActiveElapsedMs(activeElapsedMs);
    setBatchActiveSegmentStartedAt(activeSegmentStartedAt);
    setBatchStartedAt(startedAt);
    setBatchFinishedAt(null);
    let current = activeScenarios[queueIndices[startPosition]]?.name
      || resumeState?.progress.current
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
      updateBatchRecovery({
        status: "running", startedAt, finishedAt: null, activeElapsedMs, activeSegmentStartedAt,
      });
    } else {
      batchStopRef.current = false;
      const initialProgress = { done: 0, total, current };
      writeBatchRecovery({
        version: 1,
        status: "running",
        queueIndices,
        queueOfficeKeys: queueIndices.map((index) => matrixOfficeKey(activeScenarios[index])),
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
        lastRetryCheckpoint: 0,
        retryQueueIndices: [],
        retryIndex: null,
        currentFilterStartedAt: null,
        activeElapsedMs,
        activeSegmentStartedAt,
      });
      done = 0;
    }
    updateBatchProgress({ done, total, current });

    let outcome: BatchStatus = "completed";
    let hadErrors = resumeState?.hadErrors || false;

    let filterStartedAt = Date.now();
    function recordScenario(
      entry: BatchLogEntry,
      trackTiming = true,
      recoveryPatch: Partial<PersistedBatchRecovery> = {},
    ) {
      const completedAt = Date.now();
      entry.completedAt = new Date(completedAt).toISOString();
      entry.durationMs = Math.max(0, completedAt - filterStartedAt);
      const previousEntry = batchLogRef.current.find((item) => item.index === entry.index);
      const scenario = activeScenarios[entry.index];
      entry.state ||= scenario?.filters.states[0];
      entry.rto ||= scenario?.filters.rtos[0];
      if (entry.status !== 'error') {
        const confirmed = latestJobRef.current;
        if (confirmed && confirmed.id === entry.jobId && ['COMPLETED', 'NO_DATA'].includes(confirmed.status)) {
          entry.savedAt = confirmed.mainReportSavedAt || entry.completedAt;
          entry.rowCount = confirmed.mainReportSummary?.parsedRows ?? confirmed.reportRowCount ?? 0;
        }
      } else {
        entry.savedAt = undefined;
        entry.rowCount = undefined;
      }
      if (entry.autoRetryCount === undefined) entry.autoRetryCount = previousEntry?.autoRetryCount || 0;
      if (!(batchStopRef.current && entry.status === 'error')) {
        const observed = latestJobRef.current;
        const confirmedFailure = Boolean(entry.jobId && observed?.id === entry.jobId && observed?.status === 'FAILED'
          && entry.jobId !== previousEntry?.jobId);
        logRunOutcome({id: confirmedFailure ? `job:${entry.jobId}` : `batch:${sessionId}:${entry.index}:${entry.autoRetryCount}:${entry.completedAt}`,
          jobId: confirmedFailure ? entry.jobId : undefined,
          sessionId, filters: activeScenarios[entry.index]?.filters, name: entry.name,
          status: entry.status === 'error' ? 'failed' : entry.status === 'empty' ? 'no_data' : 'completed',
          detail: entry.detail, occurredAt: confirmedFailure ? observed?.updatedAt || entry.completedAt : entry.completedAt, attempt: entry.autoRetryCount});
      }
      if (trackTiming) {
        timings = [...timings.filter((sample) => sample.index !== entry.index), {
          index: entry.index,
          durationMs: entry.durationMs,
          completedCount: done + 1,
          activeElapsedMs: activeElapsedAt(completedAt),
        }];
      }
      setBatchTimings(timings);
      const currentLog = batchLogRef.current;
      const existingIndex = currentLog.findIndex((item) => item.index === entry.index);
      const nextLog = existingIndex < 0
        ? [...currentLog, entry]
        : currentLog.map((item, index) => index === existingIndex ? entry : item);
      batchLogRef.current = nextLog;
      setBatchLog(nextLog);
      hadErrors = nextLog.some((item) => item.status === "error");
      const nextFailedIndex = nextLog.find((item) => item.status === "error")?.index ?? null;
      failedAtIndexRef.current = nextFailedIndex;
      setFailedAtIndex(nextFailedIndex);
      updateBatchRecovery({
        log: nextLog,
        hadErrors,
        failedAtIndex: nextFailedIndex,
        timings,
        ...recoveryPatch,
      });
    }

    async function processAutoRetryQueue(): Promise<boolean> {
      while (retryQueueIndices.length > 0) {
        const scenarioIndex = retryQueueIndices[0];
        const failedEntry = batchLogRef.current.find((item) => item.index === scenarioIndex);
        if (!failedEntry || failedEntry.status !== "error"
          || (failedEntry.autoRetryCount || 0) >= MAX_AUTO_RETRY_ATTEMPTS) {
          retryQueueIndices = retryQueueIndices.slice(1);
          updateBatchRecovery({ retryQueueIndices, retryIndex: null });
          recoveredRetryIndex = null;
          recoveredRetryJobId = null;
          continue;
        }
        const retryJobId = recoveredRetryIndex === scenarioIndex ? recoveredRetryJobId : null;
        if (batchStopRef.current) {
          if (retryJobId) {
            try {
              const stoppedJob = await api.cancelJob(retryJobId);
              latestJobRef.current = stoppedJob;
              setJob(stoppedJob);
              persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
              setCaptcha(null);
              resolveTerminal(stoppedJob);
            } catch {
              // The retry may already have reached a terminal state.
            }
          }
          setCurrentFilterStartedAt(null);
          updateBatchRecovery({
            retryQueueIndices,
            retryIndex: null,
            currentIndex: null,
            activeJobId: null,
            currentFilterStartedAt: null,
          });
          recoveredRetryIndex = null;
          recoveredRetryJobId = null;
          return false;
        }

        const scenario = activeScenarios[scenarioIndex];
        if (!scenario) {
          setError(`Could not find failed case ${scenarioIndex + 1} while restoring automatic retries.`);
          retryQueueIndices = retryQueueIndices.slice(1);
          updateBatchRecovery({ retryQueueIndices, retryIndex: null, currentIndex: null, activeJobId: null });
          recoveredRetryIndex = null;
          recoveredRetryJobId = null;
          continue;
        }

        const attempt = (failedEntry.autoRetryCount || 0) + 1;
        current = `Retrying failed report (${attempt}/${MAX_AUTO_RETRY_ATTEMPTS}): ${scenario.name}`;
        filterStartedAt = Date.now();
        setCurrentFilterStartedAt(filterStartedAt);
        updateBatchProgress({ done, total, current });
        updateBatchRecovery({
          status: "running",
          retryQueueIndices,
          retryIndex: scenarioIndex,
          nextPosition: done,
          currentIndex: scenarioIndex,
          activeJobId: retryJobId,
          currentFilterStartedAt: filterStartedAt,
        });

        let result: Job;
        try {
          if (retryJobId) {
            result = await waitForExistingJob(retryJobId);
          } else {
            setNotice(`Waiting for the browser worker to resume automatic retry: ${scenario.name}.`);
            const runnerId = await pickAvailableRunnerWithRetry(Infinity);
            if (!runnerId) throw new Error("No online VAHAN browser runner is available.");
            if (batchStopRef.current) {
              setCurrentFilterStartedAt(null);
              updateBatchRecovery({ retryIndex: null, currentIndex: null, activeJobId: null, currentFilterStartedAt: null });
              recoveredRetryIndex = null;
              recoveredRetryJobId = null;
              return false;
            }
            result = await runOneScenarioJob(runnerId, scenario.filters, scenario.name, sessionId, failedEntry.jobId);
          }
        } catch (reason) {
          if (batchStopRef.current) {
            setCurrentFilterStartedAt(null);
            updateBatchRecovery({ retryQueueIndices, retryIndex: null, currentIndex: null, activeJobId: null, currentFilterStartedAt: null });
            recoveredRetryIndex = null;
            recoveredRetryJobId = null;
            return false;
          }
          const message = reason instanceof Error ? reason.message : "An unknown error occurred while retrying this report.";
          setCurrentFilterStartedAt(null);
          if (/No online VAHAN browser runner is available|Runner is reconnecting|Runner is offline or does not exist/i.test(message)) {
            setNotice(`Automatic retry is paused until the browser worker reconnects. ${scenario.name} remains queued and will not be skipped.`);
            updateBatchRecovery({ retryQueueIndices, retryIndex: null, currentIndex: null, activeJobId: null, currentFilterStartedAt: null });
            recoveredRetryIndex = null;
            recoveredRetryJobId = null;
            return false;
          }
          retryQueueIndices = retryQueueIndices.slice(1);
          recordScenario({
            ...failedEntry,
            status: "error",
            autoRetryCount: attempt,
            detail: `Automatic retry ${attempt}/${MAX_AUTO_RETRY_ATTEMPTS} failed: ${message}`,
          }, false, {
            retryQueueIndices,
            retryIndex: null,
            currentIndex: null,
            activeJobId: null,
            currentFilterStartedAt: null,
          });
          recoveredRetryIndex = null;
          recoveredRetryJobId = null;
          if (batchStopRef.current) return false;
          continue;
        }

        if (result.status === "CANCELLED") {
          if (!batchStopRef.current) setNotice(`Retry paused at ${scenario.name} because the browser worker cancelled the job. The case remains queued.`);
          setCurrentFilterStartedAt(null);
          updateBatchRecovery({ retryQueueIndices, retryIndex: null, currentIndex: null, activeJobId: null, currentFilterStartedAt: null });
          recoveredRetryIndex = null;
          recoveredRetryJobId = null;
          return false;
        }

        retryQueueIndices = retryQueueIndices.slice(1);
        const retryRecoveryPatch: Partial<PersistedBatchRecovery> = {
          retryQueueIndices,
          retryIndex: null,
          currentIndex: null,
          activeJobId: null,
          currentFilterStartedAt: null,
        };
        if (result.status === "NO_DATA" || (result.error || "").startsWith("NO_RECORD_FOUND")) {
          recordScenario({
            ...failedEntry,
            status: "empty",
            autoRetryCount: attempt,
            detail: `Automatic retry ${attempt}/${MAX_AUTO_RETRY_ATTEMPTS} confirmed no records. State, RTO and collection timestamp are saved to SQL.`,
            jobId: result.id,
            noDataFileName: result.noDataFileName,
          }, false, retryRecoveryPatch);
        } else if (result.status === "COMPLETED") {
          recordScenario({
            ...failedEntry,
            status: "ok",
            autoRetryCount: attempt,
            detail: `Recovered on automatic retry ${attempt}/${MAX_AUTO_RETRY_ATTEMPTS}. Manufacturer data saved to the main table.`,
            jobId: result.id,
            excelFileName: result.excelFileName,
          }, false, retryRecoveryPatch);
        } else {
          recordScenario({
            ...failedEntry,
            status: "error",
            autoRetryCount: attempt,
            detail: `Automatic retry ${attempt}/${MAX_AUTO_RETRY_ATTEMPTS} failed: ${result.error || `Job ended with status ${result.status}.`}`,
            jobId: result.id,
          }, false, retryRecoveryPatch);
        }
        recoveredRetryIndex = null;
        recoveredRetryJobId = null;
        setCurrentFilterStartedAt(null);
        updateBatchProgress({ done, total, current: scenario.name });
        if (batchStopRef.current) return false;
      }
      return true;
    }

    async function runRetryCheckpoint(primaryCount: number, force = false): Promise<boolean> {
      if (!force && primaryCount <= lastRetryCheckpoint) return true;
      const groupIndices = queueIndices.slice(lastRetryCheckpoint, primaryCount);
      lastRetryCheckpoint = primaryCount;
      const eligibleFailures = groupIndices.filter((index) => batchLogRef.current.some((entry) =>
        entry.index === index && entry.status === "error" && (entry.autoRetryCount || 0) < MAX_AUTO_RETRY_ATTEMPTS));
      retryQueueIndices = [...new Set([...retryQueueIndices, ...eligibleFailures])];
      updateBatchRecovery({ lastRetryCheckpoint, retryQueueIndices });
      return processAutoRetryQueue();
    }

    const recoveredRetryQueue = retryQueueIndices.length > 0;
    if (recoveredRetryQueue) {
      if (!(await processAutoRetryQueue())) outcome = "stopped";
    } else if (resumeState && !resumeState.activeJobId && recoveredRetryIndex === null
      && done > lastRetryCheckpoint && (done % AUTO_RETRY_CHECKPOINT_SIZE === 0 || done === total)) {
      // Recover a completed group whose checkpoint was interrupted by a reload.
      if (!(await runRetryCheckpoint(done))) outcome = "stopped";
    }

    for (let position = startPosition; position < queueIndices.length; position += 1) {
      if (outcome !== "completed") break;
      const activeJobId = resumeState && position === startPosition && resumeState.retryIndex == null
        ? resumeState.activeJobId : null;
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
          setNotice(`Waiting for the browser worker: ${scenario.name}.`);
          const runnerId = await pickAvailableRunnerWithRetry(Infinity);
          if (!runnerId) {
            setCurrentFilterStartedAt(null);
            setNotice(`The browser worker is offline. The batch is paused at ${scenario.name}; this case will resume from here.`);
            outcome = "stopped";
            break;
          }
          if (batchStopRef.current) {
            outcome = "stopped";
            break;
          }
          const previousEntry = !clearLog ? batchLogRef.current.find((entry) => entry.index === scenarioIndex && entry.status === "error") : undefined;
          result = await runOneScenarioJob(runnerId, scenario.filters, scenario.name, sessionId, previousEntry?.jobId);
        }
        if (result.status === "CANCELLED") {
          if (!batchStopRef.current) setNotice(`The browser worker cancelled ${scenario.name}. The batch is paused at this case so it can be rerun safely.`);
          setCurrentFilterStartedAt(null);
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
            detail: "No record found. State, RTO and collection timestamp saved to SQL.",
            jobId: result.id,
            noDataFileName: result.noDataFileName,
          });
        } else if (result.status === "COMPLETED") {
          recordScenario({
            index: scenarioIndex,
            name: scenario.name,
            status: "ok",
            detail: `Saved ${result.mainReportSummary?.parsedRows ?? result.reportRowCount ?? 0} manufacturer rows to the main table.`,
            jobId: result.id,
            excelFileName: result.excelFileName,
          });
        } else {
          hadErrors = true;
          recordScenario({
            index: scenarioIndex,
            name: scenario.name, status: "error",
            autoRetryCount: batchLogRef.current.find((item) => item.index === scenarioIndex)?.autoRetryCount || 0,
            state: scenario.filters.states[0],
            rto: scenario.filters.rtos[0],
            jobId: result.id,
            detail: (result.error || ("Job ended with status " + result.status + ".")) + " It will be retried automatically at the next checkpoint.",
          });
        }
      } catch (reason) {
        if (batchStopRef.current) {
          outcome = "stopped";
          break;
        }
        const message = reason instanceof Error ? reason.message : String(reason || '');
        if (/No online VAHAN browser runner is available|Runner is reconnecting|Runner is offline or does not exist/i.test(message)) {
          setCurrentFilterStartedAt(null);
          setNotice(`The browser worker is reconnecting. The batch is paused at ${scenario.name}; this case will resume from here.`);
          outcome = "stopped";
          break;
        }
        hadErrors = true;
        recordScenario({
          index: scenarioIndex,
          name: scenario.name, status: "error",
          autoRetryCount: batchLogRef.current.find((item) => item.index === scenarioIndex)?.autoRetryCount || 0,
          state: scenario.filters.states[0],
          rto: scenario.filters.rtos[0],
          jobId: batchLogRef.current.find((entry) => entry.index === scenarioIndex)?.jobId,
          detail: (reason instanceof Error ? reason.message : "An unknown error occurred while creating the job.") + " It will be retried automatically at the next checkpoint.",
        });
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
      if ((position + 1) % AUTO_RETRY_CHECKPOINT_SIZE === 0
        && !(await runRetryCheckpoint(position + 1))) {
        outcome = "stopped";
        break;
      }
    }

    if (outcome === "completed" && done === total && lastRetryCheckpoint < total
      && !(await runRetryCheckpoint(total))) {
      outcome = "stopped";
    }

    hadErrors = batchLogRef.current.some((entry) => entry.status === "error");
    const finalStatus = outcome === "completed" && hadErrors ? "completed_with_errors" : outcome;
    const finishedAtMs = Date.now();
    activeElapsedMs = activeElapsedAt(finishedAtMs);
    activeSegmentStartedAt = null;
    setBatchActiveElapsedMs(activeElapsedMs);
    setBatchActiveSegmentStartedAt(null);
    const finishedAt = new Date(finishedAtMs).toISOString();
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
      retryQueueIndices,
      retryIndex: null,
      finishedAt,
      currentFilterStartedAt: null,
      activeElapsedMs,
      activeSegmentStartedAt: null,
    });
    batchRunningRef.current = false;
    setBatchRunning(false);
    setReportsTrigger((count) => count + 1);
  }

  async function runSharedScenarioQueue(plan: MatrixPlan, resumeState?: PersistedBatchRecovery) {
    if (batchRunningRef.current && !resumeState) return;
    if (resumeState && (resumeState.version !== 3 || !validSharedLanes(resumeState.lanes, resumeState.queueIndices))) {
      setError('The saved shared queue is invalid. Start a new session.');
      return;
    }
    if (!isReportYear(plan.year) || (resumeState && resumeState.year !== plan.year)) {
      setError('The saved batch belongs to a different calendar year. Start a new session.');
      return;
    }
    const queueIndices = resumeState?.queueIndices || plan.scenarios.map((_, index) => index);
    if (!queueIndices.length || queueIndices.some((index) => !plan.scenarios[index])
      || resumeState?.queueOfficeKeys?.some((key, position) =>
        key !== matrixOfficeKey(plan.scenarios[queueIndices[position]]))) {
      setError('The saved State/RTO cases no longer match the office list.');
      return;
    }
    let savedQueue: Awaited<ReturnType<typeof api.batchQueue>> | null = null;
    let effectiveWorkerCount = selectedWorkerCount;
    let managedIds: Set<string> | null = null;
    try {
      if (resumeState) {
        savedQueue = await api.batchQueue(resumeState.sessionId);
        if (resumeState.status === 'running' && savedQueue.status === 'PAUSED') {
          batchRunningRef.current = false; setBatchRunning(false); setBatchStatus('stopped');
          writeBatchRecovery({...resumeState, status: 'stopped', stopRequested: false});
          return;
        }
        if (resumeState.status === 'running') effectiveWorkerCount = savedQueue.maxWorkers ?? resumeState.lanes!.length;
      }
      const pool = await ensureDockerWorkers(effectiveWorkerCount);
      if (pool?.enabled) managedIds = new Set(Array.from({length: effectiveWorkerCount}, (_, index) => `playwright-${index + 1}`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not prepare Docker workers.');
      return;
    }
    let lanes: ParallelLaneRecovery[];
    if (resumeState) {
      lanes = resumeState.lanes!.map((lane) => ({...lane, indices: [...lane.indices], retryQueueIndices: [...lane.retryQueueIndices]}));
      if (managedIds) {
        const saved = new Map(lanes.map(lane => [lane.runnerId, lane]));
        lanes = [...managedIds].map(runnerId => saved.get(runnerId) || {
          runnerId, indices: [], nextPosition: 0, currentIndex: null, activeJobId: null,
          lastJobId: null, retryQueueIndices: [], retryIndex: null, lastRetryCheckpoint: 0, currentFilterStartedAt: null,
        });
      } else if (effectiveWorkerCount !== lanes.length) {
        await refreshRunners();
        const available = runnersRef.current.filter(runner => runner.source === 'new'
          && runner.status === 'ONLINE' && !runner.currentJobId).sort((a, b) => compareRunnerIds(a.id, b.id));
        if (available.length < effectiveWorkerCount) {
          setError(`${effectiveWorkerCount} idle workers are required; ${available.length} available.`);
          return;
        }
        lanes = available.slice(0, effectiveWorkerCount).map(runner => ({
          runnerId: runner.id, indices: [], nextPosition: 0, currentIndex: null, activeJobId: null,
          lastJobId: null, retryQueueIndices: [], retryIndex: null, lastRetryCheckpoint: 0, currentFilterStartedAt: null,
        }));
      }
    } else {
      await refreshRunners();
      const available = runnersRef.current.filter((runner) => (runner.source || 'new') === 'new'
        && runner.status === 'ONLINE' && !runner.currentJobId && (!managedIds || managedIds.has(runner.id)))
        .sort((left, right) => compareRunnerIds(left.id, right.id));
      if (available.length < effectiveWorkerCount) {
        setError(`${effectiveWorkerCount} online, idle browser workers are required to start a full run. ${available.length} available now.`);
        return;
      }
      lanes = available.slice(0, effectiveWorkerCount).map((runner) => ({
        runnerId: runner.id, indices: [], nextPosition: 0, currentIndex: null,
        activeJobId: null, lastJobId: null, retryQueueIndices: [], retryIndex: null,
        lastRetryCheckpoint: 0, currentFilterStartedAt: null,
      }));
      batchLogRef.current = [];
      setBatchLog([]);
      setParallelCaptchas({});
      persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
    }

    const sessionId = resumeState?.sessionId || crypto.randomUUID();
    let queueTasks: BatchQueueTask[];
    try {
      const snapshot = resumeState
        ? savedQueue!
        : await api.startBatchQueue(sessionId, queueIndices.map((index) => ({
            name: plan.scenarios[index].name, filters: plan.scenarios[index].filters,
          })), lanes.length);
      if (snapshot.tasks.length !== queueIndices.length) throw new Error('The saved queue case count changed.');
      if (snapshot.status === 'PAUSED') await api.resumeBatchQueue(sessionId, lanes.length);
      else if (snapshot.maxWorkers !== undefined && snapshot.maxWorkers !== lanes.length) throw new Error('Saved worker count does not match the queue.');
      queueTasks = snapshot.tasks;
    } catch (reason) {
      batchRunningRef.current = false;
      setBatchRunning(false);
      setError(reason instanceof Error ? reason.message : 'Could not initialise the shared queue.');
      return;
    }
    setNotice('');
    setRunSettings(current => ({...current, workerCount: effectiveWorkerCount}));

    const startedAt = resumeState?.startedAt || new Date().toISOString();
    let timings = [...(resumeState?.timings || [])];
    let activeElapsedMs = resumeState?.activeElapsedMs || 0;
    let activeSegmentStartedAt = Date.now();
    batchStopRef.current = false;
    batchLoopStartedRef.current = true;
    batchRunningRef.current = true;
    setBatchRunning(true);
    setBatchStatus('running');
    setBatchStartedAt(startedAt);
    setBatchFinishedAt(null);
    setBatchActiveElapsedMs(activeElapsedMs);
    setBatchActiveSegmentStartedAt(activeSegmentStartedAt);

    const initial: PersistedBatchRecovery = resumeState
      ? {...resumeState, status: 'running', stopRequested: false, finishedAt: null,
        activeElapsedMs, activeSegmentStartedAt, lanes}
      : {version: 3, status: 'running', queueIndices,
        queueOfficeKeys: queueIndices.map((index) => matrixOfficeKey(plan.scenarios[index])),
        nextPosition: 0, currentIndex: null, activeJobId: null, stopRequested: false,
        hadErrors: false, log: [], failedAtIndex: null,
        progress: {done: 0, total: queueIndices.length, current: ''}, sessionId,
        year: plan.year, startedAt, finishedAt: null, timings: [],
        currentFilterStartedAt: null, activeElapsedMs, activeSegmentStartedAt, lanes};
    writeBatchRecovery(initial);

    function publish(patch: Partial<PersistedBatchRecovery> = {}) {
      for (const lane of lanes) {
        const owned = queueTasks.filter((task) => task.runnerId === lane.runnerId);
        lane.indices = owned.map((task) => queueIndices[task.position]);
        lane.nextPosition = owned.filter((task) => ['COMPLETED', 'NO_DATA', 'FAILED'].includes(task.status)).length;
        lane.retryQueueIndices = owned.filter((task) => task.status === 'PENDING' && task.failures > 0)
          .map((task) => queueIndices[task.position]);
        const current = owned.find((task) => task.status === 'PROCESSING');
        lane.currentIndex = current ? queueIndices[current.position] : null;
        lane.activeJobId = current?.jobId || null;
        lane.retryIndex = current && current.attempts > 1 ? queueIndices[current.position] : null;
        if (current) lane.currentFilterStartedAt ||= Date.now();
        else lane.currentFilterStartedAt = null;
        if (current?.jobId) lane.lastJobId = current.jobId;
      }
      const done = queueTasks.filter((task) => ['COMPLETED', 'NO_DATA', 'FAILED'].includes(task.status)).length;
      const current = lanes.map((lane) => lane.currentIndex === null ? ''
        : `${lane.runnerId}: ${plan.scenarios[lane.currentIndex]?.name || ''}`).filter(Boolean).join(' | ');
      const started = lanes.map((lane) => lane.currentFilterStartedAt).filter((value): value is number => value !== null);
      const currentFilterStartedAt = started.length ? Math.min(...started) : null;
      const failedAtIndex = queueTasks.find((task) => task.status === 'FAILED')?.position ?? null;
      const progress = {done, total: queueTasks.length, current};
      const next: PersistedBatchRecovery = {...batchRecoveryRef.current!, version: 3,
        nextPosition: done, lanes: lanes.map((lane) => ({...lane, indices: [...lane.indices],
          retryQueueIndices: [...lane.retryQueueIndices]})),
        log: batchLogRef.current, failedAtIndex, hadErrors: failedAtIndex !== null,
        progress, timings, currentFilterStartedAt, ...patch};
      writeBatchRecovery(next);
      setBatchProgress(progress);
      setBatchTimings(timings);
      setCurrentFilterStartedAt(currentFilterStartedAt);
      setFailedAtIndex(failedAtIndex);
    }

    function upsertTask(task: BatchQueueTask) {
      queueTasks[task.position] = task;
      publish();
    }

    function recordTask(task: BatchQueueTask, result?: Job, startedAtMs?: number) {
      if (!['COMPLETED', 'NO_DATA', 'FAILED'].includes(task.status) && task.status !== 'PENDING') return;
      const index = queueIndices[task.position];
      const previous = batchLogRef.current.find((entry) => entry.index === index);
      const status = task.status === 'COMPLETED' ? 'ok' : task.status === 'NO_DATA' ? 'empty' : 'error';
      const entry: BatchLogEntry = {
        index, name: plan.scenarios[index].name, state: plan.scenarios[index].filters.states[0],
        rto: plan.scenarios[index].filters.rtos[0], status, jobId: task.jobId || undefined,
        detail: status === 'ok' ? 'Manufacturer data saved to the main table.'
          : status === 'empty' ? 'No record found. State and RTO saved to SQL.'
          : (task.error || 'The report failed.') + (task.status === 'PENDING' ? ' Queued for retry.' : ' Retry limit reached.'),
        autoRetryCount: Math.max(0, task.attempts - 1),
        excelFileName: result?.excelFileName, noDataFileName: result?.noDataFileName,
        rowCount: result?.mainReportSummary?.parsedRows ?? result?.reportRowCount ?? previous?.rowCount,
        savedAt: result?.mainReportSavedAt || previous?.savedAt,
        durationMs: startedAtMs ? Math.max(0, Date.now() - startedAtMs) : previous?.durationMs,
        completedAt: new Date().toISOString(),
      };
      batchLogRef.current = previous
        ? batchLogRef.current.map((item) => item.index === index ? entry : item)
        : [...batchLogRef.current, entry];
      setBatchLog(batchLogRef.current);
      if (result && task.status !== 'PENDING' && (!previous || previous.jobId !== task.jobId)) {
        const elapsed = activeElapsedMs + Math.max(0, Date.now() - activeSegmentStartedAt);
        timings = [...timings, {index, durationMs: entry.durationMs || 0,
          completedCount: queueTasks.filter((item) => ['COMPLETED', 'NO_DATA', 'FAILED'].includes(item.status)).length,
          activeElapsedMs: elapsed}];
      }
      if (result && result.status === 'FAILED') logRunOutcome({
        id: `job:${result.id}`, jobId: result.id, sessionId,
        filters: plan.scenarios[index].filters, name: entry.name,
        status: 'failed', detail: entry.detail, occurredAt: result.updatedAt,
        attempt: entry.autoRetryCount,
      });
      publish();
    }

    // PostgreSQL is authoritative after a reload or a lost HTTP response.
    for (const task of queueTasks) {
      if (['COMPLETED', 'NO_DATA', 'FAILED'].includes(task.status)
        && !batchLogRef.current.some((entry) => entry.index === queueIndices[task.position]
          && entry.jobId === task.jobId)) recordTask(task);
    }
    publish();

    let lastQueueReconcileAt = 0;
    async function runLane(lane: ParallelLaneRecovery): Promise<'done' | 'stopped' | 'error'> {
      let connectionFailures = 0;
      while (!batchStopRef.current) {
        let claimed: Awaited<ReturnType<typeof api.claimBatchTask>>;
        try {
          claimed = await api.claimBatchTask(sessionId, lane.runnerId);
        } catch (reason) {
          // A committed claim may have lost its response; the next claim returns
          // the same active job for this runner rather than assigning a second one.
          if (reason instanceof ApiError && [400, 403, 404, 409, 422].includes(reason.status)) {
            setError(`Worker ${lane.runnerId}: ${reason.message}`);
            return 'error';
          }
          if (++connectionFailures >= 3) setNotice(`Connection to the queue was interrupted: ${reason instanceof Error ? reason.message : String(reason)}`);
          await sleep(Math.min(5_000, 1000 * connectionFailures));
          continue;
        }
        if (connectionFailures) setNotice('');
        connectionFailures = 0;
        if (claimed.type === 'done') return 'done';
        if (claimed.type === 'paused') return 'stopped';
        if (claimed.type === 'worker_disabled') {
          lanes = lanes.filter(item => {
            const number = /^playwright-(\d+)$/.exec(item.runnerId);
            return !number || Number(number[1]) <= claimed.workerCount;
          });
          setNotice('');
          setRunSettings(current => ({...current, workerCount: claimed.workerCount}));
          publish();
          return 'done';
        }
        if (claimed.type === 'pool_updating') {await sleep(1500); continue;}
        if (claimed.type === 'waiting' || claimed.type === 'runner_unavailable') {
          await sleep(1500);
          if (claimed.type === 'waiting' && Date.now() - lastQueueReconcileAt >= 30_000) {
            lastQueueReconcileAt = Date.now();
            try {
              const snapshot = await api.batchQueue(sessionId);
              for (const task of snapshot.tasks) {
                const prior = queueTasks[task.position];
                if (task.status !== prior?.status || task.jobId !== prior?.jobId) {
                  queueTasks[task.position] = task;
                  if (['COMPLETED', 'NO_DATA', 'FAILED'].includes(task.status)) recordTask(task);
                }
              }
              publish();
            } catch { /* Keep waiting; the next poll will reconcile. */ }
          }
          continue;
        }
        upsertTask(claimed.task);
        const index = queueIndices[claimed.task.position];
        const startedAtMs = Date.now();
        try {
          const existing = await subscribeJob(claimed.jobId).catch(() => null)
            || await api.getJob(claimed.jobId);
          rememberJob(existing);
          setJob(existing);
          if (batchStopRef.current) await api.cancelJob(claimed.jobId).catch(() => {});
          const result = await waitForExistingJob(claimed.jobId);
          let settled: BatchQueueTask | null = null;
          while (!settled && !batchStopRef.current) {
            try { settled = await api.settleBatchTask(sessionId, claimed.task.position); }
            catch { await sleep(1500); }
          }
          if (!settled) return 'stopped';
          upsertTask(settled);
          recordTask(settled, result, startedAtMs);
        } catch (reason) {
          setNotice(`Worker ${lane.runnerId} paused at ${plan.scenarios[index].name}: ${reason instanceof Error ? reason.message : String(reason)}`);
          return 'error';
        }
      }
      return 'stopped';
    }

    await Promise.all(lanes.map((lane) => runLane(lane)));
    try {
      const snapshot = await api.batchQueue(sessionId);
      queueTasks = snapshot.tasks;
      for (const task of queueTasks) {
        if (['COMPLETED', 'NO_DATA', 'FAILED'].includes(task.status)
          && !batchLogRef.current.some((entry) => entry.index === queueIndices[task.position]
            && entry.jobId === task.jobId)) recordTask(task);
      }
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : 'Could not refresh final queue state.');
    }
    const finishedAtMs = Date.now();
    activeElapsedMs += Math.max(0, finishedAtMs - activeSegmentStartedAt);
    activeSegmentStartedAt = 0;
    const allFinal = queueTasks.every((task) => ['COMPLETED', 'NO_DATA', 'FAILED'].includes(task.status));
    if (!allFinal) await api.pauseBatchQueue(sessionId).catch((reason) =>
      setNotice(reason instanceof Error ? reason.message : 'Could not pause the unfinished queue.'));
    const finalStatus: BatchStatus = allFinal
      ? queueTasks.some((task) => task.status === 'FAILED') ? 'completed_with_errors' : 'completed'
      : 'stopped';
    const finishedAt = new Date(finishedAtMs).toISOString();
    publish({status: finalStatus, stopRequested: false, finishedAt,
      activeElapsedMs, activeSegmentStartedAt: null});
    setBatchStatus(finalStatus);
    setBatchFinishedAt(finishedAt);
    setBatchActiveElapsedMs(activeElapsedMs);
    setBatchActiveSegmentStartedAt(null);
    batchRunningRef.current = false;
    setBatchRunning(false);
    setReportsTrigger((count) => count + 1);
  }

  async function runParallelScenarioQueue(plan: MatrixPlan, resumeState?: PersistedBatchRecovery) {
    if (batchRunningRef.current && !resumeState) return;
    if (resumeState && (resumeState.version !== 2 || !validParallelLanes(resumeState.lanes, resumeState.queueIndices))) {
      setError('The saved parallel-worker session is invalid. Start a new session.');
      return;
    }
    if (!isReportYear(plan.year) || (resumeState && resumeState.year !== plan.year)) {
      setError('The saved batch belongs to a different calendar year. Start a new session.');
      return;
    }
    const queueIndices = resumeState?.queueIndices || plan.scenarios.map((_, index) => index);
    if (!queueIndices.length || queueIndices.some((index) => !plan.scenarios[index])) {
      setError('The saved State/RTO cases no longer match the office list.');
      return;
    }
    if (resumeState?.queueOfficeKeys?.some((key, position) =>
      key !== matrixOfficeKey(plan.scenarios[queueIndices[position]]))) {
      setError('The State/RTO list changed since this session was saved. Start a new run.');
      return;
    }
    try {await ensureDockerWorkers(resumeState?.lanes?.length || selectedWorkerCount);}
    catch (reason) {setError(reason instanceof Error ? reason.message : 'Could not prepare Docker workers.'); return;}
    let lanes: ParallelLaneRecovery[];
    if (resumeState) {
      lanes = resumeState.lanes!.map((lane) => ({...lane, indices: [...lane.indices],
        retryQueueIndices: [...lane.retryQueueIndices]}));
    } else {
      await refreshRunners();
      const available = runnersRef.current.filter((runner) => (runner.source || 'new') === 'new'
        && runner.status === 'ONLINE' && !runner.currentJobId)
        .sort((left, right) => compareRunnerIds(left.id, right.id));
      if (available.length < selectedWorkerCount) {
        setError(`${selectedWorkerCount} online, idle browser workers are required to start a full run. ${available.length} available now.`);
        return;
      }
      lanes = splitParallelLanes(queueIndices, available.slice(0, selectedWorkerCount).map((runner) => runner.id));
      batchLogRef.current = [];
      setBatchLog([]);
      failedAtIndexRef.current = null;
      setFailedAtIndex(null);
      setParallelCaptchas({});
      persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
    }

    const sessionId = resumeState?.sessionId || crypto.randomUUID();
    const startedAt = resumeState?.startedAt || new Date().toISOString();
    let timings = [...(resumeState?.timings || [])];
    let activeElapsedMs = resumeState?.activeElapsedMs || 0;
    let activeSegmentStartedAt = Date.now();
    batchStopRef.current = false;
    batchLoopStartedRef.current = true;
    batchRunningRef.current = true;
    setBatchRunning(true);
    setBatchStatus('running');
    setBatchStartedAt(startedAt);
    setBatchFinishedAt(null);
    setBatchTimings(timings);
    setBatchActiveElapsedMs(activeElapsedMs);
    setBatchActiveSegmentStartedAt(activeSegmentStartedAt);

    const initial: PersistedBatchRecovery = resumeState
      ? {...resumeState, status: 'running', stopRequested: false, finishedAt: null,
        activeElapsedMs, activeSegmentStartedAt, lanes}
      : {
        version: 2, status: 'running', queueIndices,
        queueOfficeKeys: queueIndices.map((index) => matrixOfficeKey(plan.scenarios[index])),
        nextPosition: 0, currentIndex: null, activeJobId: null,
        stopRequested: false, hadErrors: false, log: [], failedAtIndex: null,
        progress: {done: 0, total: queueIndices.length, current: ''},
        sessionId, year: plan.year, startedAt, finishedAt: null,
        timings: [], currentFilterStartedAt: null, activeElapsedMs, activeSegmentStartedAt, lanes,
      };
    writeBatchRecovery(initial);

    function publish(patch: Partial<PersistedBatchRecovery> = {}) {
      const done = lanes.reduce((sum, lane) => sum + lane.nextPosition, 0);
      const current = lanes.map((lane) => lane.currentIndex === null ? '' :
        lane.runnerId + ': ' + (plan.scenarios[lane.currentIndex]?.name || '')).filter(Boolean).join(' | ');
      const started = lanes.map((lane) => lane.currentFilterStartedAt).filter((time): time is number => time !== null);
      const currentFilterStartedAt = started.length ? Math.min(...started) : null;
      const log = batchLogRef.current;
      const failedAtIndex = log.find((entry) => entry.status === 'error')?.index ?? null;
      const progress = {done, total: queueIndices.length, current};
      const next: PersistedBatchRecovery = {
        ...batchRecoveryRef.current!, nextPosition: done, currentIndex: null, activeJobId: null,
        lanes: lanes.map((lane) => ({...lane, indices: [...lane.indices],
          retryQueueIndices: [...lane.retryQueueIndices]})),
        log, failedAtIndex, hadErrors: failedAtIndex !== null,
        progress, timings, currentFilterStartedAt, ...patch,
      };
      writeBatchRecovery(next);
      setBatchProgress(progress);
      setBatchTimings(timings);
      setCurrentFilterStartedAt(currentFilterStartedAt);
      setFailedAtIndex(failedAtIndex);
    }
    publish();

    function recordResult(index: number, entry: BatchLogEntry, startedAtMs: number, result?: Job,
      trackTiming = true) {
      const completedAtMs = Date.now();
      const previous = batchLogRef.current.find((item) => item.index === index);
      entry.completedAt = new Date(completedAtMs).toISOString();
      entry.durationMs = Math.max(0, completedAtMs - startedAtMs);
      entry.state ||= plan.scenarios[index].filters.states[0];
      entry.rto ||= plan.scenarios[index].filters.rtos[0];
      entry.autoRetryCount ??= previous?.autoRetryCount || 0;
      if (result && entry.status !== 'error') {
        entry.savedAt = result.mainReportSavedAt || entry.completedAt;
        entry.rowCount = result.mainReportSummary?.parsedRows ?? result.reportRowCount ?? 0;
      }
      const nextLog = previous
        ? batchLogRef.current.map((item) => item.index === index ? entry : item)
        : [...batchLogRef.current, entry];
      batchLogRef.current = nextLog;
      setBatchLog(nextLog);
      if (trackTiming) {
        const elapsed = activeElapsedMs + Math.max(0, completedAtMs - activeSegmentStartedAt);
        timings = [...timings.filter((sample) => sample.index !== index), {
          index, durationMs: entry.durationMs,
          completedCount: lanes.reduce((sum, lane) => sum + lane.nextPosition, 0),
          activeElapsedMs: elapsed,
        }];
      }
      if (!(batchStopRef.current && entry.status === 'error')) {
        logRunOutcome({id: result && result.status === 'FAILED' ? 'job:' + result.id
          : 'batch:' + sessionId + ':' + index + ':' + entry.autoRetryCount + ':' + entry.completedAt,
          jobId: result?.status === 'FAILED' ? result.id : undefined, sessionId,
          filters: plan.scenarios[index].filters, name: entry.name,
          status: entry.status === 'error' ? 'failed' : entry.status === 'empty' ? 'no_data' : 'completed',
          detail: entry.detail, occurredAt: result?.updatedAt || entry.completedAt, attempt: entry.autoRetryCount});
      }
      publish();
    }

    async function findCreatedJob(lane: ParallelLaneRecovery, scenario: Scenario, retryOfJobId?: string): Promise<Job | null> {
      const jobs = await api.jobs();
      return jobs.find((candidate) => candidate.sessionId === sessionId
        && candidate.runnerId === lane.runnerId && candidate.scenarioName === scenario.name
        && (candidate.retryOfJobId || null) === (retryOfJobId || null)
        && candidate.filters.states[0] === scenario.filters.states[0]
        && candidate.filters.rtos[0] === scenario.filters.rtos[0]) || null;
    }

    async function waitForLaneRunner(runnerId: string): Promise<boolean> {
      while (!batchStopRef.current) {
        await refreshRunners();
        const runner = runnersRef.current.find((item) => item.id === runnerId);
        if (runner?.status === 'ONLINE' && !runner.currentJobId) return true;
        await sleep(1000);
      }
      return false;
    }

    async function executeLaneCase(lane: ParallelLaneRecovery, index: number, retryOfJobId?: string): Promise<Job | null> {
      const scenario = plan.scenarios[index];
      const needsReconciliation = lane.currentIndex === index && !lane.activeJobId;
      lane.currentIndex = index;
      publish();
      let existing: Job | null = null;
      if (lane.activeJobId) existing = await api.getJob(lane.activeJobId);
      else if (needsReconciliation) existing = await findCreatedJob(lane, scenario, retryOfJobId);
      if (existing?.status === 'CANCELLED' && !batchStopRef.current) {
        retryOfJobId = existing.id;
        existing = null;
        lane.activeJobId = null;
        publish();
      }
      if (existing) {
        lane.activeJobId = existing.id;
        lane.lastJobId = existing.id;
        rememberJob(existing);
        publish();
        return waitForExistingJob(existing.id);
      }

      while (!batchStopRef.current) {
        if (!(await waitForLaneRunner(lane.runnerId))) return null;
        if (batchStopRef.current) return null;
        let created: Job;
        try {
          created = await api.createJob(lane.runnerId, scenario.filters, scenario.name, sessionId, retryOfJobId);
        } catch (reason) {
          const message = reason instanceof Error ? reason.message : String(reason || '');
          // The server may have committed the job before a network response was lost.
          let recovered: Job | null = null;
          for (let attempt = 0; attempt < 3 && !recovered; attempt += 1) {
            recovered = await findCreatedJob(lane, scenario, retryOfJobId).catch(() => null);
            if (!recovered && attempt < 2) await sleep(1000);
          }
          if (recovered) created = recovered;
          else if (/Runner is already processing|Runner was assigned another job|Runner is reconnecting|Runner is offline/i.test(message)) {
            await sleep(1000);
            continue;
          } else {
            throw reason;
          }
        }
        lane.activeJobId = created.id;
        lane.lastJobId = created.id;
        rememberJob(created);
        setJob(created);
        publish();
        if (batchStopRef.current) {
          await api.cancelJob(created.id).catch(() => {});
          return null;
        }
        await subscribeJob(created.id).catch(() => {});
        return waitForExistingJob(created.id);
      }
      return null;
    }

    async function retryPending(lane: ParallelLaneRecovery): Promise<boolean> {
      while (lane.retryQueueIndices.length) {
        if (batchStopRef.current) return false;
        const index = lane.retryQueueIndices[0];
        const failed = batchLogRef.current.find((entry) => entry.index === index && entry.status === 'error');
        if (!failed || (failed.autoRetryCount || 0) >= MAX_AUTO_RETRY_ATTEMPTS) {
          lane.retryQueueIndices.shift();
          lane.retryIndex = null;
          lane.currentIndex = null;
          lane.activeJobId = null;
          publish();
          continue;
        }
        lane.retryIndex = index;
        lane.currentFilterStartedAt ||= Date.now();
        publish();
        let result: Job | null;
        try {
          result = await executeLaneCase(lane, index, failed.jobId);
        } catch (reason) {
          const message = reason instanceof Error ? reason.message : String(reason || '');
          if (!(reason instanceof ApiError) || reason.status >= 500) {
            setNotice('Worker ' + lane.runnerId + ' paused at a retry: ' + message);
            return false;
          }
          lane.retryQueueIndices.shift();
          lane.retryIndex = null;
          lane.currentIndex = null;
          lane.activeJobId = null;
          recordResult(index, {...failed, status: 'error', autoRetryCount: (failed.autoRetryCount || 0) + 1,
            detail: 'Automatic retry failed: ' + message}, lane.currentFilterStartedAt || Date.now(), undefined, false);
          lane.currentFilterStartedAt = null;
          publish();
          continue;
        }
        if (!result || result.status === 'CANCELLED') return false;
        const started = lane.currentFilterStartedAt || Date.now();
        lane.retryQueueIndices.shift();
        lane.retryIndex = null;
        lane.currentIndex = null;
        lane.activeJobId = null;
        lane.currentFilterStartedAt = null;
        const attempt = (failed.autoRetryCount || 0) + 1;
        if (result.status === 'COMPLETED') {
          recordResult(index, {...failed, status: 'ok', autoRetryCount: attempt, jobId: result.id,
            excelFileName: result.excelFileName,
            detail: 'Recovered on automatic retry. Manufacturer data saved to the main table.'}, started, result, false);
        } else if (result.status === 'NO_DATA') {
          recordResult(index, {...failed, status: 'empty', autoRetryCount: attempt, jobId: result.id,
            noDataFileName: result.noDataFileName,
            detail: 'Automatic retry confirmed no records. Saved to SQL.'}, started, result, false);
        } else {
          recordResult(index, {...failed, status: 'error', autoRetryCount: attempt, jobId: result.id,
            detail: 'Automatic retry failed: ' + (result.error || result.status)}, started, result, false);
        }
      }
      return true;
    }

    async function checkpoint(lane: ParallelLaneRecovery): Promise<boolean> {
      if (lane.lastRetryCheckpoint >= lane.nextPosition) return true;
      const group = lane.indices.slice(lane.lastRetryCheckpoint, lane.nextPosition);
      lane.lastRetryCheckpoint = lane.nextPosition;
      lane.retryQueueIndices = [...new Set([...lane.retryQueueIndices, ...group.filter((index) =>
        batchLogRef.current.some((entry) => entry.index === index && entry.status === 'error'
          && (entry.autoRetryCount || 0) < MAX_AUTO_RETRY_ATTEMPTS))])];
      publish();
      return retryPending(lane);
    }

    async function runLane(lane: ParallelLaneRecovery): Promise<'completed' | 'stopped' | 'error'> {
      if (!(await retryPending(lane))) return 'stopped';
      if (lane.nextPosition > lane.lastRetryCheckpoint
        && (lane.nextPosition % AUTO_RETRY_CHECKPOINT_SIZE === 0 || lane.nextPosition === lane.indices.length)
        && !(await checkpoint(lane))) return 'stopped';
      for (let position = lane.nextPosition; position < lane.indices.length; position += 1) {
        if (batchStopRef.current) return 'stopped';
        const index = lane.indices[position];
        const scenario = plan.scenarios[index];
        const started = lane.currentFilterStartedAt || Date.now();
        lane.currentFilterStartedAt = started;
        publish();
        let result: Job | null;
        try {
          result = await executeLaneCase(lane, index);
        } catch (reason) {
          if (batchStopRef.current) return 'stopped';
          const message = reason instanceof Error ? reason.message : String(reason || '');
          if (!(reason instanceof ApiError) || reason.status >= 500) {
            setNotice('Worker ' + lane.runnerId + ' paused at ' + scenario.name + ': ' + message);
            return 'stopped';
          }
          lane.nextPosition = position + 1;
          lane.currentIndex = null;
          lane.activeJobId = null;
          lane.currentFilterStartedAt = null;
          recordResult(index, {index, name: scenario.name, status: 'error',
            detail: message + ' It will be retried at the next checkpoint.'}, started);
          if (lane.nextPosition % AUTO_RETRY_CHECKPOINT_SIZE === 0 && !(await checkpoint(lane))) return 'stopped';
          continue;
        }
        if (!result || result.status === 'CANCELLED') return 'stopped';
        lane.nextPosition = position + 1;
        lane.currentIndex = null;
        lane.activeJobId = null;
        lane.lastJobId = result.id;
        lane.currentFilterStartedAt = null;
        if (result.status === 'COMPLETED') {
          recordResult(index, {index, name: scenario.name, status: 'ok', jobId: result.id,
            excelFileName: result.excelFileName,
            detail: 'Saved ' + (result.mainReportSummary?.parsedRows ?? result.reportRowCount ?? 0)
              + ' manufacturer rows to the main table.'}, started, result);
        } else if (result.status === 'NO_DATA') {
          recordResult(index, {index, name: scenario.name, status: 'empty', jobId: result.id,
            noDataFileName: result.noDataFileName,
            detail: 'No record found. State, RTO and collection timestamp saved to SQL.'}, started, result);
        } else {
          recordResult(index, {index, name: scenario.name, status: 'error', jobId: result.id,
            detail: (result.error || 'Job ended with status ' + result.status)
              + ' It will be retried at the next checkpoint.'}, started, result);
        }
        if (batchStopRef.current) return 'stopped';
        if (lane.nextPosition % AUTO_RETRY_CHECKPOINT_SIZE === 0 && !(await checkpoint(lane))) return 'stopped';
      }
      if (!(await checkpoint(lane))) return 'stopped';
      return 'completed';
    }

    const results = await Promise.all(lanes.map((lane) => runLane(lane).catch((reason) => {
      setError(reason instanceof Error ? reason.message : 'A worker stopped unexpectedly.');
      return 'error' as const;
    })));
    const finishedAtMs = Date.now();
    activeElapsedMs += Math.max(0, finishedAtMs - activeSegmentStartedAt);
    activeSegmentStartedAt = 0;
    const finalStatus: BatchStatus = results.includes('error') ? 'error'
      : results.includes('stopped') || batchStopRef.current ? 'stopped'
        : batchLogRef.current.some((entry) => entry.status === 'error') ? 'completed_with_errors' : 'completed';
    const finishedAt = new Date(finishedAtMs).toISOString();
    publish({status: finalStatus, stopRequested: false, finishedAt,
      activeElapsedMs, activeSegmentStartedAt: null});
    setBatchStatus(finalStatus);
    setBatchFinishedAt(finishedAt);
    setBatchActiveElapsedMs(activeElapsedMs);
    setBatchActiveSegmentStartedAt(null);
    batchRunningRef.current = false;
    setBatchRunning(false);
    setReportsTrigger((count) => count + 1);
  }

  async function stopBatch() {
    batchStopRef.current = true;
    updateBatchRecovery({ stopRequested: true });
    if (batchRecoveryRef.current?.version === 2 || batchRecoveryRef.current?.version === 3) {
      if (batchRecoveryRef.current.version === 3) {
        try { await api.pauseBatchQueue(batchRecoveryRef.current.sessionId); }
        catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not pause the shared queue.'); }
      }
      const activeIds = [...new Set(batchRecoveryRef.current.lanes?.map((lane) => lane.activeJobId)
        .filter((id): id is string => Boolean(id)) || [])];
      await Promise.allSettled(activeIds.map(async (id) => {
        try {
          const cancelled = await api.cancelJob(id);
          rememberJob(cancelled);
          setParallelCaptchas((current) => {const next = {...current}; delete next[id]; return next;});
          resolveTerminal(cancelled);
        } catch (reason) {
          const latest = await api.getJob(id).catch(() => null);
          if (latest && ['COMPLETED', 'NO_DATA', 'FAILED', 'CANCELLED'].includes(latest.status)) {
            resolveTerminal(latest);
          } else {
            setError(reason instanceof Error ? reason.message : 'Could not stop a worker job.');
          }
        }
      }));
      await refreshRunners();
      return;
    }
    const current = latestJobRef.current;
    const activeJobId = batchRecoveryRef.current?.activeJobId
      || (current && !["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(current.status) ? current.id : null);
    if (!activeJobId) return;
    try {
      const cancelled = await api.cancelJob(activeJobId);
      latestJobRef.current = cancelled;
      setJob(cancelled);
      persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
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

  async function continueStoppedBatch() {
    const recovery = batchRecoveryRef.current;
    if (!recovery || recovery.status !== "stopped") return;
    if (batchRunningRef.current) return;
    const plan = matrixPlan ? updateMatrixYear(matrixPlan, recovery.year) : null;
    if (!plan || !isReportYear(recovery.year)) {
      setError("The saved batch belongs to a different report year. Start a new session with the current office list.");
      return;
    }
    const restoredSettings = {year: recovery.year, workerCount: recovery.version === 3
      ? selectedWorkerCount : recovery.lanes?.length || 1};
    setRunSettings(restoredSettings);
    persistentState.setItem(RUN_SETTINGS_STORAGE_KEY, JSON.stringify(restoredSettings));
    setMatrixPlan(plan);
    persistentState.setItem(MATRIX_STORAGE_KEY, JSON.stringify(plan));
    if (recovery.progress.total !== recovery.queueIndices.length
      || recovery.queueIndices.some((index) => !plan.scenarios[index])) {
      setError("The saved batch no longer matches the available offices. Start a new session with the current office list.");
      return;
    }
    if (recovery.queueOfficeKeys
      ? recovery.queueOfficeKeys.length !== recovery.queueIndices.length
        || recovery.queueOfficeKeys.some((key, position) =>
          key !== matrixOfficeKey(plan.scenarios[recovery.queueIndices[position]]))
      : recovery.log.some((entry) => entry.state && entry.rto
        && (!plan.scenarios[entry.index]
          || matrixOfficeKey(plan.scenarios[entry.index]) !== `${entry.state.trim().toLocaleLowerCase()}\u0000${entry.rto.trim().toLocaleLowerCase()}`))) {
      setError("The State/RTO list changed since this session was saved. Restart all offices to avoid assigning results to the wrong RTO.");
      return;
    }
    if (recovery.version === 2) {
      await runParallelScenarioQueue(plan, {...recovery, stopRequested: false});
      return;
    }
    if (recovery.version === 3) {
      await runSharedScenarioQueue(plan, {...recovery, stopRequested: false});
      return;
    }
    await runScenarioQueue(plan.scenarios, {
      clearLog: false,
      resumeState: { ...recovery, stopRequested: false, activeJobId: null, activeSegmentStartedAt: null },
      planOverride: plan,
    });
  }

  async function continueUncoveredReports(context: CoverageContext) {
    if (batchRunningRef.current || creating || (latestJobRef.current && !["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(latestJobRef.current.status))) {
      throw new Error('Stop the current report before continuing missing data.');
    }
    if (!isReportYear(context.year)) throw new Error('Choose a supported calendar year.');
    const loadedPlan = matrixPlan || await prepareMatrix();
    if (!loadedPlan) throw new Error('Could not load the State–RTO office list. Check the browser runner connection.');
    const plan = updateMatrixYear(loadedPlan, context.year);
    setRunSettings(current => ({...current, year: context.year}));
    persistentState.setItem(RUN_SETTINGS_STORAGE_KEY, JSON.stringify({...runSettings, year: context.year}));
    persistentState.setItem(MATRIX_STORAGE_KEY, JSON.stringify(plan));
    setMatrixPlan(plan);
    const coverage = await loadReportCoverage(context, plan);
    const missing = uncoveredScenarios(plan, coverage);
    if (!missing.indices.length) {setNotice('All selected office reports are already covered.'); return;}
    // Recheck after the API read so a second click cannot replace an active queue.
    if (batchRunningRef.current) throw new Error('A report session is already running.');
    await runScenarioQueue(missing.scenarios, {selectedIndices: missing.indices, planOverride: plan});
  }

  async function restartStoppedBatch() {
    const recovery = batchRecoveryRef.current;
    if (!recovery || recovery.status !== "stopped") return;
    // A restart means every office in a freshly fetched VAHAN matrix, not
    // merely the subset or ordering retained by the stopped session.
    await runAllScenarios();
  }

  async function runAllScenarios() {
    if (batchRunningRef.current) return;
    const freshPlan = await prepareMatrix();
    if (!freshPlan) return;
    await runSharedScenarioQueue(freshPlan);
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
    const recovery = batchRecoveryRef.current;
    if (recovery?.status === "stopped") {
      setError("Continue the saved session to process queued retries before starting another run.");
      return;
    }
    const failedIndices = batchLogRef.current.filter((entry) => entry.status === "error")
      .map((entry) => entry.index);
    if (!failedIndices.length) return;
    if (!matrixPlan || !recovery || recovery.year !== matrixPlan.year
      || failedIndices.some((index) => !matrixPlan.scenarios[index])) {
      setError("The original failed cases could not be restored. Review the saved session before retrying.");
      return;
    }
    await runScenarioQueue(failedIndices.map((index) => matrixPlan.scenarios[index]), {
      selectedIndices: failedIndices,
      startIndex: failedIndices[0],
      clearLog: false,
      planOverride: matrixPlan,
      sessionIdOverride: recovery.sessionId,
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

    if (recovery.version === 2) {
      void runParallelScenarioQueue(matrixPlan!, recovery);
      return;
    }
    if (recovery.version === 3) {
      void runSharedScenarioQueue(matrixPlan!, recovery);
      return;
    }
    const activeJobId = recovery.activeJobId || persistentState.getItem(ACTIVE_JOB_STORAGE_KEY);
    if (activeJobId) persistentState.setItem(ACTIVE_JOB_STORAGE_KEY, activeJobId);
    void runScenarioQueue(scenarios, {
      clearLog: false,
      resumeState: { ...recovery, activeJobId },
    });
  }, [jobRestoreReady, scenarios]);

  async function cancelJob(jobId = job?.id) {
    if (!jobId) return;
    try {
      const cancelled = await api.cancelJob(jobId);
      setJob(cancelled);
      rememberJob(cancelled);
      resolveTerminal(cancelled);
      if (persistentState.getItem(ACTIVE_JOB_STORAGE_KEY) === jobId) persistentState.removeItem(ACTIVE_JOB_STORAGE_KEY);
      setCaptcha((current) => current?.jobId === jobId ? null : current);
      setParallelCaptchas((current) => {const next = {...current}; delete next[jobId]; return next;});
      await refreshRunners();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not cancel the job.");
    }
  }

  const busy = creating || batchRunning || makerUpdateRunning || poolChanging || Boolean(job && !["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(job.status));
  const parallelLanes = batchRecoveryRef.current?.version === 2 || batchRecoveryRef.current?.version === 3
    ? batchRecoveryRef.current.lanes || [] : [];
  const parallelMode = parallelLanes.length >= 1;
  const displayParallelLanes = parallelMode
    ? [...parallelLanes].sort((left, right) => compareRunnerIds(left.runnerId, right.runnerId)) : [];
  const parallelJobs = displayParallelLanes.map((lane) => jobSnapshots[lane.activeJobId || lane.lastJobId || ''] || null);
  const captchaItems: CaptchaInboxItem[] = parallelMode
    ? displayParallelLanes.flatMap((lane, index) => {
      const challenge = lane.activeJobId ? parallelCaptchas[lane.activeJobId] : null;
      if (!challenge) return [];
      const activeJob = jobSnapshots[challenge.jobId];
      return [{runnerId: lane.runnerId, workerLabel: `Worker ${index + 1}`,
        office: activeJob?.scenarioName || (lane.currentIndex === null ? '' : scenarios[lane.currentIndex]?.name || ''),
        challenge}];
    })
    : captcha ? [{runnerId: job?.runnerId || 'current-report', workerLabel: 'Current report',
      office: job?.scenarioName || '', challenge: captcha}] : [];
  function openCaptchaForWorker(runnerId: string) {
    const item = captchaItems.find((candidate) => candidate.runnerId === runnerId);
    if (!item) return;
    setSelectedCaptchaJobId(item.challenge.jobId);
    window.requestAnimationFrame(() => document.getElementById('captcha-assistance')?.scrollIntoView({
      behavior: 'smooth', block: 'center',
    }));
  }

  return (
    <div className="app-shell" data-view={view}>
      <header className="site-header">
        <a className="brand-lockup" href="#configure" aria-label="VAHAN Report Automation">
          <span className="brand-symbol" aria-hidden="true">V</span>
          <span className="brand-copy"><strong>VAHAN</strong><small>REPORT AUTOMATION</small></span>
        </a>
        <nav className="main-nav" aria-label="Main navigation">
          <a className={activeSection === "configure" ? "active" : undefined} aria-current={activeSection === "configure" ? "page" : undefined} href="#configure">Create Report</a>
          <a className={activeSection === "reports" ? "active" : undefined} aria-current={activeSection === "reports" ? "page" : undefined} href="#reports">Exported Reports</a>
          <a className={activeSection === "settings" ? "active" : undefined} aria-current={activeSection === "settings" ? "page" : undefined} href="#settings">Settings</a>
          <a className={activeSection === "filters" ? "active" : undefined} aria-current={activeSection === "filters" ? "page" : undefined} href="#filters">Filters</a>
        </nav>
        <div className="header-actions">
          <ConnectionBanner backend={connection} runners={runners.length} />
          <button className="logout-button" type="button" onClick={() => void flushPersistentState().then(() => api.logout()).catch(reason => setError(reason.message))}>Log out</button>
        </div>
      </header>

      <div className="app-layout">
        <div className="app-main">
          <StateSyncStatus />
          {view === 'filters' ? <FilterProfiles profiles={filterProfiles} runners={runners} year={selectedYear} busy={busy||matrixLoading}
            onSaved={refreshFilterProfiles} onSelect={(id,plan)=>{
              selectFilterProfile(id);if(batchStatus!=='stopped'){setMatrixPlan(plan);persistentState.setItem(MATRIX_STORAGE_KEY,JSON.stringify(plan));}
              window.location.hash='configure';
            }} /> : view === "settings" ? (
            <main className="page-content settings-page" id="settings">
              <div className="section-intro settings-intro">
                <div><h2>Settings</h2><p>Manage accounts and VAHAN interface checks.</p></div>
              </div>
              <UserManagement />

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
              {error && <div className="global-error" role="alert">{error}<button onClick={() => setError("")}>×</button></div>}
              {notice && <div className="global-notice" role="status">{notice}<button onClick={() => setNotice("")}>×</button></div>}
              <AnnualReports initialYear={selectedYear} refreshTrigger={reportsTrigger} coverageControls={{plan: matrixPlan, busy,
                running: batchRunning, loadingMatrix: matrixLoading, status: batchStatus, current: batchProgress.current,
                onContinue: continueUncoveredReports, onStop: stopBatch}} />
            </main>
          ) : (
              <main className="page-content report-page-content">
                <div className="section-intro report-intro" id="configure">
                  <div className="report-intro-copy">
                    <p className="report-eyebrow"><span aria-hidden="true" />REPORTING WORKSPACE</p>
                    <h2>Create Report</h2>
                    <p>Run the VAHAN Maker report across State and RTO offices.</p>
                  </div>
                  <div className="report-period-summary">
                    <span className="report-period-icon" aria-hidden="true">FY</span>
                    <span><small>REPORTING PERIOD</small><strong>Calendar year {selectedYear}</strong></span>
                  </div>
                </div>

                {error && <div className="global-error" role="alert">{error}<button onClick={() => setError("")}>×</button></div>}
                {notice && <div className="global-notice" role="status">{notice}<button onClick={() => setNotice("")}>×</button></div>}

                <RunControls workerCount={selectedWorkerCount} disabled={busy || matrixLoading}
                  applying={poolChanging} runningContainers={poolRunningCount}
                  profileId={selectedProfileId} profiles={filterProfiles} onProfile={selectFilterProfile}
                  onLoadCases={()=>void prepareMatrix()} savedRun={batchStatus==='stopped'}
                  onWorkers={workerCount => configureRun({workerCount})} />
                {batchStatus==='stopped'&&matrixPlan&&(matrixPlan.profileId||'')!==selectedProfileId&&<p className="profile-saved-run-note">Continue keeps the saved run's filters. Restart uses the selected profile.</p>}

                <WorkerDashboard
                  workerCount={selectedWorkerCount}
                  runners={runners}
                  connection={connection}
                  scenarios={scenarios}
                  lanes={displayParallelLanes}
                  jobs={jobSnapshots}
                  log={batchLog}
                  progress={batchProgress}
                  status={batchStatus}
                  running={batchRunning}
                  loading={matrixLoading}
                  disabled={busy}
                  legacySession={batchRecoveryRef.current?.version === 1}
                  sharedQueue={batchRecoveryRef.current?.version !== 1 && batchRecoveryRef.current?.version !== 2}
                  timings={batchTimings}
                  currentFilterStartedAt={currentFilterStartedAt}
                  activeElapsedMs={batchActiveElapsedMs}
                  activeSegmentStartedAt={batchActiveSegmentStartedAt}
                  captchaJobIds={Object.keys(parallelCaptchas)}
                  onOpenCaptcha={openCaptchaForWorker}
                  onRunAll={runAllScenarios}
                  onContinue={continueStoppedBatch}
                  onRestart={restartStoppedBatch}
                  onStop={stopBatch}
                />

                {captchaItems.length > 0 && <CaptchaInbox items={captchaItems} selectedJobId={selectedCaptchaJobId} taskRunning={busy}
                  onSelect={setSelectedCaptchaJobId} submitting={submittingCaptcha} refreshing={refreshingCaptcha}
                  onSubmit={submitCaptcha} onRefresh={refreshCaptcha} />}

                <div className="workspace workspace-full">
                  <div className="left-column">
                    <MatrixRunner
                      plan={matrixPlan}
                      loading={matrixLoading}
                      loadingMessage={matrixProgress}
                      scenarios={scenarios}
                      onRunFrom={runFromScenarioIndex}
                      onRunOne={runSingleScenarioIndex}
                      onRetryFailed={retryFailedScenario}
                      running={batchRunning}
                      progress={batchProgress}
                      batchStatus={batchStatus}
                      log={batchLog}
                      failedAtIndex={failedAtIndex}
                      pendingRetries={parallelMode
                        ? parallelLanes.reduce((sum, lane) => sum + lane.retryQueueIndices.length, 0)
                        : batchRecoveryRef.current?.retryQueueIndices?.length || 0}
                      disabled={busy}
                    />
                    <section className="maker-update-panel" aria-label="Incremental Maker update">
                      <div className="maker-update-heading">
                        <div><h3>Update Maker</h3><p>Quét Maker toàn State; chỉ dò và cập nhật RTO của Maker có số liệu thay đổi.</p></div>
                        <div className="maker-update-actions">
                          <button type="button" onClick={() => void startMakerUpdate()} disabled={busy||Boolean(selectedProfileId)}
                            title={selectedProfileId?'Incremental Maker update uses the standard profile.':'Update changed Makers'}>Update</button>
                          {makerUpdateRunning && <button type="button" onClick={() => void stopMakerUpdate()}>Dừng</button>}
                        </div>
                      </div>
                      {makerUpdateProgress && <p className="maker-update-progress" role="status">{makerUpdateProgress}</p>}
                      {makerUpdate && <div className="maker-update-summary">
                        <span>Trạng thái: {makerUpdate.status}</span>
                        <span>Maker thay đổi: {makerUpdate.changedMakers.length}</span>
                        <span>Việc hoàn tất: {makerUpdate.tasks?.filter((task) => task.status === "DONE").length || 0}/{makerUpdate.tasks?.length || 0}</span>
                        {makerUpdate.changedMakers.map((maker) => {
                          const location = makerUpdate.locations?.find((item) => item.maker === maker);
                          return <span key={maker}>{maker}: {location?.states || 0} State, {location?.rtos || 0} RTO</span>;
                        })}
                      </div>}
                    </section>
                  </div>
                </div>

                {(parallelJobs.some(Boolean) || job || runErrors.length > 0) && <section className="activity-section" id="activity" aria-labelledby="activity-title">
                  <div className="activity-section-header">
                    <div><p className="worker-dashboard-eyebrow">LIVE JOBS</p><h2 id="activity-title">Worker activity</h2>
                      <p>Current stage and result for each browser worker.</p></div>
                    <CopyRunErrors entries={runErrors} />
                  </div>
                  {parallelMode ? <div className="activity-grid">
                    {parallelJobs.map((activeJob, index) => activeJob && <div className="activity-worker" key={displayParallelLanes[index].runnerId}>
                      <div className="activity-worker-label"><strong>Worker {index + 1}</strong><span>{displayParallelLanes[index].runnerId}</span></div>
                      <JobStatus job={activeJob} onCancel={() => void stopBatch()} />
                    </div>)}
                  </div> : job ? <div className="activity-grid" data-single="true"><JobStatus job={job} onCancel={() => void cancelJob()} /></div>
                    : <div className="activity-empty" data-running={batchRunning}>{batchRunning
                      ? "Waiting for the next worker update…"
                      : "Job activity will appear here when a session starts."}</div>}
                </section>}

              </main>
          )}
        </div>
      </div>
    </div>
  );
}
