import { useEffect, useState } from "react";

import type { Scenario } from "../contracts";
import { currentReportYear, type MatrixPlan } from "../matrix-plan";
import { estimateBatchTiming, type FilterTiming } from "../batch-timing";
import { CompletedTasks } from './CompletedTasks';

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
  completedAt?: string;
  savedAt?: string;
  rowCount?: number;
}

interface Props {
  plan: MatrixPlan | null;
  scenarios: Scenario[];
  loading: boolean;
  loadingMessage: string;
  onRunAll: () => void;
  onRunFrom: (index: number) => void;
  onRunOne: (index: number) => void;
  onRetryFailed: () => void;
  onContinueStopped: () => void;
  onRestartAll: () => void;
  onStop: () => void;
  running: boolean;
  progress: { done: number; total: number; current: string };
  batchStatus: "idle" | "running" | "completed" | "completed_with_errors" | "stopped" | "error";
  startedAt: string | null;
  finishedAt: string | null;
  timings: FilterTiming[];
  currentFilterStartedAt: number | null;
  activeElapsedMs: number;
  activeSegmentStartedAt: number | null;
  log: BatchLogEntry[];
  failedAtIndex: number | null;
  pendingRetries: number;
  disabled: boolean;
}

function formatDuration(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  const remainingSeconds = seconds % 60;
  return hours
    ? `${hours}h ${String(minutes).padStart(2, "0")}m ${String(remainingSeconds).padStart(2, "0")}s`
    : `${minutes}m ${String(remainingSeconds).padStart(2, "0")}s`;
}

function formatEstimatedFinish(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
    hourCycle: "h23", timeZone: "Asia/Ho_Chi_Minh",
  }).format(date);
}

