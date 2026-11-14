"""One command to run the tool:  python run.py

1. brings the database schema up to date (Alembic),
2. on first run adds the default rules and the admin account from .env,
3. starts the web server (frontend + API) on http://HOST:PORT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

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


def first_run_setup() -> None:
    """No .env yet: ask a few questions, create the database if needed and write backend/.env."""
    env = HERE / ".env"
    if env.exists() or os.environ.get("DATABASE_URL"):
        return
    import pymysql

    print("\n=== First run setup (only once) ===")
    print("MySQL (or XAMPP / MariaDB) must be running.\n")
    while True:
        user = input("MySQL user name [root]: ").strip() or "root"
        pw = input("MySQL password of that user (just press Enter if it has none): ")
        host = input("MySQL server [localhost]: ").strip() or "localhost"
        port = input("MySQL port [3306]: ").strip() or "3306"
        try:
            conn = pymysql.connect(host=host, port=int(port), user=user, password=pw, connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute("CREATE DATABASE IF NOT EXISTS ipgen CHARACTER SET utf8mb4")
            conn.close()
            print("OK: connected, database 'ipgen' is ready.\n")
            break
        except Exception as exc:  # wrong password, server not running, ...
            print(f"\nCould not connect: {exc}\nCheck that MySQL is running and the user/password are right, then try again.\n")
    while True:
        admin_pw = input("Choose a password for the website admin (8 or more characters, English letters/digits): ")
        if len(admin_pw) >= 8 and admin_pw == admin_pw.strip():
            break
        print("The password must be at least 8 characters, without spaces at the start or end.")
    text = (HERE / ".env.example").read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        if line.startswith("DATABASE_URL="):
            line = f"DATABASE_URL=mysql+pymysql://{quote_plus(user)}:{quote_plus(pw)}@{host}:{port}/ipgen?charset=utf8mb4"
        elif line.startswith("ADMIN_PASSWORD="):
            line = f"ADMIN_PASSWORD={admin_pw}"
        lines.append(line)
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nSaved the settings in backend/.env")
    print("Website admin:  user name = admin   password = the one you just chose\n")


def main() -> None:
    first_run_setup()
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
