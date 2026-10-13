import {useEffect, useState} from 'react';
import {operatorMessage} from '../operator-language';
import {request} from '../services/api-client';
import {uiSocket} from '../services/socket-client';
import {useLiveQuery} from '../hooks/use-live-query';
import {useDisplayTimeZone} from '../display-time-zone';
import {formatUiDateTime, runTimeZoneLabel} from '../run-schedules';

type Run = {
  sessionId: string; filterName: string; runNumber: number; totalRuns: number; startedAt: string;
  status: string; processed: number | null; totalCases: number | null;
  withData: number | null; noData: number | null; failed: number | null;
  pending: number | null; running: number | null; lastActivityAt: string | null; finishedAt: string | null;
};
type History = {runs: Run[]; total: number};
const PAGE_SIZE = 50;
const count = (value: number | null) => value == null ? '—' : value.toLocaleString();
const statusLabels: Record<string, string> = {
  RUNNING: 'Running', PAUSED: 'Paused', PAUSING: 'Pausing', STOPPED: 'Stopped',
  PREPARING: 'Preparing', RESUMING: 'Resuming', COMPLETED: 'Completed',
  COMPLETED_WITH_ERRORS: 'Completed with errors', ERROR: 'Error', UNKNOWN: 'Details unavailable',
};

export function RunHistory() {
  const {timeZone} = useDisplayTimeZone();
  const timestamp = (value: string) => formatUiDateTime(value, timeZone, {second: '2-digit'});
  const [offset, setOffset] = useState(0);
  const query = useLiveQuery<History>(offset,
    signal => request<History>(`/api/annual-reports/run-history?offset=${offset}&limit=${PAGE_SIZE}`, {signal}), 1000);
  useEffect(() => {
    const refresh = () => query.refresh();
    const timer = window.setInterval(refresh, 15000);
    uiSocket.on('job:status', refresh);
    uiSocket.on('connect', refresh);
    return () => {
      window.clearInterval(timer);
      uiSocket.off('job:status', refresh);
      uiSocket.off('connect', refresh);
    };
  }, [query.refresh]);
  useEffect(() => {
    if (query.data && offset > 0 && offset >= query.data.total) setOffset(0);
  }, [query.data, offset]);
  const total = query.data?.total ?? 0;
  return <main className="page-content run-history-page" id="run-history">
    <div className="section-intro run-history-intro">
      <div><h2>Run History</h2><p>One row per run, newest first · {runTimeZoneLabel(timeZone)}</p></div>
      <div className="run-history-actions">
        <button className="run-history-refresh" type="button" onClick={() => query.refresh(true)}>Refresh history</button>
      </div>
    </div>
    {query.error && <p role="alert">{operatorMessage(query.error)}</p>}
    <section className="run-history-panel" aria-label="Filter run history" aria-busy={query.loading}>
      <div className="run-history-summary"><strong>{total.toLocaleString()} runs</strong>
        <span role="status">{query.loading ? 'Updating history…' : 'Auto-updated'}</span></div>
      <table className="run-history-table">
        <thead><tr><th scope="col">Run</th><th scope="col">Filter</th><th scope="col">Progress</th>
          <th scope="col">Status</th><th scope="col">Results</th><th scope="col">Run time</th></tr></thead>
        <tbody>{query.data?.runs.map(run => <tr key={run.sessionId}>
          <td data-label="Run"><div><strong>#{run.runNumber.toLocaleString()}</strong><small>{run.totalRuns.toLocaleString()} runs</small></div></td>
          <th data-label="Filter" scope="row">{run.filterName}</th>
          <td data-label="Progress"><div className="run-history-progress">
            <strong>{count(run.processed)} / {count(run.totalCases)}</strong>
            <small>cases processed{run.totalCases ? ` · ${((run.processed ?? 0) / run.totalCases * 100).toFixed(1)}%` : ''}</small>
            {run.totalCases != null && <progress aria-label={`Run ${run.runNumber} cases processed`}
              value={run.processed ?? 0} max={run.totalCases || 1}/>}
          </div></td>
          <td data-label="Status"><div><span className="run-history-status" data-status={run.status}>
            {statusLabels[run.status] ?? run.status}</span>
            {run.pending != null && run.running != null && <small>{count(run.pending)} pending · {count(run.running)} running</small>}
          </div></td>
          <td data-label="Results"><div className="run-history-results">
            <span>With data <strong>{count(run.withData)}</strong></span>
            <span>No data <strong>{count(run.noData)}</strong></span>
            <span className={run.failed ? 'has-failures' : ''}>Failed <strong>{count(run.failed)}</strong></span>
          </div></td>
          <td data-label="Run time"><div className="run-history-times">
            <span><small>Started</small><time dateTime={run.startedAt}>{timestamp(run.startedAt)}</time></span>
            {(run.finishedAt || run.lastActivityAt) && <span><small>{run.finishedAt ? 'Finished' : 'Last activity'}</small>
              <time dateTime={(run.finishedAt || run.lastActivityAt)!}>{timestamp((run.finishedAt || run.lastActivityAt)!)}</time></span>}
          </div></td>
        </tr>)}</tbody>
      </table>
      <p className="run-history-note">Processed cases include results with data, no data and failures. Retries stay in the same run.</p>
      {!query.loading && !query.error && !query.data?.runs.length && <p className="run-history-empty">No filter runs yet.</p>}
      {total > PAGE_SIZE && <div className="run-history-pagination">
        <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}</span>
        <div><button type="button" disabled={offset === 0 || query.loading} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>Previous</button>
          <button type="button" disabled={offset + PAGE_SIZE >= total || query.loading} onClick={() => setOffset(value => value + PAGE_SIZE)}>Next</button></div>
      </div>}
    </section>
  </main>;
}
