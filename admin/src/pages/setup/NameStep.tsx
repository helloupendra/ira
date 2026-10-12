import { useId, useState, type FormEvent } from 'react';
import { admin, type SettingsView } from '../../api/endpoints';
import { useToast } from '../../ui/toast';
import { useApi } from '../../ui/useApi';
import { Body } from './Body';
import { StepNav } from './StepNav';
import { detailOf, settingsUpdate, voiceLabel, voiceNote } from './steps';

// The voice id, with the voices the text-to-speech in use knows as a list
// to pick from. Any other id is still accepted, as the server says.
function VoiceField({
  id,
  value,
  placeholder,
  onChange,
}: {
  id: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  const models = useApi((signal) => admin.models(signal), []);
  const voices = models.data?.voices ?? [];
  const hasList = voices.length > 0;
  const listId = `${id}-list`;
  return (
    <div className="field">
      <label htmlFor={id}>Voice</label>
      {/* Some browsers hide a datalist's suggestions when autofill is off,
          so autofill stays on only while there is a list. */}
      <input
        id={id}
        type="text"
        maxLength={64}
        autoComplete={hasList ? undefined : 'off'}
        list={hasList ? listId : undefined}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {hasList && (
        <datalist id={listId}>
          {voices.map((voice) => (
            <option key={voice.id} value={voice.id}>
              {voiceLabel(voice)}
            </option>
          ))}
        </datalist>
      )}
      <p className="field-hint">
        {hasList
          ? 'Voices for the text-to-speech in use; another id is accepted too.'
          : 'The text-to-speech voice id: for Polly e.g. Joanna, for OpenAI e.g. alloy.'}
      </p>
    </div>
  );
}

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
        <VoiceField id={`${id}-voice`} value={voice} placeholder={data.voice.default ?? ''} onChange={setVoice} />
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
