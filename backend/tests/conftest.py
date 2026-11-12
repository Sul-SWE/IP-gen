"""Test fixtures. Tests run on SQLite by default; set TEST_DATABASE_URL to run them on MySQL/MariaDB too."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.models import Base
from app.services import importer

ADMIN = {"username": "admin", "password": "test-password-1"}


def make_settings(url: str, **over) -> Settings:
    base = dict(database_url=url, admin_username=ADMIN["username"], admin_password=ADMIN["password"], session_hours=8,
                admin_idle_minutes=5, login_max_fails=5, login_window_minutes=15, cookie_secure=False,
                viewer_can_see_worksheet=True, allowed_origins=())
    base.update(over)
    return Settings(**base)


@pytest.fixture()
def db_url(tmp_path) -> str:
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture()
def app(db_url):
    engine = make_engine(db_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    importer._previews.clear()
    application = create_app(make_settings(db_url), engine)
    with TestClient(application):      # runs startup: seed rules + admin account
        yield application
    Base.metadata.drop_all(engine)
    engine.dispose()


class Api:
    """Small helper around TestClient that sends the CSRF token like the frontend does."""

    def __init__(self, app, login: bool = True, **login_extra):
        self.c = TestClient(app)
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

    # shortcuts
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
