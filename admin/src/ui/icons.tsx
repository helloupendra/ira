import type { ReactNode } from 'react';

// Line icons on a 24-unit grid, drawn with the current text colour. Each is
// decorative: the text label next to it carries the meaning.
const SHAPES: Record<string, ReactNode> = {
  today: (
    <>
      <rect x="4" y="5" width="16" height="15" rx="1.5" />
      <path d="M4 10h16M8 3v4M16 3v4M8 14h3" />
    </>
  ),
  conversations: <path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8l-4 3.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" />,
  actions: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.5 12.5l2.5 2.5 4.5-5" />
    </>
  ),
  tools: (
    <>
      <rect x="3" y="8" width="18" height="12" rx="1.5" />
      <path d="M9 8V6a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M3 13h18" />
    </>
  ),
  models: (
    <>
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
      <path d="M10 4v3M14 4v3M10 17v3M14 17v3M4 10h3M4 14h3M17 10h3M17 14h3" />
    </>
  ),
  channels: (
    <>
      <circle cx="12" cy="12" r="1.5" />
      <path d="M8.5 15.5a5 5 0 0 1 0-7M15.5 8.5a5 5 0 0 1 0 7M5.5 18.5a9 9 0 0 1 0-13M18.5 5.5a9 9 0 0 1 0 13" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8.5" r="3.5" />
      <path d="M3 20a6 6 0 0 1 12 0M15.5 5.2a3.5 3.5 0 0 1 0 6.6M21 20a5.5 5.5 0 0 0-4-5.2" />
    </>
  ),
  tokens: (
    <>
      <circle cx="8" cy="16" r="4" />
      <path d="M10.8 13.2L20 4M16 8l2.5 2.5M13.5 10.5L16 13" />
    </>
  ),
  audit: (
    <>
      <path d="M6 3h9l4 4v14H6z" />
      <path d="M15 3v4h4M9 12h6M9 16h6" />
    </>
  ),
  more: (
    <>
      <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </>
  ),
  signOut: <path d="M14 7V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-2M9 12h11M17 9l3 3-3 3" />,
  refresh: <path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
};

export type IconName =
  | 'today'
  | 'conversations'
  | 'actions'
  | 'tools'
  | 'models'
  | 'channels'
  | 'users'
  | 'tokens'
  | 'audit'
  | 'more'
  | 'signOut'
  | 'refresh'
  | 'close';

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {SHAPES[name]}
    </svg>
  );
}

// The four bars of icon.svg: the brand, and in the Ira app the mic button.
export function Mark({ size = 20, tile = false }: { size?: number; tile?: boolean }) {
  return (
    <svg
      className={tile ? 'mark mark-tile' : 'mark'}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
    >
      <rect x="7" y="13" width="3" height="6" rx="1.5" />
      <rect x="12" y="9" width="3" height="14" rx="1.5" />
      <rect x="17" y="6" width="3" height="20" rx="1.5" />
      <rect x="22" y="11" width="3" height="10" rx="1.5" />
    </svg>
  );
}
