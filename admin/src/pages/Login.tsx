import { useEffect, useState, type FormEvent } from 'react';
import { useLocation, useSearch } from 'wouter';
import { ApiError } from '../api/client';
import { auth } from '../api/endpoints';
import { Mark } from '../ui/icons';
import { useSession } from '../ui/Session';

// Only a path inside the console may be the place to go after signing in.
function safeNext(value: string | null): string {
  if (value && value.startsWith('/') && !value.startsWith('//')) return value;
  return '/';
}

// The server's detail, as a sentence: "wrong email or password" reads as
// "Wrong email or password."
function sentence(detail: string): string {
  const text = detail.charAt(0).toUpperCase() + detail.slice(1);
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function messageFor(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return 'Too many tries. Wait 15 minutes.';
    if (err.status === 0) return 'Cannot reach the server. Check the connection and try again.';
    return sentence(err.detail);
  }
  return 'Something went wrong. Try again.';
}

export default function Login() {
  const session = useSession();
  const [, navigate] = useLocation();
  const search = useSearch();
  const next = safeNext(new URLSearchParams(search).get('next'));

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.title = 'Sign in · IRA';
  }, []);

  // Already signed in: there is nothing to do here.
  useEffect(() => {
    if (session.status === 'ready') navigate(next, { replace: true });
  }, [session.status, next, navigate]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.login(email.trim(), password);
      setPassword('');
      await session.refresh();
      navigate(next, { replace: true });
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="gate">
      <form className="gate-card login" onSubmit={onSubmit}>
        <Mark tile size={40} />
        <h1>Sign in to IRA</h1>
        <div className="field">
          <label htmlFor="login-email">Email</label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="username"
            inputMode="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="login-password">Password</label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="note muted">
          To talk to Ira, open <a href="/">the Ira app</a>. The console is for owners, admins and viewers.
        </p>
      </form>
    </main>
  );
}
