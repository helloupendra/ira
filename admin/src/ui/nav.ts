import type { Permission } from '../lib/roles';
import type { IconName } from './icons';

export type NavGroup = 'Activity' | 'Assistant' | 'Admin';

export interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  needs: Permission;
  group: NavGroup;
}

// The rail shows these under their group's name, in this order.
export const NAV_GROUPS: readonly NavGroup[] = ['Activity', 'Assistant', 'Admin'];

export const NAV: readonly NavItem[] = [
  { href: '/', label: 'Today', icon: 'today', needs: 'admin.read', group: 'Activity' },
  { href: '/conversations', label: 'Conversations', icon: 'conversations', needs: 'admin.read', group: 'Activity' },
  { href: '/actions', label: 'Actions', icon: 'actions', needs: 'admin.read', group: 'Activity' },
  { href: '/reports', label: 'Reported answers', icon: 'alert', needs: 'admin.read', group: 'Activity' },
  { href: '/tools', label: 'Tools', icon: 'tools', needs: 'admin.read', group: 'Assistant' },
  { href: '/models', label: 'Models & voice', icon: 'models', needs: 'admin.read', group: 'Assistant' },
  { href: '/channels', label: 'Channels', icon: 'channels', needs: 'admin.read', group: 'Assistant' },
  { href: '/devices', label: 'Devices', icon: 'devices', needs: 'ask', group: 'Assistant' },
  { href: '/users', label: 'Users & roles', icon: 'users', needs: 'users', group: 'Admin' },
  { href: '/tokens', label: 'Tokens & security', icon: 'tokens', needs: 'admin.read', group: 'Admin' },
  { href: '/audit', label: 'Audit & cost', icon: 'audit', needs: 'admin.read', group: 'Admin' },
];

// The four items that fit a phone's bottom bar; the rest go in "More".
export const PRIMARY_NAV = NAV.slice(0, 3);
export const MORE_NAV = NAV.slice(3);

export function currentNav(location: string): NavItem | undefined {
  return NAV.find((item) =>
    item.href === '/' ? location === '/' : location === item.href || location.startsWith(`${item.href}/`),
  );
}
