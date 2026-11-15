"""Sign-in, one admin at a time, CSRF, rate limit, cookie flags, security headers."""

from tests.api.conftest import ADMIN, CONFIG, Api, Client, sql


def _age_sessions(app, minutes: int) -> None:
    sql('UPDATE sessions SET last_seen = last_seen - INTERVAL %s MINUTE', [minutes])


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


def test_same_browser_signs_in_again_without_take_over(app):
    a = Api(app)
    r = a.c.post("/api/auth/login", json=ADMIN)          # same cookie: a second tab of the same admin
    assert r.status_code == 200
    a.csrf = r.json()["csrf"]
    assert a.preview(1).status_code == 200
    assert Api(app, login=False).c.post("/api/auth/login", json=ADMIN).status_code == 409   # a different browser is still stopped


def test_idle_admin_does_not_block_sign_in(app):
    Api(app)
    _age_sessions(app, 6)
    assert Api(app, login=False).c.post("/api/auth/login", json=ADMIN).status_code == 200


def test_expired_session(app):
    a = Api(app)
    _age_sessions(app, 9 * 60)
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
    assert "default-src 'none'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in viewer.c.get("/api/config", headers={"Origin": "http://evil.example"}).headers
    nf = viewer.get("/nope")
    assert nf.status_code == 404 and set(nf.json()) >= {"error", "message", "details"}


def test_setup_only_once_and_needs_a_strong_admin_password(app):
    c = Client()
    r = c.post("/api/setup", json={"user": "x", "admin_password": "long-enough-1"})
    assert r.status_code == 409 and r.json()["error"] == "already_setup"
    CONFIG.unlink()
    assert c.get("/api/auth/me").json()["error"] == "setup_required"
    assert c.post("/api/setup", json={"user": "ipgen", "password": "devpass", "database": "ipgen_test_php", "admin_password": "short"}).status_code == 400
    bad = c.post("/api/setup", json={"user": "ipgen", "password": "wrong", "database": "ipgen_test_php", "admin_password": "long-enough-1"})
    assert bad.status_code == 400 and bad.json()["error"] == "db_connect" and not CONFIG.exists()
    again = c.post("/api/setup", json={"user": "ipgen", "password": "devpass", "database": "ipgen_test_php", "admin_password": "another-pass-2"})
    assert again.status_code == 200 and again.json()["existing_data"] is True          # existing data and admin are kept
    assert c.post("/api/auth/login", json=ADMIN).status_code == 200
    assert not (CONFIG.parent / "config.php").read_text().count("another-pass-2")      # no admin password in the config file


def test_server_files_are_not_served(app):
    c = Client()
    for path in ("/server/config.php", "/server/schema.sql", "/tests/api/conftest.py", "/.git/config", "/.htaccess"):
        r = c.get(path)
        assert r.status_code in (403, 404) and "devpass" not in r.text, path
