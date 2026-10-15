import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import {
  ACCESS_TOKEN_STORAGE_KEY,
  api,
  AUTH_LOGOUT_EVENT,
  AUTH_REQUIRED_EVENT,
  clearAccessToken,
  getAccessToken,
} from "../services/api-client";
import { hydratePersistentState, resetPersistentState } from '../services/persistent-state';
import {observeSessionActivity} from '../services/session-activity';
import {operatorMessage} from '../operator-language';
import {Brand} from './Brand';

type GateState = "checking" | "setup" | "login" | "unavailable" | "authenticated";

export function AuthGate({ children }: { children: ReactNode }) {
  const [gate, setGate] = useState<GateState>("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const generation = useRef(0);

  useEffect(() => {
    if (gate === 'authenticated') return observeSessionActivity();
  }, [gate]);

  useEffect(() => {
    let active = true;
    const expireSession = () => {
      generation.current++;
      resetPersistentState();
      clearAccessToken();
      setPassword("");
      setGate("login");
      setError("Your sign-in has ended. Please sign in again.");
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
        if (!getAccessToken()) {
          setGate("login");
          return;
        }
        try {
          const token = getAccessToken();
          await api.currentUser();
          if (!current() || getAccessToken() !== token) return;
          await hydratePersistentState();
          if (current() && getAccessToken() === token) setGate("authenticated");
        } catch {
          if (!current()) return;
          clearAccessToken();
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
      if (event.key !== ACCESS_TOKEN_STORAGE_KEY) return;
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
    const expected = ++generation.current;
    setError("");
    setSubmitting(true);
    try {
      const result = await api.login(username.trim(), password);
      if (generation.current !== expected) return;
      window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, result.accessToken);
      setPassword("");
      await hydratePersistentState();
      if (generation.current === expected && getAccessToken() === result.accessToken) setGate("authenticated");
    } catch (reason) {
      if (generation.current === expected) setError(reason instanceof Error ? reason.message : "Sign-in failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (gate === "authenticated") return children;

  return (
    <div className="auth-layout">
      <header className="site-header auth-header">
        <Brand />
        <span className="auth-header-label">Account access</span>
      </header>
      <main className="auth-shell auth-content">
      <section className="auth-card" aria-labelledby="auth-title" aria-busy={gate === "checking" || submitting}>
        <span className="auth-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M8 10V7a4 4 0 0 1 8 0v3M7 10h10a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/><path d="M12 14v3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg></span>
        {gate === "checking" ? (
          <>
            <p className="eyebrow dark">ACCOUNT ACCESS</p>
            <h1 id="auth-title">Checking your sign-in…</h1>
            <p className="auth-description" role="status">Please wait while we check your account access.</p>
          </>
        ) : gate === "setup" ? (
          <>
            <p className="eyebrow dark">ACCOUNT SETUP</p>
            <h1 id="auth-title">Sign-in is not ready yet</h1>
            <p className="auth-description">
              Ask the person managing this system to set up your sign-in account.
            </p>
            <details><summary>Setup instructions for support</summary><p>Set the account and signing secret, then restart the system.</p><pre className="auth-setup-code">{`export VAHAN_UI_AUTH_USERNAME="admin"
export VAHAN_UI_AUTH_PASSWORD="password-at-least-12-characters"
export VAHAN_UI_AUTH_TOKEN_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python -m uvicorn app.main:application --host 127.0.0.1 --port 8000 --reload`}</pre></details>
            <p className="auth-footnote">
              For account security, you may need to sign in again after 12 hours or 60 minutes without activity.
            </p>
          </>
        ) : gate === "unavailable" ? (
          <>
            <p className="eyebrow dark">SYSTEM CONNECTION</p>
            <h1 id="auth-title">Could not connect</h1>
            <p className="auth-description">{operatorMessage(error) || "Could not check your sign-in. Check the connection and try again."}</p>
            <button className="primary-button" type="button" onClick={() => window.location.reload()}>
              Try again
            </button>
          </>
        ) : (
          <>
            <p className="eyebrow dark">ACCOUNT SIGN-IN</p>
            <h1 id="auth-title">Welcome back</h1>
            <p className="auth-description">Sign in to collect and view VAHAN reports.</p>
            <form className="auth-form" onSubmit={handleLogin}>
              <label>
                Username
                <input
                  autoComplete="username"
                  autoFocus
                  maxLength={128}
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
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
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </label>
              {error && <p className="auth-error" role="alert">{operatorMessage(error)}</p>}
              <button className="primary-button" type="submit" disabled={submitting}>
                {submitting ? "Signing in…" : "Sign in"}
              </button>
            </form>
            <p className="auth-footnote">You may be asked to sign in again after a period of inactivity or an account security change.</p>
          </>
        )}
      </section>
      </main>
    </div>
  );
}
