"""Users, roles, sessions and API tokens.

Roles, from most to least trusted:

* ``owner``  - everything, including managing users;
* ``admin``  - everything except user management;
* ``staff``  - talks to Ira and can confirm actions with the PIN;
* ``viewer`` - read-only access to the admin views.

A request is made by a *principal*: a user signed in with a session, or an
API token that belongs to a user. A token's scopes can only narrow what the
user's role allows, so a phone token with scope ``ask`` may only ask.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ira.security import new_api_token, new_id, sha256_hex
from ira.store import Store

Role = Literal["owner", "admin", "staff", "viewer"]
ROLES: tuple[Role, ...] = ("owner", "admin", "staff", "viewer")

PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {"ask", "voice", "actions", "observe", "admin.read", "admin.write", "users"}
    ),
    "admin": frozenset({"ask", "voice", "actions", "observe", "admin.read", "admin.write"}),
    "staff": frozenset({"ask", "voice", "actions", "observe"}),
    "viewer": frozenset({"admin.read"}),
}

ROLE_DESCRIPTIONS: dict[str, str] = {
    "owner": "Everything, including managing users.",
    "admin": "Everything except managing users.",
    "staff": "Talks to the assistant and confirms actions with their own PIN.",
    "viewer": "Reads the admin views; cannot ask or change anything.",
}

# What an API token may carry. Writing config and managing users need a session.
# "observe" only reports where its person is (a phone's place events), for learning.
TOKEN_SCOPES = ("ask", "voice", "actions", "observe", "admin.read")

SESSION_SECONDS = 14 * 24 * 3600
COOKIE_DAYS = SESSION_SECONDS / 86400
USER_AGENT_CHARS = 200
INVITE_SECONDS = 72 * 3600
MIN_PASSWORD = 10
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

_hasher = PasswordHasher()
# Verifying against a throwaway hash makes "no such user" cost the same time
# as "wrong password", so response time does not reveal which emails exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class AccountError(ValueError):
    pass


@dataclass(frozen=True)
class User:
    id: int
    email: str
    role: Role
    created_at: float
    last_login_at: float | None = None
    has_pin: bool = False

    @property
    def permissions(self) -> frozenset[str]:
        return PERMISSIONS[self.role]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


@dataclass(frozen=True)
class Principal:
    """Who is making a request, and what they may do in it."""

    user: User
    via: Literal["session", "token", "telegram", "device"]
    permissions: frozenset[str]
    credential_id: str | None = None

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def channel(self) -> str:
        return {"session": "web", "token": "api"}.get(self.via, self.via)

    @property
    def actor(self) -> str:
        """Who, for the logs: the person's email. The channel is recorded on its own."""
        return self.user.email


def _user(row: Any) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
        has_pin=row["pin_hash"] is not None,
    )


def _check_role(role: str) -> Role:
    if role not in ROLES:
        raise AccountError(f"role must be one of {', '.join(ROLES)}")
    return role  # type: ignore[return-value]


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"the password must be at least {MIN_PASSWORD} characters")


class LastOwnerError(AccountError):
    """Removing or demoting this user would leave nobody who can manage users."""


@dataclass(frozen=True)
class Invite:
    id: str
    email: str
    role: Role
    created_by: str
    created_at: float
    expires_at: float
    used_at: float | None = None
    revoked_at: float | None = None

    def state(self, now: float) -> str:
        if self.used_at is not None:
            return "used"
        if self.revoked_at is not None:
            return "revoked"
        return "expired" if self.expires_at <= now else "pending"


def _invite(row: Any) -> Invite:
    return Invite(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        used_at=row["used_at"],
        revoked_at=row["revoked_at"],
    )


def normalise_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL.fullmatch(email):
        raise AccountError("that does not look like an email address")
    return email


def parse_scopes(text: str | list[str]) -> list[str]:
    items = text.split(",") if isinstance(text, str) else text
    scopes = sorted({s.strip() for s in items if s.strip()})
    unknown = [s for s in scopes if s not in TOKEN_SCOPES]
    if unknown:
        raise AccountError(
            f"unknown scope(s) {', '.join(unknown)}; choose from {', '.join(TOKEN_SCOPES)}"
        )
    if not scopes:
        raise AccountError("a token needs at least one scope")
    return scopes


