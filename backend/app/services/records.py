"""Records: preview, save, modify, trash, restore, delete forever, search.

Every state-changing function expects the caller to have taken the write lock (db.lock_writes) first,
so the checks below always run on the newest data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import engine as E
from ..errors import ApiError, bad, conflict, not_found
from ..models import AuditLog, IpAssignment, Record
from . import rules as R

GONE = "That record was changed or removed elsewhere, so nothing was done. The list has been refreshed."


# ---------------------------------------------------------------- helpers
def ips_of(r: Record) -> dict[str, str]:
    vals = {a.field: a.ip for a in r.ips}
    vals.update({k: v for k, v in (r.shared_fields or {}).items() if v})
    return {f: vals[f] for f in E.ALL_FIELDS if f in vals}


def fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def serialize(r: Record) -> dict:
    return {
        "id": r.id, "name": r.name, "gcp": r.gcp_code, "vendor": r.vendor, "engineer": r.engineer_name,
        "date": r.record_date, "status": r.status, "version": r.version, "host": r.host_no, "block_id": r.block_id,
        "ips": ips_of(r), "created_at": fmt(r.created_at), "updated_at": fmt(r.updated_at),
        "deleted_at": fmt(r.deleted_at), "deleted_by": r.deleted_by, "imported": bool(r.import_batch_id),
    }


def build_index(db: Session, exclude_id: int | None = None) -> E.Index:
    """Every name and IP in use by active and trashed records (optionally ignoring one record)."""
    idx = E.Index()
    names: dict[int, str] = {}
    for rid, name, key, status in db.execute(select(Record.id, Record.name, Record.name_key, Record.status)).all():
        names[rid] = name
        if rid != exclude_id and key:
            idx.names[name.upper()] = "trash" if status == "trash" else "active"
    device, infra, uniq = idx.device, idx.infra, set(E.UNIQ)
    for rid, fld, ip in db.execute(select(IpAssignment.record_id, IpAssignment.field, IpAssignment.ip)).all():
        if rid != exclude_id:
            (device if fld in uniq else infra)[ip] = names.get(rid, "")
    return idx


def add_log(db: Session, engineer: str, action: str, name: str, details: str = "", batch: str | None = None) -> None:
    db.add(AuditLog(at=R.now(), role="admin", engineer_name=engineer[:40], action=action, record_name=name[:90],
                    details=details, import_batch_id=batch))


def signature(name: str, ips: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps([name, ips], sort_keys=True).encode()).hexdigest()[:32]


def _set_ips(r: Record, ips: dict[str, str]) -> None:
    r.ips = [IpAssignment(field=f, ip=ips[f], uniq_ip=ips[f] if f in E.UNIQ else None) for f in E.IP_FIELDS if ips.get(f)]
    r.shared_fields = {f: ips[f] for f in E.SHARED_TEXT if ips.get(f)}


def _person(value: object, label: str) -> str:
    name = E.clean_person(value)
    err = E.check_person(name)
    if err:
        raise bad(f"{label}: {err}", code="invalid_person")
    return name


def _flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:   # the database constraints are the last line of defence
        raise conflict("A name or IP of this record already exists. Nothing was saved; refresh and try again.") from exc


def _name_error(name: str, idx: E.Index) -> str:
    where = idx.names.get(name.upper())
    return f"The name {name} already exists{' (in the trash)' if where == 'trash' else ''}." if where else ""


def get(db: Session, record_id: int) -> Record:
    r = db.get(Record, record_id)
    if not r:
        raise not_found(GONE)
    return r


def _check_version(r: Record, version: int | None) -> None:
    if version is None or r.version != version:
        raise conflict(GONE, code="stale")


# ---------------------------------------------------------------- generation
def preview_new(db: Session, facility: str, well: str, gcp: str, vendor: str, engineer: str) -> dict:
    """Compute the record a save would create. Stores nothing."""
    rules = R.load(db)
    idx = build_index(db)
    well = str(well).strip()
    if not well.isascii() or not well.isdigit() or not 1 <= len(well) <= 5:
        raise bad("Type the well number (1 to 5 digits).", code="invalid_name")
    name = f"{str(facility).strip().upper()}-{well}"
    err = E.name_format_error(name, set(rules.active_facility_codes)) or _name_error(name, idx)
    if err:
        raise (conflict(err, code="name_exists") if "exists" in err else bad(err, code="invalid_name"))
    blk = rules.active_block(gcp, vendor)
    if blk is None:
        raise bad("Choose a valid GCP & Ring and vendor.", code="invalid_range")
    eng = _person(engineer, "TSU PAN Engineer")
    eblock = R.to_engine_block(blk, rules.mask)
    busy = idx.busy
    try:
        alloc = E.allocate(eblock, busy)
    except E.RangeFull:
        raise conflict(f"{gcp} / {vendor} is full ({eblock.capacity} of {eblock.capacity} host numbers used). Nothing was generated. "
                       "Choose another GCP & Ring, or ask the admin to activate the next block in Settings.", code="range_full") from None
    problems = E.check_ips(alloc.ips, idx)
    if problems:   # cannot happen when allocation is correct; kept as a guard
        raise conflict("The generated addresses conflict with existing records.", problems, code="ip_conflict")
    used, cap, _ = E.usage(eblock, busy)
    after = used + 1
    return {
        "name": name, "gcp": gcp, "vendor": vendor, "engineer": eng, "date": date.today().isoformat(),
        "host": alloc.n, "capacity": cap, "skipped": alloc.skipped, "ips": alloc.ips, "block_id": blk.id,
        "used_after": after, "warn": after / cap >= rules.warn_at, "full_after": after >= cap,
        "signature": signature(name, alloc.ips),
    }


def create(db: Session, facility: str, well: str, gcp: str, vendor: str, engineer: str, expected: str) -> Record:
    p = preview_new(db, facility, well, gcp, vendor, engineer)
    if p["signature"] != expected:
        raise conflict("The addresses changed since your preview (another change was saved meanwhile). "
                       "Check the new preview and press Save again.", code="preview_changed", extra={"preview": p})
    now = R.now()
    r = Record(name=p["name"], name_key=p["name"].lower(), gcp_code=gcp, vendor=vendor, block_id=p["block_id"], host_no=p["host"],
               engineer_name=p["engineer"], record_date=p["date"], status="active", version=1, created_at=now, updated_at=now)
    _set_ips(r, p["ips"])
    db.add(r)
    _flush(db)
    add_log(db, p["engineer"], "Created", r.name, f"{gcp} / {vendor}, host {p['host']}, RTU IP-1 {p['ips'].get('RTU IP-1', '-')}")
    return r


# ---------------------------------------------------------------- modify
def regen_preview(db: Session, r: Record, gcp: str, vendor: str) -> dict:
    """What changing GCP & Ring / vendor would do to this record's IPs."""
    if gcp == r.gcp_code and vendor == r.vendor:
        return {"regen": False}
    rules = R.load(db)
    blk = rules.active_block(gcp, vendor)
    if blk is None:
        raise bad(f"{gcp} / {vendor} is not configured, so new IPs cannot be generated. "
                  "Keep the current GCP & Ring and vendor, or choose configured ones.", code="invalid_range")
    idx = build_index(db, exclude_id=r.id)
    eblock = R.to_engine_block(blk, rules.mask)
    try:
        alloc = E.allocate(eblock, idx.busy)
    except E.RangeFull:
        raise conflict(f"{gcp} / {vendor} is full. Nothing can be generated there.", code="range_full") from None
    return {"regen": True, "host": alloc.n, "ips": alloc.ips, "old_ips": ips_of(r), "block_id": blk.id,
            "signature": signature(r.name, alloc.ips)}


