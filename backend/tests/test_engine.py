"""Engine tests: SRS section 4.6 vectors plus the prototype's tests ported from prototype/js/tests.js."""

from app import defaults
from app import engine as E


def rule(name: str) -> E.VendorRule:
    v = next(x for x in defaults.VENDORS if x["name"] == name)
    return E.VendorRule(v["name"], v["capacity"], tuple(E.FieldRule(**f) for f in v["fields"]))


def block(gcp: str, vendor: str, octet2: int | None = None) -> E.Block:
    code, o1, o2, rv, pv = next(g for g in defaults.GCP_RINGS if g[0] == gcp)
    v = next(x for x in defaults.VENDORS if x["name"] == vendor)
    return E.Block(code, o1, octet2 if octet2 is not None else o2, dict(v["octets"]), rule(vendor), rv, pv)


ALL_BLOCKS = [block(g[0], v["name"]) for g in defaults.GCP_RINGS for v in defaults.VENDORS]
CFG = E.ImportConfig(
    facilities=set(defaults.FACILITIES),
    blocks=ALL_BLOCKS,
    gcps={g[0]: (g[3], g[4]) for g in defaults.GCP_RINGS},
    vendors={v["name"] for v in defaults.VENDORS},
)
Y = block("HDGCP1-R1", "Yokogawa")


def busy_of(records: list[dict]) -> dict[str, str]:
    idx = E.Index()
    for r in records:
        idx.add(r["name"], r["ips"], "active")
    return idx.busy


# ---------------------------------------------------------------- 4.6 vectors and original 14
def test_yokogawa_n1_vector():
    r = E.build(Y, 1)
    assert (r["RTU IP-1"], r["RTU IP-2"]) == ("18.1.20.169", "18.1.21.169")
    assert (r["PLC IP-1"], r["PLC IP-2"]) == ("18.1.20.85", "18.1.21.85")
    assert r["RTU Internal IP-1"] == "18.1.20.1" and r["RTU Internal IP-2"] == "18.1.21.1"
    assert r["RTU-HMI IP"] == "18.1.20.211" and r["IES Moxa IP"] == "18.1.10.1"
    assert (r["Engg. Laptop IP"], r["Gateway-1"], r["Gateway-2"]) == ("18.1.20.250", "18.1.20.253", "18.1.21.253")
    assert (r["Subnet Mask"], r["RTU VLAN"], r["PLC VLAN"]) == ("255.255.255.0", "1800", "1801")


def test_honeywell_k1_vector():
    r = E.build(block("SHGCP1-R1", "Honeywell"), 1)
    assert r["RTU IP-1"] == "19.1.100.1" and r["RTU IP-2"] == "19.1.100.2"
    assert r["PLC IP-1"] == "19.1.100.3" and r["PLC IP-2"] == "19.1.100.4"
    assert r["RTU-HMI IP"] == "19.1.101.1" and r["IES Moxa IP"] == "19.1.11.1"
    assert "RTU Internal IP-1" not in r


def test_honeywell_formula_matches_srs_for_every_k():
    b = block("SHGCP1-R1", "Honeywell")
    for k in range(1, 63):
        s = 4 * (k - 1) + 1
        r = E.build(b, k)
        assert [r[f] for f in ("RTU IP-1", "RTU IP-2", "PLC IP-1", "PLC IP-2")] == [f"19.1.100.{s + i}" for i in range(4)]
        assert r["RTU-HMI IP"] == f"19.1.101.{k}" and r["IES Moxa IP"] == f"19.1.11.{k}"


def _fill_everything() -> list[dict]:
    recs: list[dict] = []
    for b in ALL_BLOCKS:
        for _ in range(b.capacity):
            a = E.allocate(b, busy_of(recs))
            recs.append({"name": f"T-{len(recs)}", "gcp": b.gcp, "vendor": b.vendor, "ips": a.ips})
        try:
            E.allocate(b, busy_of(recs))
            raise AssertionError(f"{b.gcp}/{b.vendor} not full")
        except E.RangeFull:
            pass
    return recs


def test_fill_all_ranges_no_duplicates_valid_hosts_then_full():
    recs = _fill_everything()
    assert len(recs) == 4 * (39 + 62)
    seen: set[str] = set()
    for r in recs:
        for f in E.UNIQ:
            ip = r["ips"].get(f)
            if not ip:
                continue
            assert ip not in seen, f"duplicate {ip}"
            seen.add(ip)
            host = int(ip.split(".")[3])
            assert 1 <= host <= 249 and host not in (250, 253)


