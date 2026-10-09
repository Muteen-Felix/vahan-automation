import {useEffect, useRef, useState, type FormEvent} from 'react';
import type {FilterProfile} from '../filter-profiles';
import {api} from '../services/api-client';
import {persistentState} from '../services/persistent-state';
import {canResumeSchedule, formatScheduledTime, isRunTimeZone, readRunTimeZone, runTimeZone, runTimeZoneLabel,
  RUN_TIME_ZONE, INDIA_TIME_ZONE, RUN_TIME_ZONE_STORAGE_KEY, scheduleDateTime, scheduleDateTimeIso,
  scheduledDayOfMonth, type RunSchedule} from '../run-schedules';
import {RunScheduleProgress} from './RunScheduleProgress';
import {BatchRetryStatus} from './BatchRetryStatus';
import {RunDiagnostics} from './RunDiagnostics';
import {FailedBatchCases} from './FailedBatchCases';

const STATUS_LABELS: Record<RunSchedule['status'], string> = {
  WAITING: 'Scheduled', PREPARING: 'Preparing', RUNNING: 'Running', COMPLETED: 'Completed',
  PAUSING: 'Pausing', PAUSED: 'Paused', RESUMING: 'Resuming',
  COMPLETED_WITH_ERRORS: 'Completed with errors', ERROR: 'Error', STOPPED: 'Stopped',
};

interface Props {
  profiles: FilterProfile[];
  selectedProfileId: string;
  workerCount: number;
  year: number;
  schedules: RunSchedule[];
  loading: boolean;
  loadError: string;
  onUpsert: (value: RunSchedule) => void;
  onDelete: (id: string) => void;
}

