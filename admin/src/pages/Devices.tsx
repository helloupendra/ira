import { useState, type FormEvent } from 'react';
import { admin, me, type DeviceView, type GrantView } from '../api/endpoints';
import { when } from '../lib/format';
import { ConfirmDialog, Dialog } from '../ui/Dialog';
import { Icon } from '../ui/icons';
import { Page } from '../ui/Page';
import { useSession } from '../ui/Session';
import { Empty } from '../ui/states';
import { Switch } from '../ui/Switch';
import { useToast } from '../ui/toast';
import { useApi, type ApiState } from '../ui/useApi';
import { PairDeviceDialog } from './devices/PairDeviceDialog';
import { grantTitle, kindWord, skillsAfter, statusOf, tierWord } from './devices/text';
import { Body } from './tokens/Body';
import { failure } from './tokens/text';
import './Devices.css';

/* One device ---------------------------------------------------------------- */

function DeviceStatus({ device }: { device: DeviceView }) {
  const status = statusOf(device);
  return <span className={status.tone === 'ok' ? 'badge badge-ok' : 'badge badge-muted'}>{status.label}</span>;
}

function Tools({ device }: { device: DeviceView }) {
  if (!device.tools.length) return null;
  return (
    <details className="devices-tools">
      <summary>{device.tools.length === 1 ? '1 tool it offers' : `${device.tools.length} tools it offers`}</summary>
      <ul>
        {device.tools.map((tool) => (
          <li key={tool.name}>
            <span className="mono">{tool.name}</span> <span className="muted">— {tierWord(tool.tier)}</span>
            {!tool.on && <span className="badge badge-muted">off</span>}
            <p className="muted">{tool.description}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}

// Switching a skill on is a new grant: it asks for the PIN in a dialog.
function SkillPinDialog({
  target,
  onClose,
  onDone,
}: {
  target: { device: DeviceView; skill: string } | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!target) return;
    setBusy(true);
    setError(null);
    const typed = pin;
    setPin('');
    try {
      await me.updateDevice(target.device.id, { skills: skillsAfter(target.device, target.skill, true), pin: typed });
      onDone();
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={target !== null} onClose={onClose} title={target ? `Switch ${target.skill} on` : 'Switch on'}>
      <form className="form" onSubmit={onSubmit}>
        <p className="dialog-text">
          Ira may then use {target?.skill} on {target?.device.label}, only when you ask. A new permission needs your PIN.
        </p>
        <div className="field">
          <label htmlFor="skill-pin">Your action PIN</label>
          <input
            id="skill-pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]{4,12}"
            minLength={4}
            maxLength={12}
            autoComplete="off"
            required
            value={pin}
            onChange={(e) => setPin(e.target.value)}
          />
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
            {busy ? 'Switching on…' : 'Switch on'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/* Your devices --------------------------------------------------------------- */

function MyDevices({ state }: { state: ApiState<DeviceView[]> }) {
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [switching, setSwitching] = useState<{ device: DeviceView; skill: string } | null>(null);
  const [revoking, setRevoking] = useState<DeviceView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function switchSkill(device: DeviceView, skill: string, on: boolean) {
    if (on) {
      setSwitching({ device, skill });
      return;
    }
    try {
      await me.updateDevice(device.id, { skills: skillsAfter(device, skill, false) });
      toast(`Switched ${skill} off on ${device.label}.`);
      state.reload();
    } catch (err) {
      toast(failure(err));
    }
  }

  async function revoke() {
    if (!revoking) return;
    setBusy(true);
    setError(null);
    try {
      await me.revokeDevice(revoking.id);
      toast(`Removed ${revoking.label}. Its token no longer works.`);
      setRevoking(null);
      state.reload();
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="toolbar">
        <button type="button" className="btn btn-primary btn-small" onClick={() => setAdding(true)}>
          <Icon name="plus" />
          Add a device
        </button>
        <span className="inline-note">A device works for you alone, with the skills you switch on.</span>
      </div>
      <Body state={state} needs="ask">
        {(rows) =>
          rows.length === 0 ? (
            <Empty
              title="No devices yet"
              text="Pair your Mac to let Ira read and watch a Chrome tab when you ask, and tell you when it finishes."
            />
          ) : (
            <ul className="cards">
              {rows.map((device) => (
                <li key={device.id}>
                  <div className="card-head">
                    <span className="card-title">{device.label}</span>
                    <DeviceStatus device={device} />
                  </div>
                  <div className="card-meta">
                    <span>{kindWord(device.kind)}</span>
                    {device.version && <span>version {device.version}</span>}
                    <span>paired {when(device.created_at)}</span>
                  </div>
                  <ul className="devices-skill-list">
                    {device.skills.map((skill) => (
                      <li key={skill.name}>
                        <Switch
                          checked={skill.on}
                          label={`${skill.name} on ${device.label}`}
                          onChange={(next) => void switchSkill(device, skill.name, next)}
                        />
                        <span>{skill.description}</span>
                      </li>
                    ))}
                  </ul>
                  <Tools device={device} />
                  <div className="card-actions">
                    <button type="button" className="btn btn-ghost btn-small" onClick={() => setRevoking(device)}>
                      <Icon name="trash" />
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )
        }
      </Body>
      <PairDeviceDialog open={adding} onClose={() => setAdding(false)} onPaired={state.reload} />
      <SkillPinDialog
        target={switching}
        onClose={() => setSwitching(null)}
        onDone={() => {
          toast(`Switched ${switching?.skill} on.`);
          setSwitching(null);
          state.reload();
        }}
      />
      <ConfirmDialog
        open={revoking !== null}
        title={`Remove ${revoking?.label ?? 'this device'}?`}
        text="Its token stops working and it disconnects at once. Pair it again to use it."
        confirmLabel="Remove the device"
        danger
        busy={busy}
        error={error}
        onConfirm={() => void revoke()}
        onClose={() => {
          setRevoking(null);
          setError(null);
        }}
      />
    </>
  );
}

/* Everyone's devices and grants (owner, admin) ------------------------------- */

function EveryonesDevices({ state, onChanged }: { state: ApiState<DeviceView[]>; onChanged: () => void }) {
  const toast = useToast();
  const [revoking, setRevoking] = useState<DeviceView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function switchOff(device: DeviceView, skill: string) {
    try {
      await admin.switchDeviceSkills(device.id, skillsAfter(device, skill, false));
      toast(`Switched ${skill} off on ${device.label}.`);
      onChanged();
    } catch (err) {
      toast(failure(err));
    }
  }

  async function revoke() {
    if (!revoking) return;
    setBusy(true);
    setError(null);
    try {
      await admin.revokeDevice(revoking.id);
      toast(`Revoked ${revoking.label}.`);
      setRevoking(null);
      onChanged();
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="inline-note devices-note">
        You can switch a skill off or revoke a device. Only its owner switches a skill on, and nobody else sees what
        a device read.
      </p>
      <Body state={state} needs="admin.write">
        {(rows) =>
          rows.length === 0 ? (
            <Empty text="Nobody has paired a device yet." />
          ) : (
            <ul className="cards">
              {rows.map((device) => (
                <li key={device.id}>
                  <div className="card-head">
                    <span className="card-title">
                      {device.label} <span className="muted">· {device.email}</span>
                    </span>
                    <DeviceStatus device={device} />
                  </div>
                  <div className="card-meta">
                    <span>{kindWord(device.kind)}</span>
                    <span>{device.tools.length} tools</span>
                    <span>
                      skills on: {device.skills.filter((s) => s.on).map((s) => s.name).join(', ') || 'none'}
                    </span>
                  </div>
                  <div className="card-actions">
                    {device.skills
                      .filter((s) => s.on)
                      .map((skill) => (
                        <button
                          key={skill.name}
                          type="button"
                          className="btn btn-ghost btn-small"
                          onClick={() => void switchOff(device, skill.name)}
                        >
                          Switch {skill.name} off
                        </button>
                      ))}
                    <button type="button" className="btn btn-ghost btn-small" onClick={() => setRevoking(device)}>
                      <Icon name="trash" />
                      Revoke
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )
        }
      </Body>
      <ConfirmDialog
        open={revoking !== null}
        title={`Revoke ${revoking?.label ?? 'this device'}?`}
        text={`It belongs to ${revoking?.email ?? 'someone'}. Its token stops working and it disconnects at once.`}
        confirmLabel="Revoke"
        danger
        busy={busy}
        error={error}
        onConfirm={() => void revoke()}
        onClose={() => {
          setRevoking(null);
          setError(null);
        }}
      />
    </>
  );
}

function Grants({ state, onChanged }: { state: ApiState<GrantView[]>; onChanged: () => void }) {
  const toast = useToast();

  async function turnOff(grant: GrantView) {
    try {
      await admin.revokeGrant(grant.id);
      toast(`Turned off: ${grantTitle(grant)} for ${grant.email}.`);
      onChanged();
    } catch (err) {
      toast(failure(err));
    }
  }

  return (
    <Body state={state} needs="admin.write">
      {(rows) =>
        rows.length === 0 ? (
          <Empty text="Nothing is switched on for anyone." />
        ) : (
          <ul className="cards">
            {rows.map((grant) => (
              <li key={grant.id}>
                <div className="card-head">
                  <span className="card-title">{grantTitle(grant)}</span>
                  <span className="muted">{grant.email}</span>
                </div>
                <p className="card-meta">{grant.description}</p>
                <div className="card-actions">
                  <button type="button" className="btn btn-ghost btn-small" onClick={() => void turnOff(grant)}>
                    Turn off
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )
      }
    </Body>
  );
}

/* The page ------------------------------------------------------------------- */

export default function Devices() {
  const { can } = useSession();
  const manage = can('admin.write');
  const mine = useApi((signal) => me.devices(signal), []);
  const everyone = useApi((signal) => (manage ? admin.devices(signal) : Promise.resolve([])), [manage]);
  const grants = useApi((signal) => (manage ? admin.grants(signal) : Promise.resolve([])), [manage]);

  function reload() {
    mine.reload();
    everyone.reload();
    grants.reload();
  }

  return (
    <Page
      title="Devices"
      subtitle="Macs and phones that work for one person, with the skills they switch on"
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <section className="section">
        <h2 className="section-title">Your devices</h2>
        <MyDevices state={mine} />
      </section>
      {manage && (
        <>
          <section className="section">
            <h2 className="section-title">Everyone's devices</h2>
            <EveryonesDevices state={everyone} onChanged={reload} />
          </section>
          <section className="section">
            <h2 className="section-title">Grants</h2>
            <p className="inline-note devices-note">
              Everything anyone allowed Ira to use: a skill on a device, or web search. Turning one off takes effect at
              once.
            </p>
            <Grants state={grants} onChanged={reload} />
          </section>
        </>
      )}
    </Page>
  );
}