def update(db: Session, record_id: int, version: int | None, actor: str, *, name: str | None, engineer: str | None,
           record_date: str | None, gcp: str | None, vendor: str | None, expected: str | None) -> tuple[Record, bool]:
    r = get(db, record_id)
    _check_version(r, version)
    if r.status != "active":
        raise conflict("This record is in the trash. Restore it before modifying it.", code="stale")
    who = _person(actor, "Your name")
    rules = R.load(db)
    changes: list[str] = []

    new_name = r.name if name is None else str(name).strip().upper()
    if new_name != r.name:
        allowed = set(rules.active_facility_codes)
        cur = E.split_name(r.name)
        if cur:
            allowed.add(cur[0])
        err = E.name_format_error(new_name, allowed) or _name_error(new_name, build_index(db, exclude_id=r.id))
        if err:
            raise (conflict(err, code="name_exists") if "exists" in err else bad(err, code="invalid_name"))
        changes.append(f"Name {r.name} -> {new_name}")

    new_eng = r.engineer_name if engineer is None else E.clean_person(engineer)
    if new_eng != E.clean_person(r.engineer_name):
        _person(new_eng, "Engineer on record")
        changes.append(f"Engineer {r.engineer_name or '-'} -> {new_eng}")

    new_date = r.record_date if record_date is None else str(record_date).strip()
    if new_date != r.record_date:
        if not E.is_iso_date(new_date):
            raise bad(f"The date must be a real date written as YYYY-MM-DD, for example {date.today().isoformat()}.", code="invalid_date")
        changes.append(f"Date {r.record_date or '-'} -> {new_date}")

    new_gcp = r.gcp_code if gcp is None else gcp
    new_vendor = r.vendor if vendor is None else vendor
    plan = regen_preview(db, r, new_gcp, new_vendor)
    if plan["regen"]:
        if plan["signature"] != expected:
            raise conflict("The free addresses changed while the dialog was open. Nothing was changed; open Modify again to see the new IPs.",
                           code="preview_changed")
        parts = []
        if new_gcp != r.gcp_code:
            parts.append(f"GCP & Ring {r.gcp_code or '-'} -> {new_gcp}")
        if new_vendor != r.vendor:
            parts.append(f"Vendor {r.vendor or '-'} -> {new_vendor}")
        parts.append(f"new IPs (host {plan['host']}, RTU IP-1 {plan['ips'].get('RTU IP-1', '-')})")
        changes.append("; ".join(parts))

    if not changes:
        raise bad("Nothing was changed.", code="nothing_changed")

    old_name = r.name
    if plan["regen"]:
        r.ips.clear()
        db.flush()                       # release the old addresses before taking the new ones
        _set_ips(r, plan["ips"])
        r.gcp_code, r.vendor, r.block_id, r.host_no = new_gcp, new_vendor, plan["block_id"], plan["host"]
    if new_name != r.name:
        r.name, r.name_key = new_name, new_name.lower()
    r.engineer_name, r.record_date = new_eng, new_date
    r.version += 1
    r.updated_at = R.now()
    _flush(db)
    add_log(db, who, "Modified", old_name + (f" -> {new_name}" if new_name != old_name else ""), "; ".join(changes))
    return r, plan["regen"]


