import {useEffect, useRef, useState, type FormEvent, type KeyboardEvent} from 'react';
import {api, request} from '../services/api-client';
import {UserManagement} from './DataManagement';

export function AccountSettings({signingOut, onSignOut}: {signingOut: boolean; onSignOut: () => Promise<void>}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'password'|'users'>('password');
  const [user, setUser] = useState<{username: string; role: string} | null>(null);
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    if (open) {
      dialog.current?.showModal();
      void api.currentUser().then(setUser).catch(reason => setError(reason.message));
    } else {
      dialog.current?.close();setCurrent('');setPassword('');setConfirm('');setError('');setNotice('');setActiveTab('password');
    }
  }, [open]);
  async function save(event: FormEvent) {
    event.preventDefault();setError('');setNotice('');
    if (password !== confirm) {setError('The new passwords do not match.');return;}
    setBusy(true);
    try {
      await request('/api/auth/password', {method:'POST',body:JSON.stringify({currentPassword:current,newPassword:password})});
      setCurrent('');setPassword('');setConfirm('');setNotice('Password changed. Other sessions have been signed out.');
    } catch (reason) {setError(reason instanceof Error ? reason.message : 'Could not change password.');}
    finally {setBusy(false);}
  }
  function moveTab(event: KeyboardEvent<HTMLDivElement>) {
    const tabs = ['password', 'users'] as const;
    const currentTab = tabs.indexOf(activeTab);
    const next = event.key === 'ArrowRight' ? (currentTab + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (currentTab + tabs.length - 1) % tabs.length
      : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault();
    setActiveTab(tabs[next]);
    document.getElementById(`account-tab-${tabs[next]}`)?.focus();
  }
  return <>
    <button type="button" className="settings-account-button" onClick={() => setOpen(true)} aria-haspopup="dialog">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg>Account
    </button>
    <dialog ref={dialog} className="account-dialog" data-admin={user?.role === 'admin' ? 'true' : 'false'} aria-labelledby="account-title" onCancel={event => {if(busy)event.preventDefault();else setOpen(false);}}>
      <div className="account-dialog-heading"><div><span className="settings-eyebrow">WORKSPACE ACCESS</span><h2 id="account-title">Account settings</h2></div>
        <button type="button" className="account-close" aria-label="Close account settings" disabled={busy} onClick={() => setOpen(false)}>×</button></div>
      {open && <>
        <div className="account-identity"><span className="account-avatar" aria-hidden="true">{user?.username.slice(0,1).toUpperCase() || '…'}</span>
          <div><strong>{user?.username || 'Loading account…'}</strong><small>{user?.role === 'admin' ? 'Administrator' : 'Workspace member'}</small></div>
          <button type="button" className="secondary-button" disabled={busy || signingOut} onClick={() => {void onSignOut().finally(() => setOpen(false));}}>{signingOut ? 'Signing out…' : 'Log out'}</button></div>
        {user?.role === 'admin' && <div className="account-tabs" role="tablist" aria-label="Account settings sections" onKeyDown={moveTab}>
          <button type="button" role="tab" id="account-tab-password" tabIndex={activeTab === 'password' ? 0 : -1} aria-controls="account-panel-password" aria-selected={activeTab === 'password'} onClick={() => setActiveTab('password')}>Change password</button>
          <button type="button" role="tab" id="account-tab-users" tabIndex={activeTab === 'users' ? 0 : -1} aria-controls="account-panel-users" aria-selected={activeTab === 'users'} onClick={() => setActiveTab('users')}>Manage user accounts</button>
        </div>}
        <div className="account-panels">
          <section id="account-panel-password" className="account-tab-panel account-password-section" role={user?.role === 'admin' ? 'tabpanel' : undefined} aria-labelledby={user?.role === 'admin' ? 'account-tab-password' : undefined} hidden={user?.role === 'admin' && activeTab !== 'password'}>
            <h3>Change password</h3><p>Use at least 12 characters for your new password.</p>
            <form className="account-password-form" onSubmit={event => void save(event)}>
              <label>Current password<input type="password" autoComplete="current-password" required maxLength={1024} value={current} onChange={event => setCurrent(event.target.value)} disabled={busy}/></label>
              <label>New password<input type="password" autoComplete="new-password" required minLength={12} maxLength={1024} value={password} onChange={event => setPassword(event.target.value)} disabled={busy}/></label>
              <label>Confirm new password<input type="password" autoComplete="new-password" required minLength={12} maxLength={1024} value={confirm} onChange={event => setConfirm(event.target.value)} disabled={busy}/></label>
              {error && <p className="account-feedback account-feedback-error" role="alert">{error}</p>}
              {notice && <p className="account-feedback" role="status">{notice}</p>}
              <button type="submit" className="primary-button" disabled={busy || !user}>{busy ? 'Saving…' : 'Update password'}</button>
            </form>
          </section>
          {user?.role === 'admin' && <>
            <section id="account-panel-users" className="account-tab-panel account-users-panel" role="tabpanel" aria-labelledby="account-tab-users" hidden={activeTab !== 'users'}>
              <UserManagement currentUsername={user.username}/>
            </section>
          </>}
        </div>
      </>}
    </dialog>
  </>;
}
