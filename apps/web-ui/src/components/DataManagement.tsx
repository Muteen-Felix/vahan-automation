import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, request } from '../services/api-client';
import { STATE_SYNC_EVENT } from '../services/persistent-state';

type User = {username: string; role: string; active: boolean};

export function StateSyncStatus() {
  const [error, setError] = useState('');
  useEffect(() => {
    const receive = (event: Event) => setError((event as CustomEvent<string>).detail);
    window.addEventListener(STATE_SYNC_EVENT, receive);
    return () => window.removeEventListener(STATE_SYNC_EVENT, receive);
  }, []);
  return error ? <div className="global-error" role="alert">{error}</div> : null;
}

export function UserManagement({currentUsername}: {currentUsername?: string}) {
  const resetDialog = useRef<HTMLDialogElement>(null);
  const [resetUser, setResetUser] = useState('');
  const [resetPassword, setResetPassword] = useState('');
  const [resetConfirm, setResetConfirm] = useState('');
  const [resetError, setResetError] = useState('');
  const [notice, setNotice] = useState('');
  const [admin, setAdmin] = useState(false);
  const [users, setUsers] = useState<User[]>([]);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = () => request<User[]>('/api/users').then(setUsers);
  useEffect(() => {
    if (resetUser) {
      if (!resetDialog.current?.open) resetDialog.current?.showModal();
    } else if (resetDialog.current?.open) resetDialog.current.close();
    return () => {if (resetDialog.current?.open) resetDialog.current.close();};
  }, [resetUser]);
  useEffect(() => { void api.currentUser().then(user => {
    if (user.role === 'admin') { setAdmin(true); return load(); }
  }).catch(reason => setError(reason.message)); }, []);
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await request('/api/users', {method: 'POST', body: JSON.stringify({username, password})});
      setUsername(''); setPassword(''); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not create account'); }
    finally { setBusy(false); }
  }
  async function reset(event: FormEvent) {
    event.preventDefault();setResetError('');setNotice('');
    if (resetPassword !== resetConfirm) {setResetError('The new passwords do not match.');return;}
    setBusy(true);
    try {
      await request(`/api/users/${encodeURIComponent(resetUser)}/password`, {method:'POST',body:JSON.stringify({password:resetPassword})});
      setNotice(`Password reset for ${resetUser}. Their existing sessions have been signed out.`);
      setResetUser('');setResetPassword('');setResetConfirm('');
    } catch(reason) {setResetError(reason instanceof Error ? reason.message : 'Could not reset password.');}
    finally {setBusy(false);}
  }
  function closeReset() {
    if (busy) return;
    setResetUser('');setResetPassword('');setResetConfirm('');setResetError('');
  }
  async function toggle(user: User) {
    setError('');
    try { await request(`/api/users/${encodeURIComponent(user.username)}`, {method: 'PATCH', body: JSON.stringify({active: !user.active})}); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update account'); }
  }
  async function changeRole(user: User) {
    setBusy(true); setError(''); setNotice('');
    try {
      await request(`/api/users/${encodeURIComponent(user.username)}`, {method:'PATCH', body:JSON.stringify({role:user.role === 'admin' ? 'user' : 'admin'})});
      setNotice(`Updated permissions for ${user.username}. They must sign in again.`);
      await load();
    } catch (reason) {setError(reason instanceof Error ? reason.message : 'Could not update permissions.');}
    finally {setBusy(false);}
  }
  if (!admin) return null;
  return <section className="data-panel"><div className="settings-card-heading"><div><h3>User accounts</h3><p>Manage access to the workspace.</p></div><span>{users.length} accounts</span></div>
    <form className="data-user-form" onSubmit={event => void create(event)}>
      <label>Username<input value={username} onChange={e => setUsername(e.target.value)} pattern="[a-zA-Z0-9_.@\-]+" maxLength={128} required /></label>
      <label>Password<input type="password" autoComplete="new-password" minLength={12} maxLength={1024} value={password} onChange={e => setPassword(e.target.value)} required /></label>
      <button className="primary-button" disabled={busy}>{busy ? 'Saving…' : 'Create user'}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status" className="account-feedback">{notice}</p>}
    <dialog ref={resetDialog} className="account-reset-dialog" aria-labelledby="account-reset-title" onCancel={event => {if(busy)event.preventDefault();else closeReset();}}>
      <div className="account-reset-heading"><div><span className="account-overview-kicker">USER ACCOUNT</span><h3 id="account-reset-title">Reset password</h3><p>Set a new password for <strong>{resetUser}</strong>.</p></div>
        <button type="button" className="account-close" aria-label="Close password reset" disabled={busy} onClick={closeReset}>×</button></div>
      <form className="account-reset-form" onSubmit={event => void reset(event)}>
        <p>This will sign out this user's existing sessions.</p>
        <label>New password<input type="password" autoComplete="new-password" required minLength={12} maxLength={1024} value={resetPassword} onChange={event=>setResetPassword(event.target.value)} disabled={busy}/></label>
        <label>Confirm new password<input type="password" autoComplete="new-password" required minLength={12} maxLength={1024} value={resetConfirm} onChange={event=>setResetConfirm(event.target.value)} disabled={busy}/></label>
        {resetError && <p className="account-feedback account-feedback-error" role="alert">{resetError}</p>}
        <div className="account-reset-actions"><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Saving…' : 'Save new password'}</button><button type="button" className="secondary-button" disabled={busy} onClick={closeReset}>Cancel</button></div>
      </form>
    </dialog>
    <div className="data-table"><table><thead><tr><th>Username</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>{users.map(user => <tr key={user.username}><td>{user.username}</td><td><span className="settings-user-role">{user.role}</span></td><td><span className="settings-user-status" data-active={user.active}>{user.active ? 'Active' : 'Disabled'}</span></td>
        <td><button type="button" className="secondary-button" disabled={busy} onClick={() => void toggle(user)}>{user.active ? 'Disable' : 'Enable'}</button> {user.username !== currentUsername && <><button type="button" className="secondary-button" disabled={busy} onClick={() => void changeRole(user)}>{user.role === 'admin' ? 'Revoke admin' : 'Grant admin'}</button> <button type="button" className="secondary-button" disabled={busy} onClick={()=>{setResetUser(user.username);setResetPassword('');setResetConfirm('');setResetError('');setError('');setNotice('');}}>Reset password</button></>}</td></tr>)}</tbody></table></div>
  </section>;
}
