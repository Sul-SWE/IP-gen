"""Numbers for the dashboard."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import engine as E
from ..models import AuditLog, Record
from . import records as RS
from . import rules as R

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def ranges(db: Session, rules: R.Rules | None = None) -> list[dict]:
    """Usage of the active block of every GCP & Ring + vendor (trashed records count as used)."""
    rules = rules or R.load(db)
    busy = RS.build_index(db).busy
    out = []
    for g in rules.gcps:
        if not g.active:
            continue
        for v in rules.vendors:
            if not v.active:
                continue
            mine = [b for b in rules.blocks if b.gcp_id == g.id and b.vendor_id == v.id]
            blk = next((b for b in mine if b.status == "active"), None)
            item = {"gcp": g.code, "vendor": v.name, "prefix": f"{g.octet1}.{g.octet2}", "rtu_vlan": g.rtu_vlan, "plc_vlan": g.plc_vlan,
                    "planned": any(b.status == "planned" for b in mine), "retired": sum(1 for b in mine if b.status == "retired"),
                    "block_seq": blk.seq if blk else 0, "used": 0, "max": 0, "next": 0, "next_rtu": "", "state": "none"}
            if blk:
                eb = R.to_engine_block(blk, rules.mask)
                used, cap, nxt = E.usage(eb, busy)
                item.update(used=used, max=cap, next=nxt, next_rtu=E.build(eb, nxt).get("RTU IP-1", "") if nxt else "",
                            state="full" if used >= cap else "warn" if used / cap >= rules.warn_at else "ok")
            out.append(item)
    return out


def dashboard(db: Session) -> dict:
    rules = R.load(db)
    rng = ranges(db, rules)
    active = db.execute(select(Record.name, Record.vendor, Record.record_date).where(Record.status == "active")).all()
    c = RS.counts(db)
    today = date.today()
    cut = (today - timedelta(days=30)).isoformat()
    used, total = sum(r["used"] for r in rng), sum(r["max"] for r in rng)
    attention = [f"{r['gcp']} / {r['vendor']}" + (" (full)" if r["state"] == "full" else "") for r in rng if r["state"] in ("warn", "full")]

    areas: dict[str, dict[str, int]] = {code: {} for code in rules.active_facility_codes}
    vendor_names = [v.name for v in rules.vendors]
    vendor_totals: dict[str, int] = {}
    for name, vendor, _ in active:
        parts = E.split_name(name)
        area = parts[0] if parts and parts[0] in rules.facility_codes else "Other"
        ven = vendor if vendor in vendor_names else "Other"
        areas.setdefault(area, {})
        areas[area][ven] = areas[area].get(ven, 0) + 1
        vendor_totals[ven] = vendor_totals.get(ven, 0) + 1

    months = []
    y, m = today.year, today.month
    for i in range(5, -1, -1):
        yy, mm = y, m - i
        while mm < 1:
            yy, mm = yy - 1, mm + 12
        key = f"{yy}-{mm:02d}"
        months.append({"key": key, "label": MONTHS[mm - 1],
                       "count": sum(1 for _, _, d in active if E.is_iso_date(d) and d.startswith(key))})

    recent = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(5)).all()
    return {
        "kpis": {"active": c["active"], "trash": c["trash"], "used": used, "total": total, "free": total - used,
                 "recent30": sum(1 for _, _, d in active if E.is_iso_date(d) and d >= cut), "since": cut,
                 "attention": attention, "any_full": any(r["state"] == "full" for r in rng)},
        "warn_at": rules.warn_at,
        "ranges": rng,
        "vendors": vendor_names,
        "areas": [{"area": a, "by_vendor": v, "total": sum(v.values())} for a, v in areas.items()],
        "vendor_totals": vendor_totals,
        "months": months,
        "recent": [{"at": RS.fmt(x.at), "who": x.engineer_name, "action": x.action, "name": x.record_name, "details": x.details} for x in recent],
    }
