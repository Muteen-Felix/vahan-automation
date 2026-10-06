import { useState } from "react";

import type { Scenario } from "../contracts";
import { currentReportYear, type MatrixPlan } from "../matrix-plan";
import { CompletedTasks } from './CompletedTasks';
import { TARGET_WORKER_COUNT } from '../worker-settings';

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
  onRunFrom: (index: number) => void;
  onRunOne: (index: number) => void;
  onRetryFailed: () => void;
  running: boolean;
  progress: { done: number; total: number; current: string };
  batchStatus: "idle" | "running" | "completed" | "completed_with_errors" | "stopped" | "error";
  log: BatchLogEntry[];
  failedAtIndex: number | null;
  pendingRetries: number;
  disabled: boolean;
}

export function MatrixRunner(props: Props) {
  const {
    plan, scenarios, loading, loadingMessage, onRunFrom,
    onRunOne, onRetryFailed,
    running, progress, batchStatus, log, failedAtIndex, disabled, pendingRetries,
  } = props;
  const [selectedIndex, setSelectedIndex] = useState(0);
  const yearIsCurrent = plan?.year === currentReportYear();
  const countByState = plan?.states.map((state) => ({
    state,
    count: scenarios.filter((scenario) => scenario.filters.states[0] === state).length,
  })) || [];
  const failed = log.filter((entry) => entry.status === "error").length;

  return <section className="card scenario-import">
    <div className="scenario-heading">
      <div><h2>State × RTO matrix</h2><p>Fixed Maker / Month Wise report for every office</p></div>
      <div className="scenario-heading-meta">
        <span className="scenario-background-indicator"><i aria-hidden="true" />Background mode</span>
        <span className="scenario-count">{plan ? `${scenarios.length} reports` : "Auto refresh"}</span>
      </div>
    </div>

    <details className="scenario-run-info">
      <summary>Fixed filters · {plan?.year || currentReportYear()} <span>View report configuration</span></summary>
      <span>All four Active/Archive types · Calendar Year · Two Wheeler · all three Two Wheeler subcategories · ELECTRIC(BOV), PURE EV · Y: Maker · X: Month Wise</span>
      <span>Run all splits the office list into {TARGET_WORKER_COUNT} ordered segments. Each browser worker runs its segment sequentially while the workers run at the same time. Keep this page open and review any CAPTCHA requests here.</span>
      <span>Each worker retries failed cases after every group of 10 reports in its segment, including the final smaller group. Retry results update the original session; no-data results count as successful.</span>
    </details>
    {loading && <div className="matrix-loading-banner" role="status" aria-live="polite">
      <span className="matrix-loading-spinner" aria-hidden="true" />
      <span>{loadingMessage || "Refreshing the State–RTO office list for this session…"}</span>
    </div>}
    {plan && !yearIsCurrent && <p className="scenario-empty-hint">The report year will update to {currentReportYear()} when you start a new run.</p>}

    {plan && <>
      {!running && <div className="scenario-actions">
        {batchStatus === "stopped" && <p className="scenario-recovery-note">Saved: {progress.done.toLocaleString()} / {progress.total.toLocaleString()} reports; {Math.max(0, progress.total - progress.done).toLocaleString()} remain{pendingRetries ? `, plus ${pendingRetries} queued retries` : ""}. Use the crawl monitor above to continue or restart this session.</p>}
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
      </div>}
      <details className="matrix-state-details">
        <summary>States and offices <span>{plan.states.length} States · {scenarios.length} RTOs</span></summary>
        <div className="matrix-states">
          {countByState.map(({ state, count }) => <span key={state}>{state} <strong>{count}</strong></span>)}
        </div>
      </details>
    </>}

    {!plan && <div className="scenario-auto-start">
      <p>The office list is not loaded yet. It will refresh when you start a full run from the crawl monitor above.</p>
    </div>}

    <CompletedTasks log={log} scenarios={scenarios} />
  </section>;
}
