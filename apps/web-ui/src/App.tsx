import {useEffect, useState} from 'react';
import {AccountSettings} from './components/AccountSettings';
import {AnnualReports} from './components/AnnualReports';
import {AutomaticRunSettings} from './components/AutomaticRunSettings';
import {ConnectionBanner} from './components/ConnectionBanner';
import {StateSyncStatus} from './components/DataManagement';
import {FilterProfiles} from './components/FilterProfiles';
import {UiHealthContract} from './components/UiHealthContract';
import type {ConnectionState, Runner} from './contracts';
import {FILTER_PROFILE_STORAGE_KEY, type FilterProfile} from './filter-profiles';
import {MATRIX_STORAGE_KEY, readMatrixPlan} from './matrix-plan';
import {readRunSettings} from './run-settings';
import {api, AUTH_REQUIRED_EVENT} from './services/api-client';
import {flushPersistentState, persistentState} from './services/persistent-state';
import {uiSocket} from './services/socket-client';
import {NetworkNotice, useNetworkStatus} from './components/NetworkNotice';
import {useRunSchedules} from './services/use-run-schedules';

type AppSection = 'reports' | 'filters' | 'settings';

function sectionFromHash(): AppSection {
  const [hash, query] = window.location.hash.slice(1).split('?');
  if (['settings', 'settings-ui-health', 'health'].includes(hash)
    || (hash === 'configure' && new URLSearchParams(query).has('scheduled'))) return 'settings';
  return hash === 'filters' ? 'filters' : 'reports';
}

