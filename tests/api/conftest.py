"""API tests against the running PHP server.

Start the server first (an empty test database is created and set up before every test):
    php -S 127.0.0.1:8030 server/dev-router.php
Settings (environment variables): PHP_BASE, TEST_DB_HOST, TEST_DB_USER, TEST_DB_PASS, TEST_DB_NAME.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pymysql
import pytest

BASE = os.environ.get("PHP_BASE", "http://127.0.0.1:8030").rstrip("/")
DB = {"host": os.environ.get("TEST_DB_HOST", "127.0.0.1"), "user": os.environ.get("TEST_DB_USER", "ipgen"),
      "password": os.environ.get("TEST_DB_PASS", "devpass"), "database": os.environ.get("TEST_DB_NAME", "ipgen_test_php")}
CONFIG = Path(__file__).resolve().parents[2] / "server" / "config.php"
ADMIN = {"username": "admin", "password": "test-password-1"}


class Client(httpx.Client):
    """httpx client that maps /api/... to the PHP entry point /api/index.php/..."""

    def __init__(self, ip: str | None = None):
        # ip: connect from another local address to act as "another computer" (127.0.0.2, ...)
        super().__init__(base_url=BASE, timeout=120, transport=httpx.HTTPTransport(local_address=ip) if ip else None)

    def request(self, method, url, *a, **kw):
        if isinstance(url, str) and url.startswith("/api/"):
            url = "/api/index.php/" + url[5:]
        return super().request(method, url, *a, **kw)


def sql(query: str, args=None, database: bool = True):
    conn = pymysql.connect(host=DB["host"], user=DB["user"], password=DB["password"], database=DB["database"] if database else None, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(query, args)
            return cur.fetchall()
    finally:
        conn.close()


def fresh_install(**config_overrides) -> None:
    if CONFIG.exists():
        CONFIG.unlink()
    sql(f"DROP DATABASE IF EXISTS `{DB['database']}`", database=False)
    with Client() as c:
        r = c.post("/api/setup", json={"host": DB["host"], "user": DB["user"], "password": DB["password"], "database": DB["database"],
                                        "admin_password": ADMIN["password"]})
        assert r.status_code == 200, r.text
    if config_overrides:
        text = CONFIG.read_text()
        for k, v in config_overrides.items():
            old = f"'{k}' => " + ("true" if not v else "false") if isinstance(v, bool) else None
            new = f"'{k}' => " + ("true" if v else "false") if isinstance(v, bool) else None
            assert old in text, k
            text = text.replace(old, new)
        CONFIG.write_text(text)


@pytest.fixture()
def app():
    fresh_install()
    yield BASE
    if CONFIG.exists():
        CONFIG.unlink()


class Api:
    """Small helper that sends the CSRF token like the frontend does."""

    def __init__(self, app=None, login: bool = True, ip: str | None = None, **login_extra):
        self.c = Client(ip)
        self.csrf = ""
        if login:
            r = self.c.post("/api/auth/login", json={**ADMIN, **login_extra})
            assert r.status_code == 200, r.text
            self.csrf = r.json()["csrf"]

    def _h(self):
        return {"X-CSRF-Token": self.csrf} if self.csrf else {}

    def get(self, url, **kw):
        return self.c.get("/api" + url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post("/api" + url, json=json, headers=self._h(), **kw)

    def patch(self, url, json=None):
        return self.c.patch("/api" + url, json=json, headers=self._h())

    def delete(self, url, json=None):
        return self.c.request("DELETE", "/api" + url, json=json, headers=self._h())

    def preview(self, well, facility="UTMN", gcp="HDGCP1-R1", vendor="Yokogawa", engineer="Eng A"):
        return self.post("/generate/preview", {"facility": facility, "well": str(well), "gcp": gcp, "vendor": vendor, "engineer": engineer})

    def save(self, well, facility="UTMN", gcp="HDGCP1-R1", vendor="Yokogawa", engineer="Eng A", signature=None):
        if signature is None:
            p = self.preview(well, facility, gcp, vendor, engineer)
            assert p.status_code == 200, p.text
            signature = p.json()["signature"]
        return self.post("/records", {"facility": facility, "well": str(well), "gcp": gcp, "vendor": vendor, "engineer": engineer, "signature": signature})


@pytest.fixture()
def admin(app) -> Api:
    return Api(app)


@pytest.fixture()
def viewer(app) -> Api:
    return Api(app, login=False)
