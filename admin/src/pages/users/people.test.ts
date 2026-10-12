import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import type { AdminUserRow, RoleView } from '../../api/endpoints';
import {
  failureText,
  inviteLink,
  isLastOwner,
  lastSignIn,
  LAST_OWNER,
  NO_PIN,
  permissionsText,
  pinReason,
  removeReason,
  roleReason,
  SELF_REMOVE,
  signInSentence,
  sortRoles,
} from './people';

function person(id: number, role: string, extra: Partial<AdminUserRow> = {}): AdminUserRow {
  return {
    id,
    email: `${role}-${id}@example.com`,
    role,
    created_at: 1_700_000_000,
    last_login_at: null,
    has_pin: false,
    ...extra,
  };
}

const owner = person(1, 'owner', { has_pin: true });
const admin = person(2, 'admin');
const second = person(5, 'owner');

describe('isLastOwner', () => {
  it('is true only for the single owner', () => {
    expect(isLastOwner(owner, [owner, admin])).toBe(true);
    expect(isLastOwner(owner, [owner, second])).toBe(false);
    expect(isLastOwner(admin, [owner, admin])).toBe(false);
  });
});

describe('roleReason and removeReason', () => {
  it('protect the last owner', () => {
    expect(roleReason(owner, [owner, admin])).toBe(LAST_OWNER);
    expect(removeReason(owner, [owner, admin], 1)).toBe(LAST_OWNER);
  });

  it('stop the signed-in person removing themselves', () => {
    expect(roleReason(owner, [owner, second])).toBeNull();
    expect(removeReason(owner, [owner, second], 1)).toBe(SELF_REMOVE);
    expect(removeReason(second, [owner, second], 1)).toBeNull();
  });

  it('leave everyone else alone', () => {
    expect(roleReason(admin, [owner, admin])).toBeNull();
    expect(removeReason(admin, [owner, admin], 1)).toBeNull();
    expect(removeReason(admin, [owner, admin], undefined)).toBeNull();
  });
});

describe('pinReason', () => {
  it('has nothing to clear without a PIN', () => {
    expect(pinReason(owner)).toBeNull();
    expect(pinReason(admin)).toBe(NO_PIN);
  });
});

describe('lastSignIn', () => {
  it('says never, or how long ago', () => {
    expect(lastSignIn(admin)).toBe('never');
    expect(lastSignIn(person(3, 'staff', { last_login_at: 1000 }), 1000 + 2 * 3600)).toBe('2 h ago');
  });

  it('reads as a sentence on a card', () => {
    expect(signInSentence(admin)).toBe('Never signed in');
    expect(signInSentence(person(3, 'staff', { last_login_at: 1000 }), 1000 + 30)).toBe('Signed in just now');
  });
});

describe('inviteLink', () => {
  it('joins the origin and the path', () => {
    expect(inviteLink('https://ira.example.com', '/admin/invite#token=abc')).toBe(
      'https://ira.example.com/admin/invite#token=abc',
    );
    expect(inviteLink('https://ira.example.com', 'admin/invite')).toBe('https://ira.example.com/admin/invite');
  });
});

describe('sortRoles', () => {
  const role = (name: string): RoleView => ({ role: name, permissions: [], description: '' });

  it('lists owner first and unknown roles last', () => {
    const sorted = sortRoles([role('viewer'), role('helper'), role('owner'), role('staff'), role('admin')]);
    expect(sorted.map((r) => r.role)).toEqual(['owner', 'admin', 'staff', 'viewer', 'helper']);
  });
});

describe('permissionsText', () => {
  it('joins the permissions', () => {
    expect(permissionsText({ role: 'viewer', permissions: ['admin.read'], description: '' })).toBe('admin.read');
    expect(permissionsText({ role: 'staff', permissions: ['actions', 'ask', 'voice'], description: '' })).toBe(
      'actions, ask, voice',
    );
  });
});

describe('failureText', () => {
  it('shows the server detail as a sentence', () => {
    expect(failureText(new ApiError(409, 'the last owner cannot be removed'))).toBe(
      'The last owner cannot be removed.',
    );
    expect(failureText(new ApiError(403, 'Not allowed for your role.'))).toBe('Not allowed for your role.');
  });

  it('explains an unreachable server and unknown errors', () => {
    expect(failureText(new ApiError(0, 'Cannot reach the server'))).toBe(
      'Cannot reach the server. Check the connection and try again.',
    );
    expect(failureText(new TypeError('boom'))).toBe('Something went wrong. Try again.');
  });
});
