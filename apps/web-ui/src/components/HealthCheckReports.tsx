import { useEffect, useState } from "react";

import type { PendingUiHealthCheck, UiHealthReportsResponse } from "../contracts";
import { api } from "../services/api-client";
import { AuthenticatedDownload } from "./AuthenticatedDownload";

const MANUAL_REPORT_POLL_INTERVAL_MS = 2_000;
const MANUAL_REPORT_POLL_TIMEOUT_MS = 90_000;

const statusLabels: Record<string, string> = {
  PASS: "Healthy",
  DATA_CHANGED: "Data changed",
  UI_DRIFT: "UI changed",
  CHECK_ERROR: "Check error",
};

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KiB`;
}

function diagnosticText(value: string) {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value || "No diagnostic details.";
  }
}

function diagnosticObject(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

function diagnosticReports(value: string): Array<Record<string, unknown>> {
  const parsed = diagnosticObject(value);
  return Array.isArray(parsed?.errors)
    ? parsed.errors.filter(
      (item): item is Record<string, unknown> => Boolean(item && typeof item === "object"),
    )
    : [];
}

function isResultForPendingManualCheck(row: Record<string, string>, pending: PendingUiHealthCheck) {
  if (row.trigger !== "manual-web") return false;
  const checkedAt = Date.parse(row.checked_at || "");
  const requestedAt = Date.parse(pending.requestedAt);
  return Number.isFinite(checkedAt) && Number.isFinite(requestedAt) && checkedAt >= requestedAt;
}

function reportValue(report: Record<string, unknown>, key: string) {
  const value = report[key];
  return value === undefined || value === null || value === "" ? "—" : String(value);
}

function HealthReportTable({ rows }: { rows: Array<Record<string, string>> }) {
  return (
    <table className="health-report-table">
      <thead>
        <tr>
          <th>Time</th>
          <th>Status</th>
          <th>Error code / title</th>
          <th>Target</th>
          <th>Expected / Actual</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const reports = diagnosticReports(row.diagnostic_details);
          const declaredErrorCount = Number(row.error_count);
          const errorCount = Number.isFinite(declaredErrorCount) && declaredErrorCount > 0
            ? declaredErrorCount
            : reports.length || (row.status === "PASS" ? 0 : 1);
          return (
          <tr key={row.log_id}>
            <td className="report-nowrap">{formatDateTime(row.checked_at)}</td>
            <td>
              <span className={`report-status report-status-${(row.status || "CHECK_ERROR").toLowerCase()}`}>
                {statusLabels[row.status] || row.status || "Unknown"}
              </span>
            </td>
            <td>
              <strong>
                {row.error_code || "—"}
                {errorCount > 1 && <span className="health-report-error-count"> · {errorCount} errors</span>}
              </strong>
              <small>{row.error_title || (row.status === "PASS" ? "UI check passed" : "No error details")}</small>
            </td>
            <td>
              <strong>{row.target || "—"}</strong>
              <small>{row.selector || row.page_path || "—"}</small>
            </td>
            <td>
              <small><b>Expected:</b> {row.expected || "—"}</small>
              <small><b>Actual:</b> {row.actual || row.error || (row.status === "PASS" ? "UI contract matched" : "—")}</small>
            </td>
            <td>
              <details>
                <summary>{errorCount > 1 ? `View ${errorCount} diagnostics` : "View diagnostic"}</summary>
                {reports.length > 1 && (
                  <ol className="health-report-errors">
                    {reports.map((report, index) => (
                      <li key={`${row.log_id}-error-${index}`}>
                        <strong>{reportValue(report, "code")}</strong>
                        <span>{reportValue(report, "target")}</span>
                        <small><b>Expected:</b> {reportValue(report, "expected")}</small>
                        <small><b>Actual:</b> {reportValue(report, "actual")}</small>
                      </li>
                    ))}
                  </ol>
                )}
                <pre>{diagnosticText(row.diagnostic_details)}</pre>
                <small><b>Log ID:</b> {row.log_id || "—"}</small>
                <small><b>Trigger:</b> {row.trigger || "—"} · <b>Failure:</b> {row.failure_type || "—"}</small>
                <small><b>Duration:</b> {row.duration_ms ? `${row.duration_ms} ms` : "—"} · <b>Path:</b> {row.page_path || "—"}</small>
                {row.action && <small><b>Action:</b> {row.action}</small>}
              </details>
            </td>
          </tr>
          );
        })}
      </tbody>
    </table>
  );
}

interface HealthCheckReportsProps {
  refreshToken?: number;
  pendingManualCheck?: PendingUiHealthCheck | null;
  onManualCheckSettled?: () => void;
}

export function HealthCheckReports({
  refreshToken = 0,
  pendingManualCheck = null,
  onManualCheckSettled,
}: HealthCheckReportsProps) {
  const [data, setData] = useState<UiHealthReportsResponse | null>(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [showAllHistory, setShowAllHistory] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let pollTimer: number | undefined;
    const pollingStartedAt = Date.now();

    async function loadReports(showLoading: boolean) {
      if (showLoading) {
        setLoading(true);
        setError("");
      }
      try {
        const value = await api.uiHealthReports(selectedDate || undefined);
        if (cancelled) return;
        setData(value);
        if (value.selectedDate && value.selectedDate !== selectedDate) {
          setSelectedDate(value.selectedDate);
        }
        if (
          pendingManualCheck
          && value.rows.some((row) => isResultForPendingManualCheck(row, pendingManualCheck))
        ) {
          onManualCheckSettled?.();
        }
      } catch (reason) {
        // A transient polling failure must not replace the existing report with
        // an error while the browser worker is still finishing its check.
        if (!cancelled && showLoading) {
          setError(reason instanceof Error ? reason.message : "Could not load UI health reports.");
        }
      } finally {
        if (!cancelled && showLoading) setLoading(false);
      }
    }

    void loadReports(true);
    if (pendingManualCheck) {
      pollTimer = window.setInterval(() => {
        if (Date.now() - pollingStartedAt >= MANUAL_REPORT_POLL_TIMEOUT_MS) {
          if (pollTimer !== undefined) window.clearInterval(pollTimer);
          return;
        }
        void loadReports(false);
      }, MANUAL_REPORT_POLL_INTERVAL_MS);
    }

    return () => {
      cancelled = true;
      if (pollTimer !== undefined) window.clearInterval(pollTimer);
    };
  }, [selectedDate, refreshToken, pendingManualCheck, onManualCheckSettled]);

  useEffect(() => {
    setShowAllHistory(false);
  }, [selectedDate, refreshToken]);

  const activeDate = selectedDate || data?.selectedDate || "";
  const selectedSummary = data?.availableDates.find((item) => item.date === activeDate);
  const selectedFiles = data?.reports.filter((report) => report.containsSelectedDate) || [];
  const historyRows = data?.rows || [];
  const visibleHistoryRows = showAllHistory ? historyRows : historyRows.slice(0, 5);
  const remainingHistoryCount = Math.max(historyRows.length - 5, 0);

  return (
    <section className="panel health-reports" id="health-reports">
      <div className="panel-heading">
        <span className="step-number">4</span>
        <div>
          <h2>Daily UI health reports</h2>
          <p>Review check history and download CSV files from the backend.</p>
        </div>
      </div>

      {loading && !data && <p className="health-reports-loading">Loading check history...</p>}
      {error && <p className="health-schedule-status error-message" role="alert">{error}</p>}
      {pendingManualCheck && (
        <p className="health-reports-pending" role="status">
          Waiting for the browser worker to return the immediate check result. Statistics and history will update when the log is recorded.
        </p>
      )}

      {data && data.availableDates.length === 0 && !loading && (
        <p className="health-reports-empty">No check logs have been received from the browser worker.</p>
      )}

      {data && data.availableDates.length > 0 && (
        <>
          <div className="health-reports-toolbar">
            <label htmlFor="health-report-date">
              Check date
              <select
                id="health-report-date"
                value={activeDate}
                onChange={(event) => setSelectedDate(event.currentTarget.value)}
                disabled={loading}
              >
                {data.availableDates.map((summary) => (
                  <option key={summary.date} value={summary.date}>
                    {summary.date} · {summary.total} checks
                  </option>
                ))}
              </select>
            </label>
            <div className="health-report-summary" aria-label="Selected date summary">
              <span><strong>{data.rows.length}</strong> records</span>
              <span className="report-count-pass">{selectedSummary?.pass || 0} healthy</span>
              <span className="report-count-warning">
                {selectedSummary?.dataChanged || 0} data changes
                {selectedSummary?.dataChangedErrors ? ` · ${selectedSummary.dataChangedErrors} errors` : ""}
              </span>
              <span className="report-count-error">
                {selectedSummary?.uiDrift || 0} UI changes · {selectedSummary?.uiDriftErrors || 0} UI errors
              </span>
              <span className="report-count-error">{selectedSummary?.checkError || 0} check errors</span>
            </div>
          </div>

          <div className="health-reports-downloads">
            <div className="health-report-download-title">
              <strong>CSV for {activeDate}</strong>
              <small>The backend retains up to 10 days or 512 KiB of logs.</small>
            </div>
            <div className="health-report-links">
              {selectedFiles.length > 0 ? selectedFiles.map((report) => (
                <div className="health-report-file" key={report.fileName}>
                  <span className="health-report-file-name" title={report.fileName}>{report.fileName}</span>
                  <small>{formatBytes(report.sizeBytes)}</small>
                  <AuthenticatedDownload
                    className="secondary-button health-report-download"
                    path={report.downloadUrl}
                    fileName={report.fileName}
                  >
                    Download CSV
                  </AuthenticatedDownload>
                </div>
              )) : <span className="health-reports-empty">No CSV files were found for this date.</span>}
            </div>
          </div>

          {historyRows.length > 0 ? (
            <>
              <div className="health-report-log health-report-history">
                <div className="health-report-log-heading">
                  <div>
                    <strong>Check history</strong>
                    <small>
                      Showing {visibleHistoryRows.length}/{historyRows.length} records, including results from “Check now”.
                    </small>
                  </div>
                  {remainingHistoryCount > 0 && (
                    <button
                      className="secondary-button health-report-more-button"
                      type="button"
                      aria-controls="health-report-history"
                      aria-expanded={showAllHistory}
                      onClick={() => setShowAllHistory((current) => !current)}
                    >
                      {showAllHistory ? "Show less" : `Show more (${remainingHistoryCount})`}
                    </button>
                  )}
                </div>
                <div
                  className={`health-report-table-wrap ${showAllHistory ? "is-expanded" : "is-collapsed"}`}
                  id="health-report-history"
                >
                  <HealthReportTable rows={visibleHistoryRows} />
                </div>
              </div>

            </>
          ) : <p className="health-reports-empty">There are no records for this date.</p>}
        </>
      )}
    </section>
  );
}
