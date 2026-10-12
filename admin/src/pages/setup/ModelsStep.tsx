import { useState } from 'react';
import { admin, type KeyView, type ModelsView, type ModelTestResult, type ProviderView } from '../../api/endpoints';
import { Icon } from '../../ui/icons';
import { Empty } from '../../ui/states';
import { useApi } from '../../ui/useApi';
import { Body } from './Body';
import { StepNav } from './StepNav';
import { chatTier, detailOf, keyState, otherKeys, providerDetail, providersInUse, testLine } from './steps';

type TestState =
  | { status: 'running' }
  | { status: 'done'; result: ModelTestResult }
  | { status: 'error'; detail: string };

function TestText({ state }: { state: TestState }) {
  if (state.status === 'running') return <span className="muted">Testing…</span>;
  if (state.status === 'error') return <span className="danger-text">failed: {state.detail}</span>;
  const line = testLine(state.result);
  return <span className={line.tone === 'ok' ? 'ok-text' : 'danger-text'}>{line.text}</span>;
}

// The tier that answers chat, model by model, each with a Test button.
function Chain({ models, onTested }: { models: ModelsView; onTested: () => void }) {
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const tier = chatTier(models);
  if (!tier) {
    return <Empty text="No tiers in ira.yaml yet. List models under tiers and restart ira serve; they appear here." />;
  }

  async function runTest(ref: string) {
    setTests((all) => ({ ...all, [ref]: { status: 'running' } }));
    try {
      const result = await admin.testModel(ref);
      setTests((all) => ({ ...all, [ref]: { status: 'done', result } }));
    } catch (err) {
      setTests((all) => ({ ...all, [ref]: { status: 'error', detail: detailOf(err) } }));
    }
    onTested();
  }

  return (
    <div className="stack">
      <div className="setup-tier">
        <h3>Tier {tier.name}</h3>
        {tier.used_by_assistant && <span className="badge badge-accent">answers chat</span>}
      </div>
      {tier.chain.length === 0 ? (
        <Empty text="No models in this tier. Add one under tiers in ira.yaml and restart ira serve." />
      ) : (
        <ol className="ordered setup-chain" aria-label={`${tier.name} chain`}>
          {tier.chain.map((ref) => {
            const state = tests[ref];
            const cooling = (models.cooling[ref] ?? 0) > 0;
            return (
              <li key={ref}>
                <span className="mono">{ref}</span>
                {cooling && <span className="badge badge-warn">cooling down</span>}
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={state?.status === 'running'}
                  onClick={() => void runTest(ref)}
                >
                  <Icon name="play" />
                  Test
                </button>
                <p className="chain-result" role="status">
                  {state && <TestText state={state} />}
                </p>
              </li>
            );
          })}
        </ol>
      )}
      <p className="inline-note">
        The first model that answers is the one Ira uses; the rest are fallbacks, in order. A test sends one short
        question to that model alone and is logged like any call.
      </p>
    </div>
  );
}

function KeyCell({ provider, keys }: { provider: ProviderView; keys: readonly KeyView[] }) {
  const state = keyState(provider, keys);
  if (state === 'none') return <span className="muted">no key needed</span>;
  const badge = state === 'set' ? 'badge badge-ok' : state === 'missing' ? 'badge badge-danger' : 'badge badge-muted';
  return (
    <span className="setup-key">
      <span className="mono">{provider.key_env}</span>
      <span className={badge}>{state}</span>
    </span>
  );
}

// Every provider in use with its key, then any other key ira.yaml names.
function Providers({ models, keys }: { models: ModelsView; keys: readonly KeyView[] }) {
  const providers = providersInUse(models);
  const extra = otherKeys(models, keys);
  if (providers.length === 0 && extra.length === 0) {
    return <Empty text="No provider is in use. Name one in a tier in ira.yaml and restart ira serve." />;
  }
  return (
    <ul className="rows">
      {providers.map((p) => (
        <li key={p.name} className="row">
          <span className="setup-rowtext">
            <span className="row-title">{p.name}</span>
            <span className="row-detail">{providerDetail(p)}</span>
          </span>
          <KeyCell provider={p} keys={keys} />
        </li>
      ))}
      {extra.map((key) => (
        <li key={key.env} className="row">
          <span className="setup-rowtext">
            <span className="mono">{key.env}</span>
            <span className="row-detail">{key.used_by.length > 0 ? `used by ${key.used_by.join(', ')}` : 'not used'}</span>
          </span>
          <span className={key.present ? 'badge badge-ok' : 'badge badge-danger'}>{key.present ? 'set' : 'missing'}</span>
        </li>
      ))}
    </ul>
  );
}

// Step 3: which models answer, whether their keys are in place, and a way
// to try each one.
export function ModelsStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const models = useApi((signal) => admin.models(signal), []);
  const keys = useApi((signal) => admin.keys(signal), []);
  return (
    <div className="setup-step">
      <div className="setup-intro">
        <h2>Model provider</h2>
        <p className="muted">Which models answer chat, and whether each provider's key is in place.</p>
      </div>
      <Body state={models} needs="admin.read">
        {(data) => (
          <>
            <Chain models={data} onTested={models.reload} />
            <div className="stack">
              <h3>Providers in use</h3>
              <Providers models={data} keys={keys.data ?? []} />
            </div>
          </>
        )}
      </Body>
      <p className="inline-note">
        Keys are never typed here. Put them in the server's environment or in .env next to ira.yaml, then restart
        ira serve. The free demo router works without any key.
      </p>
      <StepNav onBack={onBack} onNext={onNext} />
    </div>
  );
}
