import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation } from 'wouter';
import { invites, type PublicInvite, type Session } from '../api/endpoints';
import { when } from '../lib/format';
import { can, roleLabel } from '../lib/roles';
import { Mark } from '../ui/icons';
import { useSession } from '../ui/Session';
import { ErrorState, Loading } from '../ui/states';
import { useApi } from '../ui/useApi';
import {
  failure,
  GONE,
  isGone,
  MIN_PASSWORD,
  MISSING,
  passwordProblems,
  roleLine,
  tokenFrom,
  type Problems,
} from './invite/text';
import './Invite.css';

// The code leaves the address once it has been used, so a reload or a
// shared screenshot does not carry it.
function dropToken() {
  window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
}

function Missing() {
  return (
    <header className="invite-head">
      <h1>Accept your invitation</h1>
      <p className="muted">{MISSING}</p>
    </header>
  );
}

// A used invitation usually means the person already set a password, so
// signing in is the way on from here.
function Gone() {
  return (
    <>
      <header className="invite-head">
        <h1>Accept your invitation</h1>
        <p className="muted" role="status">
          {GONE}
        </p>
      </header>
      <Link href="/login" className="btn btn-ghost">
        Sign in
      </Link>
    </>
  );
}

// Signed in with a role that cannot read the console: staff use the Ira app.
function SignedIn({ me }: { me: Session }) {
  return (
    <>
      <header className="invite-head">
        <h1>You're in</h1>
        <p className="muted" role="status">
          Signed in as {me.user.email} with the {roleLabel(me.user.role)} role. To talk to Ira, open the Ira app.
        </p>
      </header>
      <a href="/" className="btn btn-primary">
        Open the Ira app
      </a>
    </>
  );
}

function AcceptForm({
  token,
  invite,
  onGone,
  onDone,
}: {
  token: string;
  invite: PublicInvite;
  onGone: () => void;
  onDone: (me: Session) => void;
}) {
  const session = useSession();
  const [, navigate] = useLocation();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [problems, setProblems] = useState<Problems>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const role = roleLine(invite.role);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = passwordProblems(password, confirm);
    setProblems(found);
    if (found.password) {
      passwordRef.current?.focus();
      return;
    }
    if (found.confirm) {
      confirmRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const me = await invites.accept(token, password);
      dropToken();
      setPassword('');
      setConfirm('');
      // The session provider learns about the new cookie before the console
      // mounts; the response itself says whether there is a console to show.
      await session.refresh();
      if (can(me.permissions, 'admin.read')) navigate('/', { replace: true });
      else onDone(me);
    } catch (err) {
      if (isGone(err)) onGone();
      else setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="invite-head">
        <h1>You're invited to IRA</h1>
        <p className="invite-who">
          <strong>{invite.email}</strong> as {roleLabel(invite.role)}, until {when(invite.expires_at)}
        </p>
        {role && <p className="note muted">{role}</p>}
      </header>
      <form className="form" onSubmit={(event) => void submit(event)}>
        <div className={problems.password ? 'field has-error' : 'field'}>
          <label htmlFor="invite-password">Password</label>
          <input
            ref={passwordRef}
            id="invite-password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            aria-invalid={problems.password ? true : undefined}
            aria-describedby="invite-password-hint"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              if (problems.password) setProblems((p) => ({ ...p, password: undefined }));
            }}
          />
          <p id="invite-password-hint" className={problems.password ? 'field-error' : 'field-hint'}>
            {problems.password ?? `At least ${MIN_PASSWORD} characters.`}
          </p>
        </div>
        <div className={problems.confirm ? 'field has-error' : 'field'}>
          <label htmlFor="invite-confirm">Confirm password</label>
          <input
            ref={confirmRef}
            id="invite-confirm"
            name="confirm"
            type="password"
            autoComplete="new-password"
            required
            aria-invalid={problems.confirm ? true : undefined}
            aria-describedby={problems.confirm ? 'invite-confirm-error' : undefined}
            value={confirm}
            onChange={(event) => {
              setConfirm(event.target.value);
              if (problems.confirm) setProblems((p) => ({ ...p, confirm: undefined }));
            }}
          />
          {problems.confirm && (
            <p id="invite-confirm-error" className="field-error">
              {problems.confirm}
            </p>
          )}
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Signing in…' : 'Set password and sign in'}
        </button>
      </form>
    </>
  );
}

// Looks the invitation up, then shows the form, or why there is none.
function Invitation({ token }: { token: string }) {
  const lookup = useApi((signal) => invites.lookup(token, signal), [token]);
  const [gone, setGone] = useState(false);
  const [me, setMe] = useState<Session | null>(null);

  if (me) return <SignedIn me={me} />;
  if (gone || isGone(lookup.error)) return <Gone />;
  if (lookup.data) {
    return <AcceptForm token={token} invite={lookup.data} onGone={() => setGone(true)} onDone={setMe} />;
  }
  if (lookup.error) return <ErrorState error={lookup.error} onRetry={lookup.reload} />;
  return <Loading label="Checking the invitation" />;
}

// The code in the fragment, read again when the fragment changes: a full
// link pasted over an incomplete one swaps the fragment without a reload.
function useToken(): string | null {
  const [token, setToken] = useState(() => tokenFrom(window.location.hash));
  useEffect(() => {
    const read = () => setToken(tokenFrom(window.location.hash));
    window.addEventListener('hashchange', read);
    return () => window.removeEventListener('hashchange', read);
  }, []);
  return token;
}

export default function Invite() {
  const token = useToken();

  useEffect(() => {
    document.title = 'Accept invitation · IRA';
  }, []);

  return (
    <main className="gate">
      <div className="gate-card">
        <Mark tile size={40} />
        {token ? <Invitation key={token} token={token} /> : <Missing />}
      </div>
    </main>
  );
}
