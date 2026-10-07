import { useEffect, useState, type FormEvent } from 'react';
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

export function UserManagement() {
  const [admin, setAdmin] = useState(false);
  const [users, setUsers] = useState<User[]>([]);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = () => request<User[]>('/api/users').then(setUsers);
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
  async function toggle(user: User) {
    setError('');
    try { await request(`/api/users/${encodeURIComponent(user.username)}`, {method: 'PATCH', body: JSON.stringify({active: !user.active})}); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update account'); }
  }
  if (!admin) return null;
  return <section className="data-panel"><div className="settings-card-heading"><div><h3>User accounts</h3><p>Manage access to the workspace.</p></div><span>{users.length} accounts</span></div>
    <form className="data-user-form" onSubmit={event => void create(event)}>
      <label>Username<input value={username} onChange={e => setUsername(e.target.value)} pattern="[a-zA-Z0-9_.@\-]+" maxLength={128} required /></label>
      <label>Password<input type="password" autoComplete="new-password" minLength={12} maxLength={1024} value={password} onChange={e => setPassword(e.target.value)} required /></label>
      <button className="primary-button" disabled={busy}>{busy ? 'Saving…' : 'Create user'}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    <div className="data-table"><table><thead><tr><th>Username</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>{users.map(user => <tr key={user.username}><td>{user.username}</td><td><span className="settings-user-role">{user.role}</span></td><td><span className="settings-user-status" data-active={user.active}>{user.active ? 'Active' : 'Disabled'}</span></td>
        <td><button className="secondary-button" onClick={() => void toggle(user)}>{user.active ? 'Disable' : 'Enable'}</button></td></tr>)}</tbody></table></div>
  </section>;
}
