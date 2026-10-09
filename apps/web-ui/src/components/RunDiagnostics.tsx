import {useEffect, useRef, useState} from 'react';
import {formatScheduledTime, type RunSchedule} from '../run-schedules';

function elapsed(seconds: number | null | undefined) {
  if (seconds == null) return '—';
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function RunDiagnostics({schedule}: {schedule: RunSchedule}) {
  const [copyState, setCopyState] = useState('');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = detailsDialog.current;
    if (!dialog) return;
    if (detailsOpen && !dialog.open) dialog.showModal();
    else if (!detailsOpen && dialog.open) dialog.close();
  }, [detailsOpen]);
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
  return <section className={`run-diagnostics ${warning || error ? 'run-diagnostics-warning' : ''}`} aria-label={`System activity for ${schedule.profileName}`} data-expanded={detailsOpen}>
    <div className="run-diagnostics-heading"><h4>System activity</h4><span className="diagnostics-current-step" title={stage}>{stage}</span><button type="button" className="secondary-button" aria-haspopup="dialog" aria-expanded={detailsOpen} onClick={() => setDetailsOpen(value => !value)}>{detailsOpen ? 'Hide details' : 'View details'}</button><button type="button" className="secondary-button" onClick={() => void copy()}>Copy diagnostics</button></div>
    {(warning || error || schedule.status === 'ERROR') && <p className="run-diagnostics-detail">{schedule.message || 'Waiting for the scheduled start.'}</p>}
    {warning && <p role="alert" className="schedule-error">{warning}</p>}
    {error && error !== schedule.message && <p role="alert" className="schedule-error">{error}</p>}
    {copyState && <p role="status">{copyState}</p>}
    <dialog ref={detailsDialog} className="run-diagnostics-dialog" aria-labelledby={`run-diagnostics-title-${schedule.id}`}
      onCancel={() => setDetailsOpen(false)} onClose={() => setDetailsOpen(false)}
      onClick={event => {if (event.target === event.currentTarget) setDetailsOpen(false);}}>
      <div className="run-diagnostics-dialog-heading"><div><h3 id={`run-diagnostics-title-${schedule.id}`}>System activity details</h3><p>{schedule.profileName} · {stage}</p></div>
        <button type="button" className="run-diagnostics-close" aria-label="Close details" title="Close" onClick={() => setDetailsOpen(false)}>×</button></div>
      <div className="run-diagnostics-dialog-body">
        <dl className="run-diagnostics-summary">
          <div><dt>Time at this step</dt><dd>{active ? elapsed(diagnostics?.stageAgeSeconds) : '—'}</dd></div>
          <div><dt>Last scheduler update</dt><dd>{formatScheduledTime(schedule.operation?.heartbeatAt || schedule.updatedAt || null)}</dd></div>
        </dl>
        <p className="run-diagnostics-detail">{schedule.message || 'Waiting for the scheduled start.'}</p>
        {error && error !== schedule.message && <p role="alert" className="schedule-error">{error}</p>}
        {active && schedule.retryAfter && <p>Next preparation retry: {formatScheduledTime(schedule.retryAfter)}</p>}
        {warning && <p role="alert" className="schedule-error">{warning}</p>}
        {active && diagnostics && <details open><summary>Worker details · checked {formatScheduledTime(diagnostics.checkedAt)}</summary>
          <div className="schedule-failed-scroll"><table><thead><tr><th>Worker</th><th>Activity / case</th><th>Last change</th><th>Connection</th></tr></thead>
            <tbody>{diagnostics.workers.map(worker => <tr key={worker.id}><td>{worker.id}{!worker.selected && ' (outside selected pool)'}</td>
              <td>{worker.optionsBusy ? 'Loading options / checking website' : worker.status === 'IDLE' ? 'Waiting for assignment' : worker.status}
                {worker.case && <p>{worker.case}</p>}{worker.error && <p>{worker.error}</p>}</td>
              <td>{elapsed(worker.jobAgeSeconds ?? worker.heartbeatAgeSeconds)}</td>
              <td>{worker.reachable === false ? 'Health endpoint unavailable' : !worker.connected ? 'Disconnected' : worker.browserReady === false ? 'Browser not ready' : 'Connected'}</td></tr>)}</tbody></table></div>
        </details>}
      </div>
    </dialog>
  </section>;
}
