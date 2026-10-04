import type { Job, JobStatus as Status } from "../contracts";
import { AuthenticatedDownload } from "./AuthenticatedDownload";

const labels: Record<Status, string> = {
  QUEUED: "Queued",
  ASSIGNED: "Assigned to browser worker",
  OPENING_VAHAN: "Opening VAHAN",
  CAPTURING_CAPTCHA: "Loading CAPTCHA",
  FILLING_FILTERS: "Filling filters",
  WAITING_CAPTCHA: "Waiting for CAPTCHA",
  SUBMITTING: "Submitting CAPTCHA",
  WAITING_RESULT: "Waiting for results",
  COMPLETED: "Completed",
  NO_DATA: "No record found",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface ParsedJobError {
  title?: string;
  detail: string;
  suggestion?: string;
}

function parseJobError(rawError: string): ParsedJobError {
  const error = String(rawError || "").trim();

  if (error.includes("VAHAN_SESSION_EXPIRED") || error.includes("Session Timeout")) {
    return {
      title: "VAHAN session expired",
      detail: "VAHAN ended the session because the tab was inactive for too long.",
      suggestion: "Reload the VAHAN page in your browser and try again.",
    };
  }

  if (error.includes("VAHAN_AUTH_REQUIRED") || error.includes("401")) {
    return {
      title: "VAHAN authentication required (HTTP 401)",
      detail: error.replace(/^VAHAN_AUTH_REQUIRED:\s*/i, ""),
      suggestion: "Close any sign-in dialog, open the official VAHAN page, and try again.",
    };
  }

  if (error.includes("VAHAN_UNREACHABLE") || error.includes("chrome-error") || error.includes("Lỗi kết nối")) {
    return {
      title: "Cannot reach VAHAN",
      detail: error.replace(/^VAHAN_UNREACHABLE:\s*/i, ""),
      suggestion: "Check your internet connection or visit https://analytics.parivahan.gov.in to see whether the site is available.",
    };
  }

  if (error.includes("VAHAN_SERVER_ERROR") || error.includes("HTTP 5")) {
    return {
      title: "VAHAN server error",
      detail: error.replace(/^VAHAN_SERVER_ERROR:\s*/i, ""),
      suggestion: "VAHAN is experiencing an internal error. Wait a few minutes and try again.",
    };
  }

  if (error.includes("Receiving end does not exist")) {
    return {
      title: "Connection to the VAHAN tab was lost",
      detail: "The browser worker cannot communicate with the VAHAN tab. The tab may be closed or on a different page.",
      suggestion: "Make sure the VAHAN tab is on the Public Report page, then reload it.",
    };
  }

  if (error.startsWith("NO_RECORD_FOUND")) {
    return {
      title: "No data found",
      detail: error.replace(/^NO_RECORD_FOUND:\s*/, ""),
      suggestion: "Try broadening or changing the filters.",
    };
  }

  return {
    detail: error,
  };
}

export function JobStatus({ job, onCancel }: { job: Job | null; onCancel: () => void }) {
  if (!job) return null;
  const terminal = ["COMPLETED", "NO_DATA", "FAILED", "CANCELLED"].includes(job.status);
  const hasExcel = job.status === "COMPLETED" && !!job.excelFileName;

  return (
    <section className="panel job-panel">
      <div className="panel-heading">
        <span className="step-number">2</span>
        <div><h2>Activity</h2></div>
      </div>
      <div className="job-state" data-state={job.status}>
        <span className="pulse" />
        <strong>{labels[job.status]}</strong>
      </div>
      {job.status === "NO_DATA" && <>
        <p>No record found for {job.filters.states.join(", ")} · {job.filters.rtos.join(", ")}. Saved to SQL.</p>
        {job.noDataFileName && <AuthenticatedDownload
          className="secondary-button" path={`/api/jobs/${job.id}/no-data`} fileName={job.noDataFileName}>
          Download TXT
        </AuthenticatedDownload>}
      </>}
      {job.status === "COMPLETED" && job.reportTableCount != null && (
        <p>Saved {job.reportTableCount} tables · {job.reportRowCount} data rows to SQL.</p>
      )}
      {job.resultObservedAt && <p>Collected: {new Date(job.resultObservedAt).toLocaleString("en-GB", {
        timeZone: "Asia/Ho_Chi_Minh", hour12: false,
      })} (UTC+7)</p>}
      {job.error && (() => {
        const parsed = parseJobError(job.error);
        return (
          <div className="job-error-box error-message">
            {parsed.title && <strong className="job-error-title">{parsed.title}</strong>}
            <p className="job-error-detail">{parsed.detail}</p>
            {parsed.suggestion && <p className="job-error-suggestion">💡 <em>Suggestion: {parsed.suggestion}</em></p>}
          </div>
        );
      })()}
      {hasExcel && (
        <div className="job-excel-download">
          <AuthenticatedDownload
            className="primary-button"
            path={`/api/jobs/${job.id}/excel`}
            fileName={job.excelFileName || "report.xlsx"}
          >
            📥 Download Excel report
          </AuthenticatedDownload>
          <p className="job-excel-meta">
            {job.excelFileName}
            {job.excelFileSize != null && ` · ${formatSize(job.excelFileSize)}`}
          </p>
        </div>
      )}
      {!terminal && <button className="secondary-button" onClick={onCancel}>Cancel job</button>}
    </section>
  );
}
