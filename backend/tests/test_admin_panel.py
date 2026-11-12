"""Settings page API: facilities, GCP & Rings, blocks, vendors."""

from app import defaults

ACT = {"actor": "Eng B"}
YOKO = next(v for v in defaults.VENDORS if v["name"] == "Yokogawa")


def rules(admin):
    return admin.get("/admin/rules").json()


def test_facilities(admin):
    assert admin.post("/admin/facilities", {"code": "ab", **ACT}).status_code == 201           # stored upper-case
    assert admin.post("/admin/facilities", {"code": "AB", **ACT}).status_code == 409
    assert admin.post("/admin/facilities", {"code": "1X", **ACT}).status_code == 400
    assert admin.post("/admin/facilities", {"code": "QQ", "actor": ""}).status_code == 400
    assert "AB" in admin.get("/config").json()["facilities"]
    a = admin.save(5, facility="AB").json()
    fid = next(f["id"] for f in rules(admin)["facilities"] if f["code"] == "AB")
    assert admin.patch(f"/admin/facilities/{fid}", {"active": False, **ACT}).status_code == 200
    assert "AB" not in admin.get("/config").json()["facilities"] and admin.preview(6, facility="AB").status_code == 400
    # the existing record keeps its name and stays editable
    assert admin.patch(f"/records/{a['id']}", {**ACT, "version": 1, "date": "2026-05-05"}).status_code == 200
    assert admin.get("/audit-log").json()["items"][1]["action"] == "Settings changed"


def test_add_gcp_creates_blocks_and_generates(admin):
    r = admin.post("/admin/gcps", {"code": "newgcp-r1", "octet1": 30, "octet2": 2, "rtu_vlan": 1900, "plc_vlan": 1901, **ACT})
    assert r.status_code == 201
    p = admin.preview(1, gcp="NEWGCP-R1").json()
    assert p["ips"]["RTU IP-1"] == "30.2.20.169" and p["ips"]["RTU VLAN"] == "1900" and p["ips"]["Gateway-2"] == "30.2.21.253"
    assert admin.preview(1, gcp="NEWGCP-R1", vendor="Honeywell").json()["ips"]["RTU IP-1"] == "30.2.100.1"
    assert admin.post("/admin/gcps", {"code": "NEWGCP-R1", "octet1": 31, "octet2": 2, "rtu_vlan": 1, "plc_vlan": 2, **ACT}).status_code == 409
    assert admin.post("/admin/gcps", {"code": "OTHER-R1", "octet1": 30, "octet2": 2, "rtu_vlan": 1, "plc_vlan": 2, **ACT}).status_code == 409  # same prefix
    assert admin.post("/admin/gcps", {"code": "bad code!", "octet1": 40, "octet2": 2, "rtu_vlan": 1, "plc_vlan": 2, **ACT}).status_code == 400
    assert admin.post("/admin/gcps", {"code": "X-R1", "octet1": 40, "octet2": 2, "rtu_vlan": 5000, "plc_vlan": 2, **ACT}).status_code == 422
    assert len(admin.get("/dashboard").json()["ranges"]) == 10


def test_disable_gcp(admin):
    g = rules(admin)["gcps"][0]
    assert admin.patch(f"/admin/gcps/{g['id']}", {"active": False, **ACT}).status_code == 200
    assert g["code"] not in admin.get("/config").json()["gcps"] and admin.preview(1).status_code == 400
    assert admin.patch(f"/admin/gcps/{g['id']}", {"active": True, "rtu_vlan": 1805, **ACT}).status_code == 200
    assert admin.preview(1).json()["ips"]["RTU VLAN"] == "1805"


