# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub: open the
repository's **Security** tab and choose **Report a vulnerability**. Do not
open a public issue for a vulnerability.

Include what you found, how to reproduce it, and what an attacker could do
with it. You should get a first reply within a week. Fixes are released as
soon as they are ready, and reporters are credited unless they prefer not.

## Supported versions

IRA is pre-1.0. Only the latest release gets security fixes.

## Scope

In scope: anything that lets someone run an action without the owner's PIN,
read another user's conversations, bypass a role or token scope, recover a
PIN, password, token or provider key, or get secrets into the repository past
its checks.

The design and its limits are described in
[docs/security.md](docs/security.md).
