import { useState } from 'react';
import { admin, type TelegramPairing, type TelegramView } from '../../api/endpoints';
import { CopyField } from '../../ui/CopyField';
import { Icon } from '../../ui/icons';
import { codeLife, pairingNote, setupReason } from './channels';
import { detailOf } from './steps';

// The three steps to pair a chat, with the second one done right here: a
// code for your own account. A chat for someone else is paired from the
// Channels page, or with ira telegram pair --user on the server.
export function TelegramPair({ view, onRefresh }: { view: TelegramView; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [pairing, setPairing] = useState<TelegramPairing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const missing = setupReason(view);
  const life = codeLife(view.pairing_seconds);
  const link = pairing?.bot_link ?? view.bot_link;

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setPairing(await admin.startPairing());
    } catch (err) {
      setError(detailOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <ol>
        <li>
          Create a bot with @BotFather, put its token in the server's environment as{' '}
          <span className="mono">{view.token_env}</span>, enable the channel in ira.yaml and restart ira serve.
        </li>
        <li>
          Get a code: press Pair a chat below (for your own account), or where the server runs type{' '}
          <span className="mono">ira telegram pair</span>, with <span className="mono">--user someone@example.com</span>{' '}
          for someone else.
        </li>
        <li>
          Send the <span className="mono">/pair CODE</span> to the bot within {life}. That chat then acts as that
          person.
        </li>
      </ol>
      <div className="actions-row">
        <button type="button" className="btn" disabled={busy} onClick={() => void start()}>
          <Icon name="plus" />
          {busy ? 'Starting…' : pairing ? 'Get another code' : 'Pair a chat'}
        </button>
        {link && (
          <a className="btn btn-ghost" href={link} target="_blank" rel="noreferrer">
            Open the bot
            <Icon name="external" size={16} />
          </a>
        )}
        <button type="button" className="btn btn-ghost" onClick={onRefresh}>
          <Icon name="refresh" />
          Refresh
        </button>
      </div>
      {missing && (
        <p className="warn-text">
          Right now {missing}, so the bot cannot answer. A code works for {life}: do step 1 first.
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {pairing && (
        <div className="stack">
          <CopyField label="Send this to the bot" value={pairing.command} />
          <p className="inline-note" role="status">
            {pairingNote(pairing)} Starting a pairing is recorded in the change log; once the chat has sent the code,
            Refresh counts it above.
          </p>
        </div>
      )}
    </>
  );
}
