import { useEffect, useState } from 'react';

// The rail breakpoint in console.css: a desktop from here up.
export const DESKTOP = '(min-width: 56rem)';

// Whether the viewport matches a media query, kept up to date as the window
// resizes or the phone turns.
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
  );

  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener('change', update);
    return () => list.removeEventListener('change', update);
  }, [query]);

  return matches;
}
