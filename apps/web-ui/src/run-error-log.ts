import type { Job, VahanFilters } from './contracts';

export const RUN_ERROR_STORAGE_KEY = 'vahanRunErrorsV1';
export const MAX_RUN_ERRORS = 500;
export interface RunOutcome {
  id: string;
  sessionId: string;
  jobId?: string;
  filters?: Pick<VahanFilters, 'states' | 'rtos'>;
  name: string;
  status: 'failed' | 'completed' | 'no_data';
  detail: string;
  occurredAt: string | null;
  attempt?: number;
}
export interface RunErrorEntry extends RunOutcome {
  caseKey: string;
  resolvedAt: string | null;
  resolution: 'completed' | 'no_data' | null;
}

function caseKey(outcome: RunOutcome) {
  return JSON.stringify([outcome.sessionId, outcome.filters?.states || [], outcome.filters?.rtos || [],
    outcome.filters?.rtos?.length ? '' : outcome.name]);
}

export function jobRunOutcome(job: Job): RunOutcome | null {
  if (job.source === 'old' || !['FAILED', 'COMPLETED', 'NO_DATA'].includes(job.status)) return null;
  if (job.status === 'FAILED' && job.error?.startsWith('NO_RECORD_FOUND')) return null;
  return {id: `job:${job.id}`, jobId: job.id, sessionId: job.sessionId,
    filters: {states: job.filters.states, rtos: job.filters.rtos},
    name: job.scenarioName || `${job.filters.states.join(', ')} · ${job.filters.rtos.join(', ')}`,
    status: job.status === 'FAILED' ? 'failed' : job.status === 'NO_DATA' ? 'no_data' : 'completed',
    detail: job.error || 'The report failed without an error message.', occurredAt: job.updatedAt};
}

export function recordRunOutcome(entries: RunErrorEntry[], outcome: RunOutcome): RunErrorEntry[] {
  if (outcome.status === 'failed' && outcome.detail.startsWith('NO_RECORD_FOUND')) return entries;
  const key = caseKey(outcome);
  if (outcome.status !== 'failed') {
    const resolution = outcome.status;
    let changed = false;
    const updated = entries.map(entry => {
      if (entry.caseKey !== key || entry.resolution || (entry.occurredAt && outcome.occurredAt
        && Date.parse(entry.occurredAt) > Date.parse(outcome.occurredAt))) return entry;
      changed = true;
      return {...entry, resolvedAt: outcome.occurredAt, resolution};
    });
    return changed ? updated : entries;
  }
  const existing = entries.find(entry => entry.id === outcome.id || (outcome.jobId && entry.jobId === outcome.jobId));
  if (existing) {
    if (existing.occurredAt || !outcome.occurredAt) return entries;
    return entries.map(entry => entry === existing ? {...entry, occurredAt: outcome.occurredAt,
      detail: outcome.detail.slice(0, 4000)} : entry);
  }
  return [{...outcome, name: outcome.name.slice(0, 500), detail: outcome.detail.slice(0, 4000),
    caseKey: key, resolvedAt: null, resolution: null}, ...entries].slice(0, MAX_RUN_ERRORS);
}

export function readRunErrors(raw: string | null): RunErrorEntry[] {
  try {
    const value: unknown = JSON.parse(raw || '[]');
    if (!Array.isArray(value)) return [];
    return value.filter((entry): entry is RunErrorEntry => entry && typeof entry.id === 'string'
      && typeof entry.sessionId === 'string' && typeof entry.caseKey === 'string'
      && typeof entry.name === 'string' && typeof entry.detail === 'string' && entry.status === 'failed'
      && (entry.occurredAt === null || typeof entry.occurredAt === 'string')
      && (entry.resolution === null || ['completed', 'no_data'].includes(entry.resolution))
      && (!entry.filters || (Array.isArray(entry.filters.states) && entry.filters.states.every((v: unknown) => typeof v === 'string')
        && Array.isArray(entry.filters.rtos) && entry.filters.rtos.every((v: unknown) => typeof v === 'string'))))
      .slice(0, MAX_RUN_ERRORS);
  } catch { return []; }
}

