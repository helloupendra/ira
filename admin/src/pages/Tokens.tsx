import { Fragment, useState, type FormEvent, type ReactNode } from 'react';
import {
  admin,
  me as account,
  type AdminSessionRow,
  type PinStatus,
  type SecurityView,
  type SessionView,
  type TokenCreated,
  type TokenRow,
} from '../api/endpoints';
import { ago, humanize, when } from '../lib/format';
import { roleLabel, whyNot } from '../lib/roles';
import { CopyField } from '../ui/CopyField';
import { ConfirmDialog, Dialog } from '../ui/Dialog';
import { Icon } from '../ui/icons';
import { Page } from '../ui/Page';
import { useSession } from '../ui/Session';
import { Empty, sentenceFor } from '../ui/states';
import { useToast } from '../ui/toast';
import { useApi, type ApiState } from '../ui/useApi';
import { Body } from './tokens/Body';
import { cursorAfter, type Cursor } from './tokens/paging';
import {
  NO_PIN_NEEDED,
  currentFirst,
  deviceLabel,
  endedText,
  failure,
  lockedLine,
  pinFailure,
  pinHint,
  pinLine,
  pinPattern,
  plain,
  plural,
  scopeHint,
  scopeList,
} from './tokens/text';
import { DESKTOP, useMediaQuery } from './tokens/useMediaQuery';
import { usePagedList, type PagedList } from './tokens/usePagedList';
import './Tokens.css';

// Sessions come fifty at a time; Load more asks for the next fifty.
const SESSION_PAGE = 50;

// Once the session making the request is gone, nothing here is valid any
// more: a full load of the sign-in page starts clean.
function leave() {
  window.location.assign('/admin/login');
}

/* API tokens ------------------------------------------------------------- */

function TokenState({ token }: { token: TokenRow }) {
  if (token.revoked_at) {
    return (
      <span className="badge badge-muted" title={`Revoked ${when(token.revoked_at)}`}>
        revoked
      </span>
    );
  }
  return <span className="badge badge-ok">active</span>;
}