# ---------------------------------------------------------------- trash, restore, delete forever
def trash(db: Session, record_id: int, version: int | None, actor: str) -> Record:
    r = get(db, record_id)
    _check_version(r, version)
    who = _person(actor, "Your name")
    if r.status == "trash":
        raise conflict(GONE, code="stale")
    r.status, r.deleted_at, r.deleted_by = "trash", R.now(), who
    r.version += 1
    r.updated_at = r.deleted_at
    db.flush()
    rtu = next((a.ip for a in r.ips if a.field == "RTU IP-1"), "-")
    add_log(db, who, "Deleted", r.name, f"Moved to trash; RTU IP-1 {rtu} stays reserved")
    return r


def restore(db: Session, record_id: int, version: int | None, actor: str) -> Record:
    r = get(db, record_id)
    _check_version(r, version)
    who = _person(actor, "Your name")
    if r.status != "trash":
        raise conflict(GONE, code="stale")
    idx = build_index(db, exclude_id=r.id)
    problems = ([_name_error(r.name, idx)] if r.name_key and _name_error(r.name, idx) else []) + E.check_ips(ips_of(r), idx)
    if problems:
        raise conflict(f"Cannot restore {r.name}.", problems, code="restore_conflict")
    r.status, r.deleted_at, r.deleted_by = "active", None, ""
    r.version += 1
    r.updated_at = R.now()
    db.flush()
    add_log(db, who, "Restored", r.name, "Back in the active list")
    return r


