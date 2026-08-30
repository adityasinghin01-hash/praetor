"""Authentication, expressed as tests.

The property that matters: the approver's identity comes from the session, so the
browser cannot name who it is. Before this, `human_id` was typed into a text box and the
segregation-of-duties control rested on a self-declaration.

These cover the identity layer. The approve path that consumes it is covered in
tests/test_store.py, and the invariant that no agent reaches APPROVED is in
tests/test_invariants.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from praetor import auth, store

TENANT = "acme-industries"


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "t.db")
    with store.tx(c):
        store.add_tenant(c, TENANT)
        store.add_user(c, "approver@acme.test", "Approver")
        store.grant(c, "approver@acme.test", TENANT, "approver")
        auth.set_password(c, "approver@acme.test", "correct horse")
    return c


# ---------------------------------------------------------------- passwords

def test_a_password_verifies():
    stored = auth.hash_password("hunter2")
    assert auth.verify_password("hunter2", stored)


def test_a_wrong_password_does_not():
    assert not auth.verify_password("hunter3", auth.hash_password("hunter2"))


def test_the_same_password_hashes_differently_each_time():
    """Per-password salt: two users with the same password must not look identical."""
    assert auth.hash_password("same") != auth.hash_password("same")


def test_an_empty_password_is_refused():
    with pytest.raises(ValueError):
        auth.hash_password("")
    assert not auth.verify_password("", auth.hash_password("x"))


def test_a_malformed_hash_fails_rather_than_raising():
    for junk in (None, "", "not-a-hash", "pbkdf2_sha256$abc", "md5$1$aa$bb"):
        assert auth.verify_password("anything", junk) is False


# ---------------------------------------------------------------- login

def test_correct_credentials_return_the_user(conn):
    assert auth.authenticate(conn, "approver@acme.test", "correct horse") == "approver@acme.test"


def test_the_email_is_case_and_space_insensitive(conn):
    assert auth.authenticate(conn, "  Approver@Acme.TEST ", "correct horse")


def test_a_wrong_password_returns_nothing(conn):
    assert auth.authenticate(conn, "approver@acme.test", "wrong") is None


def test_an_unknown_account_returns_nothing(conn):
    assert auth.authenticate(conn, "ghost@nowhere.test", "correct horse") is None


def test_a_user_with_no_password_set_cannot_log_in(conn):
    """A seeded account that never got a password must not be a way in."""
    with store.tx(conn):
        store.add_user(conn, "nopass@acme.test", "No Password")
    assert auth.authenticate(conn, "nopass@acme.test", "") is None
    assert auth.authenticate(conn, "nopass@acme.test", "anything") is None


def test_signup_creates_only_a_viewer(conn):
    user = auth.register_viewer(
        conn, " New.User@Example.test ", "New User", "a long safe password", TENANT)

    assert user == "new.user@example.test"
    assert auth.authenticate(conn, user, "a long safe password") == user
    assert store.role_of(conn, user, TENANT) == "viewer"


def test_signup_cannot_replace_an_existing_approver(conn):
    with pytest.raises(auth.RegistrationError):
        auth.register_viewer(
            conn, "approver@acme.test", "Not the approver",
            "a different long password", TENANT)

    assert store.role_of(conn, "approver@acme.test", TENANT) == "approver"
    assert auth.authenticate(conn, "approver@acme.test", "correct horse")


# ---------------------------------------------------------------- sessions

def test_a_session_identifies_its_user(conn):
    token = auth.start_session(conn, "approver@acme.test")
    assert auth.session_user(conn, token) == "approver@acme.test"


def test_an_unknown_token_identifies_nobody(conn):
    assert auth.session_user(conn, "made-up-token") is None
    assert auth.session_user(conn, None) is None
    assert auth.session_user(conn, "") is None


def test_signing_out_ends_the_session(conn):
    token = auth.start_session(conn, "approver@acme.test")
    auth.end_session(conn, token)
    assert auth.session_user(conn, token) is None


def test_an_expired_session_identifies_nobody(conn):
    token = auth.start_session(conn, "approver@acme.test")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    conn.execute("UPDATE sessions SET expires_at = ?", (past,))
    assert auth.session_user(conn, token) is None


def test_an_expired_session_is_cleaned_up_when_used(conn):
    token = auth.start_session(conn, "approver@acme.test")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    conn.execute("UPDATE sessions SET expires_at = ?", (past,))
    auth.session_user(conn, token)
    assert conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"] == 0


def test_the_raw_token_is_never_stored(conn):
    """A copy of the database must not hand over live sessions."""
    token = auth.start_session(conn, "approver@acme.test")
    stored = [r["token_hash"] for r in conn.execute("SELECT token_hash FROM sessions")]
    assert token not in stored
    assert len(stored) == 1


def test_two_sessions_are_independent(conn):
    a = auth.start_session(conn, "approver@acme.test")
    b = auth.start_session(conn, "approver@acme.test")
    auth.end_session(conn, a)
    assert auth.session_user(conn, a) is None
    assert auth.session_user(conn, b) == "approver@acme.test"


def test_purging_removes_only_expired_sessions(conn):
    live = auth.start_session(conn, "approver@acme.test")
    dead = auth.start_session(conn, "approver@acme.test")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                 (past, auth._token_hash(dead)))
    assert auth.purge_expired(conn) == 1
    assert auth.session_user(conn, live) == "approver@acme.test"


def test_changing_a_password_does_not_break_the_login(conn):
    auth.set_password(conn, "approver@acme.test", "a new one")
    assert auth.authenticate(conn, "approver@acme.test", "a new one")
    assert auth.authenticate(conn, "approver@acme.test", "correct horse") is None
