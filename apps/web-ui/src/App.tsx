import {useEffect, useState} from 'react';
import {AccountSettings} from './components/AccountSettings';
import {Brand} from './components/Brand';
import {AnnualReports} from './components/AnnualReports';
import {AutomaticRunSettings} from './components/AutomaticRunSettings';
import {StateSyncStatus} from './components/DataManagement';
import {FilterProfiles} from './components/FilterProfiles';
import {UiHealthContract} from './components/UiHealthContract';
import {RunHistory} from './components/RunHistory';
import type {ConnectionState, Runner} from './contracts';
import {operatorMessage} from './operator-language';
import {FILTER_PROFILE_STORAGE_KEY, type FilterProfile} from './filter-profiles';
import {MATRIX_STORAGE_KEY, readMatrixPlan} from './matrix-plan';
import {readRunSettings} from './run-settings';
import {api, AUTH_REQUIRED_EVENT} from './services/api-client';
import {flushPersistentState, persistentState} from './services/persistent-state';
import {uiSocket} from './services/socket-client';
import {NetworkNotice, useNetworkStatus} from './components/NetworkNotice';
import {useRunSchedules} from './services/use-run-schedules';
import {DisplayTimeZoneProvider} from './display-time-zone';
import type {RunTimeZone} from './run-schedules';

type AppSection = 'reports' | 'filters' | 'run-history' | 'settings' | 'forbidden';

function sectionFromHash(): AppSection {
  const route = window.location.hash.slice(1) || window.location.pathname.replace(/^\/+|\/+$/g, '');
  const [hash, query] = route.split('?');
  if (['settings', 'settings-ui-health', 'health'].includes(hash)
    || (hash === 'configure' && new URLSearchParams(query).has('scheduled'))) return 'settings';
  if (hash === 'configure') return 'settings';
  if (hash === 'run-history' || hash === 'update-history') return 'run-history';
  return hash === 'filters' ? 'filters' : !hash || hash === 'reports' ? 'reports' : 'forbidden';
}

export default function App() {
  return <DisplayTimeZoneProvider><AppContent/></DisplayTimeZoneProvider>;
}

