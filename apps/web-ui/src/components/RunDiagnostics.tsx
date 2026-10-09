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
  const diagnostics = schedule.diagnostics;
  const active = ['PREPARING', 'RESUMING', 'RUNNING', 'PAUSING'].includes(schedule.status);
  const stage = active ? schedule.operation?.stage || schedule.status : schedule.status;
  const warning = active ? diagnostics?.warning : null;
  const error = schedule.operation?.error;
  const dialogId = `run-diagnostics-dialog-${schedule.id}`;

  useEffect(() => {
    const dialog = detailsDialog.current;
    if (detailsOpen) {
      if (dialog && !dialog.open) dialog.showModal();
    } else if (dialog?.open) dialog.close();
  }, [detailsOpen]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(JSON.stringify({scheduleId: schedule.id, profile: schedule.profileName,
        sessionId: schedule.sessionId || schedule.lastSessionId, status: schedule.status,
        message: schedule.message, operation: schedule.operation, retryAfter: schedule.retryAfter,
        progress: {done: schedule.done, total: schedule.total, failed: schedule.failed}, diagnostics}, null, 2));
      setCopyState('Copied');
    } catch {setCopyState('Copy failed. Please allow clipboard access.');}
  }
  return <section className={`run-diagnostics ${warning || error ? 'run-diagnostics-warning' : ''}`} aria-label={`System activity for ${schedule.profileName}`}>
    <div className="run-diagnostics-heading"><h4>System activity</h4><span className="diagnostics-current-step" title={stage}>{stage}</span><button type="button" className="secondary-button" aria-haspopup="dialog" aria-controls={dialogId} aria-expanded={detailsOpen} onClick={() => setDetailsOpen(true)}>View details</button><button type="button" className="secondary-button" onClick={() => void copy()}>Copy diagnostics</button></div>
    {(warning || error || schedule.status === 'ERROR') && <p className="run-diagnostics-detail">{schedule.message || 'Waiting for the scheduled start.'}</p>}
    {error && error !== schedule.message && <p role="alert" className="schedule-error">{error}</p>}
    {active && schedule.retryAfter && <p>Next preparation retry: {formatScheduledTime(schedule.retryAfter)}</p>}
    {warning && <p role="alert" className="schedule-error">{warning}</p>}
    {copyState && <p role="status">{copyState}</p>}
    <dialog ref={detailsDialog} id={dialogId} className="run-diagnostics-dialog" aria-labelledby={`${dialogId}-title`}
      onCancel={() => setDetailsOpen(false)}
      onClick={event => {if (event.target === event.currentTarget) setDetailsOpen(false);}}>
      <div className="run-diagnostics-dialog-header"><div><span className="settings-eyebrow">SYSTEM ACTIVITY</span><h3 id={`${dialogId}-title`}>Run details</h3>
        <p><strong>{schedule.profileName}</strong><span aria-hidden="true"> · </span>{stage}</p></div>
        <button type="button" className="run-diagnostics-dialog-close" aria-label="Close run details" onClick={() => setDetailsOpen(false)}>×</button></div>
      <dl className="run-diagnostics-summary">
        <div><dt>Time at this step</dt><dd>{active ? elapsed(diagnostics?.stageAgeSeconds) : '—'}</dd></div>
        <div><dt>Last scheduler update</dt><dd>{formatScheduledTime(schedule.operation?.heartbeatAt || schedule.updatedAt || null)}</dd></div>
      </dl>
      <p className="run-diagnostics-detail">{schedule.message || 'Waiting for the scheduled start.'}</p>
      {error && error !== schedule.message && <p role="alert" className="schedule-error">{error}</p>}
      {active && schedule.retryAfter && <p>Next preparation retry: {formatScheduledTime(schedule.retryAfter)}</p>}
      {warning && <p role="alert" className="schedule-error">{warning}</p>}
      {active && diagnostics && <section className="run-diagnostics-workers" aria-labelledby={`${dialogId}-workers-title`}>
        <h4 id={`${dialogId}-workers-title`}>Worker details · checked {formatScheduledTime(diagnostics.checkedAt)}</h4>
        <div className="schedule-failed-scroll"><table><thead><tr><th>Worker</th><th>Activity / case</th><th>Last change</th><th>Connection</th></tr></thead>
          <tbody>{diagnostics.workers.map(worker => <tr key={worker.id}><td>{worker.id}{!worker.selected && ' (outside selected pool)'}</td>
            <td>{worker.optionsBusy ? 'Loading options / checking website' : worker.status === 'IDLE' ? 'Waiting for assignment' : worker.status}
              {worker.case && <p>{worker.case}</p>}{worker.error && <p>{worker.error}</p>}</td>
            <td>{elapsed(worker.jobAgeSeconds ?? worker.heartbeatAgeSeconds)}</td>
            <td>{worker.reachable === false ? 'Health endpoint unavailable' : !worker.connected ? 'Disconnected' : worker.browserReady === false ? 'Browser not ready' : 'Connected'}</td></tr>)}</tbody></table></div>
      </section>}
      <div className="run-diagnostics-dialog-actions"><button type="button" className="secondary-button" onClick={() => setDetailsOpen(false)}>Close</button></div>
    </dialog>
  </section>;
}
