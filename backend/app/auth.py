"""Admin sign-in: password hashing, server-side sessions, one admin at a time, CSRF and login rate limit.

Viewers need no account: read-only endpoints are public inside the network the tool is served on.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import Settings
from .db import lock_writes
from .errors import ApiError
from .models import Account, AuthSession

COOKIE = "ipgen_session"
_hasher = PasswordHasher()
_DUMMY = _hasher.hash("not-a-real-password")


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _sid(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_problem(pw: str) -> str:
    return "" if len(pw) >= 8 else "The password must be at least 8 characters."


def ensure_admin(db: Session, cfg: Settings) -> None:
    """Create the admin account on first run from ADMIN_USERNAME / ADMIN_PASSWORD. No default password exists."""
    if db.scalar(select(Account.id).limit(1)) is not None:
        return
    if not cfg.admin_username or not cfg.admin_password:
        raise RuntimeError("First run: set ADMIN_USERNAME and ADMIN_PASSWORD in backend/.env (see .env.example).")
    if password_problem(cfg.admin_password):
        raise RuntimeError("ADMIN_PASSWORD must be at least 8 characters.")
    db.add(Account(username=cfg.admin_username.strip(), password_hash=_hasher.hash(cfg.admin_password), role="admin"))
    db.flush()


class LoginLimiter:
    """Failed sign-ins per client IP inside a sliding window (kept in memory)."""

    def __init__(self, max_fails: int, window_minutes: int):
        self.max, self.window = max_fails, window_minutes * 60
        self.fails: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, ip: str) -> deque[float]:
        q = self.fails[ip]
        while q and time.time() - q[0] > self.window:
            q.popleft()
        return q

    def check(self, ip: str) -> None:
        q = self._trim(ip)
        if len(q) >= self.max:
            wait = max(1, int((self.window - (time.time() - q[0])) // 60) + 1)
            raise ApiError(429, "too_many_attempts", f"Too many failed sign-ins. Try again in about {wait} minute(s).")

    def fail(self, ip: str) -> None:
        self._trim(ip).append(time.time())

    def reset(self, ip: str) -> None:
        self.fails.pop(ip, None)


def login(db: Session, cfg: Settings, limiter: LoginLimiter, username: str, password: str, ip: str, force: bool) -> tuple[str, AuthSession]:
    limiter.check(ip)
    acc = db.scalar(select(Account).where(Account.username == username.strip(), Account.active.is_(True)))
    try:
        ok = _hasher.verify(acc.password_hash if acc else _DUMMY, password) and acc is not None
    except (VerificationError, InvalidHashError):
        ok = False
    if not ok:
        limiter.fail(ip)
        raise ApiError(401, "bad_credentials", "Wrong username or password.")
    limiter.reset(ip)

    lock_writes(db)   # two sign-ins at the same moment are handled one after the other
    now = _now()
    db.execute(delete(AuthSession).where(AuthSession.last_seen < now - timedelta(days=2)))
    live = db.scalars(select(AuthSession).where(AuthSession.ended_reason == "",
                                                AuthSession.last_seen >= now - timedelta(hours=cfg.session_hours))).all()
    busy = [s for s in live if s.last_seen >= now - timedelta(minutes=cfg.admin_idle_minutes)]
    if busy and not force:
        last = max(s.last_seen for s in busy)
        raise ApiError(409, "admin_busy", "Another admin is signed in right now. Only one admin can work at a time, "
                       "so that two people never change the data together.", extra={"last_seen": last.strftime("%Y-%m-%d %H:%M")})
    for s in live:
        s.ended_reason = "replaced"
    token = secrets.token_urlsafe(32)
    sess = AuthSession(id=_sid(token), account_id=acc.id, csrf=secrets.token_urlsafe(24), created_at=now, last_seen=now, ip=ip[:45])
    db.add(sess)
    db.flush()
    return token, sess


def session_for(db: Session, cfg: Settings, token: str | None) -> AuthSession | None:
    """The live admin session of this cookie, or None. Raises 401 session_replaced when another sign-in took over."""
    if not token:
        return None
    s = db.get(AuthSession, _sid(token))
    if s is None:
        return None
    if s.ended_reason:
        raise ApiError(401, "session_replaced", "Another admin signed in, so this session was ended. Sign in again to continue.")
    now = _now()
    if s.last_seen < now - timedelta(hours=cfg.session_hours):
        db.delete(s)
        db.commit()
        return None
    if (now - s.last_seen).total_seconds() > 20:
        s.last_seen = now
        db.commit()
    return s


def logout(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.id == _sid(token)))


def csrf_ok(sess: AuthSession, header: str | None) -> bool:
    return bool(header) and hmac.compare_digest(sess.csrf, header)


def change_password(db: Session, sess: AuthSession, current: str, new: str) -> None:
    acc = db.get(Account, sess.account_id)
    try:
        _hasher.verify(acc.password_hash, current)
    except (VerificationError, InvalidHashError):
        raise ApiError(400, "bad_credentials", "The current password is wrong.") from None
    problem = password_problem(new)
    if problem:
        raise ApiError(400, "invalid", problem)
    acc.password_hash = _hasher.hash(new)
    db.flush()
