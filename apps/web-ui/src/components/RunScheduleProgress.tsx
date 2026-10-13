import type {RunSchedule} from '../run-schedules';
import {useScheduleTiming} from '../hooks/use-schedule-timing';
import {formatScheduleDuration} from '../schedule-timing';
import {useDisplayTimeZone} from '../display-time-zone';
import {formatScheduledTime, runTimeZoneLabel} from '../run-schedules';

export function RunScheduleProgress({schedule, statusLabel}: {schedule: RunSchedule; statusLabel: string}) {
  const {estimate} = useScheduleTiming(schedule);
  const {timeZone} = useDisplayTimeZone();
  const total = Number.isFinite(schedule.total) ? Math.max(0, Math.floor(schedule.total)) : 0;
  const done = Number.isFinite(schedule.done) ? Math.min(total, Math.max(0, Math.floor(schedule.done))) : 0;
  const progressLabel = `${done.toLocaleString('en-GB')} / ${total ? total.toLocaleString('en-GB') : '—'} reports`;
  const waiting = estimate.stale ? 'Waiting for an update' : estimate.stalled ? 'Waiting for progress'
    : schedule.status === 'PAUSED' || schedule.status === 'PAUSING' ? 'Paused'
    : schedule.status === 'COMPLETED' || schedule.status === 'COMPLETED_WITH_ERRORS' ? 'Finished'
    : 'Estimating after the first result';
  return <div className="run-schedule-progress" aria-label={`Run summary for ${schedule.profileName}`}>
    <div className="schedule-progress-header">
      <div className="schedule-progress-count">
        <span className="schedule-progress-label">Progress</span>
        <div className="schedule-progress-numbers" title={progressLabel}>
          <strong>{done.toLocaleString('en-GB')}</strong><small> / {total ? total.toLocaleString('en-GB') : '—'} reports</small>
        </div>
        <span className={`schedule-progress-state schedule-status-${schedule.status.toLowerCase()}`} title={statusLabel}>{statusLabel}</span>
      </div>
      <div className="schedule-progress-speed" aria-label="Reports collected per minute">
        <strong>{estimate.casesPerMinute === null ? '—' : estimate.casesPerMinute.toFixed(1)}</strong><span>reports/min</span>
      </div>
    </div>
    <progress max={total || 1} value={done} aria-label={`Report progress for ${schedule.profileName}`}
      aria-valuetext={total ? `${done} of ${total} reports` : 'Preparing the list of reports'} />
    {schedule.status !== 'COMPLETED' && schedule.status !== 'COMPLETED_WITH_ERRORS' && <div className="schedule-progress-eta" aria-label="Estimated finish">
      <span>ETA</span> {estimate.remainingMs === null || estimate.finishesAt === null ? <strong>{waiting}</strong>
        : <><strong>About {formatScheduleDuration(estimate.remainingMs)} remaining</strong>
          <time dateTime={estimate.finishesAt}>{formatScheduledTime(estimate.finishesAt, timeZone)}</time></>}
      <small>{runTimeZoneLabel(timeZone)}</small>
    </div>}
  </div>;
}