def test_freed_number_is_reused_first_and_trash_stays_reserved():
    recs = _fill_everything()
    y = [r for r in recs if r["gcp"] == "HDGCP1-R1" and r["vendor"] == "Yokogawa"]
    rest = [r for r in recs if r is not y[4]]
    assert E.allocate(Y, busy_of(rest)).n == 5          # permanent delete frees host 5
    try:                                                # a trashed record is still in the list: stays reserved
        E.allocate(Y, busy_of(recs))
        raise AssertionError("should be full")
    except E.RangeFull:
        pass


def test_used_ip_makes_allocation_skip_that_number():
    base = [{"name": "UTMN-1", "ips": {"RTU IP-1": E.build(Y, 1)["RTU IP-1"]}}]
    a = E.allocate(Y, busy_of(base))
    assert a.n == 2 and a.skipped == [1]


def test_ring_2_does_not_clash():
    base = [{"name": "UTMN-1", "ips": E.build(Y, 1)}]
    assert E.allocate(block("HDGCP1-R1", "Yokogawa", octet2=2), busy_of(base)).n == 1


def test_names():
    fac = set(defaults.FACILITIES)
    assert E.name_format_error("utmn-1000", fac) == "" and E.name_format_error("UTMN-1", fac) == ""
    for bad in ("UTMN", "ABCD-12", "UTMN-12ab", "UTMN-123456", "UTMN -1", ""):
        assert E.name_format_error(bad, fac) != ""
    assert E.is_placeholder("Used") and E.is_placeholder(" - ") and E.is_placeholder("") and not E.is_placeholder("UTMN-1")


# ---------------------------------------------------------------- addresses
def test_ip_helpers():
    assert E.canon_ip("018.001.020.07") == "18.1.20.7"
    assert E.canon_ip("18.1.20.256") is None and E.canon_ip("18.1.20") is None and E.canon_ip("a.b.c.d") is None
    assert E.mask_bits("255.255.255.0") == 24 and E.mask_bits("255.0.255.0") == -1 and E.mask_bits("255.255.255.256") == -1
    assert E.edge_address("18.1.20.0", "255.255.255.0") == "network"
    assert E.edge_address("18.1.20.255", "255.255.255.0") == "broadcast"
    assert E.edge_address("18.1.20.1", "255.255.255.0") == ""


def test_rule_host():
    assert E.rule_host(Y, E.build(Y, 7)) == 7
    assert E.rule_host(block("HDGCP1-R1", "Honeywell"), E.build(Y, 7)) == 0


def test_allocation_skips_gateway_address_of_another_record():
    assert E.allocate(Y, busy_of([{"name": "USED", "ips": {"Gateway-1": "18.1.20.169"}}])).n == 2


def test_leading_zero_data_still_blocks():
    assert E.allocate(Y, busy_of([{"name": "UTMN-5", "ips": {"RTU IP-1": "018.001.020.169"}}])).n == 2


def test_person_names():
    assert E.clean_person("  Eng   A  ") == "Eng A"
    assert E.check_person("Eng A") == "" and E.check_person("O'Neil-Smith Jr.") == "" and E.check_person("محمد علي") == ""
    for bad in ("E", "<b>x</b>", "12345", "x" * 41, "A=1"):
        assert E.check_person(bad) != ""


def test_dates():
    assert E.is_iso_date("2026-11-04") and not E.is_iso_date("2026-13-01") and not E.is_iso_date("2026-02-30") and not E.is_iso_date("04/11/2026")
    assert E.import_date(46000) == "2025-12-09" and E.import_date("04/11/2026") == "04/11/2026" and E.import_date(None) == ""


# ---------------------------------------------------------------- vendor rule validation
def test_seed_rules_are_valid():
    for v in defaults.VENDORS:
        assert E.validate_rule(rule(v["name"]), v["octets"]) == []


def test_unsafe_rules_are_rejected():
    y = rule("Yokogawa")
    assert E.validate_rule(E.VendorRule("X", 90, y.fields)) != []                     # host leaves 1..254 / collides
    hits_gw = tuple(E.FieldRule(f.field, f.net, f.a, 252) if f.field == "RTU IP-1" else f for f in y.fields)
    assert any("Gateway-1" in e for e in E.validate_rule(E.VendorRule("X", 5, hits_gw)))
    overlap = tuple(E.FieldRule(f.field, f.net, f.a, 84) if f.field == "RTU IP-1" else f for f in y.fields)
    assert any("already used" in e for e in E.validate_rule(E.VendorRule("X", 5, overlap)))
    assert E.validate_rule(y, {"A": 20, "B": 20, "M": 10}) != []                      # two networks on one octet
    assert E.validate_rule(E.VendorRule("X", 0, y.fields)) != []


