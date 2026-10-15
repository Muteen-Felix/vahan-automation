import {operatorMessage} from '../operator-language';
import {useEffect, useRef, useState, type FormEvent} from 'react';
import type {FilterProfile} from '../filter-profiles';
import {api} from '../services/api-client';
import {useDisplayTimeZone} from '../display-time-zone';
import {canResumeSchedule, formatScheduledTime, runTimeZoneLabel,
  scheduleDateTime, scheduleDateTimeIso,
  scheduledDayOfMonth, sortRunSchedules, type RunSchedule} from '../run-schedules';
import {RunScheduleProgress} from './RunScheduleProgress';
import {BatchRetryStatus} from './BatchRetryStatus';
import {RunDiagnostics} from './RunDiagnostics';
import {FailedBatchCases} from './FailedBatchCases';

const STATUS_LABELS: Record<RunSchedule['status'], string> = {
  WAITING: 'Scheduled', PREPARING: 'Preparing', RUNNING: 'Running', COMPLETED: 'Completed',
  PAUSING: 'Pausing', PAUSED: 'Paused', RESUMING: 'Continuing',
  COMPLETED_WITH_ERRORS: 'Some reports unfinished', ERROR: 'Needs attention', STOPPED: 'Stopped',
};

interface Props {
  profiles: FilterProfile[];
  selectedProfileId: string;
  year: number;
  schedules: RunSchedule[];
  loading: boolean;
  loadError: string;
  onUpsert: (value: RunSchedule) => void;
  onDelete: (id: string) => void;
}

