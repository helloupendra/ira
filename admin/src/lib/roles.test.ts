import { describe, expect, it } from 'vitest';
import { can, roleLabel, whoCan, whyNot } from './roles';

describe('can', () => {
  it('checks the permission list', () => {
    expect(can(['admin.read', 'ask'], 'admin.read')).toBe(true);
    expect(can(['admin.read'], 'users')).toBe(false);
    expect(can(undefined, 'ask')).toBe(false);
  });
});

describe('whoCan', () => {
  it('names the roles in plain words', () => {
    expect(whoCan('admin.read')).toBe('an owner, admin or viewer');
    expect(whoCan('admin.write')).toBe('an owner or admin');
    expect(whoCan('users')).toBe('the owner');
    expect(whoCan('actions')).toBe('an owner, admin or staff member');
  });
});

describe('whyNot', () => {
  it('says what the role cannot do and who can', () => {
    expect(whyNot('viewer', 'admin.write')).toBe(
      "Your role (viewer) can't do this. Only an owner or admin can.",
    );
    expect(whyNot('admin', 'users')).toBe("Your role (admin) can't do this. Only the owner can.");
  });
});

describe('roleLabel', () => {
  it('capitalises the role', () => {
    expect(roleLabel('owner')).toBe('Owner');
    expect(roleLabel('viewer')).toBe('Viewer');
    expect(roleLabel('')).toBe('');
  });
});
