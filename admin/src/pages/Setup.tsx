import { useEffect } from 'react';
import { Mark } from '../ui/icons';

export default function Setup() {
  useEffect(() => {
    document.title = 'Set up · IRA';
  }, []);
  return (
    <main className="gate">
      <div className="gate-card">
        <Mark tile size={40} />
        <h1>Set up IRA</h1>
        <p className="muted">Coming in this release.</p>
      </div>
    </main>
  );
}
