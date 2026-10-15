import {useEffect, useRef, useState} from 'react';
import {useDisplayTimeZone} from '../display-time-zone';
import {formatScheduledTime, type RunSchedule} from '../run-schedules';
import {operatorMessage,operatorStage,operatorStatus,reportBrowserName} from '../operator-language';

function elapsed(seconds: number | null | undefined) {
  if (seconds == null) return '—';
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function RunDiagnostics({schedule}: {schedule: RunSchedule}) {
  const {timeZone} = useDisplayTimeZone();
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
    <div className="run-diagnostics-heading"><h4>Current activity</h4><span className="diagnostics-current-step" title={operatorStage(stage)}>{operatorStage(stage)}</span><button type="button" className="secondary-button" aria-haspopup="dialog" aria-expanded={detailsOpen} onClick={() => setDetailsOpen(value => !value)}>{detailsOpen ? 'Hide details' : 'View details'}</button><button type="button" className="secondary-button" onClick={() => void copy()}>Copy for support</button></div>
    {(warning || error || schedule.status === 'ERROR') && <p className="run-diagnostics-detail">{operatorMessage(schedule.message) || 'Waiting for the scheduled start.'}</p>}
    {warning && <p role="alert" className="schedule-error">{operatorMessage(warning)}</p>}
    {error && error !== schedule.message && <p role="alert" className="schedule-error">{operatorMessage(error)}</p>}
    {copyState && <p role="status">{copyState}</p>}
    <dialog ref={detailsDialog} className="run-diagnostics-dialog" aria-labelledby={`run-diagnostics-title-${schedule.id}`}
      onCancel={() => setDetailsOpen(false)} onClose={() => setDetailsOpen(false)}
      onClick={event => {if (event.target === event.currentTarget) setDetailsOpen(false);}}>
      <div className="run-diagnostics-dialog-heading"><div><h3 id={`run-diagnostics-title-${schedule.id}`}>Activity details</h3><p>{schedule.profileName} · {operatorStage(stage)}</p></div>
        <button type="button" className="run-diagnostics-close" aria-label="Close details" title="Close" onClick={() => setDetailsOpen(false)}>×</button></div>
      <div className="run-diagnostics-dialog-body">
        <dl className="run-diagnostics-summary">
          <div><dt>Time at this step</dt><dd>{active ? elapsed(diagnostics?.stageAgeSeconds) : '—'}</dd></div>
          <div><dt>Last progress update</dt><dd>{formatScheduledTime(schedule.operation?.heartbeatAt || schedule.updatedAt || null, timeZone)}</dd></div>
        </dl>
        <p className="run-diagnostics-detail">{operatorMessage(schedule.message) || 'Waiting for the scheduled start.'}</p>
        {error && error !== schedule.message && <p role="alert" className="schedule-error">{operatorMessage(error)}</p>}
        {active && schedule.retryAfter && <p>Next automatic attempt: {formatScheduledTime(schedule.retryAfter, timeZone)}</p>}
        {warning && <p role="alert" className="schedule-error">{operatorMessage(warning)}</p>}
        {active && diagnostics && <details open><summary>Report browsers · checked {formatScheduledTime(diagnostics.checkedAt, timeZone)}</summary>
          <div className="schedule-failed-scroll"><table><thead><tr><th>Browser</th><th>Current report</th><th>Time since last change</th><th>Connection</th></tr></thead>
            <tbody>{diagnostics.workers.map((worker,index) => <tr key={worker.id}><td>{reportBrowserName(worker.id,index)}{!worker.selected && ' (not used for this run)'}</td>
              <td>{worker.optionsBusy ? 'Loading choices / checking website' : worker.status === 'IDLE' ? 'Waiting for a report' : operatorStatus(worker.status)}
                {worker.case && <p>{worker.case}</p>}{worker.error && <p>{operatorMessage(worker.error)}</p>}</td>
              <td>{elapsed(worker.jobAgeSeconds ?? worker.heartbeatAgeSeconds)}</td>
              <td>{worker.reachable === false ? 'Could not check connection' : !worker.connected ? 'Not connected' : worker.browserReady === false ? 'Browser not ready' : 'Connected'}</td></tr>)}</tbody></table></div>
        </details>}
      </div>
    </dialog>
  </section>;
}
