import {useCallback, useEffect, useRef, useState} from 'react';
import {api} from './api-client';
import type {RunSchedule} from '../run-schedules';

/** Observe backend-owned scheduled work without dispatching browser jobs. */
export function useRunSchedules(enabled = true) {
  const [schedules, setSchedules] = useState<RunSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const revision = useRef(0);
  const mounted = useRef(false);
  const refresh = useCallback(async () => {
    const expected = ++revision.current;
    try {
      const values = await api.runSchedules();
      if (!mounted.current || revision.current !== expected) return;
      if (!Array.isArray(values)) throw new Error('Could not load automatic run schedules.');
      setSchedules(values); setError('');
    } catch (reason) {
      if (mounted.current && revision.current === expected) setError(reason instanceof Error ? reason.message : 'Could not load automatic run schedules.');
    } finally {
      if (mounted.current && revision.current === expected) setLoading(false);
    }
  }, []);
  useEffect(() => {
    // Keep the initial load pending while authorization is being resolved.
    // Otherwise the schedule form initializes against an empty list before
    // the admin's saved schedules arrive.
    if (!enabled) {setLoading(true); return;}
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;
    let live = true;
    const poll = async () => {
      await refresh();
      if (live) timer = setTimeout(() => void poll(), 3000);
    };
    void poll();
    return () => {live = false; mounted.current = false; revision.current++; clearTimeout(timer);};
  }, [refresh, enabled]);
  const upsert = useCallback((value: RunSchedule) => {
    revision.current++;
    setSchedules(current => current.some(item => item.id === value.id)
      ? current.map(item => item.id === value.id ? value : item) : [...current, value]);
  }, []);
  const remove = useCallback((id: string) => {
    revision.current++;
    setSchedules(current => current.filter(item => item.id !== id));
  }, []);
  return {schedules, loading, error, refresh, upsert, remove};
}
