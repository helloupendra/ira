// An on/off control that reads as a switch to assistive technology. The label
// next to it says what is switched; `reason` explains a disabled switch.
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
  busy = false,
  reason,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
  busy?: boolean;
  reason?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-busy={busy || undefined}
      className="switch"
      disabled={disabled || busy}
      title={disabled && reason ? reason : undefined}
      onClick={() => onChange(!checked)}
    >
      <span className="switch-track">
        <span className="switch-knob" />
      </span>
      <span className="switch-text">{checked ? 'On' : 'Off'}</span>
    </button>
  );
}
