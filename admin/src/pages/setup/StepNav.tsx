import type { ReactNode } from 'react';

// The buttons under a step: Back on the left, Continue on the right, with
// the step's own buttons after it and a quiet note when continuing needs
// a word of explanation.
export function StepNav({
  onBack,
  onNext,
  nextLabel = 'Continue',
  nextQuiet = false,
  busy = false,
  note,
  children,
}: {
  onBack?: () => void;
  onNext?: () => void;
  nextLabel?: string;
  nextQuiet?: boolean;
  busy?: boolean;
  note?: string;
  children?: ReactNode;
}) {
  return (
    <div className="setup-nav">
      {onBack && (
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={onBack}>
          Back
        </button>
      )}
      <span className="spacer" />
      {onNext && (
        <button type="button" className={nextQuiet ? 'btn btn-ghost' : 'btn btn-primary'} disabled={busy} onClick={onNext}>
          {nextLabel}
        </button>
      )}
      {children}
      {note && <p className="setup-note">{note}</p>}
    </div>
  );
}