@dataclass
class _Attempts:
    failures: list[float] = field(default_factory=list)


class LoginLimiter:
    """Five failed sign-ins for one email or address in 15 minutes blocks it for 15 minutes."""

    def __init__(
        self, limit: int = 5, window: float = 900, clock: Callable[[], float] = time.time
    ) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._attempts: dict[str, _Attempts] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        now = self.clock()
        entry = self._attempts.setdefault(key, _Attempts())
        entry.failures = [t for t in entry.failures if now - t < self.window]
        return entry.failures

    def blocked(self, *keys: str) -> bool:
        with self._lock:
            return any(len(self._recent(k)) >= self.limit for k in keys)

    def fail(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._recent(key).append(self.clock())

    def clear(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._attempts.pop(key, None)


class Accounts:
    def __init__(self, store: Store, *, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.clock = clock
        self.limiter = LoginLimiter(clock=clock)

    # Users.

    def count(self) -> int:
        row = self.store.one("SELECT COUNT(*) AS n FROM users WHERE disabled_at IS NULL")
        return int(row["n"]) if row else 0

    def needs_owner(self) -> bool:
        """True only for a brand-new installation: no account has ever been made."""
        return self.store.one("SELECT 1 FROM users LIMIT 1") is None

    def _insert_user(self, email: str, password_hash: str, role: Role) -> int:
        if self.store.one("SELECT id FROM users WHERE email = ?", (email,)):
            raise AccountError("a user with that email already exists")
        cursor = self.store.execute(
            "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (email, password_hash, role, self.clock()),
        )
        return int(cursor.lastrowid or 0)

    def create_user(self, email: str, password: str, role: Role) -> User:
        role = _check_role(role)
        email = normalise_email(email)
        _check_password(password)
        user = self.get_user(self._insert_user(email, _hasher.hash(password), role))
        assert user is not None
        return user

    def create_first_owner(self, email: str, password: str) -> User:
        """Create the owner account. Refused once any user exists, even under a race."""
        email = normalise_email(email)
        _check_password(password)
        password_hash = _hasher.hash(password)  # slow on purpose: outside the write lock
        with self.store.transaction():
            if not self.needs_owner():
                raise AccountError("setup is already done; sign in instead")
            user_id = self._insert_user(email, password_hash, "owner")
        self.store.adopt_shared_pin()
        user = self.get_user(user_id)
        assert user is not None
        return user

    def check_password(self, user_id: int, password: str) -> bool:
        """Re-check a signed-in user's password before a sensitive change."""
        row = self.store.one(
            "SELECT password_hash FROM users WHERE id = ? AND disabled_at IS NULL", (user_id,)
        )
        try:
            return row is not None and _hasher.verify(row["password_hash"], password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def set_password(self, user_id: int, password: str, *, keep_session: str | None = None) -> int:
        """A new password; every session but ``keep_session`` ends. Returns how many ended.

        API tokens stay: they are separate keys, revoked on their own.
        """
        _check_password(password)
        password_hash = _hasher.hash(password)  # slow on purpose: outside the write lock
        now = self.clock()
        with self.store.transaction():
            if self.get_user(user_id) is None:
                raise AccountError("no such user")
            self.store.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
            )
            ended = self.store.execute(
                "UPDATE sessions SET revoked_at = ? "
                "WHERE user_id = ? AND id != ? AND revoked_at IS NULL",
                (now, user_id, keep_session or ""),
            ).rowcount
        return ended

    def set_email(self, user_id: int, email: str) -> tuple[User, str]:
        """Change an account's email. Returns (updated user, the email before)."""
        email = normalise_email(email)
        with self.store.transaction():
            user = self.get_user(user_id)
            if user is None:
                raise AccountError("no such user")
            if email != user.email:
                if self.store.one("SELECT id FROM users WHERE email = ?", (email,)):
                    raise AccountError("a user with that email already exists")
                self.store.execute("UPDATE users SET email = ? WHERE id = ?", (email, user_id))
        updated = self.get_user(user_id)
        assert updated is not None
        return updated, user.email

    def _owners_besides(self, user_id: int) -> int:
        row = self.store.one(
            "SELECT COUNT(*) AS n FROM users "
            "WHERE role = 'owner' AND disabled_at IS NULL AND id != ?",
            (user_id,),
        )
        return int(row["n"]) if row else 0

    def set_role(self, user_id: int, role: str) -> tuple[User, Role]:
        """Change a user's role. Returns (updated user, previous role)."""
        new_role = _check_role(role)
        with self.store.transaction():
            user = self.get_user(user_id)
            if user is None:
                raise AccountError("no such user")
            if user.role == "owner" and new_role != "owner" and self._owners_besides(user_id) == 0:
                raise LastOwnerError("this is the last owner; make someone else owner first")
            self.store.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        updated = self.get_user(user_id)
        assert updated is not None
        return updated, user.role

    def remove_user(self, user_id: int) -> User:
        """Disable an account and end everything it holds: sessions, tokens, chats, devices.

        The row stays so that conversations and the audit log keep their author.
        """
        now = self.clock()
        with self.store.transaction():
            user = self.get_user(user_id)
            if user is None:
                raise AccountError("no such user")
            if user.role == "owner" and self._owners_besides(user_id) == 0:
                raise LastOwnerError("this is the last owner and cannot be removed")
            self.store.execute(
                "UPDATE users SET disabled_at = ?, pin_hash = NULL, pin_set_at = NULL WHERE id = ?",
                (now, user_id),
            )
            self.store.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
            self.store.execute(
                "UPDATE api_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
            self.store.execute("DELETE FROM telegram_chats WHERE user_id = ?", (user_id,))
            self.store.execute(
                "UPDATE devices SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
        return user

    # Invitations.

    def create_invite(self, email: str, role: str, created_by: str) -> tuple[str, Invite]:
        """Return (token, invite). The token is shown once; only its hash is kept.

        A newer invite for the same email replaces any that is still open.
        """
        role = _check_role(role)
        email = normalise_email(email)
        if self.find_user(email) is not None:
            raise AccountError("a user with that email already exists")
        now = self.clock()
        token = "ira_i_" + secrets.token_urlsafe(32)
        invite = Invite(
            id=new_id("inv_"),
            email=email,
            role=role,
            created_by=created_by,
            created_at=now,
            expires_at=now + INVITE_SECONDS,
        )
        with self.store.transaction():
            self.store.execute(
                "UPDATE invites SET revoked_at = ? "
                "WHERE email = ? AND used_at IS NULL AND revoked_at IS NULL",
                (now, email),
            )
            self.store.execute(
                "INSERT INTO invites (id, token_hash, email, role, created_by, created_at, "
                "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    invite.id,
                    sha256_hex(token),
                    email,
                    role,
                    created_by,
                    invite.created_at,
                    invite.expires_at,
                ),
            )
        return token, invite

    def invites(self, *, include_closed: bool = False) -> list[Invite]:
        rows = self.store.query("SELECT * FROM invites ORDER BY created_at DESC")
        now = self.clock()
        found = [_invite(r) for r in rows]
        return found if include_closed else [i for i in found if i.state(now) == "pending"]

    def get_invite(self, invite_id: str) -> Invite | None:
        row = self.store.one("SELECT * FROM invites WHERE id = ?", (invite_id,))
        return _invite(row) if row else None

    def revoke_invite(self, invite_id: str) -> bool:
        cursor = self.store.execute(
            "UPDATE invites SET revoked_at = ? WHERE id = ? AND used_at IS NULL "
            "AND revoked_at IS NULL",
            (self.clock(), invite_id),
        )
        return cursor.rowcount == 1

    def open_invite(self, token: str) -> Invite | None:
        """The invite a token belongs to, if it can still be used."""
        row = self.store.one(
            "SELECT * FROM invites WHERE token_hash = ?", (sha256_hex(token.strip()),)
        )
        if row is None:
            return None
        invite = _invite(row)
        return invite if invite.state(self.clock()) == "pending" else None

    def accept_invite(self, token: str, password: str) -> User:
        """Create the invited account. The token works once, and only within 72 hours.

        Inviting the email of a removed account brings that account back, with
        its history, the new password and the invited role.
        """
        _check_password(password)
        password_hash = _hasher.hash(password)
        now = self.clock()
        with self.store.transaction():
            invite = self.open_invite(token)
            if invite is None:
                raise AccountError("this invitation is not valid any more; ask for a new one")
            claimed = self.store.execute(
                "UPDATE invites SET used_at = ? WHERE id = ? AND used_at IS NULL "
                "AND revoked_at IS NULL AND expires_at > ?",
                (now, invite.id, now),
            )
            if claimed.rowcount != 1:
                raise AccountError("this invitation is not valid any more; ask for a new one")
            row = self.store.one(
                "SELECT id, disabled_at FROM users WHERE email = ?", (invite.email,)
            )
            if row is not None and row["disabled_at"] is None:
                raise AccountError("a user with that email already exists; sign in instead")
            if row is not None:
                user_id = int(row["id"])
                self.store.execute(
                    "UPDATE users SET password_hash = ?, role = ?, disabled_at = NULL, "
                    "pin_hash = NULL, pin_set_at = NULL WHERE id = ?",
                    (password_hash, invite.role, user_id),
                )
            else:
                user_id = self._insert_user(invite.email, password_hash, invite.role)
        user = self.get_user(user_id)
        assert user is not None
        return user

    def get_user(self, user_id: int) -> User | None:
        row = self.store.one("SELECT * FROM users WHERE id = ? AND disabled_at IS NULL", (user_id,))
        return _user(row) if row else None

    def find_user(self, email: str) -> User | None:
        row = self.store.one(
            "SELECT * FROM users WHERE email = ? AND disabled_at IS NULL",
            (email.strip().lower(),),
        )
        return _user(row) if row else None

    def users(self) -> list[User]:
        rows = self.store.query("SELECT * FROM users WHERE disabled_at IS NULL ORDER BY id")
        return [_user(r) for r in rows]

    def authenticate(self, email: str, password: str) -> User | None:
        row = self.store.one(
            "SELECT * FROM users WHERE email = ? AND disabled_at IS NULL",
            (email.strip().lower(),),
        )
        stored = row["password_hash"] if row else _DUMMY_HASH
        try:
            _hasher.verify(stored, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return None
        if row is None:
            return None
        if _hasher.check_needs_rehash(stored):
            self.store.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (_hasher.hash(password), row["id"]),
            )
        self.store.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?", (self.clock(), row["id"])
        )
        return self.get_user(row["id"])

    # Sessions.

    def start_session(
        self, user: User, seconds: float = SESSION_SECONDS, *, user_agent: str | None = None
    ) -> tuple[str, float]:
        """Return (token, expiry). Only the token's hash is kept, under a separate id.

        ``user_agent`` is the browser's, kept to help people tell their sessions apart.
        """
        token = "ira_s_" + secrets.token_urlsafe(32)
        now = self.clock()
        expires = now + seconds
        self.store.execute(
            "INSERT INTO sessions (id, token_hash, user_id, created_at, expires_at, last_seen_at, "
            "user_agent) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("ses_"),
                sha256_hex(token),
                user.id,
                now,
                expires,
                now,
                (user_agent or "").strip()[:USER_AGENT_CHARS] or None,
            ),
        )
        return token, expires

    def session_principal(self, token: str) -> Principal | None:
        row = self.store.one(
            "SELECT s.id AS sid, s.expires_at, s.revoked_at, u.* FROM sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND u.disabled_at IS NULL",
            (sha256_hex(token),),
        )
        if row is None or row["revoked_at"] is not None or row["expires_at"] <= self.clock():
            return None
        self.store.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE id = ?", (self.clock(), row["sid"])
        )
        user = _user(row)
        return Principal(user, "session", user.permissions, row["sid"])

    def end_session(self, token: str) -> bool:
        cursor = self.store.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (self.clock(), sha256_hex(token)),
        )
        return cursor.rowcount == 1

    _ACTIVE_SESSIONS = (
        "SELECT s.id, s.user_id, u.email, u.role, s.created_at, s.last_seen_at AS last_used_at, "
        "s.expires_at, s.user_agent FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.revoked_at IS NULL AND s.expires_at > ? AND u.disabled_at IS NULL"
    )

    def sessions(
        self,
        user_id: int | None = None,
        *,
        limit: int | None = None,
        before: float | None = None,
        before_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Active sessions, most recently used first (ties by id): one user's, or everyone's.

        Page with the last row's ``last_used_at`` as ``before`` and its id as
        ``before_id``. Rows carry the session id, never the token or its hash.
        """
        sql, params = self._ACTIVE_SESSIONS, [self.clock()]
        used = "COALESCE(s.last_seen_at, s.created_at)"
        if user_id is not None:
            sql += " AND s.user_id = ?"
            params.append(user_id)
        if before is not None and before_id is not None:
            sql += f" AND ({used} < ? OR ({used} = ? AND s.id < ?))"
            params += [before, before, before_id]
        elif before is not None:
            sql += f" AND {used} < ?"
            params.append(before)
        sql += f" ORDER BY {used} DESC, s.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [dict(r) for r in self.store.query(sql, params)]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """An active session by id."""
        row = self.store.one(self._ACTIVE_SESSIONS + " AND s.id = ?", (self.clock(), session_id))
        return dict(row) if row else None

    def end_session_id(self, session_id: str) -> bool:
        cursor = self.store.execute(
            "UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (self.clock(), session_id),
        )
        return cursor.rowcount == 1

    def end_other_sessions(self, user_id: int, keep: str | None) -> int:
        """End every active session of a user except ``keep``. Returns how many ended."""
        now = self.clock()
        cursor = self.store.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND id != ? "
            "AND revoked_at IS NULL AND expires_at > ?",
            (now, user_id, keep or "", now),
        )
        return cursor.rowcount

    # API tokens.

    def create_token(self, user: User, label: str, scopes: list[str]) -> tuple[str, str]:
        """Return (token, token id). The token is shown once and only its hash is kept."""
        scopes = parse_scopes(scopes)
        beyond = [s for s in scopes if s not in user.permissions]
        if beyond:
            raise AccountError(
                f"a {user.role} cannot hold a token with scope(s) {', '.join(beyond)}"
            )
        label = label.strip() or "token"
        token = new_api_token()
        token_id = new_id("tok_")
        self.store.execute(
            "INSERT INTO api_tokens (id, user_id, label, token_hash, scopes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (token_id, user.id, label, sha256_hex(token), ",".join(scopes), self.clock()),
        )
        return token, token_id

    def token_principal(self, token: str) -> Principal | None:
        row = self.store.one(
            "SELECT t.id AS tid, t.scopes, t.revoked_at, u.* FROM api_tokens t "
            "JOIN users u ON u.id = t.user_id "
            "WHERE t.token_hash = ? AND u.disabled_at IS NULL",
            (sha256_hex(token),),
        )
        if row is None or row["revoked_at"] is not None:
            return None
        self.store.execute(
            "UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (self.clock(), row["tid"])
        )
        user = _user(row)
        scopes = frozenset(row["scopes"].split(","))
        return Principal(user, "token", scopes & user.permissions, row["tid"])

    def tokens(self) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT t.id, t.label, t.scopes, t.created_at, t.last_used_at, t.revoked_at, "
            "u.email FROM api_tokens t JOIN users u ON u.id = t.user_id ORDER BY t.created_at"
        )
        return [dict(r) for r in rows]

    def get_token(self, token_id: str) -> dict[str, Any] | None:
        row = self.store.one(
            "SELECT t.id, t.label, t.scopes, t.created_at, t.last_used_at, t.revoked_at, "
            "u.email FROM api_tokens t JOIN users u ON u.id = t.user_id WHERE t.id = ?",
            (token_id,),
        )
        return dict(row) if row else None

    def revoke_token_id(self, token_id: str) -> bool:
        cursor = self.store.execute(
            "UPDATE api_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (self.clock(), token_id),
        )
        return cursor.rowcount == 1

    def revoke_token(self, id_or_label: str) -> int:
        cursor = self.store.execute(
            "UPDATE api_tokens SET revoked_at = ? "
            "WHERE (id = ? OR label = ?) AND revoked_at IS NULL",
            (self.clock(), id_or_label, id_or_label),
        )
        return cursor.rowcount

    def principal(self, bearer: str) -> Principal | None:
        """Resolve a bearer value: a session token or an API token."""
        if bearer.startswith("ira_s_"):
            return self.session_principal(bearer)
        return self.token_principal(bearer)
