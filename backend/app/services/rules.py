"""Rules stored in the database: facilities, GCP & Rings, vendors and address blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import defaults
from .. import engine as E
from ..errors import bad, conflict, not_found
from ..models import Block, BlockOctet, Facility, GcpRing, Setting, Vendor

GCP_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{1,39}$")
VENDOR_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _\-]{1,29}$")


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def get_setting(db: Session, name: str, default: str = "") -> str:
    row = db.get(Setting, name)
    return row.value if row else default


def set_setting(db: Session, name: str, value: str) -> None:
    row = db.get(Setting, name)
    if row:
        row.value = value
    else:
        db.add(Setting(name=name, value=value))


def warn_at(db: Session) -> float:
    try:
        return float(get_setting(db, "warn_at", "0.9"))
    except ValueError:
        return 0.9


def mask(db: Session) -> str:
    return get_setting(db, "subnet_mask", "255.255.255.0")


def vendor_rule(v: Vendor) -> E.VendorRule:
    return E.VendorRule(v.name, v.capacity, tuple(E.FieldRule(f["field"], f["net"], int(f["a"]), int(f["b"])) for f in v.fields))


def to_engine_block(b: Block, subnet_mask: str) -> E.Block:
    g = b.gcp
    return E.Block(g.code, g.octet1, g.octet2, {k: int(v) for k, v in b.octets.items()}, vendor_rule(b.vendor),
                   g.rtu_vlan, g.plc_vlan, subnet_mask, b.id)


@dataclass
class Rules:
    facilities: list[Facility]
    gcps: list[GcpRing]
    vendors: list[Vendor]
    blocks: list[Block]
    mask: str
    warn_at: float

    @property
    def facility_codes(self) -> set[str]:
        return {f.code for f in self.facilities}

    @property
    def active_facility_codes(self) -> list[str]:
        return [f.code for f in self.facilities if f.active]

    def active_block(self, gcp_code: str, vendor_name: str) -> Block | None:
        for b in self.blocks:
            if b.status == "active" and b.gcp.code == gcp_code and b.vendor.name == vendor_name and b.gcp.active and b.vendor.active:
                return b
        return None

    def engine_blocks(self) -> list[E.Block]:
        return [to_engine_block(b, self.mask) for b in self.blocks]

    def import_config(self) -> E.ImportConfig:
        return E.ImportConfig(
            facilities=self.facility_codes,
            blocks=self.engine_blocks(),
            gcps={g.code: (g.rtu_vlan, g.plc_vlan) for g in self.gcps},
            vendors={v.name for v in self.vendors},
            mask=self.mask,
        )


def load(db: Session) -> Rules:
    return Rules(
        facilities=list(db.scalars(select(Facility).order_by(Facility.id))),
        gcps=list(db.scalars(select(GcpRing).order_by(GcpRing.id))),
        vendors=list(db.scalars(select(Vendor).order_by(Vendor.id))),
        blocks=list(db.scalars(select(Block).order_by(Block.gcp_id, Block.vendor_id, Block.seq))),
        mask=mask(db),
        warn_at=warn_at(db),
    )


# ---------------------------------------------------------------- seeding
def seed_defaults(db: Session) -> bool:
    """First run only: copy the default (dummy) rules into the database."""
    if db.get(Setting, "write_lock") is None:
        db.add(Setting(name="write_lock", value="1"))
    for k, v in defaults.SETTINGS.items():
        if db.get(Setting, k) is None:
            db.add(Setting(name=k, value=v))
    db.flush()
    if db.scalar(select(GcpRing.id).limit(1)) is not None or db.scalar(select(Vendor.id).limit(1)) is not None:
        return False
    for code in defaults.FACILITIES:
        db.add(Facility(code=code))
    vendors = [Vendor(name=v["name"], capacity=v["capacity"], octets=dict(v["octets"]), fields=list(v["fields"])) for v in defaults.VENDORS]
    gcps = [GcpRing(code=c, octet1=o1, octet2=o2, rtu_vlan=rv, plc_vlan=pv) for c, o1, o2, rv, pv in defaults.GCP_RINGS]
    db.add_all(vendors + gcps)
    db.flush()
    for g in gcps:
        for v in vendors:
            _create_block(db, g, v, dict(v.octets), "active")
    return True


# ---------------------------------------------------------------- blocks
def _used_octets(v: Vendor, octets: dict) -> dict[str, int]:
    nets = {f["net"] for f in v.fields}
    try:
        return {n: int(octets[n]) for n in sorted(nets)}
    except (KeyError, TypeError, ValueError):
        raise bad(f"Give a third octet (0 to 255) for each network of {v.name}: {', '.join(sorted(nets))}.") from None


def _create_block(db: Session, g: GcpRing, v: Vendor, octets: dict, status: str) -> Block:
    octs = _used_octets(v, octets)
    errors = E.validate_rule(vendor_rule(v), octs)
    if errors:
        raise bad(f"The block for {g.code} / {v.name} is not valid.", errors)
    taken = {o.octet3: o.block_id for o in db.scalars(select(BlockOctet).where(BlockOctet.gcp_id == g.id))}
    clash = sorted(o for o in octs.values() if o in taken)
    if clash:
        raise conflict(f"In {g.code}, third octet {', '.join(map(str, clash))} already belongs to another block. Choose octets that are not used in this GCP & Ring.")
    seq = 1 + max((b.seq for b in db.scalars(select(Block).where(Block.gcp_id == g.id, Block.vendor_id == v.id))), default=0)
    blk = Block(gcp_id=g.id, vendor_id=v.id, seq=seq, status=status, octets=octs, created_at=now(),
                activated_at=now() if status == "active" else None)
    blk.gcp, blk.vendor = g, v
    db.add(blk)
    db.flush()
    db.add_all([BlockOctet(gcp_id=g.id, octet3=o, block_id=blk.id) for o in octs.values()])
    db.flush()
    return blk


def add_planned_block(db: Session, gcp_id: int, vendor_id: int, octets: dict) -> Block:
    g, v = db.get(GcpRing, gcp_id), db.get(Vendor, vendor_id)
    if not g or not v:
        raise not_found("GCP & Ring or vendor not found.")
    existing = list(db.scalars(select(Block).where(Block.gcp_id == g.id, Block.vendor_id == v.id)))
    if any(b.status == "planned" for b in existing):
        raise conflict(f"{g.code} / {v.name} already has a planned block. Activate or remove it first.")
    return _create_block(db, g, v, octets, "planned" if any(b.status == "active" for b in existing) else "active")


def activate_block(db: Session, block_id: int) -> tuple[Block, Block | None]:
    blk = db.get(Block, block_id)
    if not blk:
        raise not_found("Block not found.")
    if blk.status != "planned":
        raise conflict("Only a planned block can be activated.")
    old = db.scalar(select(Block).where(Block.gcp_id == blk.gcp_id, Block.vendor_id == blk.vendor_id, Block.status == "active"))
    if old:
        old.status = "retired"
    blk.status, blk.activated_at = "active", now()
    db.flush()
    return blk, old


def remove_planned_block(db: Session, block_id: int) -> Block:
    blk = db.get(Block, block_id)
    if not blk:
        raise not_found("Block not found.")
    if blk.status != "planned":
        raise conflict("Only a planned block can be removed. Active and retired blocks keep their addresses reserved.")
    db.delete(blk)
    db.flush()
    return blk


# ---------------------------------------------------------------- GCP & Ring, vendors, facilities
def _vlan(value: object, label: str) -> str:
    s = str(value).strip()
    if not re.fullmatch(r"\d{1,4}", s) or not 1 <= int(s) <= 4094:
        raise bad(f"{label} must be a number from 1 to 4094.")
    return str(int(s))


def add_gcp(db: Session, code: str, octet1: int, octet2: int, rtu_vlan: object, plc_vlan: object) -> GcpRing:
    code = str(code).strip().upper()
    if not GCP_CODE_RE.match(code):
        raise bad("The GCP & Ring code must be 2 to 40 characters: capital letters, digits, dash or underscore (for example HDGCP2-R1).")
    if not (1 <= octet1 <= 223 and octet1 != 127 and 0 <= octet2 <= 255):
        raise bad("Octet 1 must be 1 to 223 (not 127) and octet 2 must be 0 to 255.")
    if db.scalar(select(GcpRing).where(GcpRing.code == code)):
        raise conflict(f"The GCP & Ring {code} already exists.")
    other = db.scalar(select(GcpRing).where(GcpRing.octet1 == octet1, GcpRing.octet2 == octet2))
    if other:
        raise conflict(f"{octet1}.{octet2}.x.x is already used by {other.code}. Two GCP & Rings cannot share the same first two octets.")
    g = GcpRing(code=code, octet1=octet1, octet2=octet2, rtu_vlan=_vlan(rtu_vlan, "RTU VLAN"), plc_vlan=_vlan(plc_vlan, "PLC VLAN"))
    db.add(g)
    db.flush()
    for v in db.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.id)):
        _create_block(db, g, v, dict(v.octets), "active")
    return g


def update_gcp(db: Session, gcp_id: int, rtu_vlan: object | None, plc_vlan: object | None, active: bool | None) -> GcpRing:
    g = db.get(GcpRing, gcp_id)
    if not g:
        raise not_found("GCP & Ring not found.")
    if rtu_vlan is not None:
        g.rtu_vlan = _vlan(rtu_vlan, "RTU VLAN")
    if plc_vlan is not None:
        g.plc_vlan = _vlan(plc_vlan, "PLC VLAN")
    if active is not None:
        g.active = active
    db.flush()
    return g


def parse_vendor(name: str, capacity: int, octets: dict, fields: list[dict]) -> tuple[E.VendorRule, dict[str, int]]:
    name = E.clean_person(name)
    if not VENDOR_NAME_RE.match(name):
        raise bad("The vendor name must be 2 to 30 characters: letters, digits, spaces, dash or underscore, starting with a letter.")
    try:
        frs = tuple(E.FieldRule(str(f["field"]), str(f["net"]).upper(), int(f["a"]), int(f["b"])) for f in fields)
        octs = {str(k).upper(): int(v) for k, v in octets.items()}
    except (KeyError, TypeError, ValueError):
        raise bad("Every field needs a network (A, B or M) and whole numbers for the formula.") from None
    rule = E.VendorRule(name, int(capacity), frs)
    used = {f.net for f in frs}
    errors = E.validate_rule(rule, {k: v for k, v in octs.items() if k in used})
    if errors:
        raise bad("This vendor rule is not safe.", errors)
    return rule, {k: v for k, v in octs.items() if k in used}


def add_vendor(db: Session, name: str, capacity: int, octets: dict, fields: list[dict]) -> Vendor:
    rule, octs = parse_vendor(name, capacity, octets, fields)
    if db.scalar(select(Vendor).where(Vendor.name == rule.name)):
        raise conflict(f"The vendor {rule.name} already exists.")
    v = Vendor(name=rule.name, capacity=rule.capacity, octets=octs,
               fields=[{"field": f.field, "net": f.net, "a": f.a, "b": f.b} for f in rule.fields])
    db.add(v)
    db.flush()
    for g in db.scalars(select(GcpRing).where(GcpRing.active.is_(True)).order_by(GcpRing.id)):
        _create_block(db, g, v, dict(octs), "active")
    return v


def set_vendor_active(db: Session, vendor_id: int, active: bool) -> Vendor:
    v = db.get(Vendor, vendor_id)
    if not v:
        raise not_found("Vendor not found.")
    v.active = active
    db.flush()
    return v


def add_facility(db: Session, code: str) -> Facility:
    code = str(code).strip().upper()
    if not E.FACILITY_CODE_RE.match(code):
        raise bad("A facility code must be 2 to 8 characters: capital letters or digits, starting with a letter (for example UTMN).")
    if db.scalar(select(Facility).where(Facility.code == code)):
        raise conflict(f"The facility {code} already exists.")
    f = Facility(code=code)
    db.add(f)
    db.flush()
    return f


def set_facility_active(db: Session, facility_id: int, active: bool) -> Facility:
    f = db.get(Facility, facility_id)
    if not f:
        raise not_found("Facility not found.")
    f.active = active
    db.flush()
    return f
