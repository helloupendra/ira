import { useId, useState, type FormEvent } from 'react';
import { Link } from 'wouter';
import { ApiError } from '../../api/client';
import { setup } from '../../api/endpoints';
import { useSession } from '../../ui/Session';
import { ownerMessage } from './steps';

// Step 1: the setup code from the server's output, and the owner's email
// and password. Success signs the owner in.
export function OwnerStep({ initialCode, onCreated }: { initialCode: string; onCreated: () => void }) {
  const session = useSession();
  const id = useId();
  const [code, setCode] = useState(initialCode);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<{ text: string; status: number } | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await setup.owner(code.trim(), email.trim(), password);
      setPassword('');
      // The code has done its job: take it out of the address bar.
      history.replaceState(null, '', location.pathname);
      await session.refresh();
      onCreated();
    } catch (err) {
      setError({ text: ownerMessage(err), status: err instanceof ApiError ? err.status : -1 });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="setup-step" onSubmit={onSubmit}>
      <div className="setup-intro">
        <h2>The owner's account</h2>
        <p className="muted">
          The owner can do everything: settings, users and actions. You are signed in as soon as the account
          exists.
        </p>
      </div>
      <div className="field">
        <label htmlFor={`${id}-code`}>Setup code</label>
        <input
          id={`${id}-code`}
          className="mono"
          name="code"
          type="text"
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          placeholder="XXXX-XXXX-XXXX"
          required
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        <p className="field-hint">Printed where ira serve runs. It works once.</p>
      </div>
      <div className="field">
        <label htmlFor={`${id}-email`}>Email</label>
        <input
          id={`${id}-email`}
          name="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-password`}>Password</label>
        <input
          id={`${id}-password`}
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={10}
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <p className="field-hint">At least 10 characters.</p>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error.status === 409 ? (
            <>
              Setup is already done. <Link href="/login?next=/setup">Sign in instead.</Link>
            </>
          ) : (
            error.text
          )}
        </p>
      )}
      <div className="setup-nav">
        <span className="spacer" />
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Creating…' : 'Create the owner account'}
        </button>
      </div>
    </form>
  );
}
