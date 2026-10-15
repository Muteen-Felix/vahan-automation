// Presentation only: keep the original status codes and error evidence for support.
const STATUS_LABELS: Record<string, string> = {
  WAITING: 'Scheduled', PREPARING: 'Preparing', RUNNING: 'Running',
  PAUSING: 'Pausing', PAUSED: 'Paused', RESUMING: 'Continuing',
  COMPLETED: 'Completed', COMPLETED_WITH_ERRORS: 'Some reports unfinished',
  ERROR: 'Needs attention', STOPPED: 'Stopped', ONLINE: 'Ready', BUSY: 'Working',
  RECONNECTING: 'Reconnecting', OFFLINE: 'Not connected', IDLE: 'Ready',
  QUEUED: 'Waiting to start', PENDING: 'Waiting to start', PROCESSING: 'Working',
  ASSIGNED: 'Preparing report', OPENING_VAHAN: 'Opening VAHAN',
  CAPTURING_CAPTCHA: 'Preparing verification', WAITING_CAPTCHA: 'Waiting for your verification',
  FILLING_FILTERS: 'Choosing report filters', SUBMITTING: 'Requesting report',
  WAITING_RESULT: 'Waiting for VAHAN', NO_DATA: 'No records found',
  FAILED: 'Could not finish', CANCELLED: 'Stopped',
};

const STAGE_LABELS: Record<string, string> = {
  'Docker worker pool': 'Preparing report browsers', 'Worker pool': 'Preparing report browsers',
  'Worker connection': 'Connecting report browsers', 'Waiting for workers': 'Waiting for available browsers',
  'UI Health preflight': 'Checking the VAHAN website', 'UI Health gate': 'Checking the VAHAN website',
  'Loading report filters / Maker': 'Loading report choices',
  'Adding cases to PostgreSQL queue': 'Saving the list of reports to collect',
  'Recovering failed cases': 'Trying unfinished reports again',
};

export function operatorStatus(value: string): string {
  if (!STATUS_LABELS[value] && /^[A-Z][A-Z0-9]*_[A-Z0-9_]+$/.test(value)) return 'Status needs review';
  return STATUS_LABELS[value] || operatorMessage(value);
}

export function operatorStage(value: string): string {
  return STAGE_LABELS[value] || operatorStatus(value);
}

export function reportBrowserName(name: string, index: number): string {
  if (!name || /^(?:worker|runner|crawler|playwright|docker|browser runner)(?:[-_\s]|$)/i.test(name)) return `Browser ${index + 1}`;
  return name;
}

export function filterChoiceLabel(value: string): string {
  const labels: Record<string,string> = {ACTIVE_COMPLIANT:'Active Compliant',ACTIVE_NON_COMPLIANT:'Active Non-Compliant',
    PERMANENT_ARCHIVE:'Permanent Archive',TEMPORARY_ARCHIVE:'Temporary Archive'};
  return labels[value] || value;
}