export function groupRunErrors(entries: RunErrorEntry[]): {message: string; entries: RunErrorEntry[]}[] {
  const groups = new Map<string, {message: string; entries: RunErrorEntry[]}>();
  for (const entry of entries) {
    // These phrases are added by the batch UI around the original failure.
    const message = entry.detail.trim().replace(/^Automatic retry \d+\/\d+ failed:\s*/i, '')
      .replace(/\s*It will be retried automatically at the next checkpoint\.$/i, '').trim();
    const key = message.replace(/\s+/g, ' ');
    const group = groups.get(key);
    if (group) group.entries.push(entry);
    else groups.set(key, {message, entries: [entry]});
  }
  return [...groups.values()];
}

export function formatRunErrors(entries: RunErrorEntry[]): string {
  const groups = groupRunErrors(entries);
  if (!groups.length) return '';
  const time = (iso: string) => new Date(iso).toLocaleString('en-GB', {timeZone: 'Asia/Ho_Chi_Minh', hour12: false});
  const errors = groups.map((group, index) => {
    const description = describeRunError(group.message);
    const unresolved = group.entries.filter(entry => !entry.resolution).length;
    const reports = [...new Set(group.entries.map(entry => entry.name))];
    const dates = group.entries.map(entry => entry.occurredAt).filter((date): date is string => Boolean(date)
      && Number.isFinite(Date.parse(date!))).sort((a, b) => Date.parse(a) - Date.parse(b));
    return [
      `${index + 1}. ${description.title}`,
      `Message: ${group.message || 'No error message available.'}`,
      `Occurrences: ${group.entries.length} · Unresolved: ${unresolved} · Recovered: ${group.entries.length - unresolved}`,
      dates.length ? `First seen: ${time(dates[0])} · Last seen: ${time(dates[dates.length - 1])} (GMT+7)` : 'Time unavailable',
      `Reports: ${reports.join('; ')}`,
      `Description: ${description.explanation}`,
      `Suggested action: ${description.suggestion}`,
    ].join('\n');
  });
  return `VAHAN run errors · ${groups.length} unique errors\n\n${errors.join('\n\n')}`;
}

