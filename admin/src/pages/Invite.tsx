import { useEffect } from 'react';
import { Mark } from '../ui/icons';

export default function Invite() {
  useEffect(() => {
    document.title = 'Accept invite · IRA';
  }, []);
  return (
    <main className="gate">
      <div className="gate-card">
        <Mark tile size={40} />
        <h1>Accept your invite</h1>
        <p className="muted">Coming in this release.</p>
      </div>
    </main>
  );
}
