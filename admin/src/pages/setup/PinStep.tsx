import { useId, useState, type FormEvent } from 'react';
import { me, type PinStatus } from '../../api/endpoints';
import { Icon } from '../../ui/icons';
import { useToast } from '../../ui/toast';
import { useApi } from '../../ui/useApi';
import { Body } from './Body';
import { StepNav } from './StepNav';
import { lockedText, pinHint, pinLine, pinMessage, pinPattern } from './steps';

function PinBody({ data, onSet }: { data: PinStatus; onSet: () => void }) {
  const toast = useToast();
  const id = useId();
  const [password, setPassword] = useState('');
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const locked = lockedText(data);
  const hint = pinHint(data.pin_min_length, data.pin_max_length);

  if (data.has_pin) {
    return (
      <div className="stack">
        <p className="setup-ok ok-text">
          <Icon name="check" />
          {pinLine(data)}
        </p>
        {locked && <p className="warn-text">{locked}</p>}
        <p className="inline-note">Change it any time under Tokens &amp; security, or in the Ira app's menu.</p>
      </div>
    );
  }
  if (!data.can_confirm) {
    return <p className="inline-note">Your role cannot confirm actions, so there is no PIN to set.</p>;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await me.setPin(password, pin);
      setPassword('');
      setPin('');
      toast('PIN set.');
      onSet();
    } catch (err) {
      setError(pinMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <div className="field">
        <label htmlFor={`${id}-password`}>Your password</label>
        <input
          id={`${id}-password`}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <p className="field-hint">Checked again before the PIN is set.</p>
      </div>
      <div className="field">
        <label htmlFor={`${id}-pin`}>PIN</label>
        <input
          id={`${id}-pin`}
          name="pin"
          type="password"
          inputMode="numeric"
          pattern={pinPattern(data.pin_min_length, data.pin_max_length)}
          minLength={data.pin_min_length}
          maxLength={data.pin_max_length}
          autoComplete="off"
          title={hint}
          required
          value={pin}
          onChange={(e) => setPin(e.target.value)}
        />
        <p className="field-hint">{hint}.</p>
      </div>
      {locked && <p className="warn-text">{locked}</p>}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="actions-row">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Setting…' : 'Set PIN'}
        </button>
      </div>
    </form>
  );
}

// Step 4: the owner's own action PIN. Continuing without one is allowed;
// actions then wait until it is set.
export function PinStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const pin = useApi((signal) => me.pin(signal), []);
  const note =
    pin.data && !pin.data.has_pin && pin.data.can_confirm
      ? 'You can continue without a PIN; actions will wait until one is set.'
      : undefined;
  return (
    <div className="setup-step">
      <div className="setup-intro">
        <h2>Action PIN</h2>
        <p className="muted">
          Your PIN releases actions, such as cancelling an appointment. The server checks it; it never reaches a
          model.
        </p>
      </div>
      <Body state={pin} needs="admin.read">
        {(data) => <PinBody data={data} onSet={pin.reload} />}
      </Body>
      <StepNav onBack={onBack} onNext={onNext} note={note} />
    </div>
  );
}
