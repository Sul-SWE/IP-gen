# IP Generator and Tracker (prototype, TEST rules and dummy data)

Open `index.html` in Edge or Chrome (not a private window). Pages: Main (dashboard), IP Generation, IP Management, Worksheet. `test.html` runs the self-test.
Works on PC, iPad and phone. Dates are always written in English digits (YYYY-MM-DD).
Data is stored in the browser (IndexedDB). Use Worksheet > Export Excel regularly as a backup.
If data seems to disappear after moving the folder, run it from localhost: `python -m http.server 8000` then open http://localhost:8000
Rules, GCP&Ring list, ranges, engineers: edit `js/config.js` (and `js/engine.js` for the formulas).
Try Worksheet > Import Excel with `data/sample-data.xlsx`: 8 rows are valid, the last is rejected on purpose (duplicate IPs).

## Safety notes
- Use dummy numbers only. Check every real IP in the field (ping/arp) before use.
- Every change runs in one storage transaction, so two open tabs cannot overwrite each other.
- Import accepts .xlsx/.xls up to 5 MB and 5000 rows, checks names and IPs (0-255), and escapes all text.
- SheetJS (xlsx 0.18.5, Apache-2.0) is in `lib/`. That version has known weaknesses when it opens untrusted files, so import only files you trust.
- The pages block all network requests (Content-Security-Policy).