export function operatorMessage(value: string | null | undefined): string {
  if (!value) return '';
  let message = value.trim();
  // API errors may be structured objects. Never show JSON as the operator's instruction.
  if (message.startsWith('{') || message.startsWith('[')) {
    try {
      const detail = JSON.parse(message);
      if (detail && !Array.isArray(detail)) {
        message = [detail.code, detail.message, detail.detail, detail.title]
          .filter(item => typeof item === 'string').join(': ');
      } else message = '';
    } catch { message = ''; }
  }
  if (/UI_HEALTH_BLOCKED|UI_PREFLIGHT_REQUIRED|UI_CONTRACT_MISMATCH|UI_DRIFT|successful UI health check/i.test(message)) {
    return 'The VAHAN website check needs attention. Open Website check in Settings and copy the issue for support. Try again after it is fixed.';
  }
  if (/VAHAN_REPORT_NAVIGATED_AWAY/i.test(message)) {
    return 'VAHAN left the Public Report page before confirming this result. This attempt was not saved; check the case status before retrying it manually.';
  }
  if (/VAHAN_REPORT_NAVIGATED_AWAY|navigated away|unexpected page|redirect/i.test(message)) {
    return 'VAHAN opened a different page, so this report could not finish. Try again. If it happens again, copy the issue for support.';
  }
  if (/PREFLIGHT_WAITING|WORKER_BUSY|WORKER_RESERVATION_EXPIRED/i.test(message)) {
    return 'Waiting for an available report browser. The system will try again automatically.';
  }
  if (/WORKER_OFFLINE|WORKER_NOT_FOUND|NO_RUNNERS/i.test(message)) {
    return 'A report browser is not connected. Wait for it to reconnect, then try again.';
  }
  if (/CAPTCHA_WAIT_TIMEOUT|CAPTCHA_REJECTED|VALIDATION_STOP/i.test(message)) {
    return 'VAHAN verification could not be completed. Check the report browser and complete the verification before continuing.';
  }
  if (/page\.goto|Timeout \d+ms|TimeoutError|ERR_CONNECTION|ECONN|ETIMEDOUT|Failed to fetch|NetworkError/i.test(message)) {
    return 'The website or system could not be reached in time. Check the connection and try again. If it happens again, contact support.';
  }
  if (/scheduler has not reported/i.test(message)) {
    return 'The automatic schedule has not updated for over 6 minutes. Ask support to check it.';
  }
  if (/No new job status for over 5 minutes/i.test(message)) {
    return 'No report progress has been received for over 5 minutes. The report may be delayed. Open details to check the report browsers.';
  }
  message = message.replace(/^[A-Z][A-Z0-9_]+:\s*/, '');
  if (/UI_CONTRACT|CHECK_ERROR|selector|Traceback|Exception|\/api\/|PostgreSQL|SQLAlchemy|Bearer|token secret|status code|\{\s*"|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b/i.test(message) || !message) {
    return 'This action could not finish. Try again. If it happens again, contact support.';
  }
  return message
    .replace(/A worker is still busy\. Stop its job before changing containers\./gi, 'A report browser is still working. Wait for its current report to finish before changing the number of browsers.')
    .replace(/connected, idle workers/gi, 'connected, available report browsers')
    .replace(/\bidle (browser )?(workers?|runners?)\b/gi, 'available report browsers')
    .replace(/\bbrowser (workers?|runners?)\b/gi, 'report browsers')
    .replace(/\bworkers?\b/gi, match => /s$/i.test(match) ? 'report browsers' : 'report browser')
    .replace(/\brunners?\b/gi, match => /s$/i.test(match) ? 'report browsers' : 'report browser')
    .replace(/\bUI Health\b/gi, 'Website check')
    .replace(/\bpreflight\b/gi, 'website check')
    .replace(/\bdiagnostics?\b/gi, 'support details')
    .replace(/\bbackend\b|\bAPI\b/gi, 'system')
    .replace(/\bSQL\b|\bmain table\b/gi, 'saved reports')
    .replace(/\bcheckpoint\b/gi, 'group check')
    .replace(/\bqueued\b/gi, 'waiting')
    .replace(/\bqueue\b/gi, 'waiting list')
    .replace(/\bvalid cases\b/gi, 'reports to collect')
    .replace(/\bfilter profiles\b/gi, 'saved filters')
    .replace(/\bfilter profile\b/gi, 'saved filter set')
    .replace(/\bcases\b/gi, 'reports')
    .replace(/\bcase\b/gi, 'report');
}

export function websiteIssueMessage(code: string, title: string): string {
  if (/UI_CONTRACT_MISMATCH|UI_DRIFT/.test(code)) return 'The VAHAN page has changed. Some report choices could not be found or used. Support needs to review the page before collection can continue.';
  return operatorMessage(`${code}: ${title}`);
}
