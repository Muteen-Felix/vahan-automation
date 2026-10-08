import type {RunSchedule} from '../run-schedules';
import {useScheduleTiming} from '../hooks/use-schedule-timing';

export function RunScheduleProgress({schedule, statusLabel}: {schedule: RunSchedule; statusLabel: string}) {
  const {estimate} = useScheduleTiming(schedule);
  const total = Number.isFinite(schedule.total) ? Math.max(0, Math.floor(schedule.total)) : 0;
  const done = Number.isFinite(schedule.done) ? Math.min(total, Math.max(0, Math.floor(schedule.done))) : 0;
  const progressLabel = `${done.toLocaleString('en-GB')} / ${total ? total.toLocaleString('en-GB') : '—'} cases`;
  return <div className="run-schedule-progress" aria-label={`Run summary for ${schedule.profileName}`}>
    <div className="schedule-progress-header">
      <div className="schedule-progress-count">
        <span className="schedule-progress-label">Progress</span>
        <div className="schedule-progress-numbers" title={progressLabel}>
          <strong>{done.toLocaleString('en-GB')}</strong><small> / {total ? total.toLocaleString('en-GB') : '—'} cases</small>
        </div>
        <span className={`schedule-progress-state schedule-status-${schedule.status.toLowerCase()}`} title={statusLabel}>{statusLabel}</span>
      </div>
      <div className="schedule-progress-speed" aria-label="Processing speed in cases per minute">
        <strong>{estimate.casesPerMinute === null ? '—' : estimate.casesPerMinute.toFixed(1)}</strong><span>cases/min</span>
      </div>
    </div>
    <progress max={total || 1} value={done} aria-label={`Report progress for ${schedule.profileName}`}
      aria-valuetext={total ? `${done} of ${total} cases` : 'Waiting for the case plan'} />
  </div>;
}
