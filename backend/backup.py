"""One-command backup:  python backup.py   -> backups/ipgen-YYYY-MM-DD-HHMM.(sql|db)

MySQL/MariaDB: runs mysqldump (must be installed). SQLite: copies the database file safely.
The Excel export in the Worksheet page is the second backup path.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import load_settings

HERE = Path(__file__).resolve().parent


def main() -> None:
    url = make_url(load_settings().database_url)
    out_dir = HERE / "backups"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    if url.get_backend_name() == "sqlite":
        target = out_dir / f"ipgen-{stamp}.db"
        src, dst = sqlite3.connect(url.database), sqlite3.connect(target)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
    else:
        target = out_dir / f"ipgen-{stamp}.sql"
        cmd = ["mysqldump", "--single-transaction", "--routines", f"--host={url.host or 'localhost'}", f"--port={url.port or 3306}",
               f"--user={url.username}", f"--result-file={target}", url.database]
        env = {**os.environ, "MYSQL_PWD": url.password or ""}     # password via environment, not on the command line
        if subprocess.run(cmd, env=env).returncode != 0:
            print("Backup failed. Is mysqldump installed and on the PATH?", file=sys.stderr)
            raise SystemExit(1)
    print(f"Backup written to {target}")


if __name__ == "__main__":
    main()
