# Architecture

```
Browser (frontend/: HTML + CSS + JS, no inline scripts)
        |  fetch /api/...  (same origin, session cookie, X-CSRF-Token)
FastAPI app (backend/app)
  main.py        app factory, security headers (CSP), error format, serves frontend/
  api.py         all REST routes; public reads, admin writes
  auth.py        argon2 passwords, server-side sessions, one admin at a time, CSRF, login rate limit
  schemas.py     Pydantic request bodies (unknown fields rejected, lengths capped)
  engine.py      PURE rule engine: build, allocate, validate rules, IPv4 helpers, import-row checks
  services/
    rules.py     facilities, GCP & Rings, vendors, blocks (stored in the database)
    records.py   preview, save, modify, trash, restore, purge, search
    importer.py  Excel preview / confirm / undo, export
    dashboard.py numbers for the dashboard
  models.py      tables;  db.py  engine, sessions, write lock;  defaults.py  seed rules (dummy)
MySQL / MariaDB (migrations in backend/migrations)
```

## How duplicates are made impossible
1. **Global write lock.** Every state-changing request first locks one row (`settings.write_lock`, `SELECT ... FOR UPDATE`; `BEGIN IMMEDIATE` on SQLite). Changes therefore run one after another and each "check, then insert" sees the newest data (`READ COMMITTED`).
2. **Recompute on save.** Save sends the signature of the preview the engineer saw. The server recomputes inside the transaction; a different result answers `409 preview_changed` with the new preview.
3. **Database constraints** as the last line of defence: `records.name_key` UNIQUE (lower-case name; NULL for placeholders), `ip_assignments.uniq_ip` UNIQUE (device IPs of active *and* trashed records; NULL for shared gateway/laptop IPs), `block_octets (gcp_id, octet3)` UNIQUE, `gcp_rings (octet1, octet2)` UNIQUE.
4. **Record versions.** Modify / delete / restore / purge carry the record `version`; a stale one answers `409 stale`.
5. **One admin session** at a time.

## Allocation
For n = 1..capacity of the active block: build the addresses; if none of the device IPs is used by any record (active or trashed) as a device or gateway/laptop address, take n. Otherwise skip and report n. No free n: the range is full.

## Security
argon2 password hash; secrets only in `.env`; `HttpOnly` + `SameSite=Strict` session cookie (`Secure` with `COOKIE_SECURE=true`); CSRF token header on every change; login rate limit; strict input validation; ORM queries only (search wildcards escaped); output escaped in the UI plus a Content-Security-Policy without inline scripts; no CORS unless origins are listed; import limits (type, 5 MB, 5000 rows, unpacked size); Excel export writes text cells only (no formulas); errors never expose internals.

## Performance (measured with 5,000 records on MariaDB, development machine)
| Request | Median |
|---|---|
| List page, 100 rows | 28 ms |
| Search, all fields | 94 ms |
| Search by IP | 31 ms |
| Worksheet page, 200 rows | 42 ms |
| Generate preview | 149 ms |
| Dashboard | 250 ms |
| Import 5,000 rows | preview 1.2 s, confirm 4.7 s |

Usage and allocation load all assigned IPs once per request; listing and search are paginated SQL queries.
