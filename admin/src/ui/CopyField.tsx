import { useState } from 'react';
import { Icon } from './icons';

// A value shown once (a token, an invitation link) with a Copy button. The
// field is read-only so it can still be selected by hand where the clipboard
// is not available.
export function CopyField({ label, value, warning }: { label: string; value: string; warning?: string }) {
  const [copied, setCopied] = useState<'no' | 'yes' | 'failed'>('no');

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied('yes');
    } catch {
      setCopied('failed');
    }
    window.setTimeout(() => setCopied('no'), 2500);
  }

  return (
    <div className="copy-field">
      <label className="copy-label">
        <span>{label}</span>
        <input className="copy-input mono" type="text" readOnly value={value} onFocus={(e) => e.currentTarget.select()} />
      </label>
      <button type="button" className="btn btn-small" onClick={() => void copy()}>
        <Icon name={copied === 'yes' ? 'check' : 'copy'} />
        {copied === 'yes' ? 'Copied' : copied === 'failed' ? 'Select and copy' : 'Copy'}
      </button>
      {warning && (
        <p className="copy-warning" role="status">
          <Icon name="alert" size={16} />
          {warning}
        </p>
      )}
    </div>
  );
}
