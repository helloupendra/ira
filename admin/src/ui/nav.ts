import type { Permission } from '../lib/roles';
import type { IconName } from './icons';

export interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  needs: Permission;
}

export const NAV: readonly NavItem[] = [
  { href: '/', label: 'Today', icon: 'today', needs: 'admin.read' },
  { href: '/conversations', label: 'Conversations', icon: 'conversations', needs: 'admin.read' },
  { href: '/actions', label: 'Actions', icon: 'actions', needs: 'admin.read' },
  { href: '/tools', label: 'Tools', icon: 'tools', needs: 'admin.read' },
  { href: '/models', label: 'Models & voice', icon: 'models', needs: 'admin.read' },
  { href: '/channels', label: 'Channels', icon: 'channels', needs: 'admin.read' },
  { href: '/devices', label: 'Devices', icon: 'devices', needs: 'ask' },
  { href: '/users', label: 'Users & roles', icon: 'users', needs: 'users' },
  { href: '/tokens', label: 'Tokens & security', icon: 'tokens', needs: 'admin.read' },
  { href: '/audit', label: 'Audit & cost', icon: 'audit', needs: 'admin.read' },
  { href: '/reports', label: 'Reported answers', icon: 'alert', needs: 'admin.read' },
];

// The four items that fit a phone's bottom bar; the rest go in "More".
export const PRIMARY_NAV = NAV.slice(0, 3);
export const MORE_NAV = NAV.slice(3);

export function currentNav(location: string): NavItem | undefined {
  return NAV.find((item) =>
    item.href === '/' ? location === '/' : location === item.href || location.startsWith(`${item.href}/`),
  );
}
