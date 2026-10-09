import {api, getSessionMarker, type SessionDeadlines} from './api-client';

const ACTIVITY_INTERVAL_MS = 30_000;

/** Send activity only after user input; polling and socket traffic never touch idle TTL. */
export function observeSessionActivity() {
  const token = getSessionMarker();
  let live = true;
  let lastSent = 0;
  let pending: ReturnType<typeof setTimeout> | undefined;
  let expiry: ReturnType<typeof setTimeout> | undefined;
  let inFlight = false;
  const sameSession = () => live && !!token && getSessionMarker() === token;

  function applyDeadlines(value: SessionDeadlines) {
    if (!sameSession() || !value.expiresAt || !value.idleExpiresAt) return;
    if (expiry) clearTimeout(expiry);
    expiry = setTimeout(async () => {
      if (!sameSession()) return;
      // Another tab may have used the shared session since this deadline was
      // received. Validate without touching activity before showing login.
      try {applyDeadlines(await api.currentUser());}
      catch { /* A server 401 clears the session through the API client. */ }
    }, Math.max(250, Math.min(value.expiresAt, value.idleExpiresAt) * 1000 - Date.now()));
  }

  async function sendActivity() {
    pending = undefined;
    if (!sameSession() || inFlight) return;
    lastSent = Date.now();
    inFlight = true;
    try {applyDeadlines(await api.sessionActivity());}
    catch { /* Authentication failures are handled by the API client. */ }
    finally {inFlight = false;}
  }

  function onInput() {
    if (!sameSession() || document.visibilityState !== 'visible' || pending) return;
    const delay = Math.max(0, ACTIVITY_INTERVAL_MS - (Date.now() - lastSent));
    if (delay === 0) void sendActivity();
    else pending = setTimeout(() => void sendActivity(), delay);
  }

  // Opening a valid session is deliberate activity. Later calls require input.
  void sendActivity();
  const events = ['pointerdown', 'keydown', 'input', 'wheel'] as const;
  for (const event of events) document.addEventListener(event, onInput, {passive: true});
  return () => {
    live = false;
    if (pending) clearTimeout(pending);
    if (expiry) clearTimeout(expiry);
    for (const event of events) document.removeEventListener(event, onInput);
  };
}
