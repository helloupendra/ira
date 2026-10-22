import { useEffect, useState, type FormEvent } from 'react';
import { downloads, me, type DownloadView, type PairingView } from '../../api/endpoints';
import { CopyField } from '../../ui/CopyField';
import { Dialog } from '../../ui/Dialog';
import { failure } from '../tokens/text';
import { remaining, setupSteps } from './text';

// Add a device: kind, name, the skills it may use, and your PIN (a new device is a new
// grant). The answer is a one-time pairing code with its QR code, good for 10 minutes;
// the dialog waits for the device to use it.
export function PairDeviceDialog({
  open,
  onClose,
  onPaired,
}: {
  open: boolean;
  onClose: () => void;
  onPaired: () => void;
}) {
  const [pairing, setPairing] = useState<PairingView | null>(null);

  function close() {
    setPairing(null);
    onClose();
  }

  return (
    <Dialog open={open} onClose={close} title={pairing ? `Pair ${pairing.label}` : 'Add a device'} wide>
      {pairing ? (
        <PairingCode pairing={pairing} onPaired={onPaired} onDone={close} />
      ) : (
        <PairForm onMade={setPairing} onCancel={close} />
      )}
    </Dialog>
  );
}

function PairForm({ onMade, onCancel }: { onMade: (p: PairingView) => void; onCancel: () => void }) {
  const [kind, setKind] = useState('mac');
  const [label, setLabel] = useState('');
  const [chrome, setChrome] = useState(true);
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const typed = pin;
    setPin(''); // the PIN is never kept
    try {
      const skills = kind === 'mac' && chrome ? ['chrome'] : [];
      onMade(await me.pairDevice(kind, label.trim() || null, skills, typed));
    } catch (err) {
      setError(failure(err));
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <div className="field">
        <label htmlFor="device-kind">Kind</label>
        <select id="device-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="mac">Mac: reads and watches Chrome tabs</option>
          <option value="android">Android phone: the always-on ear (its app comes later)</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="device-label">Name</label>
        <input
          id="device-label"
          type="text"
          maxLength={60}
          autoComplete="off"
          placeholder={kind === 'mac' ? 'My Mac' : 'My Android phone'}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
      </div>
      {kind === 'mac' && (
        <fieldset className="devices-skills">
          <legend>What Ira may use on it</legend>
          <label className="check">
            <input type="checkbox" checked={chrome} onChange={(e) => setChrome(e.target.checked)} />
            <span>Chrome: list your tabs, read the one you ask about, and tell you when it finishes</span>
          </label>
          <p className="field-hint">Nothing else is on. You can switch skills on or off later.</p>
        </fieldset>
      )}
      <div className="field">
        <label htmlFor="device-pin">Your action PIN</label>
        <input
          id="device-pin"
          type="password"
          inputMode="numeric"
          pattern="[0-9]{4,12}"
          minLength={4}
          maxLength={12}
          autoComplete="off"
          required
          value={pin}
          onChange={(e) => setPin(e.target.value)}
        />
        <span className="field-hint">A new device is a new permission, so it needs your PIN.</span>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Making a code…' : 'Make a pairing code'}
        </button>
      </div>
    </form>
  );
}

function PairingCode({
  pairing,
  onPaired,
  onDone,
}: {
  pairing: PairingView;
  onPaired: () => void;
  onDone: () => void;
}) {
  const [now, setNow] = useState(Date.now() / 1000);
  const [state, setState] = useState<'waiting' | 'paired' | 'expired'>('waiting');
  const [mac, setMac] = useState<DownloadView | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    downloads.list(controller.signal).then(
      (list) => setMac(list.find((d) => d.name === 'ira-mac.zip') ?? null),
      () => undefined,
    );
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (state !== 'waiting') return;
    const timer = window.setInterval(() => {
      setNow(Date.now() / 1000);
      me.pairing(pairing.id).then(
        (s) => {
          if (s.state !== 'waiting') {
            setState(s.state);
            if (s.state === 'paired') onPaired();
          }
        },
        () => undefined,
      );
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pairing.id, state, onPaired]);

  const left = remaining(pairing.expires_at, now);
  const steps = setupSteps(pairing.kind);
  const local = /^http:\/\/(127\.0\.0\.1|localhost)/.test(pairing.server);

  return (
    <div className="devices-pairing">
      {state === 'paired' ? (
        <p className="inline-note ok-text" role="status">
          {pairing.label} is paired. Its skills are on: {pairing.skills.join(', ') || 'none yet'}.
        </p>
      ) : (
        <p className="inline-note" role="status">
          {left === 'expired' || state === 'expired'
            ? 'This code expired. Close this and make a new one.'
            : `Waiting for the device. The code works once, for ${left} more.`}
        </p>
      )}
      <div className="devices-code-row">
        <img className="devices-qr" src={pairing.qr_svg} alt={`QR code for pairing ${pairing.label}`} width={168} height={168} />
        <div className="stack">
          <CopyField label="Pairing link: paste it when the installer asks" value={pairing.pair_url} />
          <p className="muted">Or type this code:</p>
          <p className="devices-code mono">{pairing.code}</p>
        </div>
      </div>
      <ol className="devices-steps">
        {steps.map((step, i) => (
          <li key={step}>
            {i === 0 && pairing.kind === 'mac' && mac ? (
              <>
                Download{' '}
                <a href={mac.url} download>
                  the Ira companion for Mac
                </a>{' '}
                and open the zip.
              </>
            ) : (
              step
            )}
          </li>
        ))}
      </ol>
      {local && pairing.kind !== 'mac' && (
        <p className="inline-note warn-text">
          This server answers only on this computer. A phone needs its public address: set public_url.
        </p>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn btn-primary" onClick={onDone}>
          Done
        </button>
      </div>
    </div>
  );
}
