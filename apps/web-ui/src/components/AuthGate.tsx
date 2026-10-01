import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import {
  ACCESS_TOKEN_STORAGE_KEY,
  api,
  AUTH_LOGOUT_EVENT,
  AUTH_REQUIRED_EVENT,
  clearAccessToken,
  getAccessToken,
} from "../services/api-client";

type GateState = "checking" | "setup" | "login" | "unavailable" | "authenticated";

export function AuthGate({ children }: { children: ReactNode }) {
  const [gate, setGate] = useState<GateState>("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    const expireSession = () => {
      clearAccessToken();
      setPassword("");
      setGate("login");
      setError("Your session is no longer valid. Please sign in again.");
    };
    const signOut = () => {
      setPassword("");
      setError("You have signed out.");
      setGate("login");
    };
    window.addEventListener(AUTH_REQUIRED_EVENT, expireSession);
    window.addEventListener(AUTH_LOGOUT_EVENT, signOut);

    async function restoreSession() {
      try {
        const status = await api.authStatus();
        if (!active) return;
        if (!status.configured) {
          setGate("setup");
          return;
        }
        if (!getAccessToken()) {
          setGate("login");
          return;
        }
        try {
          await api.currentUser();
          try {
            const renewed = await api.renewSession();
            window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, renewed.accessToken);
          } catch {
            // The current token remains usable; retry renewal the next time the page opens.
            if (!getAccessToken()) {
              if (active) setGate("login");
              return;
            }
          }
          if (active) setGate("authenticated");
        } catch {
          clearAccessToken();
          if (active) setGate("login");
        }
      } catch (reason) {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "Could not connect to the API.");
        setGate("unavailable");
      }
    }

    void restoreSession();
    return () => {
      active = false;
      window.removeEventListener(AUTH_REQUIRED_EVENT, expireSession);
      window.removeEventListener(AUTH_LOGOUT_EVENT, signOut);
    };
  }, []);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const result = await api.login(username.trim(), password);
      window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, result.accessToken);
      setPassword("");
      setGate("authenticated");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign-in failed.");
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
              Keep the password and token secret on the server. Sign-in tokens do not expire automatically.
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
            <p className="eyebrow dark">ADMIN SIGN-IN</p>
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
              {error && <p className="auth-error" role="alert">{error}</p>}
              <button className="primary-button" type="submit" disabled={submitting}>
                {submitting ? "Signing in…" : "Sign in"}
              </button>
            </form>
            <p className="auth-footnote">Your sign-in stays active until you log out or the server signing secret changes.</p>
          </>
        )}
      </section>
    </main>
  );
}
