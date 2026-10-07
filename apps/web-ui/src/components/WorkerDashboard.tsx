import { useEffect, useState } from "react";

import type { ConnectionState, Job, JobStatus, Runner, Scenario } from "../contracts";
import { estimateBatchTiming, type FilterTiming } from "../batch-timing";
import { TARGET_WORKER_COUNT, compareRunnerIds, plannedWorkerRange } from "../worker-settings";

export interface WorkerLane {
  runnerId: string;
  indices: number[];
  nextPosition: number;
  currentIndex: number | null;
  activeJobId: string | null;
  retryQueueIndices: number[];
  retryIndex: number | null;
  currentFilterStartedAt: number | null;
}

interface ResultEntry {
  index: number;
  status: "ok" | "empty" | "error";
  completedAt?: string;
  rowCount?: number;
  detail?: string;
}

type BatchStatus = "idle" | "running" | "completed" | "completed_with_errors" | "stopped" | "error";

interface Props {
  workerCount?: number;
  runners: Runner[];
  connection: ConnectionState;
  scenarios: Scenario[];
  lanes: WorkerLane[];
  jobs: Record<string, Job>;
  log: ResultEntry[];
  progress: { done: number; total: number };
  status: BatchStatus;
  running: boolean;
  loading: boolean;
  disabled: boolean;
  legacySession: boolean;
  sharedQueue: boolean;
  timings: FilterTiming[];
  currentFilterStartedAt: number | null;
  activeElapsedMs: number;
  activeSegmentStartedAt: number | null;
  captchaJobIds: string[];
  onOpenCaptcha: (runnerId: string) => void;
  onRunAll: () => void;
  onContinue: () => void;
  onRestart: () => void;
  onStop: () => void;
}

