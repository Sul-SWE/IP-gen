"""Settings from environment variables (and an optional .env file next to this package). No secrets in code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
FRONTEND_DIR = BASE_DIR.parent / "frontend"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_username: str
    admin_password: str
    session_hours: int            # admin session ends after this much inactivity
    admin_idle_minutes: int       # another admin may sign in when the current one is idle this long
    login_max_fails: int
    login_window_minutes: int
    cookie_secure: bool
    viewer_can_see_worksheet: bool
    allowed_origins: tuple[str, ...]
    max_import_bytes: int = 5 * 1024 * 1024
    max_import_rows: int = 5000


def load_settings() -> Settings:
    _load_dotenv(BASE_DIR / ".env")
    return Settings(
        database_url=os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'ipgen.db'}"),
        admin_username=os.environ.get("ADMIN_USERNAME", ""),
        admin_password=os.environ.get("ADMIN_PASSWORD", ""),
        session_hours=_int("SESSION_HOURS", 8),
        admin_idle_minutes=_int("ADMIN_IDLE_MINUTES", 5),
        login_max_fails=_int("LOGIN_MAX_FAILS", 5),
        login_window_minutes=_int("LOGIN_WINDOW_MINUTES", 15),
        cookie_secure=_bool("COOKIE_SECURE", False),
        viewer_can_see_worksheet=_bool("VIEWER_CAN_SEE_WORKSHEET", True),
        allowed_origins=tuple(o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()),
    )