def test_block_lifecycle_full_then_next_block(admin):
    r = rules(admin)
    g = r["gcps"][0]
    yoko = next(x for x in g["ranges"] if x["vendor"] == "Yokogawa")
    base = {"gcp_id": g["id"], "vendor_id": yoko["vendor_id"], **ACT}
    assert admin.post("/admin/blocks", {**base, "octets": {"A": 30, "B": 31, "M": 100}}).status_code == 409      # 100 belongs to Honeywell
    assert admin.post("/admin/blocks", {**base, "octets": {"A": 30, "B": 30, "M": 12}}).status_code == 400       # same octet twice
    assert admin.post("/admin/blocks", {**base, "octets": {"A": 30}}).status_code == 400
    b = admin.post("/admin/blocks", {**base, "octets": {"A": 30, "B": 31, "M": 12}})
    assert b.status_code == 201 and b.json()["status"] == "planned" and b.json()["seq"] == 2
    assert admin.post("/admin/blocks", {**base, "octets": {"A": 40, "B": 41, "M": 13}}).status_code == 409       # one planned block at a time
    assert admin.preview(1).json()["ips"]["RTU IP-1"] == "18.1.20.169"                                           # planned is not used yet

    for i in range(39):
        assert admin.save(100 + i).status_code == 201
    assert admin.preview(999).json()["error"] == "range_full"                                                    # no automatic overflow
    assert admin.post(f"/admin/blocks/{b.json()['id']}/activate", ACT).status_code == 200
    p = admin.preview(999).json()
    assert p["host"] == 1 and p["ips"]["RTU IP-1"] == "18.1.30.169" and p["ips"]["IES Moxa IP"] == "18.1.12.1"
    assert admin.save(999).status_code == 201
    rng = next(x for x in admin.get("/ranges").json()["ranges"] if x["gcp"] == g["code"] and x["vendor"] == "Yokogawa")
    assert (rng["used"], rng["max"], rng["block_seq"], rng["retired"]) == (1, 39, 2, 1)
    # the retired block keeps every address reserved, and its octets can never be given to another block
    hw = next(x for x in g["ranges"] if x["vendor"] == "Honeywell")
    assert admin.post("/admin/blocks", {"gcp_id": g["id"], "vendor_id": hw["vendor_id"], "octets": {"A": 20, "B": 21, "M": 10}, **ACT}).status_code == 409
    assert admin.post(f"/admin/blocks/{b.json()['id']}/activate", ACT).status_code == 409                        # already active
    assert admin.delete(f"/admin/blocks/{b.json()['id']}", ACT).status_code == 409                               # only planned can be removed
    assert admin.get("/records?q=18.1.20.169&field=ip").json()["total"] == 1


def test_remove_planned_block_frees_its_octets(admin):
    g = rules(admin)["gcps"][0]
    yoko = next(x for x in g["ranges"] if x["vendor"] == "Yokogawa")
    base = {"gcp_id": g["id"], "vendor_id": yoko["vendor_id"], **ACT}
    b = admin.post("/admin/blocks", {**base, "octets": {"A": 30, "B": 31, "M": 12}}).json()
    assert admin.delete(f"/admin/blocks/{b['id']}", ACT).status_code == 200
    assert admin.post("/admin/blocks", {**base, "octets": {"A": 30, "B": 31, "M": 12}}).status_code == 201


def vendor_body(**over):
    body = {"name": "Emerson", "capacity": 20, "octets": {"A": 50, "B": 51, "M": 52},
            "fields": [dict(f) for f in YOKO["fields"]], **ACT}
    body.update(over)
    return body


def test_vendor_check_and_add(admin):
    ok = admin.post("/admin/vendors/check", vendor_body()).json()
    assert ok["ok"] and ok["sample"][0]["ips"]["RTU IP-1"] == "10.1.50.169" and ok["sample"][-1]["n"] == 20
    bad = admin.post("/admin/vendors/check", vendor_body(capacity=90)).json()
    assert not bad["ok"] and bad["errors"]
    assert admin.post("/admin/vendors", vendor_body(capacity=90)).status_code == 400
    assert admin.post("/admin/vendors", vendor_body(octets={"A": 20, "B": 51, "M": 52})).status_code == 409      # 20 is Yokogawa's
    assert [v["name"] for v in rules(admin)["vendors"]] == ["Yokogawa", "Honeywell"]                             # nothing half-created
    assert admin.post("/admin/vendors", vendor_body()).status_code == 201
    assert admin.post("/admin/vendors", vendor_body()).status_code == 409
    assert "Emerson" in admin.get("/config").json()["vendors"]
    p = admin.preview(1, vendor="Emerson").json()
    assert p["capacity"] == 20 and p["ips"]["RTU IP-1"] == "18.1.50.169" and p["ips"]["Gateway-1"] == "18.1.50.253"
    assert len(admin.get("/dashboard").json()["ranges"]) == 12
    vid = next(v["id"] for v in rules(admin)["vendors"] if v["name"] == "Emerson")
    assert admin.patch(f"/admin/vendors/{vid}", {"active": False, **ACT}).status_code == 200
    assert admin.preview(1, vendor="Emerson").status_code == 400


def test_warning_threshold(admin):
    assert admin.patch("/admin/settings", {"warn_at": 30, **ACT}).status_code == 422
    assert admin.patch("/admin/settings", {"warn_at": 50, **ACT}).status_code == 200
    for i in range(19):
        admin.save(100 + i)
    assert admin.preview(900).json()["warn"] is True and admin.get("/config").json()["warn_at"] == 0.5
