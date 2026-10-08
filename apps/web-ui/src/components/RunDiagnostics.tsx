import {useState} from 'react';
import {formatScheduledTime, type RunSchedule} from '../run-schedules';

function elapsed(seconds: number | null | undefined) {
  if (seconds == null) return '—';
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function RunDiagnostics({schedule}: {schedule: RunSchedule}) {
  const [copyState, setCopyState] = useState('');
  const [expanded, setExpanded] = useState(false);
  const diagnostics = schedule.diagnostics;
  const active = ['PREPARING', 'RESUMING', 'RUNNING', 'PAUSING'].includes(schedule.status);
  const stage = active ? schedule.operation?.stage || schedule.status : schedule.status;
  const warning = active ? diagnostics?.warning : null;
  const error = schedule.operation?.error;
  async function copy() {
    try {
      await navigator.clipboard.writeText(JSON.stringify({scheduleId: schedule.id, profile: schedule.profileName,
        sessionId: schedule.sessionId || schedule.lastSessionId, status: schedule.status,
        message: schedule.message, operation: schedule.operation, retryAfter: schedule.retryAfter,
        progress: {done: schedule.done, total: schedule.total, failed: schedule.failed}, diagnostics}, null, 2));
      setCopyState('Copied');
    } catch {setCopyState('Copy failed. Please allow clipboard access.');}
  }
  return <section className={`run-diagnostics ${warning || error ? 'run-diagnostics-warning' : ''}`} aria-label={`System activity for ${schedule.profileName}`} data-expanded={expanded}>
    <div className="run-diagnostics-heading"><h4>System activity</h4><span className="diagnostics-current-step" title={stage}>{stage}</span><button type="button" className="secondary-button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? 'Hide details' : 'View details'}</button><button type="button" className="secondary-button" onClick={() => void copy()}>Copy diagnostics</button></div>
    <div hidden={!expanded}><dl className="run-diagnostics-summary">
      <div><dt>Time at this step</dt><dd>{active ? elapsed(diagnostics?.stageAgeSeconds) : '—'}</dd></div>
      <div><dt>Last scheduler update</dt><dd>{formatScheduledTime(schedule.operation?.heartbeatAt || schedule.updatedAt || null)}</dd></div>
    </dl>
    </div>
    {(expanded || warning || error || schedule.status === 'ERROR') && <p className="run-diagnostics-detail">{schedule.message || 'Waiting for the scheduled start.'}</p>}
    {error && error !== schedule.message && <p role="alert" className="schedule-error">{error}</p>}
    {active && schedule.retryAfter && <p>Next preparation retry: {formatScheduledTime(schedule.retryAfter)}</p>}
    {warning && <p role="alert" className="schedule-error">{warning}</p>}
    {expanded && active && diagnostics && <details><summary>Worker details · checked {formatScheduledTime(diagnostics.checkedAt)}</summary>
      <div className="schedule-failed-scroll"><table><thead><tr><th>Worker</th><th>Activity / case</th><th>Last change</th><th>Connection</th></tr></thead>
        <tbody>{diagnostics.workers.map(worker => <tr key={worker.id}><td>{worker.id}{!worker.selected && ' (outside selected pool)'}</td>
          <td>{worker.optionsBusy ? 'Loading options / checking website' : worker.status === 'IDLE' ? 'Waiting for assignment' : worker.status}
            {worker.case && <p>{worker.case}</p>}{worker.error && <p>{worker.error}</p>}</td>
          <td>{elapsed(worker.jobAgeSeconds ?? worker.heartbeatAgeSeconds)}</td>
          <td>{worker.reachable === false ? 'Health endpoint unavailable' : !worker.connected ? 'Disconnected' : worker.browserReady === false ? 'Browser not ready' : 'Connected'}</td></tr>)}</tbody></table></div>
    </details>}
    {copyState && <p role="status">{copyState}</p>}
  </section>;
}
