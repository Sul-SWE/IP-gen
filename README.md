# IP Address Auto-Generator and Management Platform

Generates, checks and tracks the IP addresses of RTU / PLC devices from fixed rules, instead of typing them by hand in Excel.
**All rules and addresses in this repository are dummy test values.** Always verify a real IP in the field (ping / arp) before using it.

| Part | Technology |
|---|---|
| Pages (project root) | HTML, CSS, JavaScript (no framework) |
| Server (`api/`, `server/`) | PHP 8.0+ (no Composer, no extra libraries) |
| Database | MySQL / MariaDB (the one in XAMPP works) |
| Excel | read and written by the server in plain PHP (`.xlsx`) |
| `prototype/` | the earlier browser-only prototype, kept as reference |

## Who uses it
- **Viewer**: opens the site and sees the Dashboard and the Worksheet. No sign-in, read only.
- **Admin**: signs in (user `admin`) to generate, modify, delete, import/export and change the rules.
  **Only one admin can be signed in at a time**; a second sign-in is told so and may take over (the first session ends).
  Because the account is shared, each engineer types their own name; it is written to the change log with every change.

## Run it with XAMPP (Windows)
1. Open the **XAMPP Control Panel** and press **Start** next to **Apache** and **MySQL**.
2. Copy the project folder into `C:\xampp\htdocs\` so that you have `C:\xampp\htdocs\IP-gen\index.html`.
3. Open **http://localhost/IP-gen/** in the browser.
4. The first time, the **setup page** opens: MySQL user `root`, password empty (XAMPP default), database `ipgen`,
   then choose the website admin password. It creates the database, the tables, the default (dummy) rules and the admin account,
   and saves `server/config.php`.
5. Sign in with user **admin** and the password you chose.

Next time: start Apache and MySQL in XAMPP, then open http://localhost/IP-gen/.
To run setup again (for example a new MySQL password), delete `server/config.php`. Existing data is kept.

Other web servers: any Apache with PHP 8.0+ and `AllowOverride All` (for the `.htaccess` files) works.
Without Apache: `php -S localhost:8000 server/dev-router.php` in the project folder, then open http://localhost:8000.
To let colleagues on the same network use it, give them `http://YOUR-PC-NAME/IP-gen/` (ask IT first; use HTTPS and
`'cookie_secure' => true` in `server/config.php` on a real server).

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
Export Excel regularly (Worksheet page). Full database backup: phpMyAdmin (http://localhost/phpmyadmin) > database `ipgen` > Export,
or `C:\xampp\mysql\bin\mysqldump -u root ipgen > ipgen-backup.sql`.

## Tests
- Engine: `php tests/engine_test.php` (28 tests).
- API (49 tests, Python + pytest, server running with `php -S 127.0.0.1:8030 server/dev-router.php`):
  `pip install pytest httpx pymysql openpyxl` then `pytest tests/api` (settings: `PHP_BASE`, `TEST_DB_USER`, `TEST_DB_PASS`, `TEST_DB_NAME`).
- Browser (Node + Playwright, no `server/config.php`, empty database):
  `BASE=http://localhost/IP-gen/ ADMIN_PASS=... DB_USER=root DB_PASS= DB_NAME=ipgen_e2e node e2e/e2e.js`

## Safety rules for this repository
- Never commit real IPs, device names, rules or screenshots. Real rules are entered in **Settings** and live only in your database.
- Never commit `server/config.php` (it holds the MySQL password; already in `.gitignore`).

More: [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md), [docs/decisions.md](docs/decisions.md).
The earlier Python (FastAPI) server is in the git history (commit `c0c5440`).
