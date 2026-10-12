import {useEffect, useState} from 'react';
import {operatorMessage} from '../operator-language';
import {request} from '../services/api-client';
import {uiSocket} from '../services/socket-client';
import {useLiveQuery} from '../hooks/use-live-query';

type Run = {sessionId: string; filterName: string; runNumber: number; totalRuns: number; startedAt: string};
type History = {runs: Run[]; total: number};
const PAGE_SIZE = 50;
const timestamp = (value: string) => new Date(value).toLocaleString('en-GB', {
  timeZone: 'Asia/Ho_Chi_Minh', day: '2-digit', month: '2-digit', year: 'numeric',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});

export function RunHistory() {
  const [offset, setOffset] = useState(0);
  const query = useLiveQuery<History>(offset, signal => request<History>(
    `/api/annual-reports/run-history?offset=${offset}&limit=${PAGE_SIZE}`, {signal}), 1000);
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
      <div><h2>Run History</h2><p>Filter runs, newest first · Vietnam time</p></div>
      <button type="button" onClick={() => query.refresh(true)}>Refresh history</button>
    </div>
    {query.error && <p role="alert">{operatorMessage(query.error)}</p>}
    <section className="run-history-panel" aria-label="Filter run history" aria-busy={query.loading}>
      <div className="run-history-summary"><strong>{total.toLocaleString()} runs</strong>
        <span role="status">{query.loading ? 'Updating history…' : 'Auto-updated'}</span></div>
      <table className="run-history-table">
        <thead><tr><th scope="col">Run</th><th scope="col">Filter</th><th scope="col">Run time</th></tr></thead>
        <tbody>{query.data?.runs.map(run => <tr key={run.sessionId}>
          <td data-label="Run">{run.runNumber.toLocaleString()} / {run.totalRuns.toLocaleString()}</td>
          <th data-label="Filter" scope="row">{run.filterName}</th>
          <td data-label="Run time"><time dateTime={run.startedAt}>{timestamp(run.startedAt)}</time></td>
        </tr>)}</tbody>
      </table>
      {!query.loading && !query.error && !query.data?.runs.length && <p className="run-history-empty">No filter runs yet.</p>}
      {total > PAGE_SIZE && <div className="run-history-pagination">
        <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}</span>
        <div><button type="button" disabled={offset === 0 || query.loading} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>Previous</button>
          <button type="button" disabled={offset + PAGE_SIZE >= total || query.loading} onClick={() => setOffset(value => value + PAGE_SIZE)}>Next</button></div>
      </div>}
    </section>
  </main>;
}
