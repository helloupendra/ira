import { useEffect, useState } from 'react';

// Where the console's desktop layout starts: the rail appears at this width.
export const DESKTOP = '(min-width: 56rem)';

// True while the viewport matches the query, following it as the window
// changes. Lists with actions are a table above this width and cards below.
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches);

  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener('change', update);
    return () => list.removeEventListener('change', update);
  }, [query]);

  return matches;
}
