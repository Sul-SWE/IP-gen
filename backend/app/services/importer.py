"""Excel import (preview -> confirm -> undo last) and export. Import only ever adds rows."""

from __future__ import annotations

import io
import json
import re
import secrets
import time
import zipfile
from datetime import date

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import engine as E
from ..config import Settings
from ..errors import ApiError, bad, conflict
from ..models import Record
from . import records as RS
from . import rules as R

REQUIRED = ("Facility Name", "RTU IP-1")
ALIASES = {"name": "Facility Name", "facility": "Facility Name", "gcp": "GCP & Ring", "gcpring": "GCP & Ring",
           "engineer": "TSU PAN Engineer", "tsupanengineer": "TSU PAN Engineer"}
MAX_UNZIPPED = 60 * 1024 * 1024
PREVIEW_TTL = 30 * 60
_previews: dict[str, dict] = {}      # token -> parsed file, kept in memory between preview and confirm


def _key(s: object) -> str:
    return re.sub(r"[^a-z0-9]", "", ("" if s is None else str(s)).lower().replace("&", "and"))


_KNOWN = {**{_key(c): c for c in E.COLUMNS}, **ALIASES}


def _header_map(row: tuple) -> dict[int, str]:
    out: dict[int, str] = {}
    for i, cell in enumerate(row):
        col = _KNOWN.get(_key(cell))
        if col and col not in out.values():
            out[i] = col
    return out


def parse_xlsx(data: bytes, filename: str, cfg: Settings) -> tuple[list[tuple[int, dict]], int, str]:
    """Read the data sheet. Returns (rows as (excel line, {column: value}), known column count, sheet name)."""
    if not re.search(r"\.xlsx$", filename or "", re.I):
        raise bad("Please choose an Excel file (.xlsx). Older .xls files: open in Excel and use Save As .xlsx. Nothing was imported.", code="wrong_type")
    if len(data) > cfg.max_import_bytes:
        raise ApiError(413, "too_large", "This file is larger than 5 MB. Nothing was imported.")
    if not data:
        raise bad("This file is empty. Nothing was imported.", code="empty_file")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                raise bad("This file is too large when unpacked. Nothing was imported.", code="too_large")
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except ApiError:
        raise
    except Exception:
        raise bad("This file could not be read. It may be damaged or not a real Excel file. Nothing was imported.", code="unreadable") from None
    try:
        for ws in wb.worksheets:
            head_line, hmap, rows = 0, {}, []
            for line, raw in enumerate(ws.iter_rows(values_only=True), start=1):
                if not hmap:
                    if line > 15:
                        break
                    m = _header_map(raw)
                    if all(c in m.values() for c in REQUIRED):
                        head_line, hmap = line, m
                    continue
                if all(v is None or str(v).strip() == "" for v in raw):
                    continue
                if len(rows) >= cfg.max_import_rows:
                    raise bad(f"The sheet has more than {cfg.max_import_rows} rows. Split it into smaller files. Nothing was imported.", code="too_many_rows")
                rows.append((line, {col: raw[i] if i < len(raw) else None for i, col in hmap.items()}))
            if head_line:
                if not rows:
                    raise bad("No data rows were found under the column names. Nothing was imported.", code="no_rows")
                return rows, len(hmap), ws.title
    finally:
        wb.close()
    raise bad("No sheet has the column names Facility Name and RTU IP-1 in its first rows. "
              "Use the same column names as an exported file. Nothing was imported.", code="wrong_columns")


def _short(items: list[str], limit: int = 4) -> list[str]:
    return items[:limit] + ([f"and {len(items) - limit} more"] if len(items) > limit else [])


def preview(db: Session, data: bytes, filename: str, cfg: Settings) -> dict:
    rows, ncols, sheet = parse_xlsx(data, filename, cfg)
    rules = R.load(db)
    results = E.check_import_rows(rows, RS.build_index(db), rules.import_config())
    add = [r for r in results if r.record]
    for k in [k for k, v in _previews.items() if time.time() - v["at"] > PREVIEW_TTL]:
        _previews.pop(k, None)
    token = secrets.token_urlsafe(24)
    _previews[token] = {"rows": rows, "filename": filename[:80], "expected": [(r.line, r.record["name"]) for r in add], "at": time.time()}
    issues = [{"line": r.line, "name": r.name or "(empty)", "add": bool(r.record), "reasons": _short(r.warnings if r.record else r.errors)}
              for r in results if not r.record or r.warnings]
    return {"token": token, "filename": filename[:80], "sheet": sheet, "rows": len(rows), "columns": ncols,
            "will_add": len(add), "will_skip": len(results) - len(add), "with_notes": sum(1 for r in add if r.warnings),
            "issues": issues[:300], "issues_total": len(issues)}


