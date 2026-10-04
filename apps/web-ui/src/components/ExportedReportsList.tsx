import { useEffect, useRef, useState } from "react";

import type { ExportedReportJob, ExportedReportSession } from "../contracts";
import { AuthenticatedDownload } from "./AuthenticatedDownload";
import { api } from "../services/api-client";

function formatSize(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function reportDateKey(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDay(date: string): string {
  const [year, month, day] = date.split("-");
  return year && month && day ? `${day}/${month}/${year}` : date;
}

function formatDateDraft(value: string): string {
  const digits = value.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

function parseDateDraft(value: string): string {
  const match = value.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!match) return "";
  const [, dayText, monthText, yearText] = match;
  const day = Number(dayText);
  const month = Number(monthText);
  const year = Number(yearText);
  const date = new Date(year, month - 1, day, 12);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return "";
  return `${yearText}-${monthText}-${dayText}`;
}

function monthFromDateKey(date: string): Date {
  const [year, month] = date.split("-").map(Number);
  return new Date(year, month - 1, 1, 12);
}

function statusLabel(status: ExportedReportJob["status"]): string {
  const labels: Record<ExportedReportJob["status"], string> = {
    QUEUED: "Queued",
    ASSIGNED: "Assigned",
    OPENING_VAHAN: "Opening VAHAN",
    CAPTURING_CAPTCHA: "Loading CAPTCHA",
    FILLING_FILTERS: "Filling filters",
    WAITING_CAPTCHA: "Waiting for CAPTCHA",
    SUBMITTING: "Submitting",
    WAITING_RESULT: "Waiting for results",
    COMPLETED: "Data found",
    NO_DATA: "No data",
    FAILED: "Failed",
    CANCELLED: "Stopped",
  };
  return labels[status];
}

function filterLabel(key: string): string {
  const labels: Record<string, string> = {
    states: "State",
    rtos: "RTO",
    categoryGroups: "Category Group",
    fuels: "Fuel",
    yAxis: "Y-Axis",
    xAxis: "X-Axis",
    reportYear: "Report year",
    reportMonth: "Report month",
    fromYear: "From year",
    toYear: "To year",
    fromDate: "From date",
    toDate: "To date",
    archivedFlags: "Archive type",
    subCategories: "Sub-category",
    evTypes: "EV type",
  };
  return labels[key] ?? key.replace(/([a-z\d])([A-Z])/g, "$1 $2").replace(/^./, (letter) => letter.toUpperCase());
}

function filterValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.map(filterValue).join(", ") : "(none)";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function sessionLabel(session: ExportedReportSession): string {
  if (session.activeCount > 0) return "Running";
  if (session.failedCount > 0) return "Completed with errors";
  if (session.cancelledCount > 0) return "Stopped";
  return "Completed";
}

function sessionStatusClass(session: ExportedReportSession): string {
  if (session.activeCount > 0) return "running";
  if (session.failedCount > 0) return "failed";
  if (session.cancelledCount > 0) return "cancelled";
  return "completed";
}

function SessionDetail({ session, onClose }: { session: ExportedReportSession; onClose: () => void }) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="report-detail-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="report-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="report-detail-title">
        <header className="report-detail-header">
          <div>
            <span className={`report-session-status ${sessionStatusClass(session)}`}>{sessionLabel(session)}</span>
            <h2 id="report-detail-title">Session details</h2>
            <p>{session.sessionFolder ? `Folder: ${session.sessionFolder} · ` : ""}Session ID: {session.sessionId}</p>
          </div>
          <button className="report-detail-close" type="button" onClick={onClose} aria-label="Close details">×</button>
        </header>

        <div className="report-detail-summary">
          <span><strong>{session.jobCount}</strong> cases</span>
          <span><strong>{session.completedCount}</strong> with data</span>
          <span><strong>{session.noDataCount}</strong> no data</span>
          <span><strong>{session.failedCount}</strong> failed</span>
          <span><strong>{session.cancelledCount}</strong> stopped</span>
          <span><strong>{session.activeCount}</strong> running</span>
          <span><strong>{session.fileCount}</strong> files · {formatSize(session.totalFileSize)}</span>
        </div>
        <p className="report-detail-time">Started: {formatDate(session.startedAt)} · Updated: {formatDate(session.updatedAt)}</p>

        <div className="report-detail-list" aria-label="Reports in this session">
          {session.jobs.map((job, index) => (
            <article className="report-detail-case" key={job.jobId}>
              <div className="report-detail-case-heading">
                <span className="report-detail-index">{index + 1}</span>
                <div className="report-detail-case-main">
                  <strong>{job.scenarioName}</strong>
                  <div className="report-detail-tags">
                    <span className={`report-status-badge ${job.status.toLowerCase()}`}>{statusLabel(job.status)}</span>
                  </div>
                </div>
              </div>

              <dl className="report-case-info">
                <div><dt>State</dt><dd>{job.state || "—"}</dd></div>
                <div><dt>RTO</dt><dd>{job.rto || "—"}</dd></div>
                <div><dt>Time</dt><dd>{formatDate(job.createdAt)}</dd></div>
                <div><dt>File</dt><dd>{job.fileName || (job.status === "COMPLETED" ? "Output file missing" : "No file")}</dd></div>
                <div><dt>Size</dt><dd>{job.downloadUrl ? formatSize(job.fileSize) : "—"}</dd></div>
                <div><dt>Path</dt><dd>{job.filePath || "—"}</dd></div>
              </dl>

              {Object.keys(job.filters).length > 0 && (
                <details className="report-case-filters">
                  <summary>View all filter values</summary>
                  <dl>
                    {Object.entries(job.filters).map(([key, value]) => (
                      <div key={key}><dt>{filterLabel(key)}</dt><dd>{filterValue(value)}</dd></div>
                    ))}
                  </dl>
                </details>
              )}

              {job.error && <p className="report-case-error">Error details: {job.error}</p>}
              {job.downloadUrl && job.fileName ? (
                <AuthenticatedDownload
                  className="primary-button report-case-download"
                  path={job.downloadUrl}
                  fileName={job.fileName}
                >
                  {job.fileType === "text" ? "📥 Download TXT" : "📥 Download Excel"}
                </AuthenticatedDownload>
              ) : (
                <span className="report-case-no-download">No file available to download</span>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export function ExportedReportsList({ refreshTrigger }: { refreshTrigger?: number }) {
  const [sessions, setSessions] = useState<ExportedReportSession[]>([]);
  const [selectedSession, setSelectedSession] = useState<ExportedReportSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showDeleted, setShowDeleted] = useState(false);
  const [changingSessionId, setChangingSessionId] = useState<string | null>(null);
  const [dateInput, setDateInput] = useState("");
  const [calendarMonth, setCalendarMonth] = useState(() => {
    const today = new Date();
    return new Date(today.getFullYear(), today.getMonth(), 1, 12);
  });
  const [calendarOpen, setCalendarOpen] = useState(false);
  const calendarInitialized = useRef(false);
  const calendarPickerRef = useRef<HTMLDivElement>(null);
  const loadSequenceRef = useRef(0);

  const selectedDate = parseDateDraft(dateInput);
  const dateInputHasValue = dateInput.length > 0;
  const dateInputIncomplete = dateInputHasValue && dateInput.length < 10;
  const dateInputInvalid = dateInputHasValue && !selectedDate;
  const filteredSessions = selectedDate
    ? sessions.filter((session) => reportDateKey(session.startedAt) === selectedDate)
    : dateInputHasValue && !dateInputIncomplete ? [] : sessions;
  const sessionDates = new Set(sessions.map((session) => reportDateKey(session.startedAt)).filter(Boolean));
  const firstOfMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth(), 1, 12);
  const firstWeekdayOffset = (firstOfMonth.getDay() + 6) % 7;
  const daysInMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 0).getDate();
  const calendarCellCount = Math.ceil((firstWeekdayOffset + daysInMonth) / 7) * 7;
  const calendarCells = Array.from({ length: calendarCellCount }, (_, index) => {
    const day = index - firstWeekdayOffset + 1;
    if (day < 1 || day > daysInMonth) return null;
    const month = String(calendarMonth.getMonth() + 1).padStart(2, "0");
    const dayText = String(day).padStart(2, "0");
    const date = `${calendarMonth.getFullYear()}-${month}-${dayText}`;
    return { day, date, hasReports: sessionDates.has(date) };
  });

  useEffect(() => {
    if (calendarInitialized.current || sessions.length === 0) return;
    const dates = sessions.map((session) => reportDateKey(session.startedAt)).filter(Boolean).sort();
    const latestDate = dates[dates.length - 1];
    if (!latestDate) return;
    setCalendarMonth(monthFromDateKey(latestDate));
    calendarInitialized.current = true;
  }, [sessions]);

  useEffect(() => {
    if (!calendarOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !calendarPickerRef.current?.contains(event.target)) {
        setCalendarOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setCalendarOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [calendarOpen]);

  function moveCalendarMonth(offset: number) {
    setCalendarMonth((current) => new Date(current.getFullYear(), current.getMonth() + offset, 1, 12));
  }

  async function loadReports(background = false) {
    const sequence = ++loadSequenceRef.current;
    if (!background) {
      setLoading(true);
      setError("");
    }
    try {
      const data = await api.exportedReportSessions(showDeleted);
      if (sequence !== loadSequenceRef.current) return;
      setSessions(data);
      setError("");
      setSelectedSession((current) => current ? data.find((session) => session.sessionId === current.sessionId) ?? null : null);
    } catch (e) {
      if (sequence !== loadSequenceRef.current) return;
      setError(e instanceof Error ? e.message : "Could not load report sessions.");
    } finally {
      if (sequence === loadSequenceRef.current) setLoading(false);
    }
  }

  async function changeSession(session: ExportedReportSession, restore = false) {
    if (changingSessionId) return;
    if (!restore && !window.confirm(`Delete session ${session.sessionId} from Run history?\n\nIts files and monthly data stay saved. You can restore this session from Deleted sessions.`)) return;
    setChangingSessionId(session.sessionId);
    setError("");
    try {
      if (restore) await api.restoreReportSession(session.sessionId);
      else await api.deleteReportSession(session.sessionId);
      loadSequenceRef.current += 1;
      setSessions((current) => current.filter((item) => item.sessionId !== session.sessionId));
      setSelectedSession((current) => current?.sessionId === session.sessionId ? null : current);
      await loadReports(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update this report session.");
    } finally {
      setChangingSessionId(null);
    }
  }

  useEffect(() => {
    void loadReports();
    const timer = window.setInterval(() => void loadReports(true), 5_000);
    return () => {
      window.clearInterval(timer);
      loadSequenceRef.current += 1;
    };
  }, [refreshTrigger, showDeleted]);

  return (
    <section className="panel exported-reports-panel">
      <div className="panel-heading" style={{ justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "13px" }}>
          <span className="step-number" style={{ background: "#ecfdf3", color: "#137a37", borderColor: "#16a34a" }}>✓</span>
          <div>
            <h2>{showDeleted ? "Deleted sessions" : "Exported report sessions"} ({sessions.length})</h2>
            <p>{showDeleted ? "Restore a session to return it to Run history. Files and monthly data stay saved." : "One summary per run; open a session to inspect every case and download its files."}</p>
          </div>
        </div>
        <div className="report-session-actions">
        <button className="secondary-button report-session-details-button" type="button"
          disabled={Boolean(changingSessionId)}
          onClick={() => { setSessions([]); setSelectedSession(null); setShowDeleted((current) => !current); }}>
          {showDeleted ? "Back to Run history" : "Deleted sessions"}
        </button>
        <button
          className="secondary-button"
          type="button"
          style={{ width: "auto", minHeight: "36px", padding: "6px 14px", marginTop: 0 }}
          onClick={() => void loadReports()}
          disabled={loading}
        >
          {loading ? "Loading..." : "🔄 Refresh"}
        </button>
        </div>
      </div>

      {error && <p className="error-message" style={{ marginTop: "14px" }}>{error}</p>}

      {sessions.length > 0 && (
        <div className="exported-reports-toolbar">
          <div className="exported-date-filter" ref={calendarPickerRef}>
            <label htmlFor="exported-report-date">Filter sessions by start date</label>
            <div className="exported-date-control">
              <input
                id="exported-report-date"
                type="text"
                inputMode="numeric"
                autoComplete="off"
                placeholder="dd/mm/yyyy"
                maxLength={10}
                value={dateInput}
                aria-invalid={dateInputInvalid && !dateInputIncomplete}
                aria-describedby={dateInputIncomplete ? "exported-report-date-help" : dateInputInvalid ? "exported-report-date-error" : undefined}
                onChange={(event) => {
                  const value = formatDateDraft(event.currentTarget.value);
                  setDateInput(value);
                  const parsedDate = parseDateDraft(value);
                  if (parsedDate) setCalendarMonth(monthFromDateKey(parsedDate));
                }}
                disabled={loading}
              />
              <button
                className="exported-date-picker-trigger"
                type="button"
                aria-label={calendarOpen ? "Close calendar" : "Open calendar"}
                aria-expanded={calendarOpen}
                aria-controls="exported-report-calendar"
                onClick={() => setCalendarOpen((open) => !open)}
                disabled={loading}
              >
                <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="5" width="14" height="12" rx="2" /><path d="M6 3v4M14 3v4M3 9h14" /></svg>
              </button>
            </div>
            {dateInputIncomplete && <small className="exported-date-help" id="exported-report-date-help">Enter a date in dd/mm/yyyy format.</small>}
            {dateInputInvalid && !dateInputIncomplete && <small className="exported-date-error" id="exported-report-date-error" role="alert">Invalid date.</small>}

            {calendarOpen && (
              <section className="exported-report-calendar" id="exported-report-calendar" aria-label="Report session calendar">
                <div className="exported-report-calendar-heading">
                  <h3>{calendarMonth.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</h3>
                  <div className="exported-report-calendar-nav">
                    <button type="button" aria-label="Previous month" title="Previous month" onClick={() => moveCalendarMonth(-1)}>‹</button>
                    <button type="button" aria-label="Next month" title="Next month" onClick={() => moveCalendarMonth(1)}>›</button>
                  </div>
                </div>
                <div className="exported-report-weekdays" aria-hidden="true">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <span key={day}>{day}</span>)}</div>
                <div className="exported-report-calendar-days">
                  {calendarCells.map((cell, index) => {
                    if (!cell) return <span className="exported-report-calendar-blank" key={`blank-${index}`} />;
                    const isSelected = selectedDate === cell.date;
                    const today = new Date();
                    const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
                    const classes = ["exported-calendar-day", cell.hasReports ? "has-reports" : "", isSelected ? "selected" : "", todayKey === cell.date ? "today" : ""].filter(Boolean).join(" ");
                    return (
                      <button
                        className={classes}
                        type="button"
                        key={cell.date}
                        aria-pressed={isSelected}
                        aria-label={`${formatDay(cell.date)}${cell.hasReports ? ", sessions available" : ", no sessions"}`}
                        title={`${formatDay(cell.date)}${cell.hasReports ? " · Sessions available" : ""}`}
                        onClick={() => { setDateInput(formatDay(cell.date)); setCalendarOpen(false); }}
                      ><span>{cell.day}</span></button>
                    );
                  })}
                </div>
                <div className="exported-report-calendar-legend"><span><i /> Days with sessions</span></div>
              </section>
            )}
          </div>
          <p className="exported-reports-summary" aria-live="polite">
            <strong>{filteredSessions.length}</strong>
            {selectedDate ? ` session${filteredSessions.length === 1 ? "" : "s"} · ${formatDay(selectedDate)}` : dateInputIncomplete ? " · Entering date" : dateInputInvalid ? " · Invalid date" : " sessions · all dates"}
          </p>
          {dateInputHasValue && <button className="exported-reports-reset" type="button" onClick={() => setDateInput("")} disabled={loading}>Show all dates</button>}
        </div>
      )}

      {sessions.length === 0 && !loading && (
        <p className="health-reports-empty" style={{ margin: "18px 0 0" }}>{showDeleted ? "No deleted sessions." : "No report sessions have been recorded yet."}</p>
      )}
      {sessions.length === 0 && loading && <p className="health-reports-loading">Loading report sessions...</p>}
      {selectedDate && sessions.length > 0 && filteredSessions.length === 0 && (
        <p className="health-reports-empty exported-reports-empty">No sessions were started on {formatDay(selectedDate)}.</p>
      )}

      {filteredSessions.length > 0 && (
        <div className="report-sessions-grid">
          {filteredSessions.map((session, index) => (
            <article className="report-session-card" key={session.sessionId}>
              <div className="report-session-card-heading">
                <div>
                  <span className={`report-session-status ${sessionStatusClass(session)}`}>{sessionLabel(session)}</span>
                  <h3>{index + 1}. Session {session.sessionFolder || session.sessionId.slice(0, 8)}</h3>
                </div>
                <span className="report-session-case-count">{session.jobCount} cases</span>
              </div>
              <p className="report-session-dates">Started {formatDate(session.startedAt)} · Updated {formatDate(session.updatedAt)}</p>
              <div className="report-session-metrics">
                <span><strong>{session.completedCount}</strong><small>With data</small></span>
                <span><strong>{session.noDataCount}</strong><small>No data</small></span>
                <span><strong>{session.failedCount}</strong><small>Failed</small></span>
                <span><strong>{session.cancelledCount}</strong><small>Stopped</small></span>
                <span><strong>{session.activeCount}</strong><small>Running</small></span>
              </div>
              <div className="report-session-card-footer">
                <span>{session.fileCount} files · {formatSize(session.totalFileSize)}</span>
                <div className="report-session-actions">
                <button className={`secondary-button report-session-details-button ${showDeleted ? "" : "report-session-delete-button"}`}
                  type="button" disabled={Boolean(changingSessionId) || (!showDeleted && session.activeCount > 0)}
                  title={!showDeleted && session.activeCount > 0 ? "Stop this session before deleting it" : undefined}
                  onClick={() => void changeSession(session, showDeleted)}>
                  {changingSessionId === session.sessionId ? "Saving…" : showDeleted ? "Restore session" : "Delete session"}
                </button>
                <button className="secondary-button report-session-details-button" type="button" onClick={() => setSelectedSession(session)}>
                  View details ({session.jobCount})
                </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {selectedSession && <SessionDetail session={selectedSession} onClose={() => setSelectedSession(null)} />}
    </section>
  );
}
