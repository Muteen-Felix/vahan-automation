import { useState } from 'react';
import type { Scenario } from '../contracts';

interface CompletedTask {
  index: number;
  state?: string;
  rto?: string;
  status: 'ok' | 'empty' | 'error';
  jobId?: string;
  completedAt?: string;
  savedAt?: string;
  rowCount?: number;
}

const PAGE_SIZE = 10;
function confirmedTime(value?: string): string {
  if (!value || !Number.isFinite(Date.parse(value))) return '—';
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    timeZone: 'Asia/Ho_Chi_Minh',
  }).format(new Date(value));
}

export function CompletedTasks({ log, scenarios }: { log: CompletedTask[]; scenarios: Scenario[] }) {
  const [page, setPage] = useState(0);
  const saved = log.filter(entry => entry.jobId && (entry.status === 'ok' || entry.status === 'empty'))
    .sort((left, right) => (Date.parse(right.savedAt || right.completedAt || '') || 0)
      - (Date.parse(left.savedAt || left.completedAt || '') || 0) || right.index - left.index);
  const pages = Math.max(1, Math.ceil(saved.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages - 1);
  const start = currentPage * PAGE_SIZE;
  const visible = saved.slice(start, start + PAGE_SIZE);
  return <section className="completed-tasks" aria-labelledby="completed-tasks-title">
    <div className="completed-tasks-heading">
      <div><h3 id="completed-tasks-title">Completed &amp; saved tasks</h3><p>Current session · latest results first · Vietnam time</p></div>
      <span>{saved.length.toLocaleString('en-GB')} saved</span>
    </div>
    {visible.length ? <>
      <div className="completed-tasks-scroll">
        <table>
          <thead><tr><th>Task</th><th>State</th><th>RTO</th><th>Result</th><th>Confirmed at</th></tr></thead>
          <tbody>{visible.map(entry => <tr key={entry.index}>
            <td>{entry.index + 1}</td>
            <td>{entry.state || scenarios[entry.index]?.filters.states[0] || '—'}</td>
            <td>{entry.rto || scenarios[entry.index]?.filters.rtos[0] || '—'}</td>
            <td><span className="completed-task-result" data-result={entry.status}>
              {entry.status === 'empty' ? 'No record found · saved' : 'Data saved'}
            </span>{entry.status === 'ok' && entry.rowCount !== undefined && <small>{entry.rowCount.toLocaleString('en-GB')} manufacturer rows</small>}</td>
            <td><time dateTime={entry.savedAt || entry.completedAt}>{confirmedTime(entry.savedAt || entry.completedAt)}</time></td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="completed-tasks-pagination">
        <span>{start + 1}–{Math.min(start + PAGE_SIZE, saved.length)} of {saved.length.toLocaleString('en-GB')}</span>
        <div><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Newer</button>
          <button type="button" disabled={currentPage === pages - 1} onClick={() => setPage(currentPage + 1)}>Older</button></div>
      </div>
    </> : <p className="completed-tasks-empty">Tasks appear here after their results are confirmed saved to SQL.</p>}
  </section>;
}
