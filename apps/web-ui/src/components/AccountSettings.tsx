import {useEffect, useRef, useState, type FormEvent, type KeyboardEvent} from 'react';
import {api, request} from '../services/api-client';
import {UserManagement} from './DataManagement';

type AccountSection = 'profile' | 'password' | 'users';

const sections: {id: AccountSection; label: string}[] = [
  {id: 'profile', label: 'Profile'},
  {id: 'password', label: 'Change password'},
  {id: 'users', label: 'Manage users'},
];

export function AccountSettings({signingOut, onSignOut}: {signingOut: boolean; onSignOut: () => Promise<void>}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<AccountSection>('profile');
  const [user, setUser] = useState<{username: string; role: string} | null>(null);
  const [loadError, setLoadError] = useState('');
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const isAdmin = user?.role === 'admin';
  const visibleSections = isAdmin ? sections : sections.filter(item => item.id !== 'users');

  useEffect(() => {
    if (open) {
      dialog.current?.showModal();
      setLoadError('');
      void api.currentUser().then(setUser).catch(reason => setLoadError(reason instanceof Error ? reason.message : 'Could not load account details.'));
    } else {
      dialog.current?.close();
      setCurrent('');setPassword('');setConfirm('');setError('');setNotice('');setLoadError('');
    }
  }, [open]);

  useEffect(() => {
    if (!isAdmin && section === 'users') setSection('profile');
  }, [isAdmin, section]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();setError('');setNotice('');
    if (password !== confirm) {setError('The new passwords do not match.');return;}
    setBusy(true);
    try {
      await request('/api/auth/password', {method:'POST',body:JSON.stringify({currentPassword:current,newPassword:password})});
      setCurrent('');setPassword('');setConfirm('');setNotice('Password changed. Other sessions have been signed out.');
    } catch (reason) {setError(reason instanceof Error ? reason.message : 'Could not change password.');}
    finally {setBusy(false);}
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const index = visibleSections.findIndex(item => item.id === section);
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % visibleSections.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + visibleSections.length) % visibleSections.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = visibleSections.length - 1;
    else return;
    event.preventDefault();
    const nextSection = visibleSections[next].id;
    setSection(nextSection);
    event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`[data-account-tab="${nextSection}"]`)?.focus();
  }

  return <>
    <button type="button" className="settings-account-button" onClick={() => {setSection('profile');setOpen(true);}} aria-haspopup="dialog">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg>Account
    </button>
    <dialog ref={dialog} className="account-dialog" aria-labelledby="account-title" onCancel={event => {if(busy)event.preventDefault();else setOpen(false);}} onClose={() => setOpen(false)}>
      <div className="account-dialog-heading"><div><span className="settings-eyebrow">WORKSPACE ACCESS</span><h2 id="account-title">Account settings</h2></div>
        <button type="button" className="account-close" aria-label="Close account settings" disabled={busy} onClick={() => setOpen(false)}>×</button></div>
      {open && <div className="account-workspace">
        <nav className="account-tabs" role="tablist" aria-label="Account settings sections">
          {visibleSections.map(item => <button key={item.id} type="button" role="tab" id={`account-tab-${item.id}`}
            data-account-tab={item.id} aria-controls={`account-panel-${item.id}`} aria-selected={section === item.id}
            tabIndex={section === item.id ? 0 : -1} className="account-tab"
            onClick={() => setSection(item.id)} onKeyDown={handleTabKeyDown}>{item.label}</button>)}
        </nav>
        <div className="account-panel-viewport">
          <section id="account-panel-profile" className="account-tabpanel" role="tabpanel" aria-labelledby="account-tab-profile" hidden={section !== 'profile'}>
            <div className="account-identity"><span className="account-avatar" aria-hidden="true">{user?.username.slice(0,1).toUpperCase() || '…'}</span>
              <div><strong>{user?.username || 'Loading account…'}</strong><small>{user?.role === 'admin' ? 'Administrator' : 'Workspace member'}</small></div>
              <button type="button" className="secondary-button" disabled={busy || signingOut || !user} onClick={() => {void onSignOut().finally(() => setOpen(false));}}>{signingOut ? 'Signing out…' : 'Log out'}</button></div>
            {loadError && <p className="account-feedback account-feedback-error" role="alert">{loadError}</p>}
            <p className="account-panel-help">Manage your workspace identity and sign-in session here.</p>
          </section>
          <section id="account-panel-password" className="account-tabpanel account-password-section" role="tabpanel" aria-labelledby="account-tab-password" hidden={section !== 'password'}>
            <div className="account-panel-heading"><h3>Change password</h3><p>Use at least 12 characters for your new password.</p></div>
            <form className="account-password-form" onSubmit={event => void save(event)}>
              <label>Current password<input type="password" autoComplete="current-password" required maxLength={1024} value={current} onChange={event => setCurrent(event.target.value)} disabled={busy}/></label>
              <label>New password<input type="password" autoComplete="new-password" required minLength={12} maxLength={1024} value={password} onChange={event => setPassword(event.target.value)} disabled={busy}/></label>
              <label>Confirm new password<input type="password" autoComplete="new-password" required minLength={12} maxLength={1024} value={confirm} onChange={event => setConfirm(event.target.value)} disabled={busy}/></label>
              {error && <p className="account-feedback account-feedback-error" role="alert">{error}</p>}
              {notice && <p className="account-feedback" role="status">{notice}</p>}
              <button type="submit" className="primary-button" disabled={busy || !user}>{busy ? 'Saving…' : 'Update password'}</button>
            </form>
          </section>
          {isAdmin && <section id="account-panel-users" className="account-tabpanel account-users-panel" role="tabpanel" aria-labelledby="account-tab-users" hidden={section !== 'users'}>
            <UserManagement currentUsername={user.username}/>
          </section>}
        </div>
      </div>}
    </dialog>
  </>;
}
