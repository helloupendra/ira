import { useId, useState, type FormEvent } from 'react';
import { admin, type SettingsView } from '../../api/endpoints';
import { useToast } from '../../ui/toast';
import { useApi } from '../../ui/useApi';
import { Body } from './Body';
import { StepNav } from './StepNav';
import { detailOf, settingsUpdate, voiceNote } from './steps';

function NameForm({ data, onNext }: { data: SettingsView; onNext: () => void }) {
  const toast = useToast();
  const id = useId();
  const [name, setName] = useState(data.name.value ?? '');
  const [voice, setVoice] = useState(data.voice.value ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const update = settingsUpdate({ name, voice }, data);
    // Nothing changed: nothing to write, so just go on.
    if (!update) {
      onNext();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await admin.updateSettings(update);
      toast('Saved and written to the change log.');
      onNext();
    } catch (err) {
      setError(detailOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <div className="field">
        <label htmlFor={`${id}-name`}>Name</label>
        <input
          id={`${id}-name`}
          type="text"
          maxLength={64}
          autoComplete="off"
          placeholder={data.name.default ?? ''}
          value={name}
          disabled={!data.name.editable}
          onChange={(e) => setName(e.target.value)}
        />
        <p className="field-hint">How the assistant introduces itself in the app and on Telegram.</p>
      </div>
      {data.voice.editable ? (
        <div className="field">
          <label htmlFor={`${id}-voice`}>Voice</label>
          <input
            id={`${id}-voice`}
            type="text"
            maxLength={64}
            autoComplete="off"
            placeholder={data.voice.default ?? ''}
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
          />
          <p className="field-hint">The text-to-speech voice id: for Polly e.g. Joanna, for OpenAI e.g. alloy.</p>
        </div>
      ) : (
        <p className="inline-note">{voiceNote(data)}</p>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <StepNav onNext={onNext} nextLabel="Skip" nextQuiet busy={busy}>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </button>
      </StepNav>
    </form>
  );
}

// Step 2: what the assistant calls itself and, when text-to-speech is on,
// which voice it speaks with.
export function NameStep({ onNext }: { onNext: () => void }) {
  const settings = useApi((signal) => admin.settings(signal), []);
  return (
    <div className="setup-step">
      <div className="setup-intro">
        <h2>Name and voice</h2>
        <p className="muted">
          What the assistant calls itself, and how it sounds when it speaks. Both can be changed later under
          Models &amp; voice.
        </p>
      </div>
      <Body state={settings} needs="admin.read">
        {(data) => <NameForm data={data} onNext={onNext} />}
      </Body>
    </div>
  );
}
