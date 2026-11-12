"""REST API (prefix /api). Read-only endpoints are public (viewer); everything else needs the admin session + CSRF token."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import auth
from . import engine as E
from . import schemas as S
from .db import lock_writes
from .errors import ApiError, bad
from .models import AuditLog, AuthSession, Block
from .services import dashboard as D
from .services import importer as X
from .services import records as RS
from .services import rules as R

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- dependencies
def get_db(request: Request) -> Iterator[Session]:
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.rollback()   # routes commit explicitly; anything left is discarded
        db.close()


def cfg(request: Request):
    return request.app.state.settings


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def optional_admin(request: Request, db: Session = Depends(get_db)) -> AuthSession | None:
    return auth.session_for(db, cfg(request), request.cookies.get(auth.COOKIE))


def require_admin(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    sess = auth.session_for(db, cfg(request), request.cookies.get(auth.COOKIE))
    if sess is None:
        raise ApiError(401, "login_required", "Sign in as admin to do this.")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not auth.csrf_ok(sess, request.headers.get("X-CSRF-Token")):
        raise ApiError(403, "csrf", "The page is out of date. Reload it and try again.")
    return sess


def actor_of(value: str) -> str:
    return RS._person(value, "Your name")


def _set_cookie(resp: Response, request: Request, token: str) -> None:
    c = cfg(request)
    resp.set_cookie(auth.COOKIE, token, max_age=c.session_hours * 3600, httponly=True, samesite="strict", secure=c.cookie_secure, path="/")


# ---------------------------------------------------------------- session
@router.get("/auth/me")
def me(request: Request, sess: AuthSession | None = Depends(optional_admin), db: Session = Depends(get_db)):
    c = cfg(request)
    if sess is None:
        return {"role": "viewer", "viewer_can_see_worksheet": c.viewer_can_see_worksheet}
    return {"role": "admin", "csrf": sess.csrf, "session_hours": c.session_hours, "viewer_can_see_worksheet": True}


@router.post("/auth/login")
def login(body: S.LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    token, sess = auth.login(db, cfg(request), request.app.state.limiter, body.username, body.password, client_ip(request), body.force)
    db.commit()
    _set_cookie(response, request, token)
    return {"role": "admin", "csrf": sess.csrf}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth.logout(db, request.cookies.get(auth.COOKIE))
    db.commit()
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.post("/auth/password")
def password(body: S.PasswordIn, sess: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    auth.change_password(db, sess, body.current, body.new)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- public (viewer) reads
@router.get("/config")
def config(request: Request, db: Session = Depends(get_db)):
    rules = R.load(db)
    return {
        "facilities": rules.active_facility_codes,
        "gcps": [g.code for g in rules.gcps if g.active],
        "vendors": [v.name for v in rules.vendors if v.active],
        "warn_at": rules.warn_at, "mask": rules.mask,
        "columns": list(E.COLUMNS), "ip_columns": list(E.IP_FIELDS) + ["Subnet Mask"],
        "viewer_can_see_worksheet": cfg(request).viewer_can_see_worksheet,
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return D.dashboard(db)


@router.get("/ranges")
def ranges(db: Session = Depends(get_db)):
    return {"ranges": D.ranges(db)}


@router.get("/records")
def list_records(request: Request, q: str = Query("", max_length=60), field: str = "all", status: str = "active",
                 page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=500), sort: str = "old",
                 sess: AuthSession | None = Depends(optional_admin), db: Session = Depends(get_db)):
    if sess is None and not cfg(request).viewer_can_see_worksheet:
        raise ApiError(403, "forbidden", "The worksheet is only available to the admin.")
    out = RS.search(db, q, field, status, page, size, newest_first=sort == "new")
    out["counts"] = RS.counts(db)
    return out


# ---------------------------------------------------------------- generation and records (admin)
@router.post("/generate/preview")
def generate_preview(body: S.GenerateIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    return RS.preview_new(db, body.facility, body.well, body.gcp, body.vendor, body.engineer)


@router.get("/names/check")
def name_check(name: str = Query(max_length=40), _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    where = RS.build_index(db).names.get(name.strip().upper())
    return {"available": where is None, "where": where or ""}


@router.post("/records", status_code=201)
def create_record(body: S.SaveIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    lock_writes(db)
    r = RS.create(db, body.facility, body.well, body.gcp, body.vendor, body.engineer, body.signature)
    db.commit()
    return RS.serialize(r)


@router.get("/records/{record_id}")
def get_record(record_id: int, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    return RS.serialize(RS.get(db, record_id))


@router.post("/records/{record_id}/edit-preview")
def edit_preview(record_id: int, body: S.EditPreviewIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    return RS.regen_preview(db, RS.get(db, record_id), body.gcp, body.vendor)


@router.patch("/records/{record_id}")
def update_record(record_id: int, body: S.UpdateIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    lock_writes(db)
    r, regen = RS.update(db, record_id, body.version, body.actor, name=body.name, engineer=body.engineer, record_date=body.date,
                         gcp=body.gcp, vendor=body.vendor, expected=body.signature)
    db.commit()
    return {**RS.serialize(r), "regenerated": regen}


@router.delete("/records/{record_id}")
def trash_record(record_id: int, body: S.Acting, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    lock_writes(db)
    r = RS.trash(db, record_id, body.version, body.actor)
    db.commit()
    return RS.serialize(r)


@router.post("/records/{record_id}/restore")
def restore_record(record_id: int, body: S.Acting, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    lock_writes(db)
    r = RS.restore(db, record_id, body.version, body.actor)
    db.commit()
    return RS.serialize(r)


@router.delete("/records/{record_id}/permanent")
def purge_record(record_id: int, body: S.Acting, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    lock_writes(db)
    name = RS.purge(db, record_id, body.version, body.actor)
    db.commit()
    return {"name": name}


@router.get("/engineers/suggest")
def engineers(q: str = Query("", max_length=40), _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    return {"names": RS.suggest_engineers(db, q)}


@router.get("/audit-log")
def audit_log(q: str = Query("", max_length=60), page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=200),
              _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    conds = []
    if q.strip():
        pat = RS._like(q.strip().lower())
        conds.append(or_(*[func.lower(c).like(pat, escape="\\") for c in (AuditLog.engineer_name, AuditLog.action, AuditLog.record_name, AuditLog.details)]))
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conds)) or 0
    pages = max(1, -(-total // size))
    page = min(page, pages)
    rows = db.scalars(select(AuditLog).where(*conds).order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {"items": [{"at": RS.fmt(x.at), "role": x.role, "who": x.engineer_name, "action": x.action, "name": x.record_name,
                       "details": x.details} for x in rows], "total": total, "page": page, "pages": pages, "counts": RS.counts(db)}


# ---------------------------------------------------------------- Excel (admin)
@router.post("/import/preview")
async def import_preview(request: Request, file: UploadFile = File(...), _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    limit = cfg(request).max_import_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "too_large", "This file is larger than 5 MB. Nothing was imported.")
    return X.preview(db, data, file.filename or "", cfg(request))


@router.post("/import/confirm")
def import_confirm(body: S.ImportConfirmIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    lock_writes(db)
    out = X.confirm(db, body.token, body.actor)
    db.commit()
    return out


@router.get("/import/last")
def import_last(_: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    return {"last": X.last_import(db)}


@router.post("/import/undo-last")
def import_undo(body: S.UndoIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    lock_writes(db)
    out = X.undo_last(db, body.actor, body.batch)
    db.commit()
    return out


@router.get("/export")
def export(_: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    data, name, n = X.export_xlsx(db)
    if not n:
        raise bad("There are no active records to export.", code="nothing_to_export")
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Record-Count": str(n)})


# ---------------------------------------------------------------- settings / admin panel
def _block_json(b: Block) -> dict:
    return {"id": b.id, "seq": b.seq, "status": b.status, "octets": b.octets,
            "activated_at": RS.fmt(b.activated_at), "created_at": RS.fmt(b.created_at)}


@router.get("/admin/rules")
def admin_rules(_: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    rules = R.load(db)
    usage = {(r["gcp"], r["vendor"]): r for r in D.ranges(db, rules)}
    gcps = []
    for g in rules.gcps:
        rng = []
        for v in rules.vendors:
            blocks = [_block_json(b) for b in rules.blocks if b.gcp_id == g.id and b.vendor_id == v.id]
            u = usage.get((g.code, v.name), {})
            rng.append({"vendor": v.name, "vendor_id": v.id, "vendor_active": v.active, "blocks": blocks,
                        "used": u.get("used", 0), "max": u.get("max", 0), "state": u.get("state", "none")})
        gcps.append({"id": g.id, "code": g.code, "octet1": g.octet1, "octet2": g.octet2, "rtu_vlan": g.rtu_vlan,
                     "plc_vlan": g.plc_vlan, "active": g.active, "ranges": rng})
    return {
        "facilities": [{"id": f.id, "code": f.code, "active": f.active} for f in rules.facilities],
        "gcps": gcps,
        "vendors": [{"id": v.id, "name": v.name, "capacity": v.capacity, "octets": v.octets, "fields": v.fields, "active": v.active}
                    for v in rules.vendors],
        "settings": {"warn_at": round(rules.warn_at * 100), "mask": rules.mask},
        "ip_fields": list(E.IP_FIELDS), "device_fields": list(E.UNIQ), "infra_fields": list(E.INFRA), "nets": list(E.NETS),
    }


def _log(db: Session, who: str, what: str, details: str) -> None:
    RS.add_log(db, who, "Settings changed", what, details)


@router.post("/admin/facilities", status_code=201)
def add_facility(body: S.FacilityIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    f = R.add_facility(db, body.code)
    _log(db, who, f"Facility {f.code}", "Added")
    db.commit()
    return {"id": f.id, "code": f.code}


@router.patch("/admin/facilities/{facility_id}")
def patch_facility(facility_id: int, body: S.ActiveIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    f = R.set_facility_active(db, facility_id, body.active)
    _log(db, who, f"Facility {f.code}", "Enabled" if body.active else "Disabled for new records")
    db.commit()
    return {"id": f.id, "active": f.active}


@router.post("/admin/gcps", status_code=201)
def add_gcp(body: S.GcpIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    g = R.add_gcp(db, body.code, body.octet1, body.octet2, body.rtu_vlan, body.plc_vlan)
    _log(db, who, f"GCP & Ring {g.code}", f"Added: {g.octet1}.{g.octet2}.x.x, VLAN {g.rtu_vlan} / {g.plc_vlan}")
    db.commit()
    return {"id": g.id, "code": g.code}


@router.patch("/admin/gcps/{gcp_id}")
def patch_gcp(gcp_id: int, body: S.GcpUpdateIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    g = R.update_gcp(db, gcp_id, body.rtu_vlan, body.plc_vlan, body.active)
    parts = []
    if body.rtu_vlan is not None or body.plc_vlan is not None:
        parts.append(f"VLAN {g.rtu_vlan} / {g.plc_vlan} (applies to new records)")
    if body.active is not None:
        parts.append("Enabled" if body.active else "Disabled for new records")
    _log(db, who, f"GCP & Ring {g.code}", "; ".join(parts) or "No change")
    db.commit()
    return {"id": g.id}


def _vendor_sample(rule: E.VendorRule, octets: dict[str, int]) -> list[dict]:
    blk = E.Block("EXAMPLE", 10, 1, octets, rule)
    return [{"n": n, "ips": {k: v for k, v in E.build(blk, n).items() if k in E.IP_FIELDS}} for n in sorted({1, 2, rule.capacity})]


@router.post("/admin/vendors/check")
def check_vendor(body: S.VendorIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        rule, octs = R.parse_vendor(body.name, body.capacity, body.octets, [f.model_dump() for f in body.fields])
    except ApiError as e:
        return {"ok": False, "message": e.message, "errors": e.details}
    return {"ok": True, "errors": [], "sample": _vendor_sample(rule, octs)}


@router.post("/admin/vendors", status_code=201)
def add_vendor(body: S.VendorIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    v = R.add_vendor(db, body.name, body.capacity, body.octets, [f.model_dump() for f in body.fields])
    _log(db, who, f"Vendor {v.name}", f"Added: capacity {v.capacity}, third octets {v.octets}")
    db.commit()
    return {"id": v.id, "name": v.name}


@router.patch("/admin/vendors/{vendor_id}")
def patch_vendor(vendor_id: int, body: S.ActiveIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    v = R.set_vendor_active(db, vendor_id, body.active)
    _log(db, who, f"Vendor {v.name}", "Enabled" if body.active else "Disabled for new records")
    db.commit()
    return {"id": v.id, "active": v.active}


@router.post("/admin/blocks", status_code=201)
def add_block(body: S.BlockIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    b = R.add_planned_block(db, body.gcp_id, body.vendor_id, body.octets)
    _log(db, who, f"{b.gcp.code} / {b.vendor.name}", f"Block {b.seq} added as {b.status}, third octets {b.octets}")
    db.commit()
    return _block_json(b)


@router.post("/admin/blocks/{block_id}/activate")
def activate_block(block_id: int, body: S.ActorIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    b, old = R.activate_block(db, block_id)
    _log(db, who, f"{b.gcp.code} / {b.vendor.name}",
         f"Block {b.seq} activated (third octets {b.octets})" + (f"; block {old.seq} retired, its addresses stay reserved" if old else ""))
    db.commit()
    return _block_json(b)


@router.delete("/admin/blocks/{block_id}")
def delete_block(block_id: int, body: S.ActorIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    b = R.remove_planned_block(db, block_id)
    _log(db, who, f"{b.gcp.code} / {b.vendor.name}", f"Planned block {b.seq} removed")
    db.commit()
    return {"ok": True}


@router.patch("/admin/settings")
def patch_settings(body: S.SettingsIn, _: AuthSession = Depends(require_admin), db: Session = Depends(get_db)):
    who = actor_of(body.actor)
    lock_writes(db)
    R.set_setting(db, "warn_at", str(body.warn_at / 100))
    _log(db, who, "Warning threshold", f"Set to {body.warn_at}%")
    db.commit()
    return {"warn_at": body.warn_at}