export function AutomaticRunSettings({profiles, selectedProfileId, year, schedules, loading, loadError, onUpsert, onDelete}: Props) {
  const {timeZone} = useDisplayTimeZone();
  const initial = scheduleDateTime(new Date(Date.now() + 5 * 60_000), timeZone);
  const [profileId, setProfileId] = useState(selectedProfileId);
  const [date, setDate] = useState(initial.date);
  const [time, setTime] = useState(initial.time);
  const [repeat, setRepeat] = useState<'once' | 'monthly'>('once');
  const [saving, setSaving] = useState(false);
  const [actionId, setActionId] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const formDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const next = scheduleDateTime(new Date(Date.now() + 5 * 60_000), timeZone);
    setDate(next.date);
    setTime(next.time);
  }, [timeZone]);
  useEffect(() => {
    const dialog = formDialog.current;
    if (!dialog) return;
    if (formOpen && !dialog.open) dialog.showModal();
    else if (!formOpen && dialog.open) dialog.close();
  }, [formOpen]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const profile = profiles.find(item => item.id === profileId);
  const selectedYear = profile?.definition.report?.year ?? year;

  useEffect(() => {
    if (!profiles.some(item => item.id === profileId)) {
      setProfileId(profiles.some(item => item.id === selectedProfileId) ? selectedProfileId : profiles[0]?.id || '');
    }
  }, [profiles, selectedProfileId, profileId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const startsAt = scheduleDateTimeIso(date, time, timeZone);
    if (!profile || !date || !time || !Number.isFinite(Date.parse(startsAt)) || Date.parse(startsAt) <= Date.now()) {
      setError('Choose saved filters and a future date and time.');
      return;
    }
    setSaving(true); setError(''); setNotice('');
    try {
      const saved = await api.createRunSchedule({profileId, year: selectedYear, startsAt, timeZone, repeat});
      onUpsert(saved);
      setNotice(`Schedule saved for ${formatScheduledTime(saved.nextRunAt, timeZone)} (${runTimeZoneLabel(timeZone)}).`);
      setFormOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save the run schedule.');
    } finally {setSaving(false);}
  }

  async function action(schedule: RunSchedule, type: 'toggle' | 'pause' | 'resume' | 'delete') {
    setActionId(schedule.id); setError(''); setNotice('');
    try {
      if (type === 'delete') {
        await api.deleteRunSchedule(schedule.id);
        onDelete(schedule.id);
      } else {
        const updated = type === 'pause' ? await api.pauseRunSchedule(schedule.id)
          : type === 'resume' ? await api.resumeRunSchedule(schedule.id)
          : await api.toggleRunSchedule(schedule.id, !schedule.enabled);
        onUpsert(updated);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not update the run schedule.');
    } finally {setActionId('');}
  }

  return <div className="automatic-run-settings">
    <section className="panel automatic-run-panel" aria-labelledby="automatic-run-heading">
      <div className="panel-heading"><div>
        <h2 id="automatic-run-heading">Automatic report schedule</h2>
        <p>Schedule and follow report collection.</p>
      </div><button type="button" className="secondary-button schedule-form-toggle" aria-haspopup="dialog" aria-expanded={formOpen} aria-controls="new-schedule-form"
        onClick={() => {setError('');setNotice('');setFormOpen(true);}}>Create schedule</button></div>
      <dialog ref={formDialog} id="new-schedule-form" className="schedule-form-dialog" aria-labelledby="new-schedule-title"
        onCancel={event => {if (saving) event.preventDefault(); else setFormOpen(false);}}
        onClose={() => setFormOpen(false)}
        onClick={event => {if (event.target === event.currentTarget && !saving) setFormOpen(false);}}>
        <div className="schedule-form-dialog-header"><div><span className="settings-eyebrow">AUTOMATIC RUN</span><h3 id="new-schedule-title">Schedule a report</h3>
          <p>Choose saved filters and when to collect the reports.</p></div>
          <button type="button" className="schedule-form-dialog-close" aria-label="Hide form" title="Hide form" disabled={saving} onClick={() => setFormOpen(false)}>×</button></div>
        <div className="schedule-form-dialog-body">
          {error && <p className="schedule-dialog-error" role="alert">{operatorMessage(error)}</p>}
          <form className="automatic-run-form" onSubmit={save}>
            <label className="schedule-profile-label">Saved filters
              <select aria-label="Saved filters" value={profileId} onChange={event => setProfileId(event.target.value)} required disabled={saving || !profiles.length}>
                {!profiles.length && <option value="">No saved filters</option>}
                {profiles.map(item => <option key={item.id} value={item.id}>{item.name} · {item.definition.report?.year ?? year}</option>)}
              </select>
            </label>
            <label>Start date<input aria-label="Start date" type="date" value={date} onChange={event => setDate(event.target.value)} required disabled={saving} /></label>
            <label>Start time<input aria-label="Start time" type="time" value={time} onChange={event => setTime(event.target.value)} required disabled={saving} /></label>
            <label>Repeat<select aria-label="Repeat" value={repeat} onChange={event => setRepeat(event.target.value as 'once' | 'monthly')} disabled={saving}>
              <option value="once">Once</option><option value="monthly">Every month</option>
            </select></label>
            <div className="automatic-run-form-footer"><span>{runTimeZoneLabel(timeZone)}</span>
              <button className="primary-button" type="submit" disabled={saving || loading || !profile}>{saving ? 'Saving…' : 'Add schedule'}</button>
            </div>
          </form>
          <div className="schedule-help-slot"><p className="schedule-help">{repeat === 'monthly'
            ? `Uses the saved filters above to collect reports for year ${selectedYear}. Runs on day ${Number(date.slice(-2))} of each month at the selected time and time zone. If a month has fewer days, it runs on that month's last day (for example, day 31 runs on February's last day). After the final run for report year ${selectedYear}, this schedule ends. If it is still enabled, the system creates a separate copy of the saved filters with the same search settings and only the report year changed to ${selectedYear + 1}. A new monthly schedule then uses the same day, time, and time zone. This repeats automatically each year. Disable this schedule to stop the rollover.`
            : !profiles.length
            ? <><a href="#filters">Save your filters</a> before adding a schedule.</>
            : 'Runs once on the selected date and time, using the saved filters and selected time zone. It will not repeat or create a filter or schedule for a following year.'}</p></div>
        </div>
      </dialog>
      <div className={`schedule-feedback${loadError || (!formOpen && (error || notice)) ? ' has-feedback' : ''}`}>
        {(loadError || (!formOpen && error)) ? <p className="schedule-error" role="alert" title={operatorMessage(loadError || error)}>{operatorMessage(loadError || error)}</p>
          : <p className="schedule-notice" role="status" title={notice}>{notice || '\u00a0'}</p>}
      </div>
      <div className="run-schedule-list-heading" id="saved-schedules"><h3>Saved schedules</h3><span>{schedules.length} {schedules.length === 1 ? 'schedule' : 'schedules'}</span></div>
      <div className="run-schedule-list">
        {loading ? <p>Loading schedules…</p> : !schedules.length ? <p className="schedule-empty">No automatic report schedules yet.</p> :
          sortRunSchedules(schedules).map(schedule => <div className="schedule-run-entry" key={schedule.id}><article className="run-schedule-card" aria-label={`Schedule for ${schedule.profileName}`}>
            <div className="run-schedule-title">
              <div className="run-schedule-identity"><span className="run-schedule-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v4M16 3v4M4 10h16M8 14h3M8 17h7"/></svg>
              </span><div className="run-schedule-name"><strong title={schedule.profileName}>{schedule.profileName}</strong><small>Calendar year {schedule.year}</small></div></div>
              <span className={`schedule-status schedule-status-${schedule.status.toLowerCase()}`} aria-live="polite">
                {!schedule.enabled && !schedule.sessionId && schedule.nextRunAt ? 'Disabled' : schedule.networkPaused ? 'Waiting for network' : STATUS_LABELS[schedule.status]}
              </span></div>
            <dl className="run-schedule-details">
              <div className="run-schedule-start"><dt>{schedule.nextRunAt ? 'Next start' : 'Scheduled start'}</dt><dd title={formatScheduledTime(schedule.nextRunAt ?? schedule.startsAt, timeZone)}>{formatScheduledTime(schedule.nextRunAt ?? schedule.startsAt, timeZone)}</dd><small>{runTimeZoneLabel(timeZone)}</small></div>
              <div><dt>Repeat</dt><dd>{schedule.annualSuccessorScheduleId ? `Ended after ${schedule.year}`
                : schedule.repeat === 'monthly' ? 'Every month' : 'Once'}</dd>
                <small>{schedule.annualSuccessorScheduleId
                  ? `A separate ${schedule.annualRolloverYear ?? schedule.year + 1} filter and schedule are active`
                  : schedule.repeat === 'monthly' ? `Day ${scheduledDayOfMonth(schedule.startsAt, timeZone)} · month-end if needed · new filter each year`
                  : 'One scheduled run'}</small></div>
              <div><dt>Report browsers</dt><dd>Automatic</dd><small>Uses connected browsers; waits when none are available</small></div>
            </dl>
            <RunScheduleProgress schedule={schedule} statusLabel={!schedule.enabled && !schedule.sessionId && schedule.nextRunAt ? 'Disabled' : schedule.networkPaused ? 'Waiting for network' : STATUS_LABELS[schedule.status]} />
            <div className="schedule-retry-slot">
              {schedule.message && (['PREPARING','RESUMING','PAUSING','ERROR'].includes(schedule.status)
                  || /^(Waiting|Could not|A worker|Docker)/i.test(schedule.message))
                ? <p className={`schedule-retry-note schedule-run-message${schedule.status==='ERROR'?' has-error':''}`}
                    role={schedule.status==='ERROR'?'alert':'status'} title={operatorMessage(schedule.message)}>{operatorMessage(schedule.message)}</p>
                : schedule.retryProgress&&schedule.retryProgress.phase!=='PRIMARY'&&!(schedule.retryProgress.phase==='DONE'&&!schedule.failed)
                ?<BatchRetryStatus progress={schedule.retryProgress} running={schedule.status==='RUNNING'}/>
                :<p className="schedule-retry-note">Unfinished reports are tried again after each group, with one final check at the end.</p>}
            </div>
            <div className="run-schedule-actions">
              <button type="button" className="secondary-button"
                title={schedule.annualSuccessorScheduleId
                  ? `The ${schedule.year} filter has ended. Use the ${schedule.annualRolloverYear ?? schedule.year + 1} schedule.`
                  : 'Enable or disable future starts. A running report continues until stopped.'}
                disabled={Boolean(actionId) || Boolean(schedule.annualSuccessorScheduleId) || (schedule.repeat === 'once' && !schedule.nextRunAt)}
                onClick={() => void action(schedule, 'toggle')}>{schedule.annualSuccessorScheduleId ? 'Year complete'
                  : schedule.repeat === 'once' && !schedule.nextRunAt ? 'No future runs' : schedule.enabled ? 'Disable future runs' : 'Enable schedule'}</button>
              {canResumeSchedule(schedule) ? <button type="button" className="secondary-button schedule-continue-button" disabled={Boolean(actionId)}
                onClick={() => void action(schedule, 'resume')}>Continue run</button>
                : schedule.sessionId ? <button type="button" className="secondary-button schedule-stop-button" disabled={Boolean(actionId) || schedule.status === 'PAUSING' && !schedule.networkPaused}
                onClick={() => void action(schedule, 'pause')}>{schedule.networkPaused ? 'Keep paused' : schedule.status === 'PAUSING' ? 'Pausing…' : 'Pause run'}</button>
                : <button type="button" className="secondary-button" disabled>No active run</button>}
              <button type="button" className="secondary-button schedule-delete-button"
                title="Delete this schedule and its unfinished reports. Collected report data is kept."
                disabled={Boolean(actionId) || ['PREPARING','RUNNING','PAUSING','RESUMING'].includes(schedule.status)
                  || Boolean(schedule.sessionId && !['PAUSED','STOPPED'].includes(schedule.status))}
                onClick={() => void action(schedule, 'delete')}>Delete schedule</button>
            </div>
          </article><RunDiagnostics schedule={schedule}/><FailedBatchCases schedule={schedule}/></div>)}
      </div>
    </section>
  </div>;
}
