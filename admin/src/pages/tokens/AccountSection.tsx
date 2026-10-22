import { useState, type FormEvent } from 'react';
import { me as account } from '../../api/endpoints';
import { useSession } from '../../ui/Session';
import { useToast } from '../../ui/toast';
import { pinFailure } from './text';

const MIN_PASSWORD = 10;

/** Your own password and email. Both check your password again. */
export function AccountSection() {
  const session = useSession();
  const toast = useToast();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [emailPassword, setEmailPassword] = useState('');
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    if (next !== again) {
      setPasswordError('The two new passwords are not the same.');
      return;
    }
    setPasswordBusy(true);
    setPasswordError(null);
    try {
      const { ended } = await account.changePassword(current, next);
      toast(ended ? `Password changed. ${ended} other session${ended === 1 ? '' : 's'} signed out.` : 'Password changed');
      setNext('');
      setAgain('');
    } catch (err) {
      setPasswordError(pinFailure(err));
    } finally {
      setCurrent('');
      setPasswordBusy(false);
    }
  }

  async function changeEmail(event: FormEvent) {
    event.preventDefault();
    setEmailBusy(true);
    setEmailError(null);
    try {
      await account.changeEmail(email, emailPassword);
      toast('Email changed: sign in with it from now on');
      setEmail('');
      await session.refresh();
    } catch (err) {
      setEmailError(pinFailure(err));
    } finally {
      setEmailPassword('');
      setEmailBusy(false);
    }
  }

  return (
    <div className="stack">
      <form className="form" autoComplete="off" onSubmit={changePassword}>
        <h3 className="tokens-subhead">Password</h3>
        <div className="form-row">
          <div className="field">
            <label htmlFor="account-current">Current password</label>
            <input
              id="account-current"
              type="password"
              autoComplete="current-password"
              required
              maxLength={1024}
              disabled={passwordBusy}
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="account-new">New password</label>
            <input
              id="account-new"
              type="password"
              autoComplete="new-password"
              required
              minLength={MIN_PASSWORD}
              maxLength={1024}
              disabled={passwordBusy}
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="account-again">New password again</label>
            <input
              id="account-again"
              type="password"
              autoComplete="new-password"
              required
              minLength={MIN_PASSWORD}
              maxLength={1024}
              disabled={passwordBusy}
              value={again}
              onChange={(e) => setAgain(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={passwordBusy}>
            {passwordBusy ? 'Saving…' : 'Change password'}
          </button>
        </div>
        <p className="field-hint">
          {MIN_PASSWORD} characters or more. Your other signed-in devices are signed out; this one stays.
        </p>
        {passwordError && (
          <p className="form-error" role="alert">
            {passwordError}
          </p>
        )}
      </form>
      <form className="form" autoComplete="off" onSubmit={changeEmail}>
        <h3 className="tokens-subhead">Email</h3>
        <p className="field-hint">You sign in as {session.me?.user.email}.</p>
        <div className="form-row">
          <div className="field">
            <label htmlFor="account-email">New email</label>
            <input
              id="account-email"
              type="email"
              autoComplete="email"
              required
              maxLength={254}
              disabled={emailBusy}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="account-email-password">Your password</label>
            <input
              id="account-email-password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={1024}
              disabled={emailBusy}
              value={emailPassword}
              onChange={(e) => setEmailPassword(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={emailBusy}>
            {emailBusy ? 'Saving…' : 'Change email'}
          </button>
        </div>
        {emailError && (
          <p className="form-error" role="alert">
            {emailError}
          </p>
        )}
      </form>
    </div>
  );
}