export default function App() {
  const [activeSection, setActiveSection] = useState<AppSection>(sectionFromHash);
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
  const scheduledRuns = useRunSchedules();
  const network = useNetworkStatus();
  const scheduledResults = JSON.stringify(scheduledRuns.schedules.map(schedule => [schedule.id,
    schedule.sessionId, schedule.lastSessionId, schedule.done, schedule.withData,
    schedule.noData, schedule.failed, schedule.status]));

  useEffect(() => {setReportsRefresh(value => value + 1);}, [scheduledResults]);

  useEffect(() => {
    const navigate = () => {
      const section = sectionFromHash();
      if (window.location.hash === '#health') window.history.replaceState(null, '', '#settings-ui-health');
      else if (!['#reports', '#filters', '#settings', '#settings-ui-health'].includes(window.location.hash)) {
        window.history.replaceState(null, '', `#${section}`);
      }
      setActiveSection(section);
    };
    navigate();
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);

  useEffect(() => {
    document.title = `VAHAN · ${activeSection === 'reports' ? 'Exported Reports' : activeSection === 'filters' ? 'Filters' : 'Settings'}`;
    if (window.location.hash === '#settings-ui-health') {
      window.requestAnimationFrame(() => document.getElementById('settings-ui-health')?.scrollIntoView({block: 'start'}));
    }
  }, [activeSection, healthRefresh]);

  async function refreshProfiles() {
    const values = await api.filterProfiles();
    if (!Array.isArray(values)) throw new Error('Could not load saved filter profiles.');
    setProfiles(values);
  }

  useEffect(() => {
    let live = true;
    void api.filterProfiles().then(values => {
      if (!Array.isArray(values)) throw new Error('Could not load saved filter profiles.');
      if (live) setProfiles(values);
    }).catch(reason => {if (live) setError(reason.message);});
    return () => {live = false;};
  }, []);

  useEffect(() => {
    let live = true;
    let healthSequence = 0;
    let runnerRequest: Promise<void> | null = null;
    const refreshRunners = () => {
      if (runnerRequest) return runnerRequest;
      runnerRequest = api.runners().then(values => {if (live) setRunners(values);})
        .catch(reason => {if (live) setError(reason.message);})
        .finally(() => {runnerRequest = null;});
      return runnerRequest;
    };
    const refreshHealth = async () => {
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
      uiSocket.off('ui-health:verified', onHealthUpdate);
      uiSocket.off('ui-health:log-received', onHealthUpdate);
      window.removeEventListener('online', ensureConnection);
      window.removeEventListener('pageshow', ensureConnection);
      document.removeEventListener('visibilitychange', onVisibility);
      uiSocket.disconnect();
    };
  }, []);

  async function signOut() {
    if (signingOut) return;
    setSigningOut(true); setError('');
    try {await flushPersistentState(); await api.logout();}
    catch (reason) {setError(reason instanceof Error ? reason.message : 'Could not sign out.');}
    finally {setSigningOut(false);}
  }

  return <div className="app-shell" data-view={activeSection}>
    <header className="site-header">
      <a className="brand-lockup" href="#reports" aria-label="VAHAN Report Automation">
        <span className="brand-symbol" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none" focusable="false">
          <path d="M7 7L16 26L25 7" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M7 7L16 26L25 7" stroke="#346d43" strokeWidth="1.1" strokeDasharray="2 3" strokeLinecap="round" />
        </svg></span>
        <span className="brand-copy"><strong>VAHAN</strong><small>REPORT AUTOMATION</small></span>
      </a>
      <nav className="main-nav" aria-label="Main navigation">
        <a className={activeSection === 'reports' ? 'active' : undefined} aria-current={activeSection === 'reports' ? 'page' : undefined} href="#reports">Exported Reports</a>
        <a className={activeSection === 'filters' ? 'active' : undefined} aria-current={activeSection === 'filters' ? 'page' : undefined} href="#filters">Filters</a>
        <a className={activeSection === 'settings' ? 'active' : undefined} aria-current={activeSection === 'settings' ? 'page' : undefined} href="#settings">Settings</a>
      </nav>
      <div className="header-actions"><ConnectionBanner backend={connection} runners={runners.length} /></div>
    </header>
    <div className="app-layout"><div className="app-main">
      <NetworkNotice network={network}/>
      <StateSyncStatus />
      {error && <div className="global-error" role="alert">{error}<button type="button" onClick={() => setError('')}>×</button></div>}
      {healthBlock && activeSection !== 'settings' && <div className="ui-health-block" role="alert">
        <strong>UI Health blocked — new crawl work cannot start.</strong>
        <p>Review the website change alert in Settings and copy the diagnostic error for dev.</p>
        <a href="#settings-ui-health">Open UI Health in Settings</a>
        <button type="button" onClick={() => void navigator.clipboard.writeText(healthBlock).catch(() => setError('Could not copy the diagnostic error.'))}>Copy error</button>
      </div>}
      {activeSection === 'filters' ? <FilterProfiles profiles={profiles} runners={runners} knownPlan={knownPlan}
        busy={network.offline || scheduledRuns.schedules.some(schedule => Boolean(schedule.sessionId) && ['PREPARING', 'RUNNING', 'PAUSING', 'RESUMING'].includes(schedule.status))}
        onSaved={refreshProfiles} onSelect={(id, plan) => {
          setSelectedProfileId(id); persistentState.setItem(FILTER_PROFILE_STORAGE_KEY, JSON.stringify(id));
          setKnownPlan(plan); persistentState.setItem(MATRIX_STORAGE_KEY, JSON.stringify(plan));
          window.location.hash = 'settings';
        }} /> : activeSection === 'settings' ? <main className="page-content settings-page" id="settings">
          <div className="section-intro settings-intro"><div><h2>Settings</h2><p>Schedules, activity and account.</p></div>
            <AccountSettings signingOut={signingOut} onSignOut={signOut}/>
          </div>
          <UiHealthContract refreshToken={healthRefresh} />
          <AutomaticRunSettings profiles={profiles} selectedProfileId={selectedProfileId}
            workerCount={runDefaults.workerCount} year={runDefaults.year} schedules={scheduledRuns.schedules}
            loading={scheduledRuns.loading} loadError={scheduledRuns.error}
            onUpsert={scheduledRuns.upsert} onDelete={scheduledRuns.remove} />
        </main> : <main className="page-content exported-reports-page" id="reports">
          <AnnualReports refreshTrigger={reportsRefresh} coveragePlan={knownPlan} />
        </main>}
    </div></div>
  </div>;
}