function AppContent() {
  const [role, setRole] = useState<string | null>(null);
  const isAdmin = role === 'admin';
  const [activeSection, setActiveSection] = useState<AppSection>(sectionFromHash);
  const [routeHash, setRouteHash] = useState(() => window.location.hash);
  const [connection, setConnection] = useState<ConnectionState>('connecting');
  const [runners, setRunners] = useState<Runner[]>([]);
  const [profiles, setProfiles] = useState<FilterProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState(() => {
    const saved = persistentState.getItem(FILTER_PROFILE_STORAGE_KEY) || '';
    return /^[0-9a-f-]{36}$/i.test(saved) ? saved : '';
  });
  const [knownPlan, setKnownPlan] = useState(readMatrixPlan);
  const [runDefaults] = useState(() => readRunSettings());
  const [error, setError] = useState('');
  const [signingOut, setSigningOut] = useState(false);
  const [healthBlock, setHealthBlock] = useState<string | null>(null);
  const [healthRefresh, setHealthRefresh] = useState(0);
  const [reportsRefresh, setReportsRefresh] = useState(0);
  const scheduledRuns = useRunSchedules(isAdmin);
  const network = useNetworkStatus();
  const scheduledResults = JSON.stringify(scheduledRuns.schedules.map(schedule => [schedule.id,
    schedule.sessionId, schedule.lastSessionId, schedule.done, schedule.withData,
    schedule.noData, schedule.failed, schedule.status]));

  useEffect(() => {
    let active = true;
    void api.currentUser().then(user => {
      if (!active) return;
      if (user.role !== 'admin' && sectionFromHash() !== 'reports') {
        window.history.replaceState(null, '', '#reports');
        setActiveSection('reports');
        setRouteHash('#reports');
      }
      setRole(user.role);
    }).catch(reason => {if (active) setError(reason.message);});
    return () => {active = false;};
  }, []);

  useEffect(() => {setReportsRefresh(value => value + 1);}, [scheduledResults]);

  useEffect(() => {
    const navigate = () => {
      const section = sectionFromHash();
      if (window.location.hash === '#health') window.history.replaceState(null, '', '#settings-ui-health');
      else if (section !== 'forbidden' && !['#reports', '#filters', '#run-history', '#settings', '#settings-ui-health'].includes(window.location.hash)) {
        window.history.replaceState(null, '', `#${section}`);
      }
      setActiveSection(section);
      setRouteHash(window.location.hash);
    };
    navigate();
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);

  useEffect(() => {
    document.title = `VAHAN · ${activeSection === 'reports' ? 'Exported Reports' : activeSection === 'filters' ? 'Filters' : activeSection === 'run-history' ? 'Run History' : 'Settings'}`;
  }, [activeSection]);

  async function refreshProfiles() {
    const values = await api.filterProfiles();
    if (!Array.isArray(values)) throw new Error('Could not load saved filter profiles.');
    setProfiles(values);
  }

  useEffect(() => {
    if (!isAdmin) return;
    let live = true;
    void api.filterProfiles().then(values => {
      if (!Array.isArray(values)) throw new Error('Could not load saved filter profiles.');
      if (live) setProfiles(values);
    }).catch(reason => {if (live) setError(reason.message);});
    return () => {live = false;};
  }, [isAdmin]);

  useEffect(() => {
    if (!isAdmin) return;
    let live = true;
    let healthSequence = 0;
    let runnerRequest: Promise<void> | null = null;
    const refreshRunners = () => {
      if (!isAdmin) return Promise.resolve();
      if (runnerRequest) return runnerRequest;
      runnerRequest = api.runners().then(values => {if (live) setRunners(values);})
        .catch(reason => {if (live) setError(reason.message);})
        .finally(() => {runnerRequest = null;});
      return runnerRequest;
    };
    const refreshHealth = async () => {
      if (!isAdmin) return;
      const sequence = ++healthSequence;
      try {
        const status = await api.uiHealthStatus();
        if (!live || sequence !== healthSequence) return;
        const latest = status.latestPreflight as {status?: string} | null;
        setHealthBlock(status.blocked || latest?.status === 'BLOCKED' ? JSON.stringify(status, null, 2) : null);
      } catch { /* Retain the last diagnostic until the server confirms recovery. */ }
    };
    const ensureConnection = () => {if (!uiSocket.connected && !uiSocket.active) uiSocket.connect();};
    const onVisibility = () => {if (document.visibilityState === 'visible') ensureConnection();};
    const onConnect = () => {
      setConnection('connected');
      void refreshRunners(); void refreshHealth();
      setReportsRefresh(value => value + 1);
      setHealthRefresh(value => value + 1);
    };
    const onDisconnect = (reason: string) => {
      setConnection('disconnected');
      if (reason === 'io server disconnect') window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
    };
    const onConnectionError = (reason: Error) => {
      setConnection('error');
      if (/rejected|unauthorized|authentication required|token expired/i.test(reason.message)) {
        window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
      }
    };
    const onHealthBlocked = (details: unknown) => {
      healthSequence++;
      setHealthBlock(typeof details === 'string' ? details : JSON.stringify(details ?? {}, null, 2));
      setHealthRefresh(value => value + 1);
    };
    const onHealthUpdate = () => {void refreshHealth(); setHealthRefresh(value => value + 1);};
    uiSocket.on('connect', onConnect);
    uiSocket.on('disconnect', onDisconnect);
    uiSocket.on('connect_error', onConnectionError);
    uiSocket.on('runner:online', refreshRunners);
    uiSocket.on('runner:offline', refreshRunners);
    uiSocket.on('ui-health:blocked', onHealthBlocked);
    uiSocket.on('ui-health:waiting', onHealthUpdate);
    uiSocket.on('ui-health:verified', onHealthUpdate);
    uiSocket.on('ui-health:log-received', onHealthUpdate);
    void refreshRunners(); void refreshHealth();
    uiSocket.connect();
    window.addEventListener('online', ensureConnection);
    window.addEventListener('pageshow', ensureConnection);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      live = false;
      uiSocket.off('connect', onConnect);
      uiSocket.off('disconnect', onDisconnect);
      uiSocket.off('connect_error', onConnectionError);
      uiSocket.off('runner:online', refreshRunners);
      uiSocket.off('runner:offline', refreshRunners);
      uiSocket.off('ui-health:blocked', onHealthBlocked);
      uiSocket.off('ui-health:waiting', onHealthUpdate);
      uiSocket.off('ui-health:verified', onHealthUpdate);
      uiSocket.off('ui-health:log-received', onHealthUpdate);
      window.removeEventListener('online', ensureConnection);
      window.removeEventListener('pageshow', ensureConnection);
      document.removeEventListener('visibilitychange', onVisibility);
      uiSocket.disconnect();
    };
  }, [isAdmin]);

  async function signOut() {
    if (signingOut) return;
    setSigningOut(true); setError('');
    try {await flushPersistentState(); await api.logout();}
    catch (reason) {setError(reason instanceof Error ? reason.message : 'Could not sign out.');}
    finally {setSigningOut(false);}
  }

  async function updateAccountTimeZone(timeZone: RunTimeZone) {
    if (!isAdmin) return;
    const updated = await api.setRunScheduleTimeZone(timeZone);
    updated.forEach(scheduledRuns.upsert);
  }

  if (!role) return <main className="auth-shell"><p role={error ? 'alert' : 'status'}>{operatorMessage(error) || 'Checking your account access…'}</p></main>;
  const forbidden = activeSection === 'forbidden' || (!isAdmin && activeSection !== 'reports');
  return <div className="app-shell" data-view={activeSection}>
    <header className="site-header">
      <Brand />
      <nav className="main-nav" aria-label="Main navigation">
        <a className={activeSection === 'reports' ? 'active' : undefined} aria-current={activeSection === 'reports' ? 'page' : undefined} href="#reports">Exported Reports</a>
        {isAdmin && <><a className={activeSection === 'filters' ? 'active' : undefined} aria-current={activeSection === 'filters' ? 'page' : undefined} href="#filters">Filters</a>
        <a className={activeSection === 'run-history' ? 'active' : undefined} aria-current={activeSection === 'run-history' ? 'page' : undefined} href="#run-history">Run History</a>
        <a className={activeSection === 'settings' ? 'active' : undefined} aria-current={activeSection === 'settings' ? 'page' : undefined} href="#settings">Settings</a></>}
      </nav>
      <div className="header-actions">{!isAdmin && <AccountSettings signingOut={signingOut} onSignOut={signOut} onTimeZoneChange={updateAccountTimeZone}/>}</div>
    </header>
    <div className="app-layout"><div className="app-main">
      <NetworkNotice network={network} connection={connection}/>
      <StateSyncStatus />
      {error && <div className="global-error" role="alert">{operatorMessage(error)}<button type="button" aria-label="Dismiss message" onClick={() => setError('')}>×</button></div>}
      {isAdmin && healthBlock && activeSection !== 'settings' && <div className="ui-health-block" role="alert">
        <strong>The VAHAN website check needs attention. New reports cannot start yet.</strong>
        <p>Open Website check in Settings. Copy the issue for support, then try again after it is fixed.</p>
        <a href="#settings-ui-health">Open Website check in Settings</a>
        <button type="button" onClick={() => void navigator.clipboard.writeText(healthBlock).catch(() => setError('Could not copy the issue. Allow clipboard access and try again.'))}>Copy for support</button>
      </div>}
      {forbidden ? <main className="page-content access-denied-page">
        <section className="access-denied-card" aria-labelledby="access-denied-title">
          <span className="access-denied-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M7.5 10V7.5a4.5 4.5 0 0 1 9 0V10M6.75 10h10.5A1.75 1.75 0 0 1 19 11.75v7.5A1.75 1.75 0 0 1 17.25 21H6.75A1.75 1.75 0 0 1 5 19.25v-7.5A1.75 1.75 0 0 1 6.75 10Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/><path d="M12 14v3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg></span>
          <p className="access-denied-kicker">ACCESS RESTRICTED</p>
          <h2 id="access-denied-title">You don’t have access to this feature</h2>
          <p className="access-denied-description">This section is available to administrators. You can still view and export reports with your account.</p>
          <a className="access-denied-action" href="#reports">Go to Exported Reports <span aria-hidden="true">→</span></a>
        </section>
      </main> : activeSection === 'filters' ? <FilterProfiles profiles={profiles} runners={runners} knownPlan={knownPlan}
        busy={network.offline || scheduledRuns.schedules.some(schedule => Boolean(schedule.sessionId) && ['PREPARING', 'RUNNING', 'PAUSING', 'RESUMING'].includes(schedule.status))}
        onSaved={refreshProfiles} onSelect={(id, plan) => {
          setSelectedProfileId(id); persistentState.setItem(FILTER_PROFILE_STORAGE_KEY, JSON.stringify(id));
          setKnownPlan(plan); persistentState.setItem(MATRIX_STORAGE_KEY, JSON.stringify(plan));
          window.location.hash = 'settings';
        }} /> : activeSection === 'run-history' ? <RunHistory/> : activeSection === 'settings' ? <main className="page-content settings-page" id="settings">
          <div className="section-intro settings-intro"><div><h2>Settings</h2><p>Schedules, activity and account.</p></div>
            <AccountSettings signingOut={signingOut} onSignOut={signOut} onTimeZoneChange={updateAccountTimeZone}/>
          </div>
          <UiHealthContract refreshToken={healthRefresh} scrollIntoView={routeHash === '#settings-ui-health'} />
          <AutomaticRunSettings profiles={profiles} selectedProfileId={selectedProfileId}
            year={runDefaults.year} schedules={scheduledRuns.schedules}
            loading={scheduledRuns.loading} loadError={scheduledRuns.error}
            onUpsert={scheduledRuns.upsert} onDelete={scheduledRuns.remove} />
        </main> : <main className="page-content exported-reports-page" id="reports">
          <AnnualReports refreshTrigger={reportsRefresh} coveragePlan={isAdmin ? knownPlan : null} />
        </main>}
    </div></div>
  </div>;
}
