import { useEffect, useRef, useState, type FormEvent } from 'react';
import { admin, type InviteCreated, type RoleView } from '../../api/endpoints';
import { roleLabel } from '../../lib/roles';
import { CopyField } from '../../ui/CopyField';
import { Dialog } from '../../ui/Dialog';
import { failureText, inviteLink, ROLES, sortRoles } from './people';

const LINK_WARNING = 'Shown once. Send it yourself: IRA sends no email. It works once and expires in 72 hours.';

// The form, then the link once the invitation exists. It mounts afresh each
// time the dialog opens, so nothing from the last invitation lingers.
function Body({
  roles,
  onClose,
  onCreated,
}: {
  roles: RoleView[] | undefined;
  onClose: () => void;
  onCreated: (created: InviteCreated) => void;
}) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('staff');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<InviteCreated | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  // The dialog opens with focus on its Close button; the email field is the
  // better place to start.
  useEffect(() => {
    const timer = window.setTimeout(() => emailRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const choices = roles ? sortRoles(roles).map((r) => r.role) : [...ROLES];
  const hint = roles?.find((r) => r.role === role)?.description;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await admin.createInvite(email.trim(), role);
      setCreated(result);
      onCreated(result);
    } catch (err) {
      setError(failureText(err));
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <>
        <p className="dialog-text">
          {created.invite.email} is invited as {roleLabel(created.invite.role)}.
        </p>
        <CopyField
          label="Invitation link"
          value={inviteLink(window.location.origin, created.path)}
          warning={LINK_WARNING}
        />
        <div className="dialog-actions">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Done
          </button>
        </div>
      </>
    );
  }

  return (
    <form className="form" onSubmit={(event) => void submit(event)}>
      <div className="field">
        <label htmlFor="invite-email">Email</label>
        <input
          ref={emailRef}
          id="invite-email"
          name="email"
          type="email"
          inputMode="email"
          autoComplete="off"
          required
          maxLength={254}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="invite-role">Role</label>
        <select id="invite-role" name="role" value={role} onChange={(event) => setRole(event.target.value)}>
          {choices.map((name) => (
            <option key={name} value={name}>
              {roleLabel(name)}
            </option>
          ))}
        </select>
        {hint && <p className="field-hint">{hint}</p>}
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Creating…' : 'Create invitation'}
        </button>
      </div>
    </form>
  );
}

export function InviteDialog({
  open,
  roles,
  onClose,
  onCreated,
}: {
  open: boolean;
  roles: RoleView[] | undefined;
  onClose: () => void;
  onCreated: (created: InviteCreated) => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} title="Invite someone">
      <Body roles={roles} onClose={onClose} onCreated={onCreated} />
    </Dialog>
  );
}
