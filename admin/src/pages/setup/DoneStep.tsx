import { Link } from 'wouter';
import { StepNav } from './StepNav';

// Step 6: where to go next.
export function DoneStep({ onBack }: { onBack: () => void }) {
  return (
    <div className="setup-step">
      <div className="setup-intro">
        <h2>Ira is ready.</h2>
        <p className="muted">
          Open the app to talk to Ira, carry on in the console, or invite the people who will use it. This page
          stays at /admin/setup if you want to run through it again.
        </p>
      </div>
      <div className="actions-row">
        <a className="btn btn-primary" href="/">
          Open Ira
        </a>
        <Link className="btn" href="/">
          Open the console
        </Link>
        <Link className="btn" href="/users">
          Invite your staff
        </Link>
      </div>
      <StepNav onBack={onBack} />
    </div>
  );
}
