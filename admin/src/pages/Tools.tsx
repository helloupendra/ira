import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { admin, type ToolDetail } from '../api/endpoints';
import { humanize, seconds } from '../lib/format';
import { whyNot } from '../lib/roles';
import { fieldsFor, initialValues, paramsFrom, type Field, type JsonSchema, type Values } from '../lib/schemaForm';
import { onOffBadge } from '../ui/badges';
import { Icon } from '../ui/icons';
import { Json } from '../ui/Json';
import { Page } from '../ui/Page';
import { useSession } from '../ui/Session';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { Switch } from '../ui/Switch';
import { useToast } from '../ui/toast';
import { useApi } from '../ui/useApi';
import { failure, kindBadge, listed, switchedToast } from './tools/helpers';
import './Tools.css';

function Parameters({ fields, schema }: { fields: Field[]; schema: unknown }) {
  return (
    <div className="tool-block">
      <h3 className="tool-h">Parameters</h3>
      {fields.length === 0 ? (
        <p className="muted">This tool takes no parameters.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">Required</th>
                <th scope="col">Description</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => (
                <tr key={field.name}>
                  <td className="mono">{field.name}</td>
                  <td>{field.kind}</td>
                  <td>{field.required ? 'yes' : <span className="muted">no</span>}</td>
                  <td>
                    {field.description}
                    {field.options && <div className="muted">One of: {field.options.join(', ')}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details className="disclosure tool-schema">
        <summary>
          <Icon name="chevronRight" />
          <span className="disclosure-title">JSON schema</span>
        </summary>
        <div className="disclosure-body">
          <Json value={schema} />
        </div>
      </details>
    </div>
  );
}

function Confirmers({ tool }: { tool: ToolDetail }) {
  const roles = tool.confirm_roles ?? [];
  return (
    <div className="tool-block">
      <dl className="kv">
        <dt>Who may confirm</dt>
        <dd>
          {roles.length ? listed(roles) : <span className="muted">no role is listed</span>}{' '}
          <span className="muted">(set in ira.yaml)</span>
        </dd>
      </dl>
      <p className="inline-note">Actions never run from here: Ira proposes them and a person confirms with a PIN.</p>
    </div>
  );
}

// One input per parameter, by the kind the schema gives it. Validation is
// left to paramsFrom so every kind reports errors the same way.
function ParamInput({
  field,
  id,
  value,
  invalid,
  describedBy,
  onChange,
}: {
  field: Field;
  id: string;
  value: string;
  invalid: boolean;
  describedBy: string | undefined;
  onChange: (value: string) => void;
}) {
  const a11y = {
    'aria-invalid': invalid || undefined,
    'aria-describedby': describedBy,
    'aria-required': field.required || undefined,
  };
  switch (field.kind) {
    case 'json':
      return (
        <textarea
          id={id}
          name={field.name}
          className="mono"
          rows={3}
          placeholder={field.placeholder}
          spellCheck={false}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          {...a11y}
        />
      );
    case 'integer':
      return (
        <input
          id={id}
          name={field.name}
          type="number"
          step={1}
          inputMode="numeric"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          {...a11y}
        />
      );
    case 'number':
      return (
        <input
          id={id}
          name={field.name}
          type="number"
          step="any"
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          {...a11y}
        />
      );
    case 'boolean':
    case 'select': {
      const options = field.kind === 'boolean' ? ['true', 'false'] : (field.options ?? []);
      // An optional field can be left empty; a required one starts empty but
      // cannot go back to it once a choice is made.
      const blank = !field.required || value === '';
      return (
        <select id={id} name={field.name} value={value} onChange={(e) => onChange(e.target.value)} {...a11y}>
          {blank && <option value="" disabled={field.required}></option>}
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
    }
    default:
      return (
        <input
          id={id}
          name={field.name}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          {...a11y}
        />
      );
  }
}

type Outcome = { status: 'ok'; seconds: number; result: unknown } | { status: 'failed'; error: string };

function ToolTest({
  tool,
  fields,
  canWrite,
  role,
}: {
  tool: ToolDetail;
  fields: Field[];
  canWrite: boolean;
  role: string;
}) {
  const id = useId();
  const [values, setValues] = useState<Values>(() => initialValues(fields));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  function setValue(name: string, value: string) {
    setValues((v) => ({ ...v, [name]: value }));
    setErrors((e) => {
      if (!(name in e)) return e;
      const next = { ...e };
      delete next[name];
      return next;
    });
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (busy || !canWrite) return;
    const parsed = paramsFrom(fields, values);
    setErrors(parsed.errors);
    const first = fields.find((f) => f.name in parsed.errors);
    if (first) {
      document.getElementById(`${id}-${first.name}`)?.focus();
      return;
    }
    setBusy(true);
    setOutcome(null);
    try {
      const result = await admin.testTool(tool.name, parsed.params);
      if (result.ok) setOutcome({ status: 'ok', seconds: result.seconds, result: result.result });
      else setOutcome({ status: 'failed', error: result.error || 'The tool failed without saying why.' });
    } catch (err) {
      setOutcome({ status: 'failed', error: failure(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tool-block">
      <h3 className="tool-h">Test this tool</h3>
      <form className="form tool-form" noValidate onSubmit={onSubmit}>
        <fieldset className="tool-fields" disabled={!canWrite}>
          {fields.length === 0 && <p className="muted">Nothing to fill in: the tool takes no parameters.</p>}
          {fields.map((field) => {
            const inputId = `${id}-${field.name}`;
            const error = errors[field.name];
            const describedBy =
              [field.description && `${inputId}-hint`, error && `${inputId}-error`].filter(Boolean).join(' ') ||
              undefined;
            return (
              <div key={field.name} className={error ? 'field has-error' : 'field'}>
                <label htmlFor={inputId}>
                  {field.label}
                  {field.required && <span className="tool-required">required</span>}
                </label>
                <ParamInput
                  field={field}
                  id={inputId}
                  value={values[field.name] ?? ''}
                  invalid={Boolean(error)}
                  describedBy={describedBy}
                  onChange={(value) => setValue(field.name, value)}
                />
                {field.description && (
                  <p id={`${inputId}-hint`} className="field-hint">
                    {field.description}
                  </p>
                )}
                {error && (
                  <p id={`${inputId}-error`} className="field-error">
                    {error}
                  </p>
                )}
              </div>
            );
          })}
          <div className="actions-row">
            <button type="submit" className="btn" disabled={busy}>
              <Icon name="play" />
              {busy ? 'Running…' : 'Run test'}
            </button>
          </div>
        </fieldset>
        <p className="inline-note">
          A test runs the tool for real with these parameters and is written to the change log.
        </p>
        {!canWrite && <p className="inline-note">{whyNot(role, 'admin.write')}</p>}
      </form>
      <div className="tool-outcome" role="status" aria-live="polite">
        {outcome?.status === 'ok' && (
          <>
            <p>Ran in {seconds(outcome.seconds)}</p>
            <Json value={outcome.result} />
          </>
        )}
        {outcome?.status === 'failed' && <p className="danger-text">{outcome.error}</p>}
      </div>
    </div>
  );
}

function ToolItem({
  tool,
  canWrite,
  role,
  busy,
  onSwitch,
}: {
  tool: ToolDetail;
  canWrite: boolean;
  role: string;
  busy: boolean;
  onSwitch: (tool: ToolDetail, enabled: boolean) => void;
}) {
  const label = humanize(tool.name);
  const fields = useMemo(() => fieldsFor(tool.parameters as JsonSchema), [tool.parameters]);

  return (
    <details className={tool.enabled ? 'disclosure tool' : 'disclosure tool is-off'}>
      <summary>
        <Icon name="chevronRight" />
        <span className="disclosure-title tool-title">
          <span className="tool-label">{label}</span>
          <span className="tool-id mono muted">{tool.name}</span>
        </span>
        <span className="disclosure-meta tool-badges">
          <span className={kindBadge(tool.kind)}>{tool.kind}</span>
          {canWrite ? (
            !tool.enabled && <span className="badge badge-muted">off</span>
          ) : (
            <span className={onOffBadge(tool.enabled)}>{tool.enabled ? 'on' : 'off'}</span>
          )}
        </span>
        {canWrite && (
          // The switch must not open or close the disclosure it sits in.
          <span className="tool-switch" onClick={(e) => e.preventDefault()}>
            <Switch checked={tool.enabled} onChange={(next) => onSwitch(tool, next)} label={label} busy={busy} />
          </span>
        )}
      </summary>
      <div className="disclosure-body">
        <p className="tool-desc">{tool.description}</p>
        {!canWrite && <p className="inline-note">Switching it off or on: {whyNot(role, 'admin.write')}</p>}
        <Parameters fields={fields} schema={tool.parameters} />
        {tool.kind === 'action' && <Confirmers tool={tool} />}
        {tool.kind === 'read' && <ToolTest tool={tool} fields={fields} canWrite={canWrite} role={role} />}
      </div>
    </details>
  );
}

export default function Tools() {
  const { me, can } = useSession();
  const toast = useToast();
  const canWrite = can('admin.write');
  const role = me?.user.role ?? 'viewer';
  const tools = useApi((signal) => admin.tools(signal), []);
  // What a switch returned, shown until the list is fetched again.
  const [patched, setPatched] = useState<Record<string, ToolDetail>>({});
  const [switching, setSwitching] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setPatched((p) => (Object.keys(p).length ? {} : p));
  }, [tools.data]);

  async function onSwitch(tool: ToolDetail, enabled: boolean) {
    setSwitching((s) => ({ ...s, [tool.name]: true }));
    try {
      const updated = await admin.switchTool(tool.name, enabled);
      setPatched((p) => ({ ...p, [tool.name]: updated }));
      toast(switchedToast(tool.name, updated.enabled));
      tools.reload();
    } catch (err) {
      toast(`Couldn't switch ${humanize(tool.name)} ${enabled ? 'on' : 'off'}. ${failure(err)}`);
    } finally {
      setSwitching((s) => ({ ...s, [tool.name]: false }));
    }
  }

  function body() {
    if (tools.data === undefined) {
      if (tools.error) return <ErrorState error={tools.error} onRetry={tools.reload} needs="admin.read" />;
      return <Loading />;
    }
    if (tools.data.length === 0) {
      return <Empty text="No tools are registered. Add a tool module under tools: in ira.yaml." />;
    }
    return (
      <>
        {tools.error && (
          <p className="error-line" role="alert">
            Couldn't refresh. {sentenceFor(tools.error)}
          </p>
        )}
        {tools.data.map((tool) => (
          <ToolItem
            key={tool.name}
            tool={patched[tool.name] ?? tool}
            canWrite={canWrite}
            role={role}
            busy={switching[tool.name] ?? false}
            onSwitch={onSwitch}
          />
        ))}
      </>
    );
  }

  return (
    <Page
      title="Tools"
      subtitle="What Ira can look up and what it can propose"
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={tools.reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <div className="tools">{body()}</div>
    </Page>
  );
}
