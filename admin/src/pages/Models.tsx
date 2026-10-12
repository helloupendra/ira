import { useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import {
  admin,
  type CoolingReason,
  type KeyView,
  type ModelsView,
  type ModelTestResult,
  type ProviderView,
  type SettingsUpdate,
  type SettingsView,
  type SettingValue,
  type TierView,
  type VoiceOption,
} from '../api/endpoints';
import { ago } from '../lib/format';
import { whyNot } from '../lib/roles';
import { Icon } from '../ui/icons';
import { Page } from '../ui/Page';
import { useSession } from '../ui/Session';
import { Empty } from '../ui/states';
import { useToast } from '../ui/toast';
import { useApi } from '../ui/useApi';
import { Body } from './models/Body';
import { coolingLeft, coolingNote, detailOf, move, sameOrder, testLine, voiceLabel } from './models/helpers';
import './Models.css';

// Fallback chains --------------------------------------------------------

type TestState =
  | { status: 'running' }
  | { status: 'done'; result: ModelTestResult }
  | { status: 'error'; detail: string };

function TestText({ state }: { state: TestState }) {
  if (state.status === 'running') return <span className="muted">Testing…</span>;
  if (state.status === 'error') return <span className="danger-text">failed: {state.detail}</span>;
  const line = testLine(state.result);
  return (
    <>
      <span className={line.tone === 'ok' ? 'ok-text' : 'danger-text'}>{line.text}</span>
      {line.detail && <span className="muted"> {line.detail}</span>}
    </>
  );
}

function TierBlock({
  tier,
  cooling,
  reasons,
  elapsed,
  canWrite,
  onChanged,
}: {
  tier: TierView;
  cooling: Record<string, number>;
  reasons: Record<string, CoolingReason>;
  elapsed: number;
  canWrite: boolean;
  onChanged: () => void;
}) {
  const toast = useToast();
  const uid = useId();
  const [fresh, setFresh] = useState<TierView | null>(null);
  const [draft, setDraft] = useState<string[] | null>(null);
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);

  // A save answers with the tier as it now is; that stands in until the next
  // load brings the same thing, so the list never jumps back in between.
  useEffect(() => setFresh(null), [tier]);
  const view = fresh ?? tier;
  const order = draft ?? view.chain;
  const dirty = draft !== null && !sameOrder(draft, view.chain);

  // Keep the keyboard on the arrow that was just pressed now that its row has
  // moved, or on the other arrow when that one no longer applies.
  useEffect(() => {
    if (focusKey === null) return;
    const [slot, dir] = focusKey.split('/');
    const other = dir === 'up' ? 'down' : 'up';
    const target = [`${uid}${slot}-${dir}`, `${uid}${slot}-${other}`]
      .map((id) => document.getElementById(id))
      .find((el): el is HTMLButtonElement => el instanceof HTMLButtonElement && !el.disabled);
    target?.focus();
    setFocusKey(null);
  }, [focusKey, uid]);

  // The row's place in the chain as ira.yaml lists it: stable while it moves.
  const slotOf = (ref: string) => view.chain.indexOf(ref);

  function shift(index: number, delta: -1 | 1, ref: string) {
    setDraft(move(order, index, delta));
    setFocusKey(`${slotOf(ref)}/${delta < 0 ? 'up' : 'down'}`);
  }

  async function runTest(ref: string) {
    setTests((all) => ({ ...all, [ref]: { status: 'running' } }));
    try {
      const result = await admin.testModel(ref);
      setTests((all) => ({ ...all, [ref]: { status: 'done', result } }));
    } catch (err) {
      setTests((all) => ({ ...all, [ref]: { status: 'error', detail: detailOf(err) } }));
    }
    onChanged();
  }

  async function put(newOrder: string[] | null, said: string) {
    setSaving(true);
    setSaveError(null);
    try {
      const result = await admin.orderTier(view.name, newOrder);
      setFresh(result);
      setDraft(null);
      toast(said);
      onChanged();
    } catch (err) {
      setSaveError(detailOf(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="tier">
      <div className="tier-head">
        <h3 className="tier-name">{view.name}</h3>
        {view.used_by_assistant && <span className="badge badge-accent">answers chat</span>}
      </div>
      {order.length === 0 ? (
        <Empty text="No models in this tier." />
      ) : (
        <ol className="ordered" aria-label={`${view.name} chain`}>
          {order.map((ref, i) => {
            const left = coolingLeft(cooling, ref, elapsed);
            const reason = left === null ? undefined : reasons[ref];
            const state = tests[ref];
            return (
              <li key={ref}>
                <div className="chain-line">
                  <span className="mono">{ref}</span>
                  {left !== null && <span className="badge badge-warn">cooling {left} s</span>}
                </div>
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={!canWrite || state?.status === 'running'}
                  onClick={() => void runTest(ref)}
                >
                  <Icon name="play" />
                  Test
                </button>
                <button
                  type="button"
                  id={`${uid}${slotOf(ref)}-up`}
                  className="icon-btn"
                  aria-label={`Move ${ref} up`}
                  disabled={!canWrite || i === 0}
                  onClick={() => shift(i, -1, ref)}
                >
                  <Icon name="arrowUp" />
                </button>
                <button
                  type="button"
                  id={`${uid}${slotOf(ref)}-down`}
                  className="icon-btn"
                  aria-label={`Move ${ref} down`}
                  disabled={!canWrite || i === order.length - 1}
                  onClick={() => shift(i, 1, ref)}
                >
                  <Icon name="arrowDown" />
                </button>
                {reason && <p className="chain-reason muted">{coolingNote(reason)}</p>}
                <p className="chain-result" role="status">
                  {state && <TestText state={state} />}
                </p>
              </li>
            );
          })}
        </ol>
      )}
      {(dirty || view.overridden || saveError) && (
        <div className="tier-foot">
          {dirty && (
            <div className="actions-row">
              <button
                type="button"
                className="btn btn-primary btn-small"
                disabled={saving}
                onClick={() => void put(order, `Order for ${view.name} saved and written to the change log.`)}
              >
                {saving ? 'Saving…' : 'Save order'}
              </button>
              <button type="button" className="btn btn-ghost btn-small" disabled={saving} onClick={() => setDraft(null)}>
                Discard
              </button>
            </div>
          )}
          {view.overridden && (
            <>
              <p className="inline-note">Reordered here; ira.yaml lists: {view.configured.join(', ')}</p>
              <button
                type="button"
                className="btn btn-small"
                disabled={!canWrite || saving}
                onClick={() => void put(null, `${view.name} follows ira.yaml again.`)}
              >
                <Icon name="reset" />
                Reset to ira.yaml
              </button>
            </>
          )}
          {saveError && (
            <p className="field-error" role="alert">
              {saveError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// Seconds since the models view arrived, ticking only while a model is still
// cooling down, so the badges count down without another request.
function useElapsed(data: ModelsView | undefined): number {
  const loadedAt = useMemo(() => Date.now(), [data]);
  const [now, setNow] = useState(loadedAt);
  const longest = data ? Math.max(0, ...Object.values(data.cooling)) : 0;
  const elapsed = Math.max(0, (now - loadedAt) / 1000);
  const ticking = longest > elapsed;
  useEffect(() => {
    if (!ticking) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [ticking, loadedAt]);
  return elapsed;
}

function Chains({
  data,
  elapsed,
  canWrite,
  onChanged,
}: {
  data: ModelsView;
  elapsed: number;
  canWrite: boolean;
  onChanged: () => void;
}) {
  if (data.tiers.length === 0) {
    return <Empty text="No tiers configured. Chains appear here once ira.yaml lists models under tiers." />;
  }
  return (
    <>
      {data.tiers.map((tier) => (
        <TierBlock
          key={tier.name}
          tier={tier}
          cooling={data.cooling}
          reasons={data.cooling_reasons ?? {}}
          elapsed={elapsed}
          canWrite={canWrite}
          onChanged={onChanged}
        />
      ))}
    </>
  );
}

// Providers --------------------------------------------------------------

function isSet(n: number | null | undefined): n is number {
  return n !== null && n !== undefined;
}

function inUse(p: ProviderView): ReactNode {
  return p.in_use ? <span className="badge badge-ok">in use</span> : <span className="badge badge-muted">unused</span>;
}

function keyCell(p: ProviderView): ReactNode {
  if (!p.key_env) return <span className="muted">not needed</span>;
  return (
    <>
      <span className="mono">{p.key_env}</span>{' '}
      {p.key_present === true && <span className="badge badge-ok">set</span>}
      {p.key_present === false && <span className="badge badge-danger">missing</span>}
    </>
  );
}

function lastOk(p: ProviderView): ReactNode {
  return isSet(p.last_ok_at) ? ago(p.last_ok_at) : <span className="muted">never</span>;
}

function lastError(p: ProviderView): ReactNode {
  if (!isSet(p.last_error_at)) return <span className="muted">none</span>;
  return (
    <>
      {ago(p.last_error_at)}
      {p.last_error_kind && <span className="muted"> {p.last_error_kind}</span>}
    </>
  );
}

function Providers({ providers }: { providers: ProviderView[] }) {
  if (providers.length === 0) return <Empty text="No providers configured." />;
  return (
    <>
      <div className="providers-table table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Provider</th>
              <th scope="col">In use</th>
              <th scope="col">Auth</th>
              <th scope="col">Key</th>
              <th scope="col">Last ok</th>
              <th scope="col">Last error</th>
            </tr>
          </thead>
          <tbody>
            {providers.map((p) => (
              <tr key={p.name}>
                <td>
                  <div className="row-title">{p.name}</div>
                  <div className="row-detail">{p.type}</div>
                </td>
                <td>{inUse(p)}</td>
                <td>{p.auth}</td>
                <td>{keyCell(p)}</td>
                <td>{lastOk(p)}</td>
                <td>{lastError(p)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="providers-cards cards">
        {providers.map((p) => (
          <li key={p.name}>
            <div className="card-head">
              <div>
                <div className="card-title">{p.name}</div>
                <div className="row-detail">{p.type}</div>
              </div>
              {inUse(p)}
            </div>
            <dl className="kv provider-kv">
              <dt>Auth</dt>
              <dd>{p.auth}</dd>
              <dt>Key</dt>
              <dd>{keyCell(p)}</dd>
              <dt>Last ok</dt>
              <dd>{lastOk(p)}</dd>
              <dt>Last error</dt>
              <dd>{lastError(p)}</dd>
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}

// Keys -------------------------------------------------------------------

function Keys({ keys }: { keys: KeyView[] }) {
  if (keys.length === 0) return <Empty text="No secret variables are named in ira.yaml." />;
  return (
    <ul className="rows">
      {keys.map((key) => (
        <li key={key.env} className="row">
          <div className="key-main">
            <span className="mono">{key.env}</span>
            <span className="row-detail">
              {key.used_by.length > 0 ? `used by ${key.used_by.join(', ')}` : 'not used'}
            </span>
          </div>
          <span className={key.present ? 'badge badge-ok' : 'badge badge-danger'}>
            {key.present ? 'set' : 'missing'}
          </span>
        </li>
      ))}
    </ul>
  );
}

// Assistant name and voice -----------------------------------------------

interface Option {
  value: string;
  label: string;
}

function SettingForm({
  id,
  label,
  setting,
  canWrite,
  hint,
  offHint,
  options,
  optionsHint,
  onSave,
  onReset,
}: {
  id: string;
  label: string;
  setting: SettingValue;
  canWrite: boolean;
  hint?: string;
  offHint?: string;
  // Suggestions for the value; anything typed is still accepted. When there
  // are any, `optionsHint` says so in place of `hint`.
  options?: Option[];
  optionsHint?: string;
  onSave: (value: string) => Promise<void>;
  onReset: () => Promise<void>;
}) {
  const current = setting.value ?? '';
  const [draft, setDraft] = useState(current);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setDraft(current), [current]);

  const editable = setting.editable;
  const locked = !canWrite || !editable;
  const changed = draft.trim() !== '' && draft.trim() !== current;
  const list = editable && options && options.length > 0 ? options : null;
  const listId = `${id}-options`;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(detailOf(err));
    } finally {
      setBusy(false);
    }
  }

  const hints: string[] = [];
  if (!editable && offHint) hints.push(offHint);
  if (editable && setting.overridden) hints.push(`ira.yaml says ${setting.default || 'nothing'}.`);
  const what = list ? optionsHint : hint;
  if (editable && what) hints.push(what);

  return (
    <form
      className="setting-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (changed && !locked && !busy) void run(() => onSave(draft.trim()));
      }}
    >
      <div className="form-row">
        <div className={error ? 'field has-error' : 'field'}>
          <div className="setting-label">
            <label htmlFor={id}>{label}</label>
            {editable && (
              <span className={setting.overridden ? 'badge badge-accent' : 'badge badge-muted'}>
                {setting.overridden ? 'set here' : 'from ira.yaml'}
              </span>
            )}
          </div>
          {/* Some browsers hide a datalist's suggestions when autofill is
              off, so autofill stays on only while there is a list. */}
          <input
            id={id}
            type="text"
            maxLength={64}
            autoComplete={list ? undefined : 'off'}
            list={list ? listId : undefined}
            placeholder={setting.default ?? ''}
            value={draft}
            disabled={locked}
            onChange={(event) => setDraft(event.target.value)}
          />
          {list && (
            <datalist id={listId}>
              {list.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </datalist>
          )}
        </div>
        {editable && (
          <div className="actions-row">
            <button type="submit" className="btn btn-primary btn-small" disabled={locked || busy || !changed}>
              {busy ? 'Saving…' : 'Save'}
            </button>
            {setting.overridden && (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                disabled={locked || busy}
                onClick={() => void run(onReset)}
              >
                <Icon name="reset" />
                Reset to ira.yaml
              </button>
            )}
          </div>
        )}
      </div>
      {hints.length > 0 && <p className="field-hint">{hints.join(' ')}</p>}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function Settings({
  data,
  voices,
  canWrite,
  onSave,
}: {
  data: SettingsView;
  voices: VoiceOption[];
  canWrite: boolean;
  onSave: (update: SettingsUpdate, said: string) => Promise<void>;
}) {
  const options = voices.map((voice) => ({ value: voice.id, label: voiceLabel(voice) }));
  return (
    <>
      <div className="form">
        <SettingForm
          id="setting-name"
          label="Name"
          setting={data.name}
          canWrite={canWrite}
          onSave={(name) => onSave({ name }, 'Name saved and written to the change log.')}
          onReset={() => onSave({ name: null }, 'Name follows ira.yaml again.')}
        />
        <SettingForm
          id="setting-voice"
          label="Voice"
          setting={data.voice}
          canWrite={canWrite}
          hint="The text-to-speech voice id: for Polly e.g. Joanna, for OpenAI e.g. alloy."
          offHint="Text-to-speech is off (tts: none), so there is no voice to choose."
          options={options}
          optionsHint="Voices for the text-to-speech in use; others are accepted."
          onSave={(voice) => onSave({ voice }, 'Voice saved and written to the change log.')}
          onReset={() => onSave({ voice: null }, 'Voice follows ira.yaml again.')}
        />
        <dl className="kv">
          <dt>Business</dt>
          <dd>{data.business}</dd>
          <dt>Tier</dt>
          <dd>{data.tier}</dd>
          <dt>Speech to text</dt>
          <dd>{data.stt ?? 'none'}</dd>
          <dt>Text to speech</dt>
          <dd>{data.tts ?? 'none'}</dd>
        </dl>
        <p className="inline-note">Changes take effect at once and are written to the change log.</p>
      </div>
    </>
  );
}

// The page ---------------------------------------------------------------

export default function Models() {
  const session = useSession();
  const toast = useToast();
  const canWrite = session.can('admin.write');
  const reason = canWrite ? null : whyNot(session.me?.user.role ?? 'viewer', 'admin.write');

  const models = useApi((signal) => admin.models(signal), []);
  const keys = useApi((signal) => admin.keys(signal), []);
  const settings = useApi((signal) => admin.settings(signal), []);
  const elapsed = useElapsed(models.data);
  const voices = models.data?.voices ?? [];

  function reload() {
    models.reload();
    keys.reload();
    settings.reload();
  }

  async function saveSetting(update: SettingsUpdate, said: string) {
    await admin.updateSettings(update);
    toast(said);
    settings.reload();
  }

  return (
    <Page
      title="Models & voice"
      subtitle="Fallback chains, providers, keys, and how Ira sounds"
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <section className="section">
        <h2 className="section-title">Fallback chains</h2>
        <div className="stack">
          {reason && <p className="inline-note">{reason}</p>}
          <Body state={models} needs="admin.read">
            {(data) => <Chains data={data} elapsed={elapsed} canWrite={canWrite} onChanged={models.reload} />}
          </Body>
          <p className="inline-note">A test sends one short question to that model alone and is logged like any call.</p>
        </div>
      </section>

      <section className="section">
        <h2 className="section-title">Providers</h2>
        <Body state={models} needs="admin.read">
          {(data) => <Providers providers={data.providers} />}
        </Body>
      </section>

      <section className="section">
        <h2 className="section-title">Keys</h2>
        <div className="stack">
          <p className="inline-note">
            Keys stay in the server's environment or the .env file next to ira.yaml. The console only shows
            whether each one is set; it never sees the value.
          </p>
          <Body state={keys} needs="admin.read">
            {(data) => <Keys keys={data} />}
          </Body>
        </div>
      </section>

      <section className="section">
        <h2 className="section-title">Assistant name and voice</h2>
        <div className="stack">
          {reason && <p className="inline-note">{reason}</p>}
          <Body state={settings} needs="admin.read">
            {(data) => <Settings data={data} voices={voices} canWrite={canWrite} onSave={saveSetting} />}
          </Body>
        </div>
      </section>
    </Page>
  );
}
