import { api, getSessionMarker } from './api-client';

export const STATE_SYNC_EVENT = 'vahan:state-sync';
const LEGACY_KEYS = ['vahanStateRtoMatrixV1', 'vahanStateRtoBatchRecoveryV1', 'vahanActiveJobId'];
let values: Record<string, unknown> = {};
let owner = '';
let pending = new Map<string, unknown>();
let writing: Promise<void> | null = null;
let generation = 0;
let retry: ReturnType<typeof setTimeout> | undefined;

export function resetPersistentState() {
  generation++;
  values = {}; owner = ''; pending.clear();
  clearTimeout(retry); retry = undefined;
}

export async function hydratePersistentState() {
  resetPersistentState();
  const current = generation;
  const user = await api.currentUser();
  const restored = await api.userState();
  if (current !== generation) return;
  // Claim unowned legacy browser data once, for the administrator only.
  const previous = localStorage.getItem('vahanStateOwner');
  if (user.role === 'admin' && (!previous || previous === user.username)) {
    for (const key of LEGACY_KEYS) {
      const raw = localStorage.getItem(key);
      if (raw && restored[key] === undefined) {
        let value: unknown;
        try { value = key === 'vahanActiveJobId' ? raw : JSON.parse(raw); }
        catch { continue; }
        await api.putUserState(key, value);
        restored[key] = value;
      }
    }
  }
  if (current !== generation) return;
  for (const key of LEGACY_KEYS) localStorage.removeItem(key);
  localStorage.setItem('vahanStateOwner', user.username);
  values = restored; owner = user.username;
}

function notify(error: string) {
  window.dispatchEvent(new CustomEvent(STATE_SYNC_EVENT, {detail: error}));
}

function flush(): Promise<void> {
  if (writing) return writing;
  if (!owner || !pending.size) return Promise.resolve();
  writing = drain().finally(() => { writing = null; if (pending.size && !retry) void flush(); });
  return writing;
}

async function drain() {
  const current = generation;
  const token = getSessionMarker();
  try {
    while (pending.size && current === generation) {
      const [key, value] = pending.entries().next().value as [string, unknown];
      await api.putUserState(key, value, token);
      if (current === generation && pending.get(key) === value) pending.delete(key);
    }
    if (current === generation) notify('');
  } catch (error) {
    if (current === generation) {
      notify(`Your latest changes have not been saved yet: ${error instanceof Error ? error.message : 'API unavailable'}`);
      retry = setTimeout(() => { retry = undefined; void flush(); }, 5_000);
    }
  } finally {
    if (current !== generation) clearTimeout(retry);
  }
}

export async function flushPersistentState() {
  await flush();
  if (pending.size) throw new Error('Wait for your latest changes to be saved before signing out.');
}

export const persistentState = {
  getItem(key: string): string | null {
    const value = values[key];
    return value == null ? null : typeof value === 'string' ? value : JSON.stringify(value);
  },
  setItem(key: string, raw: string) {
    let value: unknown = raw;
    try { value = JSON.parse(raw); } catch { /* Plain identifiers remain strings. */ }
    values[key] = value; pending.set(key, value); void flush();
  },
  removeItem(key: string) {
    values[key] = null; pending.set(key, null); void flush();
  },
};
