# IP Generator and Tracker (front-end prototype, TEST rules and dummy data)

Open `index.html` in Edge or Chrome (not a private window), or run it from localhost:
`python -m http.server 8000` then open http://localhost:8000

Pages: **Dashboard**, **IP Generation**, **IP Management**, **Worksheet**. `test.html` runs the engine self-test (41 tests).
Sized for 13-14" laptops first; works on iPad and phone. Dates are always English digits (`YYYY-MM-DD`).
Data is stored in this browser only (IndexedDB). Export Excel regularly as a backup.
This prototype will later move to a server and database (full stack); `js/engine.js` has no UI or storage code so it can be ported.

## How it works
- **Your name**: the tool uses one shared account, so each engineer types their own name (top-right button). It is kept for the browser session and written to the change log with every change.
- **Dashboard**: free host numbers per GCP & Ring and vendor, the next host and RTU IP-1 each range will give, facilities by area, new facilities per month, recent activity. Click a range to open IP Generation with it pre-selected.
- **IP Generation**: Generate shows a preview only; Save re-checks everything and stores it. If anything changed meanwhile, nothing is saved and a new preview is shown.
- **IP Management**: Modify shows exactly which IPs change (old vs new) before saving. Delete moves a record to the Trash; its name and IPs stay reserved until **Delete forever**.
- **Worksheet import** is two steps: a preview (will add / will skip / notes, with reasons), then Confirm. It only adds rows and never changes existing records. **Undo last import** removes exactly those rows while none of them has been changed.

## Import checks (per row)
- Name `FACILITY-NUMBER` (or placeholder `Used`, `unknown`, `-`, empty, which may repeat); unique against active rows, trashed rows and earlier rows of the same file.
- IPv4 with octets 0-255 (leading zeros are normalised, e.g. `018.1.20.07` -> `18.1.20.7`, so duplicates cannot hide).
- Device IPs (RTU, PLC, Internal, HMI, Moxa) must not repeat anywhere (any column, any record), must not repeat inside the same row, must not be a gateway/laptop address, and must not be the network or broadcast address of the subnet.
- Subnet mask must be a valid mask; VLANs must be 1-4094; text length caps (name 40, GCP 40, vendor 30, engineer 40, others 30).
- Notes (row is still added): unconfigured GCP or vendor, IPs that do not follow the current rule, VLANs that differ from the GCP, non-ISO dates.

Try it with `data/sample-data.xlsx`: 10 rows are added (2 with notes) and 3 are skipped on purpose.

## Rules
Edit `js/config.js` for GCP & Ring, octets, VLANs, vendors, capacity and facilities; `js/engine.js` for the address formulas.

## Safety notes
- Use dummy numbers and names only. Check every real IP in the field (ping/arp) before use.
- Every change runs in one storage transaction, so two open tabs cannot overwrite each other.
- SheetJS (xlsx 0.18.5, Apache-2.0) is in `lib/`. That version has known weaknesses when it opens untrusted files, so import only files you trust. The full-stack version will read Excel on the server instead.
- The pages block all network requests (Content-Security-Policy).
