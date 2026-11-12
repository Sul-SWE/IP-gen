"""Rule engine: address generation, allocation and validation.

Pure module: no web, no database, no I/O. Everything it needs is passed in.
Messages returned to callers are plain text (the UI escapes them).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

# IPs that must never repeat across records (active or in the trash)
UNIQ = (
    "RTU IP-1", "RTU IP-2", "PLC IP-1", "PLC IP-2",
    "RTU Internal IP-1", "RTU Internal IP-2", "RTU-HMI IP", "IES Moxa IP",
)
# infrastructure addresses: shared by design, never given to a device
INFRA = ("Engg. Laptop IP", "Gateway-1", "Gateway-2")
IP_FIELDS = UNIQ + INFRA
SHARED_TEXT = ("Subnet Mask", "RTU VLAN", "PLC VLAN")
# worksheet / Excel order (FR-WS-2)
ALL_FIELDS = (
    "RTU IP-1", "RTU IP-2", "PLC IP-1", "PLC IP-2", "RTU Internal IP-1", "RTU Internal IP-2",
    "RTU-HMI IP", "Engg. Laptop IP", "IES Moxa IP", "Gateway-1", "Gateway-2",
    "Subnet Mask", "RTU VLAN", "PLC VLAN",
)
COLUMNS = ("Facility Name", "GCP & Ring", "Vendor", "Date", "TSU PAN Engineer") + ALL_FIELDS
PLACEHOLDER_NAMES = {"USED", "UNKNOWN", "-", ""}
NETS = ("A", "B", "M")  # network slots a vendor rule may use (M = Moxa network)

_IP_RE = re.compile(r"^\s*(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\s*$")
_PERSON_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ .'\-])*$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
FACILITY_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")


# ---------------------------------------------------------------- rules
@dataclass(frozen=True)
class FieldRule:
    """One address of a vendor rule: host = a * n + b on network slot `net`."""

    field: str
    net: str
    a: int
    b: int

    def host(self, n: int) -> int:
        return self.a * n + self.b


@dataclass(frozen=True)
class VendorRule:
    name: str
    capacity: int
    fields: tuple[FieldRule, ...]


@dataclass(frozen=True)
class Block:
    """A concrete address block: one GCP & Ring + one vendor rule + the third octets it uses."""

    gcp: str
    octet1: int
    octet2: int
    octets: dict[str, int]  # net slot -> third octet
    rule: VendorRule
    rtu_vlan: str = ""
    plc_vlan: str = ""
    mask: str = "255.255.255.0"
    block_id: int | None = None

    @property
    def vendor(self) -> str:
        return self.rule.name

    @property
    def capacity(self) -> int:
        return self.rule.capacity


@dataclass
class Allocation:
    n: int
    ips: dict[str, str]
    skipped: list[int] = field(default_factory=list)


class RangeFull(Exception):
    def __init__(self, skipped: list[int]):
        super().__init__("range is full")
        self.skipped = skipped


def build(block: Block, n: int) -> dict[str, str]:
    """All addresses of host number n in this block, in worksheet order."""
    p = f"{block.octet1}.{block.octet2}."
    out: dict[str, str] = {}
    by_field = {f.field: f for f in block.rule.fields}
    for name in ALL_FIELDS:
        fr = by_field.get(name)
        if fr is not None:
            out[name] = f"{p}{block.octets[fr.net]}.{fr.host(n)}"
    out["Subnet Mask"] = block.mask
    if block.rtu_vlan:
        out["RTU VLAN"] = block.rtu_vlan
    if block.plc_vlan:
        out["PLC VLAN"] = block.plc_vlan
    return {k: out[k] for k in ALL_FIELDS if k in out}


def validate_rule(rule: VendorRule, octets: dict[str, int] | None = None) -> list[str]:
    """Problems that would make a vendor rule unsafe. Empty list = safe for every host number."""
    errors: list[str] = []
    if not 1 <= rule.capacity <= 254:
        errors.append("Capacity must be between 1 and 254.")
        return errors
    names = [f.field for f in rule.fields]
    if len(set(names)) != len(names):
        errors.append("A field is listed twice.")
    for f in rule.fields:
        if f.field not in IP_FIELDS:
            errors.append(f"{f.field} is not an IP field.")
        if f.net not in NETS:
            errors.append(f"{f.field}: network must be one of {', '.join(NETS)}.")
        if f.field in INFRA and f.a != 0:
            errors.append(f"{f.field} is shared by all records, so its host must be a fixed number.")
        if f.field in UNIQ and f.a < 1:
            errors.append(f"{f.field} must change with the host number (multiplier of n must be 1 or more).")
    if not any(f.field == "RTU IP-1" for f in rule.fields):
        errors.append("The rule must define RTU IP-1.")
    if errors:
        return errors
    used_nets = {f.net for f in rule.fields}
    if octets is not None:
        missing = sorted(used_nets - set(octets))
        if missing:
            errors.append(f"Third octet missing for network {', '.join(missing)}.")
        vals = [octets[k] for k in used_nets if k in octets]
        if any(not 0 <= v <= 255 for v in vals):
            errors.append("Third octets must be between 0 and 255.")
        if len(set(vals)) != len(vals):
            errors.append("Each network of a block needs its own third octet.")
    infra = {(f.net, f.b): f.field for f in rule.fields if f.field in INFRA}
    for (_, host), name in infra.items():
        if not 1 <= host <= 254:
            errors.append(f"{name}: host {host} is outside 1 to 254.")
    seen: dict[tuple[str, int], str] = {}
    for n in range(1, rule.capacity + 1):
        for f in rule.fields:
            if f.field not in UNIQ:
                continue
            h = f.host(n)
            if not 1 <= h <= 254:
                errors.append(f"{f.field}: host number {n} gives .{h}, outside 1 to 254.")
                return errors
            key = (f.net, h)
            if key in infra:
                errors.append(f"{f.field}: host number {n} gives .{h}, which is {infra[key]}.")
                return errors
            if key in seen:
                errors.append(f"{f.field}: host number {n} gives .{h} on network {f.net}, already used by {seen[key]}.")
                return errors
            seen[key] = f"{f.field} (host number {n})"
    return errors


# ---------------------------------------------------------------- IPv4 helpers
def canon_ip(value: object) -> str | None:
    """'018.1.20.07' -> '18.1.20.7'; anything that is not dotted IPv4 -> None."""
    m = _IP_RE.match("" if value is None else str(value))
    if not m:
        return None
    octs = [int(x) for x in m.groups()]
    return ".".join(map(str, octs)) if all(o <= 255 for o in octs) else None


def ip_int(ip: str) -> int:
    a, b, c, d = (int(x) for x in ip.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def mask_bits(mask: object) -> int:
    """Prefix length of a subnet mask, or -1 when it is not a valid mask."""
    c = canon_ip(mask)
    if c is None:
        return -1
    bits = f"{ip_int(c):032b}"
    return bits.count("1") if re.fullmatch(r"1+0*", bits) else -1


def edge_address(ip: str, mask: str) -> str:
    """'network' / 'broadcast' when ip is the first or last address of its subnet, else ''."""
    b = mask_bits(mask)
    if not 1 <= b <= 30:
        return ""
    size = 1 << (32 - b)
    host = ip_int(ip) % size
    return "network" if host == 0 else "broadcast" if host == size - 1 else ""


def same_subnet(a: str, b: str, mask: str) -> bool:
    bits = mask_bits(mask)
    if bits < 1:
        return True
    return ip_int(a) >> (32 - bits) == ip_int(b) >> (32 - bits)


def ip_key(ip: str) -> str:
    return canon_ip(ip) or str(ip)


# ---------------------------------------------------------------- allocation
def is_busy(ips: dict[str, str], busy: dict[str, str] | set[str]) -> bool:
    return any(ips.get(f) and ips[f] in busy for f in UNIQ)


def allocate(block: Block, busy: dict[str, str] | set[str]) -> Allocation:
    """First free host number (section 4.4). `busy` holds every device and infrastructure IP in use."""
    skipped: list[int] = []
    for n in range(1, block.capacity + 1):
        ips = build(block, n)
        if not is_busy(ips, busy):
            return Allocation(n, ips, skipped)
        skipped.append(n)
    raise RangeFull(skipped)


def usage(block: Block, busy: dict[str, str] | set[str]) -> tuple[int, int, int]:
    """(used, max, next free host number or 0)."""
    free, nxt = 0, 0
    for n in range(1, block.capacity + 1):
        if not is_busy(build(block, n), busy):
            free += 1
            nxt = nxt or n
    return block.capacity - free, block.capacity, nxt


def rule_host(block: Block, ips: dict[str, str]) -> int:
    """Host number n when the device IPs follow this block's rule exactly, else 0."""
    for n in range(1, block.capacity + 1):
        b = build(block, n)
        if all(b.get(f, "") == (ip_key(ips[f]) if ips.get(f) else "") for f in UNIQ):
            return n
    return 0