def confirm(db: Session, token: str, actor: str) -> dict:
    """Write the previewed rows. Caller holds the write lock."""
    who = RS._person(actor, "Your name")
    pv = _previews.get(token)
    if not pv or time.time() - pv["at"] > PREVIEW_TTL:
        raise conflict("This import preview has expired. Choose the file again.", code="preview_expired")
    rules = R.load(db)
    eblocks = rules.engine_blocks()
    results = E.check_import_rows(pv["rows"], RS.build_index(db), rules.import_config())
    add = [r for r in results if r.record]
    if [(r.line, r.record["name"]) for r in add] != pv["expected"]:
        _previews.pop(token, None)
        raise conflict("The stored data changed after the preview (another change was saved). Nothing was imported. "
                       "Import the file again to see a new preview.", code="preview_changed")
    if not add:
        raise bad("No row of this file can be imported. Nothing was imported.", code="nothing_to_import")
    now, batch = R.now(), "imp-" + secrets.token_hex(8)
    for res in add:
        rec = res.record
        placeholder = E.is_placeholder(rec["name"]) or rec["name"] == "UNKNOWN"
        blk_id, host = None, None
        for b in eblocks:
            if b.gcp == rec["gcp"] and b.vendor == rec["vendor"]:
                n = E.rule_host(b, rec["ips"])
                if n:
                    blk_id, host = b.block_id, n
                    break
        r = Record(name=rec["name"], name_key=None if placeholder else rec["name"].lower(), gcp_code=rec["gcp"], vendor=rec["vendor"],
                   block_id=blk_id, host_no=host, engineer_name=rec["engineer"], record_date=rec["date"], status="active",
                   import_batch_id=batch, version=1, created_at=now, updated_at=now)
        RS._set_ips(r, rec["ips"])
        db.add(r)
    RS._flush(db)
    skipped = [r for r in results if not r.record]
    info = {"batch": batch, "file": pv["filename"], "at": RS.fmt(now), "who": who, "count": len(add)}
    R.set_setting(db, "last_import", json.dumps(info)[:255])
    RS.add_log(db, who, "Imported", f"{len(add)} row(s)", f"From {pv['filename']}; {len(skipped)} row(s) skipped", batch)
    _previews.pop(token, None)
    return {"imported": len(add), "skipped": len(skipped), "filename": pv["filename"],
            "skipped_rows": [{"line": r.line, "name": r.name or "no name", "reasons": _short(r.errors, 2)} for r in skipped[:15]]}


def last_import(db: Session) -> dict | None:
    raw = R.get_setting(db, "last_import", "")
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except ValueError:
        return None
    rows = db.scalars(select(Record).where(Record.import_batch_id == info["batch"])).all()
    why = ""
    if len(rows) < info["count"]:
        why = f"{info['count'] - len(rows)} of its rows were deleted forever"
    else:
        changed = [r.name for r in rows if r.version != 1 or r.status != "active"]
        if changed:
            why = "these rows were changed since: " + ", ".join(changed[:5]) + (f" +{len(changed) - 5}" if len(changed) > 5 else "")
    return {**info, "can_undo": not why, "why": why}


def undo_last(db: Session, actor: str, batch: str | None = None) -> dict:
    who = RS._person(actor, "Your name")
    info = last_import(db)
    if not info or (batch and batch != info["batch"]):
        raise conflict("There is no import to undo, or another import happened meanwhile. Nothing was removed.", code="no_import")
    if not info["can_undo"]:
        raise conflict(f"The last import cannot be undone: {info['why']}. Undo only works while every imported row is unchanged.", code="import_changed")
    for r in db.scalars(select(Record).where(Record.import_batch_id == info["batch"])).all():
        db.delete(r)
    R.set_setting(db, "last_import", "")
    db.flush()
    RS.add_log(db, who, "Import undone", f"{info['count']} row(s)", f"Removed the rows imported from {info['file']} on {info['at']}", info["batch"])
    return {"removed": info["count"], "filename": info["file"]}


def export_xlsx(db: Session) -> tuple[bytes, str, int]:
    """All active records with the worksheet columns. Cells are written as text, never as formulas."""
    wb = Workbook()
    ws = wb.active
    ws.title = "IPs"
    ws.append(list(E.COLUMNS))
    n = 0
    for r in db.scalars(select(Record).where(Record.status == "active").order_by(Record.id)):
        ips = RS.ips_of(r)
        ws.append([r.name, r.gcp_code, r.vendor, r.record_date, r.engineer_name] + [ips.get(f, "") for f in E.ALL_FIELDS])
        n += 1
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.data_type = "s"            # text only: a cell starting with = is never treated as a formula
    for i, col in enumerate(E.COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(len(col) + 2, 16 if col in E.IP_FIELDS else 13)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(E.COLUMNS))}{n + 1}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"IP-Generator-{date.today().isoformat()}.xlsx", n