export function AutomaticRunSettings({profiles, selectedProfileId, workerCount, year, schedules, loading, loadError, onUpsert, onDelete}: Props) {
  const [timeZone, setTimeZone] = useState(readRunTimeZone);
  const initial = scheduleDateTime(new Date(Date.now() + 5 * 60_000), timeZone);
  const [profileId, setProfileId] = useState(selectedProfileId);
  const [date, setDate] = useState(initial.date);
  const [time, setTime] = useState(initial.time);
  const [workers, setWorkers] = useState(workerCount);
  const [reportYear, setReportYear] = useState(year);
  const [repeat, setRepeat] = useState<'once' | 'daily' | 'monthly'>('once');
  const [saving, setSaving] = useState(false);
  const [timeZoneSaving, setTimeZoneSaving] = useState(false);
  const [actionId, setActionId] = useState('');
  const [workerChoices, setWorkerChoices] = useState<Record<string, number>>({});
  const [formOpen, setFormOpen] = useState(false);
  const formDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = formDialog.current;
    if (!dialog) return;
    if (formOpen && !dialog.open) dialog.showModal();
    else if (!formOpen && dialog.open) dialog.close();
  }, [formOpen]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const profile = profiles.find(item => item.id === profileId);
  const selectedYear = profile?.definition.report?.year ?? reportYear;

  async function updateTimeZone(value: string) {
    if (!isRunTimeZone(value) || value === timeZone) return;
    setTimeZoneSaving(true); setError(''); setNotice('');
    try {
      const updated = await api.setRunScheduleTimeZone(value);
      updated.forEach(onUpsert);
      setTimeZone(value);
      persistentState.setItem(RUN_TIME_ZONE_STORAGE_KEY, value);
      const next = scheduleDateTime(new Date(Date.now() + 5 * 60_000), value);
      setDate(next.date);
      setTime(next.time);
      setNotice(updated.length
        ? `Time zone changed for your ${updated.length} saved ${updated.length === 1 ? 'schedule' : 'schedules'}. Their next run times are unchanged.`
        : `Schedule time zone set to ${runTimeZoneLabel(value)}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not change the schedule time zone.');
    } finally {setTimeZoneSaving(false);}
  }

  useEffect(() => {
    setWorkerChoices(previous => {
      const next = {...previous};
      let changed = false;
      for (const schedule of schedules) {
        if (!canResumeSchedule(schedule) && previous[schedule.id] !== undefined && previous[schedule.id] !== schedule.workerCount) {
          next[schedule.id] = schedule.workerCount; changed = true;
        }
      }
      return changed ? next : previous;
    });
  }, [schedules]);

  useEffect(() => {
    if (!profiles.some(item => item.id === profileId)) {
      setProfileId(profiles.some(item => item.id === selectedProfileId) ? selectedProfileId : profiles[0]?.id || '');
    }
  }, [profiles, selectedProfileId, profileId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const startsAt = scheduleDateTimeIso(date, time, timeZone);
    if (!profile || !date || !time || !Number.isFinite(Date.parse(startsAt)) || Date.parse(startsAt) <= Date.now()) {
      setError('Choose a report profile and a future date and time.');
      return;
    }
    setSaving(true); setError(''); setNotice('');
    try {
      const saved = await api.createRunSchedule({profileId, year: selectedYear, workerCount: workers, startsAt, timeZone, repeat});
      onUpsert(saved);
      const savedTimeZone = runTimeZone(saved.timeZone);
      setNotice(`Schedule saved for ${formatScheduledTime(saved.nextRunAt, savedTimeZone)} (${runTimeZoneLabel(savedTimeZone)}).`);
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
          : type === 'resume' ? await api.resumeRunSchedule(schedule.id, workerChoices[schedule.id] ?? schedule.workerCount)
          : await api.toggleRunSchedule(schedule.id, !schedule.enabled);
        if (type === 'pause' || type === 'resume') setWorkerChoices(current => ({...current, [schedule.id]: updated.workerCount}));
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
        onClick={() => {setError('');setNotice('');setFormOpen(true);}}>Show form</button></div>
      <div className="schedule-timezone-setting">
        <label htmlFor="schedule-time-zone">Schedule time zone
          <select id="schedule-time-zone" value={timeZone} onChange={event => void updateTimeZone(event.target.value)} disabled={saving || timeZoneSaving}>
            <option value={RUN_TIME_ZONE}>Vietnam time (UTC+07:00)</option>
            <option value={INDIA_TIME_ZONE}>India time (UTC+05:30)</option>
          </select>
        </label>
        <p>New schedules and repeats use this zone. Changing it converts your saved schedules while keeping their next run times unchanged.</p>
      </div>
      <dialog ref={formDialog} id="new-schedule-form" className="schedule-form-dialog" aria-labelledby="new-schedule-title"
        onCancel={event => {if (saving) event.preventDefault(); else setFormOpen(false);}}
        onClose={() => setFormOpen(false)}
        onClick={event => {if (event.target === event.currentTarget && !saving) setFormOpen(false);}}>
        <div className="schedule-form-dialog-header"><div><span className="settings-eyebrow">AUTOMATIC RUN</span><h3 id="new-schedule-title">Schedule a report</h3>
          <p>Choose when the saved report profile should run.</p></div>
          <button type="button" className="schedule-form-dialog-close" aria-label="Hide form" title="Hide form" disabled={saving} onClick={() => setFormOpen(false)}>×</button></div>
        <div className="schedule-form-dialog-body">
          {error && <p className="schedule-dialog-error" role="alert">{error}</p>}
          <form className="automatic-run-form" onSubmit={save}>
            <label className="schedule-profile-label">Report / filter profile
              <select aria-label="Report / filter profile" value={profileId} onChange={event => setProfileId(event.target.value)} required disabled={saving || !profiles.length}>
                {!profiles.length && <option value="">No saved profiles</option>}
                {profiles.map(item => <option key={item.id} value={item.id}>{item.name} · {item.definition.report?.year ?? reportYear}</option>)}
              </select>
            </label>
            <label>Parallel task limit<input aria-label="Parallel task limit" type="number" min="1" step="1" value={workers}
              onChange={event => setWorkers(Math.max(1, Math.floor(Number(event.target.value) || 1)))} disabled={saving} /></label>
            <label>Start date<input aria-label="Start date" type="date" value={date} onChange={event => setDate(event.target.value)} required disabled={saving} /></label>
            <label>Start time<input aria-label="Start time" type="time" value={time} onChange={event => setTime(event.target.value)} required disabled={saving} /></label>
            <label>Repeat<select aria-label="Repeat" value={repeat} onChange={event => setRepeat(event.target.value as 'once' | 'daily' | 'monthly')} disabled={saving}>
              <option value="once">Once</option><option value="daily">Every day</option><option value="monthly">Every month</option>
            </select></label>
            <label>Report year<input aria-label="Report year" type="number" min="1900" max={new Date().getFullYear()} value={selectedYear}
              onChange={event => setReportYear(Number(event.target.value))} required disabled={saving || Boolean(profile?.definition.report)} /></label>
            <div className="automatic-run-form-footer"><span>{runTimeZoneLabel(timeZone)}</span>
              <button className="primary-button" type="submit" disabled={saving || loading || !profile}>{saving ? 'Saving…' : 'Add schedule'}</button>
            </div>
          </form>
          <div className="schedule-help-slot"><p className="schedule-help">{repeat === 'monthly'
            ? `Runs on day ${Number(date.slice(-2))} each month; shorter months use their last day.`
            : !profiles.length
            ? <>Create a <a href="#filters">filter profile</a> to select a report.</>
            : 'Saved schedules keep the selected profile. View collected data in Exported Reports.'}</p></div>
        </div>
      </dialog>
      <div className={`schedule-feedback${loadError || (!formOpen && (error || notice)) ? ' has-feedback' : ''}`}>
        {(loadError || (!formOpen && error)) ? <p className="schedule-error" role="alert" title={loadError || error}>{loadError || error}</p>
          : <p className="schedule-notice" role="status" title={notice}>{notice || '\u00a0'}</p>}
      </div>
      <div className="run-schedule-list-heading" id="saved-schedules"><h3>Saved schedules</h3><span>{schedules.length} {schedules.length === 1 ? 'schedule' : 'schedules'}</span></div>
      <div className="run-schedule-list">
        {loading ? <p>Loading schedules…</p> : !schedules.length ? <p className="schedule-empty">No automatic report schedules yet.</p> :
          schedules.map(schedule => <div className="schedule-run-entry" key={schedule.id}><article className="run-schedule-card" aria-label={`Schedule for ${schedule.profileName}`}>
            <div className="run-schedule-title">
              <div className="run-schedule-identity"><span className="run-schedule-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v4M16 3v4M4 10h16M8 14h3M8 17h7"/></svg>
              </span><div className="run-schedule-name"><strong title={schedule.profileName}>{schedule.profileName}</strong><small>Calendar year {schedule.year}</small></div></div>
              <span className={`schedule-status schedule-status-${schedule.status.toLowerCase()}`} aria-live="polite">
                {!schedule.enabled && !schedule.sessionId && schedule.nextRunAt ? 'Disabled' : schedule.networkPaused ? 'Waiting for network' : STATUS_LABELS[schedule.status]}
              </span></div>
            <dl className="run-schedule-details">
              <div className="run-schedule-start"><dt>{schedule.nextRunAt ? 'Next start' : 'Scheduled start'}</dt><dd title={formatScheduledTime(schedule.nextRunAt ?? schedule.startsAt, runTimeZone(schedule.timeZone))}>{formatScheduledTime(schedule.nextRunAt ?? schedule.startsAt, runTimeZone(schedule.timeZone))}</dd><small>{runTimeZoneLabel(schedule.timeZone)}</small></div>
              <div><dt>Repeat</dt><dd>{schedule.repeat === 'monthly' ? 'Every month' : schedule.repeat === 'daily' ? 'Every day' : 'Once'}</dd>
                <small>{schedule.repeat === 'monthly' ? `Day ${scheduledDayOfMonth(schedule.startsAt, runTimeZone(schedule.timeZone))} · month-end if needed` : schedule.repeat === 'daily' ? 'At the same time' : 'One scheduled run'}</small></div>
              <div className="schedule-worker-setting"><dt>Parallel tasks</dt><dd>
                <input aria-label={`Parallel tasks for ${schedule.profileName}`} type="number" min="1" step="1" value={workerChoices[schedule.id] ?? schedule.workerCount}
                  disabled={Boolean(actionId) || !canResumeSchedule(schedule)}
                  onChange={event => setWorkerChoices(current => ({...current, [schedule.id]: Math.max(1, Math.floor(Number(event.target.value) || 1))}))} />
              </dd><small>{canResumeSchedule(schedule) ? 'Applied on continue' : schedule.status === 'PAUSING' ? 'Waiting for cases to save' : 'Pause to change task limit'}</small></div>
            </dl>
            <RunScheduleProgress schedule={schedule} statusLabel={!schedule.enabled && !schedule.sessionId && schedule.nextRunAt ? 'Disabled' : schedule.networkPaused ? 'Waiting for network' : STATUS_LABELS[schedule.status]} />
            <div className="schedule-retry-slot">
              {schedule.message && (['PREPARING','RESUMING','PAUSING','ERROR'].includes(schedule.status)
                  || /^(Waiting|Could not|A worker|Docker)/i.test(schedule.message))
                ? <p className={`schedule-retry-note schedule-run-message${schedule.status==='ERROR'?' has-error':''}`}
                    role={schedule.status==='ERROR'?'alert':'status'} title={schedule.message}>{schedule.message}</p>
                : schedule.retryProgress&&schedule.retryProgress.phase!=='PRIMARY'&&!(schedule.retryProgress.phase==='DONE'&&!schedule.failed)
                ?<BatchRetryStatus progress={schedule.retryProgress} running={schedule.status==='RUNNING'}/>
                :<p className="schedule-retry-note">Errors are checked after each report group, then all remaining failures receive a final recovery pass.</p>}
            </div>
            <div className="run-schedule-actions">
              <button type="button" className="secondary-button"
                title="Enable or disable future starts. A running report continues until stopped."
                disabled={Boolean(actionId) || (schedule.repeat === 'once' && !schedule.nextRunAt)} onClick={() => void action(schedule, 'toggle')}>{schedule.repeat === 'once' && !schedule.nextRunAt ? 'No future runs' : schedule.enabled ? 'Disable future runs' : 'Enable schedule'}</button>
              {canResumeSchedule(schedule) ? <button type="button" className="secondary-button schedule-continue-button" disabled={Boolean(actionId)}
                onClick={() => void action(schedule, 'resume')}>Continue run</button>
                : schedule.sessionId ? <button type="button" className="secondary-button schedule-stop-button" disabled={Boolean(actionId) || schedule.status === 'PAUSING' && !schedule.networkPaused}
                onClick={() => void action(schedule, 'pause')}>{schedule.networkPaused ? 'Keep paused' : schedule.status === 'PAUSING' ? 'Pausing…' : 'Pause run'}</button>
                : <button type="button" className="secondary-button" disabled>No active run</button>}
              <button type="button" className="secondary-button schedule-delete-button"
                title="Delete this schedule and its remaining cases. Collected report data is kept."
                disabled={Boolean(actionId) || ['PREPARING','RUNNING','PAUSING','RESUMING'].includes(schedule.status)
                  || Boolean(schedule.sessionId && !['PAUSED','STOPPED'].includes(schedule.status))}
                onClick={() => void action(schedule, 'delete')}>Delete schedule</button>
            </div>
          </article><RunDiagnostics schedule={schedule}/><FailedBatchCases schedule={schedule}/></div>)}
      </div>
    </section>
  </div>;
}
