"""One command to run the tool:  python run.py

1. brings the database schema up to date (Alembic),
2. on first run adds the default rules and the admin account from .env,
3. starts the web server (frontend + API) on http://HOST:PORT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from app.config import load_settings
from app.db import make_engine
from app.main import create_app

HERE = Path(__file__).resolve().parent


def migrate(engine) -> None:
    cfg = Config(str(HERE / "alembic.ini"))
    cfg.set_main_option("script_location", str(HERE / "migrations"))
    cfg.attributes["engine"] = engine
    command.upgrade(cfg, "head")


def main() -> None:
    settings = load_settings()
    try:
        engine = make_engine(settings.database_url)
        migrate(engine)
    except Exception as exc:  # the most common first-run problem: wrong DATABASE_URL
        print(f"\nCould not open the database. Check DATABASE_URL in backend/.env\n  {type(exc).__name__}: {exc}\n", file=sys.stderr)
        raise SystemExit(1) from None
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))
    print(f"\nIP Generator is running:  http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}\nPress Ctrl+C to stop.\n")
    uvicorn.run(create_app(settings, engine), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
