import {TARGET_WORKER_COUNT} from '../worker-settings';
import type {FilterProfile} from '../filter-profiles';

export function RunControls({workerCount, disabled, onWorkers, applying, runningContainers, profileId='', profiles=[], onProfile, onLoadCases, savedRun}: {
  workerCount: number; disabled: boolean;
  applying?: boolean; runningContainers?: number | null;
  onWorkers: (count: number) => void;
  profileId?:string; profiles?:FilterProfile[];onProfile?:(id:string)=>void;
  onLoadCases?:()=>void;savedRun?:boolean;
}) {
  return <section className="run-controls" data-profiles={Boolean(onProfile)} aria-label="Crawl configuration">
    <div><p className="worker-dashboard-eyebrow">RUN CONFIGURATION</p><h3>Choose your crawl</h3>
      <p>{applying ? 'Updating Docker containers…' : runningContainers != null
        ? `${runningContainers} Docker worker containers running.`
        : 'One case at a time per worker.'}</p></div>
    {onProfile&&<label>Filter profile<select aria-label="Filter profile" value={profileId} disabled={disabled} onChange={event=>onProfile(event.target.value)}>
      <option value="">Choose a saved filter profile</option>
      {profileId&&!profiles.some(profile=>profile.id===profileId)&&<option value={profileId}>Unavailable saved profile</option>}
      {profiles.map(profile=><option key={profile.id} value={profile.id}>{profile.name} · {profile.definition.report?.year??'Set year in Filters'}</option>)}
    </select></label>}
    <label>Active workers<select aria-label="Active workers" value={workerCount} disabled={disabled} onChange={event => onWorkers(Number(event.target.value))}>
      {Array.from({length: TARGET_WORKER_COUNT}, (_, index) => index + 1).map(count =>
        <option key={count} value={count}>{count} {count === 1 ? 'worker' : 'workers'}</option>)}
    </select></label>
    <p className="run-controls-note">Year and filters come from the saved profile. Continue keeps the saved run.
      {onLoadCases&&<button type="button" className="secondary-button" disabled={disabled||savedRun||!profileId} onClick={onLoadCases}>Load cases</button>}
      {runningContainers != null && runningContainers !== workerCount && <button type="button"
        className="secondary-button" disabled={disabled} onClick={() => onWorkers(workerCount)}>Apply {workerCount} workers</button>}
    </p>
  </section>;
}
