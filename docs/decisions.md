# Decisions and changes to SRS v1.0

Agreed with the project owner during implementation. Where this file and the SRS differ, this file wins.

| # | Topic | SRS v1.0 | Decision |
|---|---|---|---|
| 1 | Database | SQLite | **MySQL / MariaDB** (allowed-technology list). SQLite still works for a quick trial and for fast tests. |
| 2 | Viewer | Read-only account with password | **No sign-in.** Anyone who can open the site sees Dashboard and Worksheet (`VIEWER_CAN_SEE_WORKSHEET=false` hides the worksheet). Admin endpoints answer 401 without an admin session. |
| 3 | Admin sessions | Not specified | **One admin at a time.** A second sign-in gets `409 admin_busy`; "Sign in anyway" ends the other session, whose next request gets `401 session_replaced`. An admin idle for `ADMIN_IDLE_MINUTES` (default 5) no longer blocks. |
| 4 | Engineer name | Typed, with suggestions | Kept: typed once per browser session, suggested from earlier names, written to the change log. No engineer list in configuration. |
| 5 | Range full | Block, no overflow | Kept, plus **address blocks**: each GCP & Ring + vendor has blocks (`planned`, `active`, `retired`). The admin plans the next block ahead and activates it by hand; the retired block stays reserved. A third octet belongs to at most one block per GCP & Ring (database constraint). |
| 6 | Old rules moved to another octet | Not covered | Imported records keep their addresses as they are (reserved). Only the active block gives new addresses ("new only; old is retired"). |
| 7 | Vendor rules | Fixed in code | **Data-driven**: every address is `host = a*n + b` on network slot A, B or M. Both seed vendors fit this exactly. New vendors are added in Settings after an automatic safety check (hosts 1-254, no repeats, never a gateway/laptop address). Rules are not editable once created. |
| 8 | Admin settings screen | Optional | **Built** (Settings page): GCP & Rings, blocks, vendors, facilities, warning level, admin password. Every change is logged as "Settings changed". |
| 9 | Excel reading | SheetJS in the browser / openpyxl | **Server only (openpyxl)**; `.xlsx` only. Old `.xls` files must be saved as `.xlsx` (adding an `.xls` reader would need another dependency). |
| 10 | Import checks | Name, duplicates, octets | Added: same IP twice in one row, device IP equal to a gateway/laptop address, network/broadcast address, mask validity, VLAN 1-4094, leading zeros normalised. Notes (not blocking): unconfigured GCP/vendor, IPs not following a rule, VLAN mismatch, non-ISO date. |
| 11 | Sheet layout | First sheet, header in row 1 | First sheet **that has the columns** `Facility Name` and `RTU IP-1` within its first 15 rows; other sheets (e.g. "Backend") and unknown/empty columns are ignored. |
| 12 | Optimistic locking | "never overwrite newer data" | Each record has a `version`; modify/delete/restore/purge must send it, otherwise `409 stale`. All writes also take one global row lock, so two changes never interleave. |
| 13 | Delete forever | Admin, with confirmation | Only for records already in the Trash. |
| 14 | Dashboard | KPI + capacity bars + vendor donut | Range matrix (GCP & Ring x vendor) with used/max and **next host + RTU IP-1**, free host numbers, facilities by area split by vendor, per month, recent activity. |
| 15 | Rate limit / import previews | - | Kept in server memory (single process). Use one worker process, which is also what `run.py` starts. |

Open question for the owner: in the Yokogawa rule the Moxa address is on network `P.10.x`, which has no gateway field of its own. Confirm this matches the field.