# ---------------------------------------------------------------- names, people, dates
def split_name(name: str) -> tuple[str, str] | None:
    m = re.fullmatch(r"([A-Z][A-Z0-9]{1,7})-(\d{1,5})", str(name).strip().upper())
    return (m.group(1), m.group(2)) if m else None


def is_std_name(name: str) -> bool:
    return split_name(name) is not None


def name_format_error(name: str, facilities: set[str] | list[str]) -> str:
    parts = split_name(name)
    if parts is None or parts[0] not in facilities:
        return "Name must look like UTMN-1000: a facility from the list, a dash, then the well number (1 to 5 digits)."
    return ""


def is_placeholder(name: str) -> bool:
    return str(name).strip().upper() in PLACEHOLDER_NAMES


def clean_person(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def check_person(value: object) -> str:
    s = clean_person(value)
    if not 2 <= len(s) <= 40:
        return "Type your name (2 to 40 characters)."
    if not _PERSON_RE.match(s):
        return "A name may only contain letters, spaces, dots, dashes and apostrophes."
    return ""


def is_iso_date(s: object) -> bool:
    m = _ISO_RE.match(str(s))
    if not m:
        return False
    try:
        date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return False
    return True


def import_date(v: object) -> str:
    """Excel serial dates and date objects -> YYYY-MM-DD; other values kept as text (max 20 chars)."""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")  # type: ignore[union-attr]
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 20000 < v < 80000:
        return (date(1899, 12, 30) + timedelta(days=round(v))).isoformat()
    return ("" if v is None else str(v)).strip()[:20]


# ---------------------------------------------------------------- conflicts
@dataclass
class Index:
    """What is already taken. Built from stored records, then extended with accepted import rows."""

    names: dict[str, str] = field(default_factory=dict)   # UPPER name -> 'active' | 'trash' | 'file'
    device: dict[str, str] = field(default_factory=dict)  # device IP -> record name
    infra: dict[str, str] = field(default_factory=dict)   # gateway / laptop IP -> record name

    def add(self, name: str, ips: dict[str, str], where: str = "file") -> None:
        if not is_placeholder(name):
            self.names[name.upper()] = where
        for f in UNIQ:
            if ips.get(f):
                self.device[ip_key(ips[f])] = name
        for f in INFRA:
            if ips.get(f):
                self.infra[ip_key(ips[f])] = name

    @property
    def busy(self) -> dict[str, str]:
        return {**self.infra, **self.device}


def check_ips(ips: dict[str, str], idx: Index) -> list[str]:
    """Conflicts of a record's device IPs with the index and with each other."""
    errors: list[str] = []
    seen: dict[str, str] = {}
    for f in UNIQ:
        if not ips.get(f):
            continue
        k = ip_key(ips[f])
        if k in seen:
            errors.append(f"{f} {k} repeats {seen[k]} of the same record")
        elif k in idx.device:
            errors.append(f"{f} {k} is already used by {idx.device[k]}")
        elif k in idx.infra:
            errors.append(f"{f} {k} is a gateway or laptop address of {idx.infra[k]}")
        seen[k] = f
    return errors


# ---------------------------------------------------------------- import
@dataclass
class ImportConfig:
    facilities: set[str]
    blocks: list[Block]           # every block (any status) for rule matching
    gcps: dict[str, tuple[str, str]]  # GCP code -> (rtu vlan, plc vlan)
    vendors: set[str]
    mask: str = "255.255.255.0"


@dataclass
class RowResult:
    line: int
    name: str
    record: dict | None
    errors: list[str]
    warnings: list[str]


def check_import_row(row: dict, idx: Index, cfg: ImportConfig, line: int = 0) -> RowResult:
    """Validate one imported row (keys = COLUMNS). Does not modify idx."""
    errors: list[str] = []
    warnings: list[str] = []

    def val(k: str) -> str:
        v = row.get(k)
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return ("" if v is None else str(v)).strip()

    name = val("Facility Name").upper()
    placeholder = is_placeholder(name)
    if len(name) > 40:
        errors.append("Facility Name is longer than 40 characters")
    elif not placeholder:
        if name_format_error(name, cfg.facilities):
            errors.append(f'Facility Name "{name}" must look like UTMN-1000 (a facility from the list, a dash, 1 to 5 digits)')
        elif name in idx.names:
            where = {"trash": " (in the trash)", "file": " (earlier row in this file)"}.get(idx.names[name], "")
            errors.append(f"the name {name} already exists{where}")

    gcp, vendor, eng = val("GCP & Ring"), val("Vendor"), clean_person(row.get("TSU PAN Engineer"))
    if len(gcp) > 40:
        errors.append("GCP & Ring is longer than 40 characters")
    if len(vendor) > 30:
        errors.append("Vendor is longer than 30 characters")
    if len(eng) > 40:
        errors.append("TSU PAN Engineer is longer than 40 characters")
    gcp = next((g for g in cfg.gcps if g.lower() == gcp.lower()), gcp)
    vendor = next((v for v in cfg.vendors if v.lower() == vendor.lower()), vendor)

    ips: dict[str, str] = {}
    for f in ALL_FIELDS:
        s = val(f)
        if not s:
            continue
        if len(s) > 30:
            errors.append(f"{f} is longer than 30 characters")
        elif f in IP_FIELDS:
            c = canon_ip(s)
            if c is None:
                errors.append(f'{f} "{s}" is not a valid IPv4 address (4 numbers from 0 to 255)')
                continue
            if c != s:
                warnings.append(f"{f} {s} was read as {c}")
            ips[f] = c
        elif f == "Subnet Mask":
            if mask_bits(s) < 0:
                errors.append(f'Subnet Mask "{s}" is not a valid mask')
            else:
                ips[f] = canon_ip(s) or s
        else:  # VLAN
            if not re.fullmatch(r"\d{1,4}", s) or not 1 <= int(s) <= 4094:
                errors.append(f'{f} "{s}" must be a number from 1 to 4094')
            else:
                ips[f] = str(int(s))
    if not any(ips.get(f) for f in UNIQ):
        errors.append("no device IPs in this row (RTU, PLC, HMI or Moxa)")

    mask = ips.get("Subnet Mask") or cfg.mask
    row_infra = {ips[f]: f for f in INFRA if ips.get(f)}
    for f in UNIQ:
        if not ips.get(f):
            continue
        edge = edge_address(ips[f], mask)
        if edge:
            errors.append(f"{f} {ips[f]} is the {edge} address of its subnet")
        if ips[f] in row_infra:
            errors.append(f"{f} {ips[f]} is the same as {row_infra[ips[f]]}")
    errors.extend(check_ips(ips, idx))

    # non-blocking notes: imported data may come from older rules
    if gcp and gcp not in cfg.gcps:
        warnings.append(f"GCP & Ring {gcp} is not configured, so this record can be edited but its IPs cannot be regenerated")
    if vendor and vendor not in cfg.vendors:
        warnings.append(f"Vendor {vendor} is not configured")
    if gcp in cfg.gcps and vendor in cfg.vendors and not errors:
        blocks = [b for b in cfg.blocks if b.gcp == gcp and b.vendor == vendor]
        if not any(rule_host(b, ips) for b in blocks):
            warnings.append(f"the IPs do not follow the {gcp} / {vendor} rule; they are kept as they are and stay reserved")
        rv, pv = cfg.gcps[gcp]
        if (ips.get("RTU VLAN") and ips["RTU VLAN"] != rv) or (ips.get("PLC VLAN") and ips["PLC VLAN"] != pv):
            warnings.append(f"the VLANs differ from {gcp} ({rv} / {pv})")
    if ips.get("Gateway-1") and ips.get("RTU IP-1") and not same_subnet(ips["Gateway-1"], ips["RTU IP-1"], mask):
        warnings.append("RTU IP-1 is not in the same subnet as Gateway-1")
    record_date = import_date(row.get("Date"))
    if record_date and not is_iso_date(record_date):
        warnings.append(f'Date "{record_date}" is not YYYY-MM-DD; it is kept as text')

    if errors:
        return RowResult(line, name, None, errors, warnings)
    rec = {"name": name or "UNKNOWN", "gcp": gcp, "vendor": vendor, "engineer": eng, "date": record_date, "ips": ips}
    return RowResult(line, name, rec, [], warnings)


def check_import_rows(rows: list[tuple[int, dict]], idx: Index, cfg: ImportConfig) -> list[RowResult]:
    """Validate rows in order; each accepted row is added to idx so later rows are checked against it."""
    out: list[RowResult] = []
    for line, row in rows:
        res = check_import_row(row, idx, cfg, line)
        if res.record:
            idx.add(res.record["name"], res.record["ips"], "file")
        out.append(res)
    return out
