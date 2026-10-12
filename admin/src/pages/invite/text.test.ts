import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { failure, isGone, NO_MATCH, passwordProblems, roleLine, tokenFrom, TOO_SHORT } from './text';

describe('tokenFrom', () => {
  it('reads the code from the fragment', () => {
    expect(tokenFrom('#token=ira_i_abc')).toBe('ira_i_abc');
    expect(tokenFrom('token=ira_i_abc')).toBe('ira_i_abc');
    expect(tokenFrom('#from=mail&token=ira_i_abc')).toBe('ira_i_abc');
    expect(tokenFrom('#token=%20ira_i_abc%20')).toBe('ira_i_abc');
  });

  it('is null when there is none', () => {
    expect(tokenFrom('')).toBeNull();
    expect(tokenFrom('#')).toBeNull();
    expect(tokenFrom('#token=')).toBeNull();
    expect(tokenFrom('#token=%20')).toBeNull();
    expect(tokenFrom('#code=ira_i_abc')).toBeNull();
  });
});

describe('roleLine', () => {
  it('describes each role in one line', () => {
    expect(roleLine('owner')).toMatch(/everything/);
    expect(roleLine('admin')).toMatch(/except managing users/);
    expect(roleLine('staff')).toMatch(/PIN/);
    expect(roleLine('viewer')).toMatch(/reads the console/);
    expect(roleLine('robot')).toBeNull();
  });
});

describe('passwordProblems', () => {
  it('accepts ten characters that match', () => {
    expect(passwordProblems('ten-chars!', 'ten-chars!')).toEqual({});
  });

  it('refuses a short password', () => {
    expect(passwordProblems('short', 'short')).toEqual({ password: TOO_SHORT });
  });

  it('refuses a confirmation that differs', () => {
    expect(passwordProblems('ten-chars!', 'ten-chars?')).toEqual({ confirm: NO_MATCH });
    expect(passwordProblems('ten-chars!', '')).toEqual({ confirm: NO_MATCH });
  });

  it('reports both at once', () => {
    expect(passwordProblems('short', 'other')).toEqual({ password: TOO_SHORT, confirm: NO_MATCH });
  });
});

describe('isGone', () => {
  it('is only a 410', () => {
    expect(isGone(new ApiError(410, 'this invitation is not valid any more'))).toBe(true);
    expect(isGone(new ApiError(400, 'bad'))).toBe(false);
    expect(isGone(new Error('boom'))).toBe(false);
    expect(isGone(null)).toBe(false);
  });
});

describe('failure', () => {
  it('shows the server detail as a sentence', () => {
    expect(failure(new ApiError(400, 'the password must be at least 10 characters'))).toBe(
      'The password must be at least 10 characters.',
    );
    expect(failure(new ApiError(400, 'That email already has an account.'))).toBe(
      'That email already has an account.',
    );
  });

  it('has a sentence for the connection and for too many tries', () => {
    expect(failure(new ApiError(0, 'Cannot reach the server'))).toBe(
      'Cannot reach the server. Check the connection and try again.',
    );
    expect(failure(new ApiError(429, 'too many'))).toBe('Too many tries. Wait a moment and try again.');
    expect(failure(new ApiError(500, ''))).toBe('Something went wrong. Try again.');
    expect(failure('x')).toBe('Something went wrong. Try again.');
  });
});