const jobLabels: Record<JobStatus, string> = {
  QUEUED: "Queued",
  ASSIGNED: "Assigned to browser",
  OPENING_VAHAN: "Opening VAHAN",
  CAPTURING_CAPTCHA: "Loading CAPTCHA",
  FILLING_FILTERS: "Applying filters",
  WAITING_CAPTCHA: "Waiting for CAPTCHA",
  SUBMITTING: "Submitting report",
  WAITING_RESULT: "Waiting for result",
  COMPLETED: "Completed",
  NO_DATA: "No data",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

const statusLabels: Record<BatchStatus, string> = {
  idle: "Ready",
  running: "Running",
  completed: "Completed",
  completed_with_errors: "Completed with errors",
  stopped: "Stopped",
  error: "Error",
};

function formatDuration(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  const remainingSeconds = seconds % 60;
  return hours
    ? hours + "h " + String(minutes).padStart(2, "0") + "m"
    : minutes + "m " + String(remainingSeconds).padStart(2, "0") + "s";
}

function latestResult(entries: ResultEntry[]): ResultEntry | null {
  return entries.reduce<ResultEntry | null>((latest, entry) =>
    !latest || (entry.completedAt || "") >= (latest.completedAt || "") ? entry : latest, null);
}

function resultLabel(entry: ResultEntry | null): string {
  if (!entry) return "No completed case yet";
  if (entry.status === "ok") return entry.rowCount == null
    ? "Saved to SQL" : "Saved " + entry.rowCount.toLocaleString("en-GB") + " rows to SQL";
  if (entry.status === "empty") return "No data · completed";
  return "Failed · queued for retry or review";
}

export function WorkerDashboard(props: Props) {
  const [clockNow, setClockNow] = useState(Date.now());
  useEffect(() => {
    if (!props.running) return;
    setClockNow(Date.now());
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [props.running]);

  const availableRunners = props.runners
    .filter((runner) => runner.source === "new")
    .sort((left, right) => compareRunnerIds(left.id, right.id));
  const hasParallelSession = props.lanes.length >= 1;
  const selectedCount = props.workerCount || TARGET_WORKER_COUNT;
  const activeWorkerCount = hasParallelSession ? props.lanes.length : props.legacySession ? 1 : selectedCount;
  const savedSmallerRun = hasParallelSession && activeWorkerCount !== selectedCount;
  const workerCards = Array.from({length: activeWorkerCount}, (_, workerIndex) => {
    const lane = props.lanes[workerIndex];
    const runnerId = lane?.runnerId || availableRunners[workerIndex]?.id || null;
    const runner = props.runners.find((item) => item.id === runnerId) || null;
    const planned = plannedWorkerRange(props.scenarios.length, activeWorkerCount, workerIndex);
    const from = lane?.indices[0] ?? planned.start;
    const to = lane?.indices.at(-1) ?? planned.end;
    const assigned = lane?.indices.length ?? planned.count;
    const completed = lane ? Math.min(lane.nextPosition, assigned) : 0;
    const results = lane ? props.log.filter((entry) => props.sharedQueue
      ? lane.indices.includes(entry.index) : entry.index >= from && entry.index <= to) : [];
    const withData = results.filter((entry) => entry.status === "ok").length;
    const noData = results.filter((entry) => entry.status === "empty").length;
    const errors = results.filter((entry) => entry.status === "error").length;
    const last = latestResult(results);
    const currentIndex = lane?.retryIndex ?? lane?.currentIndex ?? null;
    const currentCase = currentIndex === null ? null : props.scenarios[currentIndex];
    const activeJob = lane?.activeJobId ? props.jobs[lane.activeJobId] : null;
    const captchaWaiting = Boolean(lane?.activeJobId && props.captchaJobIds.includes(lane.activeJobId));
    const online = Boolean(props.connection === "connected" && runner && runner.status !== "RECONNECTING");
    const connectionLabel = !runner || props.connection !== "connected" ? "Offline" :
      runner.status === "RECONNECTING" ? "Reconnecting" : runner.status === "BUSY" ? "Busy" : "Online";
    const taskLabel = captchaWaiting ? "CAPTCHA required" :
      activeJob ? jobLabels[activeJob.status] :
      props.running && lane && !online ? "Waiting for worker" :
      props.running && lane && (props.sharedQueue || completed < assigned) ? "Ready for next case" :
      lane && completed === assigned && assigned > 0 ? "Assigned cases finished" :
      props.status === "stopped" && lane ? "Paused" : lane ? "Waiting for run" : "Next-run preview";
    const taskTone = captchaWaiting ? "attention" :
      activeJob?.status === "FAILED" ? "error" :
      props.running && lane && (props.sharedQueue || completed < assigned) ? "running" : "neutral";
    const nextIndex = props.sharedQueue ? null : lane?.indices[lane.nextPosition] ?? null;
    const nextCase = nextIndex === null ? null : props.scenarios[nextIndex];
    return {
      workerIndex, lane, runner, runnerId, from, to, assigned, completed, withData, noData, errors,
      last, currentIndex, currentCase, activeJob, captchaWaiting, online, connectionLabel,
      taskLabel, taskTone, nextIndex, nextCase,
    };
  });
  const onlineCount = workerCards.filter(card => card.online).length;
  const total = props.progress.total || props.scenarios.length;
  const done = props.progress.total ? Math.min(props.progress.done, total) : 0;
  const progressPercent = total ? Math.round(done / total * 100) : 0;
  const withData = props.log.filter((entry) => entry.status === "ok").length;
  const noData = props.log.filter((entry) => entry.status === "empty").length;
  const errors = props.log.filter((entry) => entry.status === "error").length;
  const pendingRetries = hasParallelSession
    ? props.lanes.reduce((sum, lane) => sum + lane.retryQueueIndices.length, 0) : 0;
  const estimate = estimateBatchTiming(
    props.timings, total, done, props.currentFilterStartedAt, clockNow,
    props.activeElapsedMs, props.activeSegmentStartedAt,
  );
  const casesPerMinute = estimate.reportsPerHour !== null ? estimate.reportsPerHour / 60
    : ['completed', 'completed_with_errors'].includes(props.status) && estimate.activeElapsedMs > 0
      ? done * 60_000 / estimate.activeElapsedMs : null;
  return <section className="worker-dashboard" data-workers={activeWorkerCount} aria-labelledby="worker-dashboard-title">
    <div className="worker-dashboard-header">
      <div>
        <p className="worker-dashboard-eyebrow">WORKERS</p>
        <h2 id="worker-dashboard-title">{activeWorkerCount}-worker crawl monitor</h2>
        <p>{savedSmallerRun
          ? props.sharedQueue ? `Saved progress used ${activeWorkerCount} workers. Continue or restart with ${selectedCount} selected workers.`
            : `This saved run keeps its ${activeWorkerCount}-worker assignment. New full runs use ${selectedCount} workers.`
          : props.sharedQueue
            ? `One shared queue · ${activeWorkerCount} workers · one case per worker.`
            : `Each worker processes its assigned cases in order.`}</p>
      </div>
      <div className="worker-dashboard-actions">
        <span className="worker-dashboard-online" data-online={onlineCount === activeWorkerCount ? "all" : "partial"}>
          <i aria-hidden="true" />{onlineCount}/{activeWorkerCount} workers online
        </span>
        {props.running
          ? <button type="button" className="secondary-button" onClick={props.onStop}>Stop run</button>
          : props.status === "stopped"
            ? <>
                <button type="button" className="primary-button" disabled={props.disabled || props.loading}
                  onClick={props.onContinue}>Continue · {props.legacySession ? "1 worker" : `${props.sharedQueue ? selectedCount : activeWorkerCount} workers`}</button>
                <button type="button" className="secondary-button" disabled={props.disabled || props.loading}
                  onClick={props.onRestart}>Restart · {selectedCount} workers</button>
              </>
            : <button type="button" className="primary-button" disabled={props.disabled || props.loading}
                onClick={props.onRunAll}>Run all · {selectedCount} workers</button>}
      </div>
    </div>

    {props.legacySession && <p className="worker-dashboard-legacy">This saved session uses one worker. Restart to use {selectedCount} selected workers.</p>}

    <div className="worker-dashboard-overall">
      <div className="worker-dashboard-total">
        <div className="crawl-progress-heading"><span>Progress</span><strong>{done.toLocaleString("en-GB")} <small>/ {total.toLocaleString("en-GB")} cases</small></strong>
          <span className="worker-dashboard-status" data-status={props.status}>{statusLabels[props.status]}</span></div>
        <div className="crawl-throughput" aria-label="Crawl speed in cases per minute">
          <strong>{casesPerMinute === null ? '—' : casesPerMinute.toFixed(1)}</strong><span>cases/min</span>
        </div>
      </div>
      <div className="worker-progress-track" role="progressbar" aria-label="Overall crawl progress"
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressPercent}>
        <span style={{ width: progressPercent + "%" }} />
      </div>
      <div className="worker-dashboard-summary">
        <span><strong>{Math.max(0, total - done).toLocaleString("en-GB")}</strong>Remaining</span>
        <span><strong>{withData.toLocaleString("en-GB")}</strong>With data</span>
        <span><strong>{noData.toLocaleString("en-GB")}</strong>No data</span>
        <span><strong>{errors.toLocaleString("en-GB")}</strong>Failed</span>
        <span><strong>{pendingRetries.toLocaleString("en-GB")}</strong>Queued retries</span>
        <span><strong>{props.running ? estimate.remainingMs !== null
          ? formatDuration(estimate.remainingMs) : "Calibrating" : "—"}</strong>
          ETA</span>
      </div>
    </div>

    <div className="worker-dashboard-grid">
      {workerCards.map((card) => {
        const percent = card.assigned ? Math.round(card.completed / card.assigned * 100) : 0;
        const caseElapsed = props.running && card.lane?.currentFilterStartedAt
          ? formatDuration(clockNow - card.lane.currentFilterStartedAt) : null;
        return <article className="worker-card" key={card.runnerId || card.workerIndex} data-state={card.taskTone}>
          <div className="worker-card-top">
            <div className="worker-card-title"><span className="worker-card-number">{String(card.workerIndex + 1).padStart(2, "0")}</span>
              <div><small>BROWSER WORKER</small><h3>Worker {card.workerIndex + 1}</h3><span title={card.runnerId || undefined}>{card.runner?.name || "Awaiting connection"}{card.runner && card.runnerId ? " · " + card.runnerId : ""}</span></div>
            </div>
            <span className="worker-connection" data-state={card.connectionLabel.toLowerCase()}><i aria-hidden="true" />{card.connectionLabel}</span>
          </div>

          <div className="worker-card-assignment">
            <div><small>{props.sharedQueue ? "SHARED QUEUE CLAIMS" : card.lane ? "ASSIGNED CASES" : "PLANNED CASE RANGE"}</small><strong>{props.sharedQueue
              ? `${card.assigned.toLocaleString("en-GB")} claimed`
              : card.assigned ? "#" + (card.from + 1).toLocaleString("en-GB") + "–#" + (card.to + 1).toLocaleString("en-GB") : props.scenarios.length ? "No cases assigned" : "Waiting for matrix"}</strong></div>
            <span>{props.sharedQueue ? `${card.completed.toLocaleString("en-GB")} settled` : `${card.assigned.toLocaleString("en-GB")} filters`}</span>
          </div>
          <div className="worker-card-progress-title"><span>{props.sharedQueue ? "Processed claims" : "Worker progress"}</span><strong>{card.completed.toLocaleString("en-GB")} / {card.assigned.toLocaleString("en-GB")} <em>{percent}%</em></strong></div>
          <div className="worker-progress-track" role="progressbar" aria-label={"Worker " + (card.workerIndex + 1) + " progress"}
            aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
            <span style={{ width: percent + "%" }} />
          </div>
          <div className="worker-card-metrics">
            <span><strong>{card.withData}</strong>With data</span>
            <span><strong>{card.noData}</strong>No data</span>
            <span><strong>{card.errors}</strong>Failed</span>
            <span><strong>{card.lane?.retryQueueIndices.length || 0}</strong>To retry</span>
          </div>

          <div className="worker-current">
            <div className="worker-current-heading"><span>{card.currentCase ? "CURRENT CASE" : "WORK STATUS"}</span>
              <strong data-tone={card.taskTone}>{card.taskLabel}</strong></div>
            {card.currentCase ? <>
              <p className="worker-current-name" title={card.currentCase.name}>#{(card.currentIndex! + 1).toLocaleString("en-GB")} · {card.currentCase.filters.states[0]} · {card.currentCase.filters.rtos[0]}</p>
              <p className="worker-current-detail" title={card.currentCase.name}>{card.currentCase.caseKey&&card.currentCase.name.includes(' · ')
                ?card.currentCase.name.split(' · ').slice(1).join(' · ')
                :card.lane?.retryIndex !== null && card.lane?.retryIndex !== undefined ? "Retrying failed case" : props.sharedQueue ? "Processing a shared-queue case" : "Processing assigned case"}{caseElapsed ? " · " + caseElapsed + " elapsed" : ""}</p>
            </> : <p className="worker-current-name">{card.nextCase
              ? "Next: #" + (card.nextIndex! + 1).toLocaleString("en-GB") + " · " + card.nextCase.filters.states[0] + " · " + card.nextCase.filters.rtos[0]
              : props.sharedQueue && props.running ? "Ready to claim the next available case"
                : card.assigned && card.completed === card.assigned && hasParallelSession ? "All assigned cases processed" : "No case in progress"}</p>}
            {card.captchaWaiting && card.runnerId && <button type="button" className="worker-captcha-link"
              onClick={() => props.onOpenCaptcha(card.runnerId!)}>Open this worker's CAPTCHA →</button>}
            {!card.captchaWaiting && card.activeJob?.error && <p className="worker-current-error" title={card.activeJob.error}>{card.activeJob.error}</p>}
          </div>
          <div className="worker-card-footer">
            <span>Last result</span><strong title={card.last?.detail}>{card.lane ? resultLabel(card.last) : "No parallel session yet"}</strong>
            {card.lane && card.completed < card.assigned && <small>{(card.assigned - card.completed).toLocaleString("en-GB")} {card.assigned - card.completed === 1 ? "case" : "cases"} remain</small>}
          </div>
        </article>;
      })}
    </div>

  </section>;
}