function TokenTable({ rows, action }: { rows: TokenRow[]; action: (token: TokenRow) => ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="table tokens-table">
        <thead>
          <tr>
            <th scope="col">Label</th>
            <th scope="col">Owner</th>
            <th scope="col">Scopes</th>
            <th scope="col">Created</th>
            <th scope="col">Last used</th>
            <th scope="col">State</th>
            <th scope="col">
              <span className="sr-only">Revoke</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((token) => (
            <tr key={token.id} className={token.revoked_at ? 'muted' : undefined}>
              <td>{token.label}</td>
              <td>{token.email}</td>
              <td className="mono">{scopeList(token.scopes)}</td>
              <td>{when(token.created_at)}</td>
              <td>{token.last_used_at ? ago(token.last_used_at) : 'never'}</td>
              <td>
                <TokenState token={token} />
              </td>
              <td>{!token.revoked_at && action(token)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TokenCards({ rows, action }: { rows: TokenRow[]; action: (token: TokenRow) => ReactNode }) {
  return (
    <ul className="cards">
      {rows.map((token) => (
        <li key={token.id} className={token.revoked_at ? 'muted' : undefined}>
          <div className="card-head">
            <span className="card-title">{token.label}</span>
            <TokenState token={token} />
          </div>
          <div className="card-meta">
            <span>{token.email}</span>
            <span className="mono">{scopeList(token.scopes)}</span>
            <span>Created {when(token.created_at)}</span>
            <span>{token.last_used_at ? `Last used ${ago(token.last_used_at)}` : 'Never used'}</span>
            {token.revoked_at && <span>Revoked {when(token.revoked_at)}</span>}
          </div>
          {!token.revoked_at && <div className="card-actions">{action(token)}</div>}
        </li>
      ))}
    </ul>
  );
}

function CreateTokenForm({
  scopes,
  onCreated,
  onCancel,
}: {
  scopes: string[] | undefined;
  onCreated: (token: TokenCreated) => void;
  onCancel: () => void;
}) {
  const [label, setLabel] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scopeError, setScopeError] = useState<string | null>(null);

  function toggle(scope: string) {
    setScopeError(null);
    setPicked((list) => (list.includes(scope) ? list.filter((s) => s !== scope) : [...list, scope]));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (picked.length === 0) {
      setScopeError('Pick at least one scope.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // The scopes go in the server's order, not the order they were ticked.
      const created = await admin.createToken(
        label.trim(),
        (scopes ?? []).filter((s) => picked.includes(s)),
      );
      onCreated(created);
    } catch (err) {
      setError(failure(err));
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <div className="field">
        <label htmlFor="token-label">Label</label>
        <input
          id="token-label"
          type="text"
          required
          maxLength={64}
          autoComplete="off"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <span className="field-hint">What it is for: a phone shortcut, a report script, another service.</span>
      </div>
      <fieldset className="tokens-scopes">
        <legend>Scopes</legend>
        {scopes === undefined ? (
          <p className="field-hint">The scopes have not loaded yet. Refresh the page and try again.</p>
        ) : scopes.length === 0 ? (
          <p className="field-hint">Your role holds none of the token scopes.</p>
        ) : (
          <div className="checks">
            {scopes.map((scope) => {
              const hint = scopeHint(scope);
              return (
                <label key={scope} className="check">
                  <input type="checkbox" checked={picked.includes(scope)} onChange={() => toggle(scope)} />
                  <span className="mono">{scope}</span>
                  {hint && <span className="muted">{hint}</span>}
                </label>
              );
            })}
          </div>
        )}
        <p className="field-hint">A token can only do what your role can.</p>
        {scopeError && (
          <p className="field-error" role="alert">
            {scopeError}
          </p>
        )}
      </fieldset>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <p className="inline-note">Creating and revoking tokens is recorded in the change log.</p>
      <div className="dialog-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy || !scopes || scopes.length === 0}>
          {busy ? 'Creating…' : 'Create'}
        </button>
      </div>
    </form>
  );
}

function NewToken({ token, onDone }: { token: TokenCreated; onDone: () => void }) {
  return (
    <>
      <dl className="kv">
        <dt>Label</dt>
        <dd>{token.label}</dd>
        <dt>Scopes</dt>
        <dd className="mono">{scopeList(token.scopes)}</dd>
      </dl>
      <CopyField
        label="Token"
        value={token.token}
        warning="Shown once. Only its hash is stored, so copy it now and keep it somewhere safe."
      />
      <div className="dialog-actions">
        <button type="button" className="btn btn-primary" onClick={onDone}>
          Done
        </button>
      </div>
    </>
  );
}

function TokensSection({
  state,
  scopes,
  canWrite,
  role,
  wide,
}: {
  state: ApiState<TokenRow[]>;
  scopes: string[] | undefined;
  canWrite: boolean;
  role: string;
  wide: boolean;
}) {
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<TokenCreated | null>(null);
  const [revoking, setRevoking] = useState<TokenRow | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const reason = canWrite ? undefined : whyNot(role, 'admin.write');

  function closeCreate() {
    setCreating(false);
    setCreated(null);
  }

  // The token is shown once, so the dialog opens again if it was closed
  // while the request was still running.
  function onCreated(token: TokenCreated) {
    setCreated(token);
    setCreating(true);
    state.reload();
  }

  async function revoke() {
    if (!revoking) return;
    setRevokeBusy(true);
    setRevokeError(null);
    try {
      await admin.revokeToken(revoking.id);
      setRevoking(null);
      toast(`Revoked the token "${revoking.label}".`);
      state.reload();
    } catch (err) {
      setRevokeError(failure(err));
    } finally {
      setRevokeBusy(false);
    }
  }

  const revokeButton = (token: TokenRow) => (
    <button
      type="button"
      className="btn btn-ghost btn-small"
      disabled={!canWrite}
      title={reason}
      onClick={() => setRevoking(token)}
    >
      <Icon name="trash" />
      Revoke
    </button>
  );

  return (
    <>
      <div className="toolbar">
        <button
          type="button"
          className="btn btn-primary btn-small"
          disabled={!canWrite}
          title={reason}
          onClick={() => setCreating(true)}
        >
          <Icon name="plus" />
          Create a token
        </button>
        {reason && <span className="inline-note">{reason}</span>}
      </div>
      <Body state={state} needs="admin.read">
        {(rows) =>
          rows.length === 0 ? (
            <Empty text="No API tokens. Create one for a phone shortcut, a script or another service." />
          ) : wide ? (
            <TokenTable rows={rows} action={revokeButton} />
          ) : (
            <TokenCards rows={rows} action={revokeButton} />
          )
        }
      </Body>

      <Dialog open={creating} onClose={closeCreate} title={created ? 'Your new token' : 'Create a token'}>
        {created ? (
          <NewToken token={created} onDone={closeCreate} />
        ) : (
          <CreateTokenForm scopes={scopes} onCreated={onCreated} onCancel={closeCreate} />
        )}
      </Dialog>

      <ConfirmDialog
        open={revoking !== null}
        title="Revoke this token?"
        text={
          revoking
            ? `Anything using "${revoking.label}" stops working right away. This cannot be undone.`
            : ''
        }
        confirmLabel="Revoke"
        danger
        busy={revokeBusy}
        error={revokeError}
        onConfirm={() => void revoke()}
        onClose={() => {
          if (revokeBusy) return;
          setRevoking(null);
          setRevokeError(null);
        }}
      />
    </>
  );
}

/* Signed-in devices ------------------------------------------------------ */

function ThisDevice({ row }: { row: SessionView }) {
  if (!row.current) return null;
  return <span className="badge badge-accent">This device</span>;
}

// Whose session it is, with the role that person holds now.
function Who({ row, title }: { row: AdminSessionRow; title?: boolean }) {
  return (
    <span className="tokens-who">
      <span className={title ? 'card-title' : undefined}>{row.email}</span>
      <span className="badge badge-muted">{roleLabel(row.role)}</span>
    </span>
  );
}

function LoadMore<T>({ list }: { list: PagedList<T> }) {
  if (!list.hasMore) return null;
  return (
    <div className="tokens-more">
      {list.moreError && (
        <p className="error-line" role="alert">
          {sentenceFor(list.moreError)}
        </p>
      )}
      <button type="button" className="btn btn-small" onClick={list.loadMore} disabled={list.loadingMore}>
        {list.loadingMore ? 'Loading…' : 'Load more'}
      </button>
    </div>
  );
}

function SessionTable<T extends SessionView>({
  rows,
  who,
  action,
}: {
  rows: T[];
  who?: (row: T, asTitle: boolean) => ReactNode;
  action: (row: T) => ReactNode;
}) {
  return (
    <div className="table-wrap">
      <table className="table tokens-table">
        <thead>
          <tr>
            {who && <th scope="col">Who</th>}
            <th scope="col">Device</th>
            <th scope="col">Signed in</th>
            <th scope="col">Last used</th>
            <th scope="col">Expires</th>
            <th scope="col">
              <span className="sr-only">End</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              {who && <td>{who(row, false)}</td>}
              <td className="tokens-device" title={row.user_agent ?? undefined}>
                {deviceLabel(row)} <ThisDevice row={row} />
              </td>
              <td>{when(row.created_at)}</td>
              <td>{row.last_used_at ? ago(row.last_used_at) : 'never'}</td>
              <td>{when(row.expires_at)}</td>
              <td>{action(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SessionCards<T extends SessionView>({
  rows,
  who,
  action,
}: {
  rows: T[];
  who?: (row: T, asTitle: boolean) => ReactNode;
  action: (row: T) => ReactNode;
}) {
  return (
    <ul className="cards">
      {rows.map((row) => (
        <li key={row.id}>
          <div className="card-head">
            {who ? who(row, true) : <span className="card-title">{deviceLabel(row)}</span>}
            <ThisDevice row={row} />
          </div>
          {who && (
            <p className="row-detail tokens-device" title={row.user_agent ?? undefined}>
              {deviceLabel(row)}
            </p>
          )}
          <div className="card-meta">
            <span>Signed in {when(row.created_at)}</span>
            <span>{row.last_used_at ? `Last used ${ago(row.last_used_at)}` : 'Never used'}</span>
            <span>Expires {when(row.expires_at)}</span>
          </div>
          <div className="card-actions">{action(row)}</div>
        </li>
      ))}
    </ul>
  );
}

function DevicesSection({
  mine,
  everyone,
  isOwner,
  myEmail,
  wide,
  onChanged,
}: {
  mine: PagedList<SessionView>;
  everyone: PagedList<AdminSessionRow>;
  isOwner: boolean;
  myEmail: string;
  wide: boolean;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [othersBusy, setOthersBusy] = useState(false);
  const [confirming, setConfirming] = useState<AdminSessionRow | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  async function end(row: SessionView, request: () => Promise<unknown>, done: string) {
    setBusyId(row.id);
    try {
      await request();
      if (row.current) {
        leave();
        return;
      }
      toast(done);
      onChanged();
    } catch (err) {
      toast(failure(err));
    } finally {
      setBusyId(null);
    }
  }

  async function endOthers() {
    setOthersBusy(true);
    try {
      const { ended } = await account.endOtherSessions();
      toast(endedText(ended));
      onChanged();
    } catch (err) {
      toast(failure(err));
    } finally {
      setOthersBusy(false);
    }
  }

  // The owner may end anyone's session; someone else's asks first.
  function endAnyone(row: AdminSessionRow) {
    if (row.email === myEmail) {
      void end(row, () => admin.revokeSession(row.id), 'Signed out that device.');
    } else {
      setConfirming(row);
    }
  }

  async function confirmEnd() {
    if (!confirming) return;
    setConfirmBusy(true);
    setConfirmError(null);
    try {
      await admin.revokeSession(confirming.id);
      toast(`Signed out ${confirming.email} on that device.`);
      setConfirming(null);
      onChanged();
    } catch (err) {
      setConfirmError(failure(err));
    } finally {
      setConfirmBusy(false);
    }
  }

  const endButton = (row: SessionView, onEnd: () => void) => {
    const busy = busyId === row.id;
    return (
      <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={onEnd}>
        {row.current ? (busy ? 'Signing out…' : 'Sign out') : busy ? 'Ending…' : 'End'}
      </button>
    );
  };

  const endMine = (row: SessionView) =>
    endButton(row, () => void end(row, () => account.endSession(row.id), 'Signed out that device.'));
  const endTheirs = (row: AdminSessionRow) => endButton(row, () => endAnyone(row));
  const whoIs = (row: AdminSessionRow, asTitle: boolean) => <Who row={row} title={asTitle} />;

  return (
    <>
      <Body state={mine.state}>
        {(data) => {
          const rows = currentFirst(data);
          const others = rows.filter((row) => !row.current);
          // Another page may hold more devices than the ones loaded so far.
          const alone = others.length === 0 && !mine.hasMore;
          return (
            <>
              <div className="toolbar">
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={alone || othersBusy}
                  onClick={() => void endOthers()}
                >
                  <Icon name="signOut" />
                  {othersBusy ? 'Signing out…' : 'Sign out other devices'}
                </button>
              </div>
              {wide ? <SessionTable rows={rows} action={endMine} /> : <SessionCards rows={rows} action={endMine} />}
              {alone && <Empty text="No other devices are signed in." />}
              <LoadMore list={mine} />
            </>
          );
        }}
      </Body>

      {isOwner && (
        <>
          <h3 className="tokens-subhead">Everyone's sessions</h3>
          <Body state={everyone.state} needs="users">
            {(data) => {
              const rows = currentFirst(data);
              if (rows.length === 0) return <Empty text="No one is signed in." />;
              return (
                <>
                  {wide ? (
                    <SessionTable rows={rows} who={whoIs} action={endTheirs} />
                  ) : (
                    <SessionCards rows={rows} who={whoIs} action={endTheirs} />
                  )}
                  <LoadMore list={everyone} />
                </>
              );
            }}
          </Body>
        </>
      )}

      <ConfirmDialog
        open={confirming !== null}
        title="Sign out this device?"
        text={
          confirming
            ? `${confirming.email} will be signed out on ${deviceLabel(confirming)} and will need to sign in again.`
            : ''
        }
        confirmLabel="End session"
        busy={confirmBusy}
        error={confirmError}
        onConfirm={() => void confirmEnd()}
        onClose={() => {
          if (confirmBusy) return;
          setConfirming(null);
          setConfirmError(null);
        }}
      />
    </>
  );
}

/* Your action PIN -------------------------------------------------------- */

function PinSection({ state, onSaved }: { state: ApiState<PinStatus>; onSaved: () => void }) {
  const toast = useToast();
  const [password, setPassword] = useState('');
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await account.setPin(password, pin);
      toast('PIN saved');
      onSaved();
    } catch (err) {
      setError(pinFailure(err));
    } finally {
      // Neither secret stays in the form, whatever happened.
      setPassword('');
      setPin('');
      setBusy(false);
    }
  }

  return (
    <Body state={state}>
      {(status) => {
        const allowed = status.can_confirm;
        const hint = pinHint(status.pin_min_length, status.pin_max_length);
        return (
          <>
            <p className="tokens-status" role="status">
              <Icon name={status.locked_until ? 'lock' : 'key'} />
              <span>
                {pinLine(status)}
                {status.locked_until ? (
                  <>
                    {' '}
                    <span className="warn-text">{lockedLine(status.locked_until)}</span>
                  </>
                ) : null}
              </span>
            </p>
            <form className="form tokens-pin-form" autoComplete="off" onSubmit={onSubmit}>
              <div className="form-row">
                <div className="field">
                  <label htmlFor="pin-password">Your password</label>
                  <input
                    id="pin-password"
                    type="password"
                    autoComplete="off"
                    required
                    maxLength={1024}
                    disabled={!allowed || busy}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="pin-new">New PIN</label>
                  <input
                    id="pin-new"
                    type="password"
                    inputMode="numeric"
                    pattern={pinPattern(status.pin_min_length, status.pin_max_length)}
                    minLength={status.pin_min_length}
                    maxLength={status.pin_max_length}
                    autoComplete="off"
                    required
                    title={hint}
                    disabled={!allowed || busy}
                    value={pin}
                    onChange={(e) => setPin(e.target.value)}
                  />
                </div>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={!allowed || busy}
                  title={allowed ? undefined : NO_PIN_NEEDED}
                >
                  {busy ? 'Saving…' : status.has_pin ? 'Change PIN' : 'Set PIN'}
                </button>
              </div>
              <p className="field-hint">
                {hint}. Ira asks for it before carrying out an action; your password is checked again here to
                be sure it is you.
              </p>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
            </form>
          </>
        );
      }}
    </Body>
  );
}

/* Rules ------------------------------------------------------------------ */

function roles(list: string[]): string {
  return list.join(', ') || 'no one';
}

function RulesSection({ state }: { state: ApiState<SecurityView> }) {
  return (
    <Body state={state} needs="admin.read">
      {(rules) => (
        <div className="stack">
          {rules.locked_until ? (
            <p className="warn-text" role="status">
              {lockedLine(rules.locked_until)}
            </p>
          ) : null}
          <dl className="kv tokens-rules">
            <dt>Wrong PINs before a lock</dt>
            <dd className={rules.wrong_pins > 0 ? 'warn-text' : undefined}>
              {rules.wrong_pins} of {rules.max_wrong_pins} so far
            </dd>
            <dt>Lock lasts</dt>
            <dd>{plain(rules.lock_minutes)} min</dd>
            <dt>A proposal expires after</dt>
            <dd>{plain(rules.expiry_seconds)} s</dd>
            <dt>Sessions last</dt>
            <dd>{plural(rules.session_days, 'day')}</dd>
            <dt>Cookie</dt>
            <dd className="mono">SameSite={rules.cookie_samesite}</dd>
            <dt>Token scopes</dt>
            <dd className="mono">{rules.token_scopes.join(', ')}</dd>
            <dt>Who may confirm actions by default</dt>
            <dd>{roles(rules.confirm_roles)}</dd>
            {rules.action_rules.map((rule) => (
              <Fragment key={rule.tool}>
                <dt>Who may confirm {humanize(rule.tool)}</dt>
                <dd>{roles(rule.confirm_roles)}</dd>
              </Fragment>
            ))}
            <dt>People without a PIN</dt>
            <dd>
              {rules.users_without_pin.length > 0
                ? rules.users_without_pin.join(', ')
                : 'everyone who can confirm has one'}
            </dd>
          </dl>
          <p className="inline-note">Set in ira.yaml; the console shows it but cannot change it.</p>
        </div>
      )}
    </Body>
  );
}

/* The page --------------------------------------------------------------- */

export default function Tokens() {
  const session = useSession();
  const role = session.me?.user.role ?? 'viewer';
  const myEmail = session.me?.user.email ?? '';
  const permissions = session.me?.permissions ?? [];
  const canWrite = session.can('admin.write');
  const isOwner = session.can('users');
  const wide = useMediaQuery(DESKTOP);

  const tokens = useApi((signal) => admin.tokens(signal), []);
  const security = useApi((signal) => admin.security(signal), []);
  const mine = usePagedList<SessionView, Cursor>(
    (cursor, signal) => account.sessionsPage({ limit: SESSION_PAGE, ...cursor }, signal),
    cursorAfter,
    [],
  );
  const everyone = usePagedList<AdminSessionRow, Cursor>(
    (cursor, signal) =>
      isOwner
        ? admin.sessionsPage({ limit: SESSION_PAGE, ...cursor }, signal)
        : Promise.resolve({ rows: [], hasMore: false }),
    cursorAfter,
    [isOwner],
  );
  const pin = useApi((signal) => account.pin(signal), []);

  // A token may have any of the server's scopes that this role holds itself.
  const scopes = security.data?.token_scopes.filter((scope) => permissions.includes(scope));

  function reload() {
    tokens.reload();
    security.reload();
    mine.state.reload();
    everyone.state.reload();
    pin.reload();
  }

  function sessionsChanged() {
    mine.state.reload();
    everyone.state.reload();
  }

  // A new PIN can take someone off the list of people without one.
  function pinSaved() {
    pin.reload();
    security.reload();
  }

  return (
    <Page
      title="Tokens & security"
      subtitle="API tokens, signed-in devices, and the rules that guard actions"
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <section className="section">
        <h2 className="section-title">API tokens</h2>
        <TokensSection state={tokens} scopes={scopes} canWrite={canWrite} role={role} wide={wide} />
      </section>
      <section className="section">
        <h2 className="section-title">Signed-in devices</h2>
        <DevicesSection
          mine={mine}
          everyone={everyone}
          isOwner={isOwner}
          myEmail={myEmail}
          wide={wide}
          onChanged={sessionsChanged}
        />
      </section>
      <section className="section">
        <h2 className="section-title">Your action PIN</h2>
        <PinSection state={pin} onSaved={pinSaved} />
      </section>
      <section className="section">
        <h2 className="section-title">Rules</h2>
        <RulesSection state={security} />
      </section>
    </Page>
  );
}
