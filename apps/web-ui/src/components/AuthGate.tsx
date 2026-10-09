import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import {
  SESSION_MARKER_STORAGE_KEY,
  api,
  AUTH_LOGOUT_EVENT,
  AUTH_REQUIRED_EVENT,
  clearSessionMarker,
  getSessionMarker,
  acceptLoginSession,
  ApiError,
} from "../services/api-client";
import { hydratePersistentState, resetPersistentState } from '../services/persistent-state';
import {observeSessionActivity} from '../services/session-activity';

type GateState = "checking" | "setup" | "login" | "unavailable" | "authenticated";

export function AuthGate({ children }: { children: ReactNode }) {
  const [gate, setGate] = useState<GateState>("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [retryUntil, setRetryUntil] = useState(0);
  const [retrySeconds, setRetrySeconds] = useState(0);
  const generation = useRef(0);

  useEffect(() => {
    if (!retryUntil) return;
    const update = () => {
      const remaining = Math.max(0, Math.ceil((retryUntil - Date.now()) / 1000));
      setRetrySeconds(remaining);
      if (!remaining) setRetryUntil(0);
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [retryUntil]);

  const signInError = retrySeconds > 0
    ? `Too many sign-in attempts. Try again in ${Math.floor(retrySeconds / 60)}:${String(retrySeconds % 60).padStart(2, '0')}.`
    : error;

  function rateLimited(reason: unknown) {
    if (!(reason instanceof ApiError) || reason.status !== 429) return false;
    const seconds = reason.retryAfterSeconds || 60;
    setRetrySeconds(seconds);
    setRetryUntil(Date.now() + seconds * 1000);
    setError('');
    return true;
  }

  useEffect(() => {
    if (gate === 'authenticated') return observeSessionActivity();
  }, [gate]);

  useEffect(() => {
    let active = true;
    const expireSession = () => {
      generation.current++;
      resetPersistentState();
      clearSessionMarker();
      setPassword("");
      setGate("login");
      setError("Your session is no longer valid. Please sign in again.");
    };
    const signOut = () => {
      generation.current++;
      resetPersistentState();
      setPassword("");
      setError("You have signed out.");
      setGate("login");
    };
    window.addEventListener(AUTH_REQUIRED_EVENT, expireSession);
    window.addEventListener(AUTH_LOGOUT_EVENT, signOut);

    async function restoreSession() {
      const expected = ++generation.current;
      const current = () => active && generation.current === expected;
      try {
        const status = await api.authStatus();
        if (!current()) return;
        if (!status.configured) {
          setGate("setup");
          return;
        }
        try {
          const token = getSessionMarker();
          await api.currentUser();
          if (!current() || getSessionMarker() !== token) return;
          if (!token) localStorage.setItem(SESSION_MARKER_STORAGE_KEY, crypto.randomUUID());
          await hydratePersistentState();
          if (current()) setGate("authenticated");
        } catch {
          if (!current()) return;
          clearSessionMarker();
          setGate("login");
        }
      } catch (reason) {
        if (!current()) return;
        setError(reason instanceof Error ? reason.message : "Could not connect to the API.");
        setGate("unavailable");
      }
    }

    void restoreSession();
    const onStorage = (event: StorageEvent) => {
      if (event.key !== SESSION_MARKER_STORAGE_KEY) return;
      resetPersistentState();
      if (!event.newValue) signOut();
      else {
        setGate('checking');
        void restoreSession();
      }
    };
    window.addEventListener('storage', onStorage);
    return () => {
      active = false;
      window.removeEventListener(AUTH_REQUIRED_EVENT, expireSession);
      window.removeEventListener(AUTH_LOGOUT_EVENT, signOut);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || retrySeconds > 0) return;
    const expected = ++generation.current;
    setError("");
    setSubmitting(true);
    try {
      const result = await api.login(username.trim(), password);
      if (generation.current !== expected) return;
      setPassword("");
      acceptLoginSession(result);
      await hydratePersistentState();
      if (generation.current === expected) setGate("authenticated");
    } catch (reason) {
      if (generation.current === expected) {
        if (rateLimited(reason)) return;
        const message = reason instanceof Error ? reason.message : "Sign-in failed.";
        setError(message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (gate === "authenticated") return children;

  if (gate === "checking") {
    return <main className="auth-shell"><p>Checking your session…</p></main>;
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        {gate === "setup" ? (
          <>
            <p className="eyebrow dark">DASHBOARD SECURITY</p>
            <h1>Sign-in is not configured</h1>
            <p className="auth-description">
              Set a username, a password of at least 12 characters, and a random token secret of at least 32 characters in the API terminal, then restart the backend.
            </p>
            <pre className="auth-setup-code">{`export VAHAN_UI_AUTH_USERNAME="admin"
export VAHAN_UI_AUTH_PASSWORD="password-at-least-12-characters"
export VAHAN_UI_AUTH_TOKEN_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python -m uvicorn app.main:application --host 127.0.0.1 --port 8000 --reload`}</pre>
            <p className="auth-footnote">
              Keep the password and token secret on the server. Sessions end after 12 hours or 60 minutes without activity.
            </p>
          </>
        ) : gate === "unavailable" ? (
          <>
            <p className="eyebrow dark">API CONNECTION</p>
            <h1>Could not connect</h1>
            <p className="auth-description">{error || "Could not check the sign-in configuration."}</p>
            <button className="primary-button" type="button" onClick={() => window.location.reload()}>
              Try again
            </button>
          </>
        ) : (
          <>
            <p className="eyebrow dark">ACCOUNT SIGN-IN</p>
            <h1>Welcome back</h1>
            <p className="auth-description">Sign in to open the VAHAN RPA dashboard.</p>
            <form className="auth-form" onSubmit={handleLogin}>
              <label>
                Username
                <input
                  autoComplete="username"
                  autoFocus
                  maxLength={128}
                  value={username}
                  onChange={(event) => {setUsername(event.target.value); setError('');}}
                  required
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  autoComplete="current-password"
                  maxLength={1024}
                  value={password}
                  onChange={(event) => {setPassword(event.target.value); setError('');}}
                  required
                />
              </label>
              {signInError && <p className="auth-error" role="alert">{signInError}</p>}
              <button className="primary-button" type="submit" disabled={submitting || retrySeconds > 0}>
                {submitting ? "Signing in…" : "Sign in"}
              </button>
            </form>
            <p className="auth-footnote">Sessions end after 12 hours or 60 minutes without activity.</p>
          </>
        )}
      </section>
    </main>
  );
}
