import { useState, type FormEvent } from 'react';
import { admin, type AdminUserRow } from '../../api/endpoints';
import { Dialog } from '../../ui/Dialog';
import { failureText } from './people';

const MIN_PASSWORD = 10;

// The owner changes someone's email, or sets a password for them to change
// later. A new password signs them out everywhere. It mounts afresh each time
// the dialog opens, so no password lingers.
function Body({
  user,
  onClose,
  onChanged,
}: {
  user: AdminUserRow;
  onClose: () => void;
  onChanged: (text: string) => void;
}) {
  const [email, setEmail] = useState(user.email);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState<'email' | 'password' | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function saveEmail(event: FormEvent) {
    event.preventDefault();
    setBusy('email');
    setError(null);
    try {
      const row = await admin.changeEmail(user.id, email);
      onChanged(`${user.email} now signs in as ${row.email}.`);
    } catch (err) {
      setError(failureText(err));
    } finally {
      setBusy(null);
    }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    setBusy('password');
    setError(null);
    try {
      const { ended } = await admin.resetPassword(user.id, password);
      const sessions = `${ended} session${ended === 1 ? '' : 's'} signed out`;
      onChanged(`New password set for ${user.email}; ${sessions}. Tell them yourself: IRA sends no email.`);
    } catch (err) {
      setError(failureText(err));
    } finally {
      setPassword('');
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <form className="form" autoComplete="off" onSubmit={saveEmail}>
        <div className="field">
          <label htmlFor="account-email">Email they sign in with</label>
          <input
            id="account-email"
            type="email"
            required
            maxLength={254}
            disabled={busy !== null}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <button type="submit" className="btn" disabled={busy !== null || email.trim() === user.email}>
          {busy === 'email' ? 'Saving…' : 'Change email'}
        </button>
      </form>
      <form className="form" autoComplete="off" onSubmit={savePassword}>
        <div className="field">
          <label htmlFor="account-password">New password</label>
          <input
            id="account-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={MIN_PASSWORD}
            maxLength={1024}
            disabled={busy !== null}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p className="field-hint">
            {MIN_PASSWORD} characters or more. Every session of theirs ends; they can change it under Tokens &amp;
            security.
          </p>
        </div>
        <button type="submit" className="btn" disabled={busy !== null}>
          {busy === 'password' ? 'Saving…' : 'Set password'}
        </button>
      </form>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}

export function AccountDialog({
  user,
  onClose,
  onChanged,
}: {
  user: AdminUserRow | null;
  onClose: () => void;
  onChanged: (text: string) => void;
}) {
  return (
    <Dialog open={user !== null} onClose={onClose} title={user ? `Account of ${user.email}` : 'Account'}>
      {user && <Body key={user.id} user={user} onClose={onClose} onChanged={onChanged} />}
    </Dialog>
  );
}
