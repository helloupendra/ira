import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'wouter';
import { setup } from '../api/endpoints';
import { roleLabel, whoCan } from '../lib/roles';
import { Mark } from '../ui/icons';
import { useSession } from '../ui/Session';
import { ErrorState, Loading } from '../ui/states';
import { useApi } from '../ui/useApi';
import { ChannelsStep } from './setup/ChannelsStep';
import { DoneStep } from './setup/DoneStep';
import { ModelsStep } from './setup/ModelsStep';
import { NameStep } from './setup/NameStep';
import { OwnerStep } from './setup/OwnerStep';
import { PinStep } from './setup/PinStep';
import { clampStep, codeFromHash, FIRST_STEP_AFTER_OWNER, readStep, STEPS, writeStep } from './setup/steps';
import './Setup.css';

// The strip of six steps: the current one highlighted, finished ones
// ticked. On a phone only the current step keeps its name.
function StepList({ current }: { current: number }) {
  return (
    <ol className="step-list setup-steps" aria-label="Setup steps">
      {STEPS.map((step) => (
        <li
          key={step.n}
          className={step.n < current ? 'is-done' : undefined}
          aria-current={step.n === current ? 'step' : undefined}
        >
          <span className="step-label">{step.label}</span>
        </li>
      ))}
    </ol>
  );
}

// Step 1 once the owner exists and nobody is signed in.
function OwnerExists() {
  return (
    <div className="setup-step">
      <div className="setup-intro">
        <h2>The owner's account</h2>
        <p>The owner account exists.</p>
        <p className="muted">Sign in as the owner, or as an admin, to go on with the setup.</p>
      </div>
      <div className="actions-row">
        <Link className="btn btn-primary" href="/login?next=/setup">
          Sign in to continue the setup
        </Link>
      </div>
    </div>
  );
}

// A viewer or a staff member who followed the link.
function NotForYou({ email, role }: { email: string; role: string }) {
  return (
    <div className="setup-step">
      <div className="setup-intro">
        <h2>Setup is for the owner</h2>
        <p className="muted">
          You are signed in as {email} with the {roleLabel(role)} role. Only {whoCan('admin.write')} can run the
          setup.
        </p>
      </div>
      <div className="actions-row">
        <Link className="btn" href="/">
          Go to the console
        </Link>
      </div>
    </div>
  );
}

export default function Setup() {
  const session = useSession();
  const status = useApi((signal) => setup.status(signal), []);
  const [code] = useState(() => codeFromHash(location.hash));
  const [step, setStep] = useState(() => readStep());
  const [ownerMade, setOwnerMade] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const moved = useRef(false);

  useEffect(() => {
    document.title = 'Set up · IRA';
  }, []);

  // After a step change, reading starts from the top of the new step.
  useEffect(() => {
    if (moved.current) bodyRef.current?.focus();
  }, [step]);

  function go(n: number) {
    const next = clampStep(n);
    writeStep(next);
    moved.current = true;
    setStep(next);
  }

  // The owner is signed in now; the status is re-read so it agrees.
  function ownerCreated() {
    setOwnerMade(true);
    go(FIRST_STEP_AFTER_OWNER);
    status.reload();
  }

  let current: number | null = null;
  let body: ReactNode;
  if (status.data === undefined) {
    body = status.error ? <ErrorState error={status.error} onRetry={status.reload} /> : <Loading />;
  } else if (status.data.needs_owner && !ownerMade) {
    current = 1;
    body = <OwnerStep initialCode={code} onCreated={ownerCreated} />;
  } else if (session.status === 'loading') {
    body = <Loading />;
  } else if (session.status === 'error' && session.error) {
    body = <ErrorState error={session.error} onRetry={() => void session.refresh()} />;
  } else if (session.status !== 'ready' || !session.me) {
    current = 1;
    body = <OwnerExists />;
  } else if (!session.can('admin.write')) {
    body = <NotForYou email={session.me.user.email} role={session.me.user.role} />;
  } else {
    current = step;
    switch (step) {
      case 2:
        body = <NameStep onNext={() => go(3)} />;
        break;
      case 3:
        body = <ModelsStep onBack={() => go(2)} onNext={() => go(4)} />;
        break;
      case 4:
        body = <PinStep onBack={() => go(3)} onNext={() => go(5)} />;
        break;
      case 5:
        body = <ChannelsStep onBack={() => go(4)} onNext={() => go(6)} />;
        break;
      default:
        body = <DoneStep onBack={() => go(5)} />;
    }
  }

  return (
    <main className="gate">
      <div className="gate-card wide">
        <Mark tile size={40} />
        <div className="setup-head">
          <h1>Set up IRA</h1>
          <p className="muted">
            {status.data ? `Version ${status.data.version}. ` : ''}Close this page any time and come back; it
            remembers where you were.
          </p>
        </div>
        {current !== null && <StepList current={current} />}
        <div ref={bodyRef} tabIndex={-1} className="setup-body">
          {body}
        </div>
      </div>
    </main>
  );
}
