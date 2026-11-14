# IP Address Auto-Generator and Management Platform

Generates, checks and tracks the IP addresses of RTU / PLC devices from fixed rules, instead of typing them by hand in Excel.
**All rules and addresses in this repository are dummy test values.** Always verify a real IP in the field (ping / arp) before using it.

| Part | Technology |
|---|---|
| Frontend (`frontend/`) | HTML, CSS, JavaScript (no framework) |
| Backend (`backend/`) | Python, FastAPI, SQLAlchemy, Alembic |
| Database | MySQL / MariaDB (SQLite works for a quick trial) |
| Excel | openpyxl on the server (`.xlsx`) |
| `prototype/` | the earlier browser-only prototype, kept as reference |

## Who uses it
- **Viewer**: opens the site and sees the Dashboard and the Worksheet. No sign-in, read only.
- **Admin**: signs in with the shared admin account to generate, modify, delete, import/export and change the rules.
  **Only one admin can be signed in at a time**; a second sign-in is told so and may take over (the first session ends).
  Because the account is shared, each engineer types their own name; it is written to the change log with every change.

## Run it on your computer (Windows)

1. Install **Python 3.11 or newer** from python.org and tick **"Add Python to PATH"** on the first installer screen.
2. Make sure **MySQL** is running (MySQL service, or XAMPP: press Start next to MySQL).
3. Double-click **`start.bat`** in the project folder.
   - First time only: it installs the packages, then asks for the MySQL user (Enter = `root`), its password
     (Enter if none) and a password for the website admin. It creates the database `ipgen` and the file `backend/.env` by itself.
4. The browser opens **http://localhost:8000**. Admin sign-in: user `admin` and the password you chose.

Keep the black window open while you use the site; closing it stops the site. Next time: double-click `start.bat` again.
To change the settings later, edit `backend/.env` (see `.env.example`) or delete it to be asked again.

Manual start (any system): in `backend/`, `python -m venv .venv`, activate it, `pip install -r requirements.txt`, `python run.py`.

To let colleagues on the same network open it, set `HOST=0.0.0.0` in `.env` and give them `http://YOUR-PC-NAME:8000`
(ask IT first; use HTTPS and `COOKIE_SECURE=true` on a real server).

## Everyday use
- **Dashboard**: free host numbers per GCP & Ring and vendor, the next host and RTU IP-1 each range will give, facilities by area.
- **IP Generation**: Generate shows a preview only. Save re-checks everything on the server; if anything changed meanwhile, nothing is saved and a new preview is shown.
- **IP Management**: search, Modify (shows old vs new IPs before saving), Delete (to Trash: name and IPs stay reserved), Restore, Delete forever, Change log.
- **Worksheet**: the full table; Export Excel; Import Excel in two steps (preview, then confirm); Undo last import.
- **Settings** (admin panel): add GCP & Rings, plan and activate address blocks, add vendors and facilities, warning level, admin password.

### Address blocks
New facilities always come from the **active block** of a GCP & Ring + vendor. When it is full, generation stops; nothing overflows by itself.
Plan the next block in Settings, prepare the network, then press **Activate now**: the old block becomes *retired* (its addresses stay reserved).

### Import rules (each row is checked on its own)
Name format or placeholder (`Used`, `unknown`, `-`, empty); name and device IPs unique against active rows, trashed rows and earlier rows of the same file,
in any column; IPv4 octets 0-255 (leading zeros normalised); no device on a gateway/laptop address or on the network/broadcast address; valid mask; VLAN 1-4094.
Import only adds rows and never changes existing records. Unknown or empty extra columns and other sheets (for example "Backend") are ignored.

## Backup
```bash
python backup.py
```
writes `backend/backups/ipgen-DATE.sql` (needs `mysqldump`). The Excel export is the second backup.

## Tests
```bash
pip install -r requirements-dev.txt
pytest                       # 70 tests: engine, API, security, concurrency, import/export, admin panel
ruff check app tests
```
Run the same tests on MySQL: set `TEST_DATABASE_URL=mysql+pymysql://user:pass@localhost/ipgen_test?charset=utf8mb4` (an empty test database).
Browser tests (Node + Playwright, server running on an empty database): `BASE=http://localhost:8000 ADMIN_PASS=... node e2e/e2e.js`

## Safety rules for this repository
- Never commit real IPs, device names, rules or screenshots. Real rules are entered in **Settings** and live only in your database.
- Never commit `.env` or database files (already in `.gitignore`).

More: [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md), [docs/decisions.md](docs/decisions.md).
