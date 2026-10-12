export type Permission = 'ask' | 'voice' | 'actions' | 'admin.read' | 'admin.write' | 'users';

export function can(permissions: readonly string[] | null | undefined, p: Permission): boolean {
  return permissions?.includes(p) ?? false;
}

// Who holds a permission, in plain words, for messages that say why
// something is not available.
export function whoCan(p: Permission): string {
  switch (p) {
    case 'admin.read':
      return 'an owner, admin or viewer';
    case 'admin.write':
      return 'an owner or admin';
    case 'users':
      return 'the owner';
    case 'ask':
    case 'voice':
    case 'actions':
      return 'an owner, admin or staff member';
  }
}

export function whyNot(role: string, p: Permission): string {
  return `Your role (${role}) can't do this. Only ${whoCan(p)} can.`;
}

export function roleLabel(role: string): string {
  if (!role) return '';
  return role.charAt(0).toUpperCase() + role.slice(1);
}
