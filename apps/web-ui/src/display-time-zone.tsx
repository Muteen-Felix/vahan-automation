import {createContext, useCallback, useContext, useEffect, useState, type ReactNode} from 'react';
import {api} from './services/api-client';
import {persistentState} from './services/persistent-state';
import {accountRunTimeZoneKey, isRunTimeZone, readRunTimeZone, RUN_TIME_ZONE_STORAGE_KEY,
  runTimeZone, type RunTimeZone} from './run-schedules';

interface DisplayTimeZoneContextValue {
  timeZone: RunTimeZone;
  setTimeZone: (value: RunTimeZone) => void;
}

const DisplayTimeZoneContext = createContext<DisplayTimeZoneContextValue | null>(null);

export function DisplayTimeZoneProvider({children}: {children: ReactNode}) {
  const [timeZone, setTimeZoneState] = useState(readRunTimeZone);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    void api.currentUser().then(user => {
      if (!active) return;
      const savedForAccount = localStorage.getItem(accountRunTimeZoneKey(user.username));
      const savedForAdmin = user.role === 'admin' ? persistentState.getItem(RUN_TIME_ZONE_STORAGE_KEY) : null;
      const saved = savedForAccount ?? savedForAdmin;
      setTimeZoneState(isRunTimeZone(saved) ? saved : readRunTimeZone());
    }).catch(() => { /* Keep the default if the account preference cannot be loaded. */ })
      .finally(() => {if (active) setReady(true);});
    return () => {active = false;};
  }, []);
  const setTimeZone = useCallback((value: RunTimeZone) => setTimeZoneState(runTimeZone(value)), []);
  if (!ready) return <div className="display-time-zone-loading" role="status">Loading account preferences…</div>;
  return <DisplayTimeZoneContext.Provider value={{timeZone, setTimeZone}}>{children}</DisplayTimeZoneContext.Provider>;
}

export function useDisplayTimeZone() {
  const context = useContext(DisplayTimeZoneContext);
  if (!context) throw new Error('useDisplayTimeZone must be used within DisplayTimeZoneProvider.');
  return context;
}