# ---------------------------------------------------------------- import rows
def row(n: int, **extra) -> dict:
    r = {"Facility Name": f"UTMN-{n}", "GCP & Ring": "HDGCP1-R1", "Vendor": "Yokogawa", "Date": "2026-01-02", "TSU PAN Engineer": "Eng A"}
    r.update(E.build(Y, n))
    r.update(extra)
    return r


def run(rows: list[dict], existing: list[dict] | None = None) -> list[E.RowResult]:
    idx = E.Index()
    for r in existing or []:
        idx.add(r["name"], r["ips"], r.get("where", "active"))
    return E.check_import_rows(list(enumerate(rows, start=2)), idx, CFG)


EX = [{"name": "UTMN-1", "ips": E.build(Y, 1)}, {"name": "UTMN-2", "ips": E.build(Y, 2), "where": "trash"}]


def test_import_clean_row():
    res = run([row(3)], EX)[0]
    assert res.record and not res.warnings and res.line == 2


def test_import_name_conflicts():
    assert run([row(9, **{"Facility Name": "UTMN-1"})], EX)[0].record is None
    res = run([row(9, **{"Facility Name": "utmn-2"})], EX)[0]
    assert res.record is None and "trash" in " ".join(res.errors)


def test_import_ip_conflicts():
    res = run([row(2, **{"Facility Name": "UTMN-50"})], EX)[0]
    assert res.record is None and "already used" in " ".join(res.errors)
    assert run([row(9, **{"Facility Name": "UTMN-60", "RTU IP-1": EX[0]["ips"]["PLC IP-1"]})], EX)[0].record is None  # cross-column
    two = run([row(10), row(10, **{"Facility Name": "UTMN-61"})])
    assert two[0].record and two[1].record is None                                                               # same file
    res = run([row(10, **{"PLC IP-1": "18.1.20.178"})])[0]
    assert res.record is None and "same record" in " ".join(res.errors)                                          # same row


def test_import_bad_values():
    assert run([row(11, **{"RTU IP-1": "18.1.20.300"})])[0].record is None
    assert "same as Gateway-1" in " ".join(run([row(12, **{"RTU IP-1": "18.1.20.253"})])[0].errors)
    assert "network address" in " ".join(run([row(13, **{"RTU-HMI IP": "18.1.20.0"})])[0].errors)
    assert run([row(14, **{"RTU VLAN": "5000"})])[0].record is None
    assert run([row(15, **{"Subnet Mask": "255.0.255.0"})])[0].record is None
    assert run([row(16, **{"Facility Name": "X" * 41})])[0].record is None
    res = run([row(23, **{"Facility Name": "<img src=x onerror=alert(1)>"})])[0]
    assert res.record is None


def test_import_placeholders_and_notes():
    used = [{"Facility Name": "Used", "RTU IP-1": f"30.1.1.{n}"} for n in (1, 2)]
    assert all(r.record for r in run(used))
    res = run([row(16, **{"RTU IP-1": "18.1.20.017"})])[0]
    assert res.record and res.record["ips"]["RTU IP-1"] == "18.1.20.17" and res.warnings
    res = run([row(17, **{"RTU IP-1": "18.1.20.5"})])[0]
    assert res.record and "do not follow" in " ".join(res.warnings)
    res = run([row(18, **{"GCP & Ring": "OLDGCP-R9"})])[0]
    assert res.record and "not configured" in " ".join(res.warnings)
    res = run([row(19, **{"RTU VLAN": 1800.0, "Date": 46000})])[0]      # Excel numbers
    assert res.record and res.record["ips"]["RTU VLAN"] == "1800" and res.record["date"] == "2025-12-09"


def test_import_same_file_twice_and_round_trip():
    file = [row(20), row(21), row(22)]
    first = run(file)
    assert all(r.record for r in first)
    stored = [{"name": r.record["name"], "ips": r.record["ips"]} for r in first]
    assert all(r.record is None for r in run(file, stored))
    exported = [{"Facility Name": s["name"], "GCP & Ring": "HDGCP1-R1", "Vendor": "Yokogawa", "Date": "2026-01-02", **s["ips"]} for s in stored]
    assert all(r.record and not r.warnings for r in run(exported))
