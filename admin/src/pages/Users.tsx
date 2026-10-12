import { Fragment, useEffect, useState, type ReactNode } from 'react';
import { admin, type AdminUserRow, type InviteView, type RoleView } from '../api/endpoints';
import { when } from '../lib/format';
import { roleLabel, type Permission } from '../lib/roles';
import { inviteBadge } from '../ui/badges';
import { ConfirmDialog } from '../ui/Dialog';
import { Icon } from '../ui/icons';
import { Page } from '../ui/Page';
import { useSession } from '../ui/Session';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useToast } from '../ui/toast';
import { useApi, type ApiState } from '../ui/useApi';
import { InviteDialog } from './users/InviteDialog';
import {
  failureText,
  isOpen,
  lastSignIn,
  permissionsText,
  pinReason,
  removeReason,
  roleReason,
  ROLES,
  signInSentence,
  sortRoles,
} from './users/people';
import { DESKTOP, useMediaQuery } from './users/useMediaQuery';
import './Users.css';

const PEOPLE_NOTE =
  'Removing a user disables the account; nothing is deleted. Everything here is written to the change log.';
const NOT_OPEN = 'Only a pending invitation can be withdrawn.';

// Shows the data when there is any, with a quiet line when a refresh failed;
// otherwise the loading or error state for that request alone.
function Body<T>({
  state,
  needs,
  children,
}: {
  state: ApiState<T>;
  needs: Permission;
  children: (data: T) => ReactNode;
}) {
  if (state.data === undefined) {
    if (state.error) return <ErrorState error={state.error} onRetry={state.reload} needs={needs} />;
    return <Loading />;
  }
  return (
    <>
      {state.error && (
        <p className="error-line" role="alert">
          Couldn't refresh. {sentenceFor(state.error)}
        </p>
      )}
      {children(state.data)}
    </>
  );
}

// A question before a write that cannot be undone, and what to run on yes.
interface Confirm {
  title: string;
  text: string;
  confirmLabel: string;
  danger?: boolean;
  run: () => Promise<void>;
}

// What one person's controls need. `role` is the role on screen, which runs
// ahead of the data while a change is in flight.
interface PersonProps {
  user: AdminUserRow;
  users: AdminUserRow[];
  meId: number | undefined;
  role: string;
  busy: boolean;
  error: string | null;
  onRole: (role: string) => void;
  onReset: () => void;
  onRemove: () => void;
}

function RoleSelect({
  user,
  users,
  role,
  busy,
  onRole,
  id,
  labelled,
}: Pick<PersonProps, 'user' | 'users' | 'role' | 'busy' | 'onRole'> & { id: string; labelled: boolean }) {
  const reason = roleReason(user, users);
  return (
    <select
      id={id}
      className="role-select"
      aria-label={labelled ? undefined : `Role for ${user.email}`}
      value={role}
      disabled={busy || reason !== null}
      title={reason ?? undefined}
      onChange={(event) => onRole(event.target.value)}
    >
      {ROLES.map((name) => (
        <option key={name} value={name}>
          {roleLabel(name)}
        </option>
      ))}
    </select>
  );
}

function ResetPinButton({ user, onReset }: Pick<PersonProps, 'user' | 'onReset'>) {
  const reason = pinReason(user);
  return (
    <button
      type="button"
      className="btn btn-small"
      disabled={reason !== null}
      title={reason ?? undefined}
      onClick={onReset}
    >
      Reset PIN
    </button>
  );
}

function RemoveButton({ reason, onRemove }: { reason: string | null; onRemove: () => void }) {
  return (
    <button
      type="button"
      className="btn btn-danger btn-small"
      disabled={reason !== null}
      title={reason ?? undefined}
      onClick={onRemove}
    >
      Remove
    </button>
  );
}

function PinBadge({ user, long }: { user: AdminUserRow; long: boolean }) {
  const text = user.has_pin ? 'set' : 'not set';
  return (
    <span className={user.has_pin ? 'badge badge-ok' : 'badge badge-muted'}>{long ? `PIN ${text}` : text}</span>
  );
}

function You({ user, meId }: Pick<PersonProps, 'user' | 'meId'>) {
  if (user.id !== meId) return null;
  return <span className="badge badge-muted">you</span>;
}

function PersonRow({ user, users, meId, role, busy, error, onRole, onReset, onRemove }: PersonProps) {
  const note = removeReason(user, users, meId);
  return (
    <tr>
      <td>
        <span className="who">
          {user.email}
          <You user={user} meId={meId} />
        </span>
        {note && <p className="inline-note">{note}</p>}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
      </td>
      <td>
        <RoleSelect
          user={user}
          users={users}
          role={role}
          busy={busy}
          onRole={onRole}
          id={`role-${user.id}`}
          labelled={false}
        />
      </td>
      <td>
        <span className="cell-actions">
          <PinBadge user={user} long={false} />
          <ResetPinButton user={user} onReset={onReset} />
        </span>
      </td>
      <td className="cell-nowrap">{lastSignIn(user)}</td>
      <td>
        <RemoveButton reason={note} onRemove={onRemove} />
      </td>
    </tr>
  );
}

