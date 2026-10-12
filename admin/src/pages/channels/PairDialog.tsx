import { useEffect, useRef, useState, type FormEvent } from 'react';
import { admin, type AdminUserRow, type TelegramPairing, type TelegramView, type UserView } from '../../api/endpoints';
import { CopyField } from '../../ui/CopyField';
import { Dialog } from '../../ui/Dialog';
import { Icon } from '../../ui/icons';
import { useApi } from '../../ui/useApi';
import { codeLife, failureText, pairChoices, pairingNote, setupReason, userLabel } from './helpers';

type Choice = Pick<AdminUserRow, 'id' | 'email' | 'role'>;

// The form, then the code once the server made one. It mounts afresh each
// time the dialog opens, so nothing from the last pairing lingers.
function Form({
  view,
  isOwner,
  me,
  onStarted,
  onCancel,
}: {
  view: TelegramView;
  isOwner: boolean;
  me: UserView | undefined;
  onStarted: (pairing: TelegramPairing) => void;
  onCancel: () => void;
}) {
  // Only the owner may pair a chat for someone else, so only the owner
  // needs the list of accounts.
  const users = useApi((signal) => (isOwner ? admin.users(signal) : Promise.resolve(null)), [isOwner]);
  const [userId, setUserId] = useState<number | undefined>(me?.id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectRef = useRef<HTMLSelectElement>(null);

  // The dialog opens with focus on its Close button; the choice is the
  // better place to start.
  useEffect(() => {
    const timer = window.setTimeout(() => selectRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const missing = setupReason(view);
  const choices: Choice[] = users.data ? pairChoices(users.data, me?.id) : me ? [me] : [];

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Your own account is the server's default and needs no extra permission.
      const forSelf = userId === undefined || userId === me?.id;
      const pairing = await admin.startPairing(forSelf ? undefined : userId);
      onStarted(pairing);
    } catch (err) {
      setError(failureText(err));
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={(event) => void submit(event)}>
      {isOwner ? (
        <div className="field">
          <label htmlFor="pair-user">The chat acts as</label>
          <select
            ref={selectRef}
            id="pair-user"
            name="user"
            value={userId === undefined ? '' : String(userId)}
            onChange={(event) => setUserId(Number(event.target.value))}
          >
            {choices.map((user) => (
              <option key={user.id} value={user.id}>
                {userLabel(user, me?.id)}
              </option>
            ))}
          </select>
          {users.error ? (
            <p className="field-error" role="alert">
              Couldn't list the other accounts. {failureText(users.error)}
            </p>
          ) : (
            <p className="field-hint">The bot answers that chat as this account, with its role.</p>
          )}
        </div>
      ) : (
        <p className="dialog-text">
          The chat will act as you{me ? ` (${me.email})` : ''}. Only the owner can pair a chat for someone else.
        </p>
      )}
      {missing && (
        <p className="warn-text pair-warning">
          Right now {missing}, so the bot cannot answer. A code works for {codeLife(view.pairing_seconds)}: finish the
          setup steps first.
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <p className="inline-note">Starting a pairing is recorded in the change log.</p>
      <div className="dialog-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Starting…' : 'Get a code'}
        </button>
      </div>
    </form>
  );
}

function Code({ pairing, view, onDone }: { pairing: TelegramPairing; view: TelegramView; onDone: () => void }) {
  const link = pairing.bot_link ?? view.bot_link;
  return (
    <>
      <CopyField label="Send this to the bot" value={pairing.command} />
      <p className="dialog-text" role="status">
        {pairingNote(pairing, view.pairing_seconds)}
      </p>
      {link && (
        <div className="actions-row">
          <a className="btn btn-small" href={link} target="_blank" rel="noreferrer">
            Open the bot
            <Icon name="external" size={16} />
          </a>
        </div>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn btn-primary" onClick={onDone}>
          Done
        </button>
      </div>
    </>
  );
}

export function PairDialog({
  open,
  view,
  isOwner,
  me,
  started,
  onStarted,
  onClose,
}: {
  open: boolean;
  view: TelegramView;
  isOwner: boolean;
  me: UserView | undefined;
  started: TelegramPairing | null;
  onStarted: (pairing: TelegramPairing) => void;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} title={started ? 'Send the code' : 'Pair a chat'}>
      {started ? (
        <Code pairing={started} view={view} onDone={onClose} />
      ) : (
        <Form view={view} isOwner={isOwner} me={me} onStarted={onStarted} onCancel={onClose} />
      )}
    </Dialog>
  );
}