def purge(db: Session, record_id: int, version: int | None, actor: str) -> str:
    r = get(db, record_id)
    _check_version(r, version)
    who = _person(actor, "Your name")
    if r.status != "trash":
        raise conflict("Move the record to the trash first. Only records in the trash can be deleted forever.", code="not_in_trash")
    rtu = next((a.ip for a in r.ips if a.field == "RTU IP-1"), "-")
    name = r.name
    db.delete(r)
    db.flush()
    add_log(db, who, "Deleted forever", name, f"Name and IPs freed; RTU IP-1 was {rtu}")
    return name


# ---------------------------------------------------------------- search
def _like(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


SEARCH_FIELDS = ("all", "name", "gcp", "vendor", "engineer", "ip")


def search(db: Session, q: str = "", field: str = "all", status: str = "active", page: int = 1, size: int = 100,
           newest_first: bool = False) -> dict:
    if field not in SEARCH_FIELDS:
        raise ApiError(422, "invalid", "Unknown search field.")
    if status not in ("active", "trash", "all"):
        raise ApiError(422, "invalid", "Unknown status.")
    conds = []
    if status != "all":
        conds.append(Record.status == status)
    q = q.strip()[:60]
    if q:
        pat = _like(q.lower())
        ip_match = select(IpAssignment.id).where(IpAssignment.record_id == Record.id, IpAssignment.ip.like(pat, escape="\\")).exists()
        by = {
            "name": func.lower(Record.name).like(pat, escape="\\"),
            "gcp": func.lower(Record.gcp_code).like(pat, escape="\\"),
            "vendor": func.lower(Record.vendor).like(pat, escape="\\"),
            "engineer": func.lower(Record.engineer_name).like(pat, escape="\\"),
            "ip": ip_match,
        }
        conds.append(or_(*by.values(), Record.record_date.like(pat, escape="\\")) if field == "all" else by[field])
    total = db.scalar(select(func.count()).select_from(Record).where(*conds)) or 0
    size = max(1, min(size, 500))
    pages = max(1, -(-total // size))
    page = max(1, min(page, pages))
    order = (Record.deleted_at.desc(), Record.id.desc()) if status == "trash" else (Record.id.desc(),) if newest_first else (Record.id,)
    rows = db.scalars(select(Record).where(*conds).order_by(*order).offset((page - 1) * size).limit(size)).all()
    return {"items": [serialize(r) for r in rows], "total": total, "page": page, "pages": pages, "size": size}


def counts(db: Session) -> dict:
    rows = dict(db.execute(select(Record.status, func.count()).group_by(Record.status)).all())
    return {"active": rows.get("active", 0), "trash": rows.get("trash", 0), "log": db.scalar(select(func.count()).select_from(AuditLog)) or 0}


def suggest_engineers(db: Session, q: str = "", limit: int = 12) -> list[str]:
    q = E.clean_person(q).lower()
    names: set[str] = set()
    for col in (Record.engineer_name, AuditLog.engineer_name):
        for (n,) in db.execute(select(col).distinct()):
            n = E.clean_person(n)
            if n and not E.check_person(n) and q in n.lower():
                names.add(n)
    return sorted(names, key=str.lower)[:limit]