export function MatrixRunner(props: Props) {
  const {
    plan, scenarios, loading, loadingMessage, onRunAll, onRunFrom,
    onRunOne, onRetryFailed, onContinueStopped, onRestartAll, onStop,
    running, progress, batchStatus, log, startedAt, failedAtIndex, disabled,
    timings, currentFilterStartedAt, activeElapsedMs, activeSegmentStartedAt, pendingRetries,
  } = props;
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [clockNow, setClockNow] = useState(Date.now());
  useEffect(() => {
    if (!running || !startedAt) return;
    setClockNow(Date.now());
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running, startedAt]);
  const yearIsCurrent = plan?.year === currentReportYear();
  const countByState = plan?.states.map((state) => ({
    state,
    count: scenarios.filter((scenario) => scenario.filters.states[0] === state).length,
  })) || [];
  const failed = log.filter((entry) => entry.status === "error").length;
  const progressPercent = progress.total ? Math.min(100, progress.done / progress.total * 100) : 0;
  const estimate = estimateBatchTiming(
    timings, progress.total, progress.done, currentFilterStartedAt, clockNow, activeElapsedMs, activeSegmentStartedAt,
  );
  const statusLabels = {
    idle: "Ready",
    running: "Running",
    completed: "Completed",
    completed_with_errors: "Completed with errors",
    stopped: "Stopped",
    error: "Error",
  } as const;

  return <section className="card scenario-import">
    <div className="scenario-heading">
      <div><h2>State × RTO matrix</h2><p>Fixed Maker / Month Wise report for every office</p></div>
      <div className="scenario-heading-meta">
        <span className="scenario-background-indicator"><i aria-hidden="true" />Background mode</span>
        <span className="scenario-count">{plan ? `${scenarios.length} reports` : "Auto refresh"}</span>
      </div>
    </div>

    <div className="scenario-run-info">
      <strong>Fixed filters · {plan?.year || currentReportYear()}</strong>
      <span>All four Active/Archive types · Calendar Year · Two Wheeler · all three Two Wheeler subcategories · ELECTRIC(BOV), PURE EV · Y: Maker · X: Month Wise</span>
      <span>State and RTO refresh at the start of a new session. Keep this page open while the browser worker runs; enter any requested CAPTCHA here.</span>
      <span>After each group of 10 reports, failed cases in that group retry once before the next group starts. The final smaller group is also checked. Retry results update the original session; no-data results count as successful.</span>
    </div>
    {loading && <div className="matrix-loading-banner" role="status" aria-live="polite">
      <span className="matrix-loading-spinner" aria-hidden="true" />
      <span>{loadingMessage || "Refreshing the State–RTO office list for this session…"}</span>
    </div>}
    {plan && !yearIsCurrent && <p className="scenario-empty-hint">The report year will update to {currentReportYear()} when you start a new run.</p>}

    {plan && <>
      <div className="scenario-list-heading"><h3>States and offices</h3><span>{plan.states.length} States · {scenarios.length} RTOs</span></div>
      <div className="matrix-states">
        {countByState.map(({ state, count }) => <span key={state}>{state} <strong>{count}</strong></span>)}
      </div>
      <div className="scenario-actions">
        {running
          ? <div className="scenario-main-actions"><button className="secondary-button scenario-stop-button" type="button" onClick={onStop}>Stop now</button></div>
          : batchStatus === "stopped"
            ? <div className="scenario-recovery-actions">
                <div className="scenario-main-actions">
                  <button className="primary-button" type="button" disabled={disabled || loading}
                    onClick={onContinueStopped}>Continue saved session</button>
                  <button className="secondary-button" type="button" disabled={disabled || loading}
                    onClick={onRestartAll}>Restart all offices from start</button>
                </div>
                <p className="scenario-recovery-note">Saved: {progress.done.toLocaleString()} / {progress.total.toLocaleString()} reports; {Math.max(0, progress.total - progress.done).toLocaleString()} remain{pendingRetries ? `, plus ${pendingRetries} queued retries` : ""}. Continue processes pending retries first, then resumes at the first unfinished report. Restart refreshes the full State/RTO list and replaces this saved session.</p>
              </div>
            : <div className="scenario-main-actions">
              <button className="secondary-button scenario-all-button" type="button" disabled={disabled || loading}
                onClick={onRunAll}>Run all {scenarios.length}</button>
            </div>}
        {!running && batchStatus !== "stopped" && <div className="scenario-start-row">
          <label>Select office
            <select value={Math.min(selectedIndex, Math.max(0, scenarios.length - 1))} disabled={disabled || loading}
              onChange={(event) => setSelectedIndex(Number(event.target.value))}>
              {scenarios.map((scenario, index) => <option key={`${index}-${scenario.name}`} value={index}>
                {index + 1}. {scenario.filters.states[0]} · {scenario.filters.rtos[0]}
              </option>)}
            </select>
          </label>
          <div className="scenario-run-buttons">
            <button className="secondary-button" type="button" disabled={disabled}
              onClick={() => onRunFrom(selectedIndex)}>Run from here</button>
            <button className="primary-button" type="button" disabled={disabled}
              onClick={() => onRunOne(selectedIndex)}>Run one</button>
          </div>
        </div>}
        {!running && batchStatus !== "stopped" && failedAtIndex !== null && <button className="retry-button" type="button"
          disabled={disabled || loading} onClick={onRetryFailed}>Retry {failed} failed reports</button>}
      </div>
    </>}

    {!plan && <div className="scenario-auto-start">
      <p>The office list is not loaded yet. It will refresh automatically when this session starts.</p>
      <button className="primary-button" type="button" disabled={disabled || loading} onClick={onRunAll}>
        Start session
      </button>
    </div>}

    {(running || progress.total > 0) && <div className="scenario-progress" role="status">
      <div className="scenario-progress-heading">
        <div className="scenario-progress-state">
          <span>Session status</span>
          <strong className="scenario-status-badge" data-status={batchStatus}>{statusLabels[batchStatus]}</strong>
        </div>
        <div className="scenario-progress-count">
          <strong>{Math.min(progress.done, progress.total).toLocaleString("en-GB")}</strong>
          <span>/ {progress.total.toLocaleString("en-GB")} reports</span>
        </div>
      </div>
      <div className="scenario-progress-track" role="progressbar" aria-label="Session progress"
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progressPercent)}>
        <span style={{ width: `${progressPercent}%` }} />
      </div>
      {running && progress.current && <p className="scenario-progress-current">Current report <strong>{progress.current}</strong></p>}
      {running && <div className="scenario-timing-grid">
        <div className="scenario-time-card scenario-time-estimate">
          <span>Estimated session completion</span>
          <strong>{estimate.remainingMs === null
            ? "Calculating…"
            : formatEstimatedFinish(new Date(clockNow + estimate.remainingMs))}</strong>
          <small>{estimate.remainingMs === null
            ? "Available after the first report completes."
            : `${formatDuration(estimate.remainingMs)} remaining · ${Math.max(1, Math.round(estimate.reportsPerHour || 0)).toLocaleString("en-GB")} reports/hour ${estimate.pace === "recent" ? "recent pace" : "session pace"} · Vietnam time`}</small>
        </div>
      </div>}
    </div>}
    <CompletedTasks log={log} scenarios={scenarios} />
  </section>;
}