function PersonCard({ user, users, meId, role, busy, error, onRole, onReset, onRemove }: PersonProps) {
  const note = removeReason(user, users, meId);
  const id = `role-${user.id}`;
  return (
    <li className="person">
      <div className="card-head">
        <span className="card-title who">
          {user.email}
          <You user={user} meId={meId} />
        </span>
        <PinBadge user={user} long />
      </div>
      <div className="card-meta">
        <span>{signInSentence(user)}</span>
      </div>
      <div className="field">
        <label htmlFor={id}>Role</label>
        <RoleSelect user={user} users={users} role={role} busy={busy} onRole={onRole} id={id} labelled />
      </div>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="card-actions">
        <ResetPinButton user={user} onReset={onReset} />
        <RemoveButton reason={note} onRemove={onRemove} />
      </div>
      {note && <p className="inline-note">{note}</p>}
    </li>
  );
}

function WithdrawButton({ invite, onWithdraw }: { invite: InviteView; onWithdraw: () => void }) {
  const open = isOpen(invite);
  return (
    <button
      type="button"
      className="btn btn-small"
      disabled={!open}
      title={open ? undefined : NOT_OPEN}
      onClick={onWithdraw}
    >
      Withdraw
    </button>
  );
}

export default function Users() {
  const session = useSession();
  const toast = useToast();
  const desktop = useMediaQuery(DESKTOP);
  const users = useApi((signal) => admin.users(signal), []);
  const roles = useApi((signal) => admin.roles(signal), []);
  const invites = useApi((signal) => admin.invites(signal), []);
  const meId = session.me?.user.id;

  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  // A chosen role shows at once and stays until fresh data arrives.
  const [shown, setShown] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [roleError, setRoleError] = useState<{ id: number; text: string } | null>(null);
  useEffect(() => setShown({}), [users.data]);

  function reload() {
    users.reload();
    roles.reload();
    invites.reload();
  }

  function ask(next: Confirm) {
    setConfirmError(null);
    setConfirm(next);
  }

  async function onConfirm() {
    if (!confirm) return;
    setConfirmBusy(true);
    setConfirmError(null);
    try {
      await confirm.run();
      setConfirm(null);
    } catch (err) {
      setConfirmError(failureText(err));
    } finally {
      setConfirmBusy(false);
    }
  }

  function closeConfirm() {
    if (confirmBusy) return;
    setConfirm(null);
    setConfirmError(null);
  }

  async function changeRole(user: AdminUserRow, role: string) {
    if (role === user.role) return;
    setShown((s) => ({ ...s, [user.id]: role }));
    setBusyId(user.id);
    setRoleError(null);
    try {
      await admin.changeRole(user.id, role);
      toast(`${user.email} is now ${role}`);
      // Changing your own role changes what the console lets you see.
      if (user.id === meId) await session.refresh();
      users.reload();
    } catch (err) {
      setShown((s) => {
        const next = { ...s };
        delete next[user.id];
        return next;
      });
      setRoleError({ id: user.id, text: failureText(err) });
    } finally {
      setBusyId(null);
    }
  }

  function resetPin(user: AdminUserRow) {
    ask({
      title: 'Reset PIN',
      text: `Clear the PIN for ${user.email}? They cannot confirm actions until they set a new one in the Ira app.`,
      confirmLabel: 'Clear the PIN',
      run: async () => {
        await admin.resetPin(user.id);
        toast(`The PIN for ${user.email} is cleared.`);
        users.reload();
      },
    });
  }

  function remove(user: AdminUserRow) {
    ask({
      title: 'Remove user',
      text: `Remove ${user.email}? Their account is disabled and their sessions, tokens and Telegram chats are revoked. Their conversations stay in the logs.`,
      confirmLabel: 'Remove',
      danger: true,
      run: async () => {
        await admin.removeUser(user.id);
        toast(`${user.email} was removed.`);
        users.reload();
      },
    });
  }

  function withdraw(invite: InviteView) {
    ask({
      title: 'Withdraw invitation',
      text: `Withdraw the invitation for ${invite.email}? Its link stops working.`,
      confirmLabel: 'Withdraw',
      run: async () => {
        await admin.revokeInvite(invite.id);
        toast(`The invitation for ${invite.email} was withdrawn.`);
        invites.reload();
      },
    });
  }

  const people = (list: AdminUserRow[]) => {
    if (list.length === 0) return <Empty text="No accounts yet. The owner's account appears here after setup." />;
    const propsFor = (user: AdminUserRow): PersonProps => ({
      user,
      users: list,
      meId,
      role: shown[user.id] ?? user.role,
      busy: busyId === user.id,
      error: roleError?.id === user.id ? roleError.text : null,
      onRole: (role) => void changeRole(user, role),
      onReset: () => resetPin(user),
      onRemove: () => remove(user),
    });
    if (!desktop) {
      return (
        <ul className="cards">
          {list.map((user) => (
            <PersonCard key={user.id} {...propsFor(user)} />
          ))}
        </ul>
      );
    }
    return (
      <div className="table-wrap">
        <table className="table people-table">
          <thead>
            <tr>
              <th scope="col">Person</th>
              <th scope="col">Role</th>
              <th scope="col">PIN</th>
              <th scope="col">Last sign-in</th>
              <th scope="col">
                <span className="sr-only">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {list.map((user) => (
              <PersonRow key={user.id} {...propsFor(user)} />
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const invitations = (list: InviteView[]) => {
    if (list.length === 0) return <Empty text="No open invitations." />;
    if (!desktop) {
      return (
        <ul className="cards">
          {list.map((invite) => (
            <li key={invite.id} className="person">
              <div className="card-head">
                <span className="card-title">{invite.email}</span>
                <span className={inviteBadge(invite.state)}>{invite.state}</span>
              </div>
              <div className="card-meta">
                <span className="badge badge-muted">{roleLabel(invite.role)}</span>
                <span>invited by {invite.created_by}</span>
                <span>expires {when(invite.expires_at)}</span>
              </div>
              <div className="card-actions">
                <WithdrawButton invite={invite} onWithdraw={() => withdraw(invite)} />
              </div>
            </li>
          ))}
        </ul>
      );
    }
    return (
      <div className="table-wrap">
        <table className="table invite-table">
          <thead>
            <tr>
              <th scope="col">Person</th>
              <th scope="col">Role</th>
              <th scope="col">Invited by</th>
              <th scope="col">Expires</th>
              <th scope="col">State</th>
              <th scope="col">
                <span className="sr-only">Withdraw</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {list.map((invite) => (
              <tr key={invite.id}>
                <td>
                  <span className="who">{invite.email}</span>
                </td>
                <td>
                  <span className="badge badge-muted">{roleLabel(invite.role)}</span>
                </td>
                <td>{invite.created_by}</td>
                <td className="cell-nowrap">{when(invite.expires_at)}</td>
                <td>
                  <span className={inviteBadge(invite.state)}>{invite.state}</span>
                </td>
                <td>
                  <WithdrawButton invite={invite} onWithdraw={() => withdraw(invite)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const roleTable = (list: RoleView[]) => {
    const sorted = sortRoles(list);
    if (sorted.length === 0) return <Empty text="No roles reported." />;
    if (!desktop) {
      return (
        <dl className="kv roles-kv">
          {sorted.map((role) => (
            <Fragment key={role.role}>
              <dt>{roleLabel(role.role)}</dt>
              <dd>
                <span>{role.description}</span>
                <span className="mono muted">{permissionsText(role)}</span>
              </dd>
            </Fragment>
          ))}
        </dl>
      );
    }
    return (
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">What they can do</th>
              <th scope="col">Permissions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((role) => (
              <tr key={role.role}>
                <td>{roleLabel(role.role)}</td>
                <td>{role.description}</td>
                <td className="mono">{permissionsText(role)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <Page
      title="Users & roles"
      subtitle="Who can use Ira, and what each role may do"
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <section className="section">
        <h2 className="section-title">People</h2>
        <div className="stack">
          <p className="inline-note">{PEOPLE_NOTE}</p>
          <Body state={users} needs="admin.read">
            {people}
          </Body>
        </div>
      </section>

      <section className="section">
        <h2 className="section-title">Invitations</h2>
        <div className="toolbar">
          <button type="button" className="btn btn-primary" onClick={() => setInviting(true)}>
            <Icon name="plus" />
            Invite someone
          </button>
        </div>
        <Body state={invites} needs="users">
          {invitations}
        </Body>
      </section>

      <section className="section">
        <h2 className="section-title">Roles</h2>
        <Body state={roles} needs="admin.read">
          {roleTable}
        </Body>
      </section>

      <ConfirmDialog
        open={confirm !== null}
        title={confirm?.title ?? ''}
        text={confirm?.text ?? ''}
        confirmLabel={confirm?.confirmLabel ?? 'Confirm'}
        danger={confirm?.danger ?? false}
        busy={confirmBusy}
        error={confirmError}
        onConfirm={() => void onConfirm()}
        onClose={closeConfirm}
      />
      <InviteDialog
        open={inviting}
        roles={roles.data}
        onClose={() => setInviting(false)}
        onCreated={() => invites.reload()}
      />
    </Page>
  );
}
