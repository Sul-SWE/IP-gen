# IP Address Auto-Generator and Management Platform

A web tool that generates, checks and tracks the IP addresses of RTU / PLC devices from fixed rules, instead of typing them by hand in Excel.
It prevents duplicate IPs, shows how full every address range is, and keeps a change log.
**All rules and addresses here are dummy test values.** Always verify a real IP in the field (ping / arp) before using it.

**Technology:** HTML, CSS, JavaScript and Chart.js (pages) · PHP 8 (server) · MySQL / MariaDB (database) · runs on **XAMPP**.

## Run it (XAMPP)
1. XAMPP Control Panel: **Start** Apache and MySQL.
2. Copy this folder to `C:\xampp\htdocs\IP-gen`.
3. Open **http://localhost/IP-gen/**.
4. First time only, the setup page opens: MySQL user `root`, password empty, database `ipgen`, and a password for the website admin.
5. Sign in with user **admin** and that password.

## How it works
```
Browser (pages)  -->  api/index.php (PHP)  -->  MySQL
HTML/CSS/JS          rules and checks          the data
```
1. A page (for example IP Generation) sends a request to `api/index.php`.
2. PHP reads the used addresses from MySQL and applies the rules (first free host number).
3. The result goes back to the page. On **Save**, PHP checks everything again before writing, so an IP can never repeat.

## Users
- **Viewer**: opens the site and sees the Dashboard and the Worksheet. No sign-in, read only.
- **Admin** (user `admin`): generates, modifies, deletes, imports/exports and changes the rules. Only one admin works at a time;
  each engineer types their own name, which is written to the change log.

## Project files
| Path | What it is |
|---|---|
| `index.html` | Dashboard: numbers, address ranges, charts |
| `generate.html` | IP Generation: form, preview, save |
| `management.html` | IP Management: search, modify, delete, restore, change log |
| `worksheet.html` | Worksheet: full table, Excel import / export |
| `settings.html` | Admin panel: GCP & Rings, address blocks, vendors, facilities, password |
| `login.html`, `setup.html` | Admin sign-in, first-time setup |
| `css/style.css` | The look of every page |
| `js/util.js`, `js/api.js`, `js/common.js` | Shared helpers, the connection to the server, the page frame (menu, dialogs) |
| `js/pages/*.js` | The behaviour of each page (one file per page) |
| `lib/chart.umd.min.js` | Chart.js library used by the dashboard charts |
| `api/index.php` | The single entry point of the server: every request from the pages comes here |
| `server/Api.php` | Routes and input checks: which request does what |
| `server/Engine.php` | **The rules**: builds the addresses, finds the first free host number, checks Excel rows |
| `server/Records.php` | Create, modify, delete to trash, restore, delete forever, search |
| `server/Rules.php` | GCP & Rings, vendors, facilities and address blocks (the Settings page) |
| `server/Importer.php`, `server/Xlsx.php` | Excel import (preview, confirm, undo) and export |
| `server/Dashboard.php` | The numbers for the dashboard |
| `server/Auth.php` | Admin sign-in, one admin at a time, protection of requests |
| `server/Db.php`, `server/bootstrap.php` | Database connection; loading of the server files |
| `server/config.example.php` | Layout of `config.php`, which the setup page creates (MySQL login) |
| `database/ipgen.sql` | **The database**: all tables and the starting rules |
| `database/sample-data.xlsx` | Sample sheet to try the import (10 rows added, 3 rejected on purpose) |
| `tests/engine_test.php` | Automatic check of the rules (28 tests): `php tests/engine_test.php` |
| `.htaccess` (root, `server/`, `database/`, `tests/`) | Security: server files, settings and tests can never be opened from the browser |

## Database (`database/ipgen.sql`)
| Table | Holds |
|---|---|
| `records` | One row per facility (name, GCP & Ring, vendor, engineer, date, status active / trash) |
| `ip_assignments` | The IPs of each record. A UNIQUE column makes a duplicate device IP impossible |
| `gcp_rings`, `vendors`, `blocks`, `block_octets`, `facilities` | The rules (changed from the Settings page) |
| `audit_log` | The change log (who, what, when) |
| `accounts`, `sessions`, `login_failures` | Admin sign-in |
| `settings` | Warning level, subnet mask, last import |

The setup page runs this file automatically. It can also be imported by hand in phpMyAdmin.

## How duplicates are prevented
1. **First free host number:** the engine skips every number whose IPs are already used (active records and records in the trash).
2. **Check again on Save:** if anything changed since the preview, nothing is saved and a new preview is shown.
3. **One change at a time:** every change locks the data briefly, so two saves can never take the same number.
4. **Database rule:** the `ip_assignments.uniq_ip` column is UNIQUE, so MySQL itself refuses a duplicate.

## Address blocks
Every GCP & Ring + vendor has an **active block** of host numbers. When it is full, generation stops (no automatic overflow).
The admin plans the next block in Settings, prepares the network, then presses **Activate now**; the old block is retired and its addresses stay reserved.

## Backup
Worksheet > **Export Excel**, or phpMyAdmin > database `ipgen` > Export.

## Never commit
Real IPs, device names or rules, and `server/config.php` (it holds the MySQL password; already in `.gitignore`).
