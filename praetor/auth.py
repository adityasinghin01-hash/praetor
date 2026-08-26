"""Who is actually approving.

Until now the approver typed their own identity into a text box. `gate.approve()`
rejected blanks and anything starting `agent:`, and membership decided what a role could
do -- but nothing established that the person claiming to be the CFO was the CFO. The
segregation-of-duties control this project keeps claiming rested on a self-declaration.

This closes that. A password proves the identity, a session carries it, and the approve
path reads the approver from the session instead of from the request body. The browser
can no longer name who it is.

Deliberately stdlib-only: PBKDF2-HMAC-SHA256 for passwords, `secrets` for session
tokens, SQLite for session state. No dependency, and nothing here needs an account with
anyone.

**This is local auth, and it is a stand-in.** Google Sign-In is the intended production
identity provider, and swapping it in touches one function: `authenticate()` stops
checking a password hash and starts verifying an ID token. Everything downstream --
sessions, membership, roles, the approve path -- is unchanged, because none of it knows
how the identity was established.

Session tokens are stored hashed, so a stolen database does not hand over live sessions.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

ITERATIONS = 240_000
SESSION_HOURS = 12


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a per-password salt, stored as one self-describing string.

    The iteration count travels with the hash so it can be raised later without
    invalidating everyone's password.
    """
    if not password:
        raise ValueError("a password is required")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time comparison, and False for anything malformed rather than an error."""
    if not password or not stored:
        return False
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


# ---------------------------------------------------------------- sessions

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(conn, email: str, password: str) -> str | None:
    """Return the canonical user id if the password checks out, else None.

    This is the whole of the identity-provider seam. Swapping in Google Sign-In replaces
    the body of this function and nothing else.
    """
    email = (email or "").strip().lower()
    row = conn.execute("SELECT id, password_hash FROM users WHERE id = ?",
                       (email,)).fetchone()
    if row is None:
        # Spend the time anyway, so a missing account and a wrong password take the same
        # length of time to reject.
        verify_password(password, hash_password("decoy"))
        return None
    return row["id"] if verify_password(password, row["password_hash"]) else None


def start_session(conn, user_id: str) -> str:
    """Issue a session token. Only its hash is stored."""
    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(hours=SESSION_HOURS)
    conn.execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at)"
        " VALUES (?,?,?,?)",
        (_token_hash(token), user_id, _now().isoformat(timespec="seconds"),
         expires.isoformat(timespec="seconds")))
    return token


def session_user(conn, token: str | None) -> str | None:
    """The user this token belongs to, or None if it is unknown or expired."""
    if not token:
        return None
    row = conn.execute(
        "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
        (_token_hash(token),)).fetchone()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) <= _now():
        end_session(conn, token)
        return None
    return row["user_id"]


def end_session(conn, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def purge_expired(conn) -> int:
    cur = conn.execute("DELETE FROM sessions WHERE expires_at <= ?",
                       (_now().isoformat(timespec="seconds"),))
    return cur.rowcount or 0


def set_password(conn, user_id: str, password: str) -> None:
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (hash_password(password), user_id.strip().lower()))