export function describeRunError(raw: string): {title: string; explanation: string; suggestion: string} {
  const categories = [
    {match: /MAIN_REPORT_PARSE_FAILED.*(?:OTHERS|OTHER|UNKNOWN)|MAIN_REPORT_UNRESOLVED_MAKERS/i, title: 'Source manufacturer names missing', explanation: 'VAHAN returned an unnamed manufacturer group. Its registrations cannot be assigned to a real manufacturer safely.', suggestion: 'Review the source data and its unresolved counts; repeated retries cannot invent a missing manufacturer name.'},
    {match: /MAIN_REPORT_PARSE_FAILED/i, title: 'Invalid main report data', explanation: 'The workbook could not be validated for the main table. The filter was not saved as a complete report.', suggestion: 'Check the workbook headers, manufacturer names and month counts before retrying.'},
    {match: /VAHAN_REPORT_NAVIGATED_AWAY|redirected away from the Public Report/i, title: 'VAHAN report page redirected', explanation: 'VAHAN left the Public Report page before the result was confirmed.', suggestion: 'Restore the Public Report session and retry the same filter; the redirect does not mean no data.'},
    {match: /Execution context was destroyed|Cannot find context with specified id/i, title: 'Report interrupted by navigation', explanation: 'VAHAN replaced the page document while the browser worker was reading the report result.', suggestion: 'Retry the same report with the updated worker; it waits for the new document without submitting Apply twice.'},
    {match: /RUNNER_BUSY|(?:Browser )?Worker is busy/i, title: 'Browser worker busy', explanation: 'The browser worker was processing or cleaning up an earlier request and could not start this operation yet.', suggestion: 'Wait for the current operation to finish. Options loading now waits for the worker before using a retry attempt.'},
    {match: /FILTER_VERIFICATION_FAILED|FILTER_UNSUPPORTED/i, title: 'Filter validation error', explanation: 'The page filters did not match the requested values, so the report was not applied.', suggestion: 'Reload the report controls and retry with the original filters.'},
    {match: /RTO_OPTIONS_TIMEOUT|#rtoCode:.*options|RTO.*options.*(timeout|timed out)/i, title: 'RTO options timeout', explanation: 'VAHAN did not load the RTO options for the selected State in time.', suggestion: 'Check VAHAN and retry this same State/RTO.'},
    {match: /#xAxis:|X-Axis options did not settle/i, title: 'X-Axis options timeout', explanation: 'VAHAN did not finish loading the X-Axis choices for the selected Y-Axis.', suggestion: 'Retry the same filter after the report controls reload.'},
    {match: /VAHAN_PAGE_NOT_READY|#stateName|page.goto: Timeout/i, title: 'VAHAN page loading timeout', explanation: 'The Public Report page or its State control did not become ready in time.', suggestion: 'Check VAHAN connectivity and retry the same filter.'},
    {match: /Job ended with status CANCELLED|Job was cancelled/i, title: 'Report cancelled', explanation: 'The report was cancelled before completion; this is not a confirmed no-data result.', suggestion: 'Continue the saved session to run the unfinished filter again.'},
    {match: /VAHAN_RESULT_TIMEOUT|wait.*result.*(timeout|timed out)|result.*timed out/i, title: 'Result timeout', explanation: 'VAHAN did not return a confirmed report result in time.', suggestion: 'Retry the same report; a timeout does not confirm that there is no data.'},
    {match: /CAPTCHA_INVALID_LIMIT/i, title: 'CAPTCHA validation limit', explanation: 'VAHAN rejected the CAPTCHA until the attempt limit was reached.', suggestion: 'Retry the report and enter the new CAPTCHA shown in the interface.'},
    {match: /CAPTCHA/i, title: 'CAPTCHA error', explanation: 'Loading, sending or validating the CAPTCHA failed.', suggestion: 'Check the message below and request a fresh CAPTCHA if needed.'},
    {match: /VAHAN_SESSION_EXPIRED|Session Timeout/i, title: 'VAHAN session expired', explanation: 'The VAHAN session expired before the report finished.', suggestion: 'Open VAHAN, restore the session and retry this report.'},
    {match: /VAHAN_AUTH_REQUIRED|HTTP 401/i, title: 'Authentication required', explanation: 'The report request was rejected because authentication was required.', suggestion: 'Restore the relevant sign-in session and retry.'},
    {match: /upload|import|SQL|save.*report|backend no longer|backend.*restart/i, title: 'Report saving / backend error', explanation: 'The report could not be saved or its backend job could not be recovered.', suggestion: 'Check the API connection and retry this report; verify that it appears in the main table.'},
    {match: /VAHAN_SERVER_ERROR|HTTP 5\d\d/i, title: 'Server error', explanation: 'A server returned an error while processing the report.', suggestion: 'Wait briefly, check the original message and retry.'},
    {match: /VAHAN_UNREACHABLE|chrome-error|Failed to fetch|network|connection|Receiving end|runner.*available|Runner is reconnecting/i, title: 'Connection / browser worker error', explanation: 'The interface could not reach VAHAN, the API or an available browser worker.', suggestion: 'Check the network and browser worker, then continue the session.'},
    {match: /timeout|timed out/i, title: 'Operation timeout', explanation: 'An operation did not finish within its waiting time.', suggestion: 'Check the original message to identify the step and retry the affected report.'},
  ];
  return categories.find(category => category.match.test(raw)) || {title: 'Report error', explanation: 'The report did not complete successfully.', suggestion: 'Review the original message below and retry the affected report.'};
}
