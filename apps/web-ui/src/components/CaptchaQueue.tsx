import {useEffect, useRef, useState, type FormEvent} from 'react';
import type {CurrentCaptcha} from '../run-schedules';
import {api} from '../services/api-client';
import {uiSocket} from '../services/socket-client';

type Image = {jobId: string; captchaId: string; imageDataUrl: string};

function CaptchaCard({job, onChanged}: {job: CurrentCaptcha; onChanged: () => void}) {
  const [image, setImage] = useState<Image | null>(null);
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const revision = useRef(0);
  useEffect(() => {
    let live = true;
    const expected = ++revision.current;
    setImage(null); setValue(''); setError('');
    void api.captchaImage(job.jobId).then(result => {
      if (live && revision.current === expected) setImage(result);
    }).catch(reason => {
      if (live && revision.current === expected) setError(reason instanceof Error ? reason.message : 'Could not load CAPTCHA.');
    });
    return () => {live = false; revision.current++;};
  }, [job.jobId, job.captchaId, reload]);

  async function act(event: 'captcha:submitted' | 'captcha:refresh') {
    if (!image || busy) return;
    setBusy(true); setError('');
    try {
      if (!uiSocket.connected) throw new Error('Dashboard connection is unavailable. Please wait for reconnection.');
      const response = await uiSocket.timeout(25_000).emitWithAck(event, {
        jobId: job.jobId, captchaId: image.captchaId,
        ...(event === 'captcha:submitted' ? {value: value.trim()} : {}),
      });
      if (!response?.ok) throw new Error(response?.error || 'The worker could not process CAPTCHA.');
      setValue('');
      if (event === 'captcha:refresh') setReload(count => count + 1);
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not send CAPTCHA.');
    } finally {setBusy(false);}
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (value.trim().length === 6) void act('captcha:submitted');
  }
  return <article className="captcha-card" aria-label={`CAPTCHA for ${job.runnerId}`}>
    <strong>{job.runnerId}</strong>
    <p className="captcha-case">{job.scenarioName || 'Report waiting for CAPTCHA'}</p>
    {image ? <img src={image.imageDataUrl} alt={`VAHAN CAPTCHA for ${job.runnerId}`} /> : !error && <p role="status">Loading CAPTCHA…</p>}
    <form onSubmit={submit}>
      <label>CAPTCHA code for {job.runnerId}<input autoComplete="off" spellCheck={false} maxLength={6} pattern="[A-Za-z0-9]{6}" value={value} onChange={event => setValue(event.target.value)} disabled={!image || busy} required /></label>
      <div className="captcha-actions">
        <button type="submit" className="primary-button" disabled={!image || busy || value.trim().length !== 6}>{busy ? 'Processing…' : 'Submit and continue'}</button>
        <button type="button" className="secondary-button" disabled={!image || busy} onClick={() => void act('captcha:refresh')}>Refresh image</button>
      </div>
    </form>
    {error && <p role="alert">{error} <button type="button" className="secondary-button" disabled={busy} onClick={() => {setReload(count => count + 1); onChanged();}}>Reload CAPTCHA</button></p>}
  </article>;
}

export function CaptchaQueue() {
  const [jobs, setJobs] = useState<CurrentCaptcha[]>([]);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const revision = useRef(0);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const expected = ++revision.current;
      try {
        const result = await api.currentCaptchas();
        if (live && revision.current === expected) {setJobs(result); setError('');}
      } catch (reason) {
        if (live && revision.current === expected) setError(reason instanceof Error ? reason.message : 'Could not load waiting CAPTCHAs.');
      } finally {
        if (live) timer = setTimeout(() => void poll(), 3000);
      }
    };
    void poll();
    return () => {live = false; revision.current++; clearTimeout(timer);};
  }, [refresh]);
  if (!jobs.length && !error) return null;
  return <section className="captcha-queue" aria-label="CAPTCHAs waiting for your input">
    <h2>CAPTCHA requires your input {jobs.length > 0 && `(${jobs.length})`}</h2>
    <p>Enter each code shown by VAHAN to continue its report. Workers stop waiting after 10 minutes.</p>
    {error && <p role="alert">{error}</p>}
    <div className="captcha-grid">{jobs.map(job => <CaptchaCard key={`${job.jobId}:${job.captchaId}`} job={job} onChanged={() => setRefresh(count => count + 1)} />)}</div>
  </section>;
}
