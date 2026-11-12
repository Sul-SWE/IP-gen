"""Sign-in, one admin at a time, CSRF, rate limit, cookie flags, security headers."""

from datetime import timedelta

from sqlalchemy import select

from app.models import AuthSession
from tests.conftest import ADMIN, Api


def _age_sessions(app, by: timedelta) -> None:
    with app.state.session_factory() as db:
        for s in db.scalars(select(AuthSession)):
            s.last_seen = s.last_seen - by
        db.commit()


def test_login_logout_and_cookie_flags(app):
    a = Api(app, login=False)
    r = a.c.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    a.csrf = r.json()["csrf"]
    assert a.get("/auth/me").json()["role"] == "admin"
    assert a.post("/auth/logout").status_code == 200
    assert a.get("/auth/me").json()["role"] == "viewer"
    assert a.get("/audit-log").status_code == 401


def test_wrong_password_and_rate_limit(app):
    a = Api(app, login=False)
    for _ in range(5):
        assert a.c.post("/api/auth/login", json={**ADMIN, "password": "nope"}).status_code == 401
    r = a.c.post("/api/auth/login", json=ADMIN)                 # even the right password is refused now
    assert r.status_code == 429 and r.json()["error"] == "too_many_attempts"
    assert a.c.post("/api/auth/login", json={"username": "ghost", "password": "x"}).status_code == 429


def test_csrf_token_is_required_for_changes(admin):
    body = {"facility": "UTMN", "well": "1", "gcp": "HDGCP1-R1", "vendor": "Yokogawa", "engineer": "Eng A"}
    assert admin.c.post("/api/generate/preview", json=body).status_code == 403
    assert admin.c.post("/api/generate/preview", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert admin.post("/generate/preview", body).status_code == 200


def test_only_one_admin_at_a_time(app):
    first = Api(app)
    second = Api(app, login=False)
    r = second.c.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 409 and r.json()["error"] == "admin_busy" and r.json()["last_seen"]
    assert first.preview(1).status_code == 200                               # the first admin is not disturbed
    r = second.c.post("/api/auth/login", json={**ADMIN, "force": True})      # explicit take-over
    assert r.status_code == 200
    second.csrf = r.json()["csrf"]
    gone = first.preview(1)
    assert gone.status_code == 401 and gone.json()["error"] == "session_replaced"
    assert first.save(1, signature="x").status_code == 401                   # the replaced session can no longer write
    assert second.save(1).status_code == 201


def test_idle_admin_does_not_block_sign_in(app):
    Api(app)
    _age_sessions(app, timedelta(minutes=6))
    assert Api(app, login=False).c.post("/api/auth/login", json=ADMIN).status_code == 200


def test_expired_session(app):
    a = Api(app)
    _age_sessions(app, timedelta(hours=9))
    assert a.get("/auth/me").json()["role"] == "viewer" and a.get("/audit-log").status_code == 401


def test_change_password(app):
    a = Api(app)
    assert a.post("/auth/password", {"current": "bad", "new": "another-pass-9"}).status_code == 400
    assert a.post("/auth/password", {"current": ADMIN["password"], "new": "short"}).status_code == 400
    assert a.post("/auth/password", {"current": ADMIN["password"], "new": "another-pass-9"}).status_code == 200
    a.post("/auth/logout")
    b = Api(app, login=False)
    assert b.c.post("/api/auth/login", json=ADMIN).status_code == 401
    assert b.c.post("/api/auth/login", json={**ADMIN, "password": "another-pass-9"}).status_code == 200


def test_security_headers_and_error_shape(viewer):
    r = viewer.get("/config")
    assert "script-src 'self'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in viewer.c.get("/api/config", headers={"Origin": "http://evil.example"}).headers
    nf = viewer.get("/nope")
    assert nf.status_code == 404 and set(nf.json()) >= {"error", "message", "details"}


def test_no_default_password(tmp_path):
    import pytest
    from fastapi.testclient import TestClient

    from app.db import make_engine
    from app.main import create_app
    from app.models import Base
    from tests.conftest import make_settings

    url = f"sqlite:///{tmp_path / 'x.db'}"
    eng = make_engine(url)
    Base.metadata.create_all(eng)
    with pytest.raises(RuntimeError), TestClient(create_app(make_settings(url, admin_password=""), eng)):
        pass
    eng.dispose()
