# Architecture

```
Browser: index.html, generate.html, management.html, worksheet.html, settings.html, login.html, setup.html
         css/, js/ (util.js, api.js, common.js, pages/*.js)  -- no inline scripts, strict CSP
        |  fetch api/index.php/<route>   (same origin, session cookie, X-CSRF-Token header)
api/index.php            single entry point
server/ (never served: .htaccess "Require all denied")
  bootstrap.php          PHP settings, extension check, loads the classes
  Api.php                routes, input validation, security headers, error format, first-run setup
  Auth.php               password_hash (bcrypt), server-side sessions, one admin at a time, CSRF, login rate limit (table)
  Engine.php             PURE rule engine: build, allocate, rule safety check, IPv4 helpers, import-row checks
  Rules.php              facilities, GCP & Rings, vendors, blocks (stored in the database)
  Records.php            preview, save, modify, trash, restore, purge, search
  Importer.php           Excel preview (stored in server/storage/previews) / confirm / undo, export
  Xlsx.php               minimal .xlsx reader and writer (zip + XML), no library
  Dashboard.php          numbers for the dashboard
  Db.php                 PDO wrapper, transactions, global write lock, API error type
  schema.sql, defaults.php (dummy seed rules), config.example.php, dev-router.php (php -S)
MySQL / MariaDB (InnoDB, utf8mb4)
```

## How duplicates are made impossible
1. **Global write lock.** Every state-changing request runs in one transaction that first locks one row (`settings.write_lock`, `SELECT ... FOR UPDATE`). Changes therefore run one after another and each "check, then insert" sees the newest data (`READ COMMITTED`).
2. **Recompute on save.** Save sends the signature of the preview the engineer saw. The server recomputes inside the transaction; a different result answers `409 preview_changed` with the new preview.
3. **Database constraints** as the last line of defence: `records.name_key` UNIQUE (lower-case name; NULL for placeholders), `ip_assignments.uniq_ip` UNIQUE (device IPs of active *and* trashed records; NULL for shared gateway/laptop IPs), `block_octets (gcp_id, octet3)` UNIQUE, `gcp_rings (octet1, octet2)` UNIQUE.
4. **Record versions.** Modify / delete / restore / purge carry the record `version`; a stale one answers `409 stale`.
5. **One admin session** at a time.

## Allocation
For n = 1..capacity of the active block: build the addresses; if none of the device IPs is used by any record (active or trashed) as a device or gateway/laptop address, take n. Otherwise skip and report n. No free n: the range is full.

## Time
All timestamps come from MySQL `NOW()`, i.e. the clock of the computer running the database, so PHP's time-zone setting does not matter.

## Security
bcrypt password hash; MySQL password only in `server/config.php` (not served, not committed); `HttpOnly` + `SameSite=Strict` cookie scoped to the tool's folder (`Secure` with `cookie_secure`); CSRF token header on every change; login rate limit; strict input validation (unknown fields rejected, lengths capped); prepared statements only (search wildcards escaped); output escaped in the UI plus a Content-Security-Policy without inline scripts; setup only from the server computer itself (localhost) and only while not configured; import limits (type, 5 MB, 5000 rows, unpacked size); Excel export writes text cells only (no formulas); errors never expose internals (details go to `server/storage/error.log`).

## Verification
- `tests/engine_test.php`: 28 engine tests. The PHP engine was also compared with the earlier Python engine on 404 address builds, 314 rule checks and 400 random import batches: identical, except that whole numbers in notes are printed `1800` instead of `1800.0`.
- `tests/api/`: 49 HTTP tests (permissions, validation, duplicates incl. trash and cross-column, full range, 409 on changed preview, trash/restore/purge, edit with regeneration, placeholder and imported records, one admin at a time, CSRF, rate limit, cookie flags, 12 parallel saves, import/export round trip, file problems, admin panel, setup).
- `e2e/e2e.js`: 54 browser checks, run on PHP's built-in server and on Apache in a sub-folder (like XAMPP `htdocs/IP-gen`).

## Performance (5,000 records, Apache + MariaDB, development machine)
| Request | Median |
|---|---|
| List page, 100 rows | 8 ms |
| Search, all fields | 93 ms |
| Search by IP | 28 ms |
| Worksheet page, 200 rows | 10 ms |
| Generate preview | 41 ms |
| Dashboard | 64 ms |
| Export 5,000 rows | 230 ms |
| Import 5,000 rows | preview 0.4 s, confirm 2.2 s |
