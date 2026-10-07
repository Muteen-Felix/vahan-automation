import {useCallback, useEffect, useRef, useState} from 'react';

// Worker completions invalidate data while a read can still be in flight.
// Finish that read, publish it, then read again for any queued invalidations.
// Only changing the viewed filters or unmounting cancels a request.
export function useLiveQuery<T>(key: unknown, load: (signal: AbortSignal) => Promise<T>, intervalMs = 1_000) {
  const [state, setState] = useState<{key: unknown; data: T | null; loading: boolean; error: string}>({
    key, data: null, loading: true, error: '',
  });
  const loader = useRef(load);
  loader.current = load;
  const invalidate = useRef<(immediate?: boolean) => void>(() => {});
  const refresh = useCallback((immediate = false) => invalidate.current(immediate), []);

  useEffect(() => {
    const read = loader.current;
    let disposed = false, running = false, dirty = false, nextAllowedAt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    setState({key, data: null, loading: true, error: ''});

    function schedule() {
      if (disposed || running || !dirty || timer !== undefined) return;
      const wait = Math.max(0, nextAllowedAt - Date.now());
      if (!wait) { void run(); return; }
      timer = setTimeout(() => {timer = undefined; void run();}, wait);
    }
    async function run() {
      if (disposed || running) return;
      running = true; dirty = false; nextAllowedAt = Date.now() + intervalMs;
      controller = new AbortController();
      setState(current => ({...current, loading: true, error: ''}));
      try {
        const data = await read(controller.signal);
        if (!disposed) setState({key, data, loading: false, error: ''});
      } catch (reason) {
        if (!disposed) setState(current => ({...current, loading: false,
          error: reason instanceof Error ? reason.message : 'Could not load reports.'}));
      } finally {
        running = false;
        if (!disposed) schedule();
      }
    }
    invalidate.current = (immediate = false) => {
      if (disposed) return;
      dirty = true;
      if (immediate) {nextAllowedAt = 0; clearTimeout(timer); timer = undefined;}
      schedule();
    };
    void run();
    return () => {disposed = true; clearTimeout(timer); controller?.abort();};
  }, [key, intervalMs]);

  return {...state, data: Object.is(state.key, key) ? state.data : null, refresh};
}
