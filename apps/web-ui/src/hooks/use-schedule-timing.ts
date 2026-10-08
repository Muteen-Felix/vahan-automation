import {useEffect, useState} from 'react';
import type {RunSchedule} from '../run-schedules';
import {estimateScheduleTiming, observeScheduleTiming, type ScheduleTimingObservation} from '../schedule-timing';

export function useScheduleTiming(schedule: RunSchedule) {
  const [now, setNow] = useState(Date.now());
  const [observation, setObservation] = useState<ScheduleTimingObservation | null>(null);
  useEffect(() => {
    const receivedAt = Date.now();
    setNow(receivedAt);
    setObservation(previous => observeScheduleTiming(previous, schedule, receivedAt));
  }, [schedule]);
  useEffect(() => {
    if (schedule.status !== 'RUNNING') return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [schedule.status]);
  return {now, estimate: estimateScheduleTiming(schedule, observation, now)};
}
