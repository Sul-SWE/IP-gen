# API (prefix `/api`, JSON)

Errors: `{"error": "code", "message": "text", "details": ["..."]}` with status 400 / 401 / 403 / 404 / 409 / 413 / 422 / 429.
Admin endpoints need the session cookie; every POST / PATCH / DELETE also needs the header `X-CSRF-Token` (from `/auth/me` or `/auth/login`).
Interactive documentation while the server runs: `/api/docs`.

| Method and path | Purpose | Who |
|---|---|---|
| GET `/auth/me` | role (`viewer` / `admin`), CSRF token | all |
| POST `/auth/login` `{username, password, force?}` | sign in; `409 admin_busy` when another admin is active | all |
| POST `/auth/logout`, POST `/auth/password` `{current, new}` | sign out, change password | admin |
| GET `/config` | enabled facilities, GCP & Rings, vendors, columns | all |
| GET `/dashboard`, GET `/ranges` | dashboard numbers; usage per range | all |
| GET `/records?q=&field=&status=&page=&size=&sort=` | list / search (`field`: all, name, gcp, vendor, engineer, ip; `status`: active, trash, all) | all |
| POST `/generate/preview` `{facility, well, gcp, vendor, engineer}` | compute, store nothing; returns `signature` | admin |
| GET `/names/check?name=` | is a name free | admin |
| POST `/records` (preview body + `signature`) | save; `409 preview_changed` + new preview | admin |
| POST `/records/{id}/edit-preview` `{gcp, vendor}` | new IPs a network change would give | admin |
| PATCH `/records/{id}` `{version, actor, name?, engineer?, date?, gcp?, vendor?, signature?}` | modify | admin |
| DELETE `/records/{id}` `{version, actor}` | move to trash | admin |
| POST `/records/{id}/restore`, DELETE `/records/{id}/permanent` `{version, actor}` | restore, delete forever | admin |
| GET `/engineers/suggest?q=`, GET `/audit-log?q=&page=` | name suggestions, change log | admin |
| POST `/import/preview` (multipart `file`) | check a sheet, store nothing; returns `token` | admin |
| POST `/import/confirm` `{token, actor}`, GET `/import/last`, POST `/import/undo-last` `{actor, batch?}` | import flow | admin |
| GET `/export` | `.xlsx` of active records | admin |
| GET `/admin/rules` | everything for the Settings page | admin |
| POST `/admin/facilities`, PATCH `/admin/facilities/{id}` | add, enable/disable | admin |
| POST `/admin/gcps`, PATCH `/admin/gcps/{id}` | add (creates first blocks), VLAN / enable | admin |
| POST `/admin/vendors/check`, POST `/admin/vendors`, PATCH `/admin/vendors/{id}` | validate, add, enable/disable | admin |
| POST `/admin/blocks`, POST `/admin/blocks/{id}/activate`, DELETE `/admin/blocks/{id}` | plan, activate, remove planned | admin |
| PATCH `/admin/settings` `{warn_at, actor}` | warning level (percent) | admin |
