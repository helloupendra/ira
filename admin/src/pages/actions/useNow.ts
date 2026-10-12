import { useEffect, useState } from 'react';

// The time in seconds, refreshed now and then so "expires at" turns into
// "expired" while the page stays open.
export function useNow(everyMs = 30000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), everyMs);
    return () => window.clearInterval(id);
  }, [everyMs]);
  return now;
}
