"""Excel import (preview, confirm, undo) and export."""

import io

from openpyxl import Workbook, load_workbook

from app import engine as E
from tests.conftest import Api
from tests.test_engine import Y, block

ACT = {"actor": "Eng B"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def row(n, name=None, blk=Y, **extra):
    r = {"Facility Name": name or f"UTMN-{n}", "GCP & Ring": blk.gcp, "Vendor": blk.vendor, "Date": "2026-01-02", "TSU PAN Engineer": "Eng A"}
    r.update(E.build(blk, n))
    r.update(extra)
    return r


def xlsx(rows, columns=None, sheet="IPs", extra_sheets=(), top_rows=0) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    columns = columns or list(E.COLUMNS)
    for _ in range(top_rows):
        ws.append(["Company sheet title"])
    ws.append(columns)
    for r in rows:
        ws.append([r.get(c, "") for c in columns])
        for c in ws[ws.max_row]:
            if isinstance(c.value, str):
                c.data_type = "s"          # typed text, like a cell formatted as Text in Excel
    for name in extra_sheets:
        wb.create_sheet(name).append(["GCP", "Rule", "Notes"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(api: Api, data: bytes, name="sheet.xlsx"):
    return api.c.post("/api/import/preview", files={"file": (name, data, XLSX)}, headers={"X-CSRF-Token": api.csrf})


def do_import(api: Api, rows, **kw):
    p = upload(api, xlsx(rows, **kw))
    assert p.status_code == 200, p.text
    return p.json(), api.post("/import/confirm", {"token": p.json()["token"], **ACT})


def test_preview_writes_nothing_then_confirm_adds(admin):
    p = upload(admin, xlsx([row(1), row(2)])).json()
    assert (p["will_add"], p["will_skip"], p["rows"]) == (2, 0, 2)
    assert admin.get("/records").json()["total"] == 0
    c = admin.post("/import/confirm", {"token": p["token"], **ACT})
    assert c.status_code == 200 and c.json()["imported"] == 2
    items = admin.get("/records").json()["items"]
    assert [i["name"] for i in items] == ["UTMN-1", "UTMN-2"] and items[0]["host"] == 1 and items[0]["imported"]
    assert admin.post("/import/confirm", {"token": p["token"], **ACT}).status_code == 409        # a token works once
    log = admin.get("/audit-log").json()
    assert log["total"] == 1 and log["items"][0]["action"] == "Imported" and log["items"][0]["who"] == "Eng B"
    assert admin.preview(3).json()["host"] == 3                                                  # imported IPs are reserved


def test_existing_rows_are_never_changed(admin):
    admin.save(1)
    b = admin.save(2).json()
    admin.delete(f"/records/{b['id']}", {**ACT, "version": 1})
    before = admin.get("/records?status=all").json()["items"]
    p, c = do_import(admin, [row(1, name="UTMN-900"), row(2, name="UTMN-901"), row(5, name="utmn-1"), row(6, name="UTMN-2"), row(7)])
    assert (p["will_add"], p["will_skip"]) == (1, 4) and c.json()["imported"] == 1
    reasons = {i["line"]: " ".join(i["reasons"]) for i in p["issues"]}
    assert "already used by UTMN-1" in reasons[2] and "already used by UTMN-2" in reasons[3]   # active and trashed IPs
    assert "already exists" in reasons[4] and "trash" in reasons[5]                              # active and trashed names
    after = admin.get("/records?status=all").json()["items"]
    assert after[:2] == before and after[2]["name"] == "UTMN-7"


def test_duplicates_inside_the_file_and_bad_values(admin):
    rows = [row(1), row(1, name="UTMN-50"), row(2, name="UTMN-1"), row(3, **{"RTU IP-1": "18.1.20.300"}),
            row(4, **{"PLC IP-1": "18.1.20.172"}), row(5, **{"RTU IP-1": "18.1.20.253"}), row(6, **{"RTU VLAN": "0"})]
    p, c = do_import(admin, rows)
    assert (p["will_add"], p["will_skip"]) == (1, 6) and c.json()["imported"] == 1
    assert len(c.json()["skipped_rows"]) == 6 and c.json()["skipped_rows"][0]["line"] == 3


def test_same_file_twice_adds_nothing(admin):
    rows = [row(1), row(2), {"Facility Name": "Used", "RTU IP-1": "30.1.1.1"}, {"Facility Name": "Used", "RTU IP-1": "30.1.1.2"}]
    p, c = do_import(admin, rows)
    assert c.json()["imported"] == 4                                 # placeholder names may repeat
    p2 = upload(admin, xlsx(rows)).json()
    assert (p2["will_add"], p2["will_skip"]) == (0, 4)
    assert admin.post("/import/confirm", {"token": p2["token"], **ACT}).status_code == 400
    assert admin.get("/records").json()["total"] == 4


def test_export_then_import_round_trip(admin):
    for i in range(3):
        admin.save(10 + i)
    admin.save(20, gcp="SHGCP1-R1", vendor="Honeywell")
    exp = admin.get("/export")
    assert exp.status_code == 200 and "IP-Generator-" in exp.headers["content-disposition"]
    original = admin.get("/records").json()["items"]
    for r in original:                                               # empty the system
        t = admin.delete(f"/records/{r['id']}", {**ACT, "version": r["version"]}).json()
        assert admin.delete(f"/records/{r['id']}/permanent", {**ACT, "version": t["version"]}).status_code == 200
    p = upload(admin, exp.content, "IP-Generator.xlsx").json()
    assert (p["will_add"], p["will_skip"], p["with_notes"]) == (4, 0, 0)
    assert admin.post("/import/confirm", {"token": p["token"], **ACT}).status_code == 200
    again = admin.get("/records").json()["items"]
    strip = lambda r: {k: r[k] for k in ("name", "gcp", "vendor", "engineer", "date", "ips", "host")}   # noqa: E731
    assert [strip(r) for r in again] == [strip(r) for r in original]


def test_export_cells_are_text_not_formulas(admin):
    do_import(admin, [row(1, **{"TSU PAN Engineer": "=1+1", "Date": "@SUM(A1)"})])
    ws = load_workbook(io.BytesIO(admin.get("/export").content)).active
    assert ws["E2"].value == "=1+1" and ws["E2"].data_type == "s" and ws["D2"].data_type == "s"
    assert [c.value for c in ws[1]] == list(E.COLUMNS)


def test_file_problems_import_nothing(admin):
    assert upload(admin, b"this is not excel", "bad.xlsx").json()["error"] == "unreadable"
    assert upload(admin, b"", "empty.xlsx").json()["error"] == "empty_file"
    assert upload(admin, xlsx([row(1)]), "sheet.csv").json()["error"] == "wrong_type"
    assert upload(admin, xlsx([row(1)]), "sheet.xls").json()["error"] == "wrong_type"
    big = upload(admin, b"PK" + b"0" * (5 * 1024 * 1024 + 10), "big.xlsx")
    assert big.status_code == 413
    assert upload(admin, xlsx([{"A": 1}], columns=["A", "B"])).json()["error"] == "wrong_columns"
    assert upload(admin, xlsx([])).json()["error"] == "no_rows"
    assert upload(admin, xlsx([row(i % 39 + 1, name=f"UTMN-{i}") for i in range(5001)])).json()["error"] == "too_many_rows"
    assert admin.post("/import/confirm", {"token": "nope", **ACT}).status_code == 409
    assert admin.get("/records").json()["total"] == 0 and admin.get("/audit-log").json()["total"] == 0


def test_real_world_sheet_layout(admin):
    """Extra empty/unknown columns, shuffled order, a title row above the header, and a second 'Backend' sheet."""
    cols = ["Remarks", "RTU IP-1", "", "Facility Name", "Vendor", "gcp & ring", "PLC IP-1", "Old column"] + [c for c in E.ALL_FIELDS if c not in ("RTU IP-1", "PLC IP-1")]
    p, c = do_import(admin, [row(1, Remarks="x"), row(2)], columns=cols, sheet="Data", extra_sheets=("Backend",), top_rows=2)
    assert c.json()["imported"] == 2 and p["sheet"] == "Data" and p["issues"] == []
    assert admin.get("/records").json()["items"][0]["ips"]["PLC IP-1"] == "18.1.20.85"


def test_notes_do_not_block_and_markup_is_plain_text(admin):
    rows = [row(1, **{"RTU IP-1": "018.001.020.169"}), row(2, **{"GCP & Ring": "OLDGCP-R9", "TSU PAN Engineer": "<img src=x onerror=alert(1)>"}),
            row(3, name="<script>alert(1)</script>")]
    p, c = do_import(admin, rows)
    assert (p["will_add"], p["will_skip"], p["with_notes"]) == (2, 1, 2)
    items = admin.get("/records").json()["items"]
    assert items[0]["ips"]["RTU IP-1"] == "18.1.20.169" and items[1]["engineer"] == "<img src=x onerror=alert(1)>" and items[1]["host"] is None
    # an imported record with an unconfigured GCP can be edited, but not regenerated into an unknown range
    r = admin.patch(f"/records/{items[1]['id']}", {**ACT, "version": 1, "date": "2026-02-02"})
    assert r.status_code == 200 and r.json()["gcp"] == "OLDGCP-R9"
    assert admin.post(f"/records/{items[1]['id']}/edit-preview", {"gcp": "OLDGCP-R9", "vendor": "Honeywell"}).status_code == 400


def test_placeholder_records_can_be_edited_deleted_restored(admin):
    do_import(admin, [{"Facility Name": "Used", "RTU IP-1": "30.1.1.1"}, {"Facility Name": "-", "RTU IP-1": "30.1.1.2"}])
    a = admin.get("/records").json()["items"][0]
    assert a["name"] == "USED"
    e = admin.patch(f"/records/{a['id']}", {**ACT, "version": 1, "engineer": "Eng C", "date": "2026-03-03"}).json()
    assert e["name"] == "USED" and e["engineer"] == "Eng C"
    t = admin.delete(f"/records/{a['id']}", {**ACT, "version": e["version"]}).json()
    assert admin.post(f"/records/{a['id']}/restore", {**ACT, "version": t["version"]}).status_code == 200
    renamed = admin.patch(f"/records/{a['id']}", {**ACT, "version": t["version"] + 1, "name": "UTMN-77"})
    assert renamed.status_code == 200 and admin.preview(77).status_code == 409


def test_undo_last_import(admin):
    admin.save(1)
    do_import(admin, [row(2), row(3)])
    last = admin.get("/import/last").json()["last"]
    assert last["count"] == 2 and last["can_undo"] and last["who"] == "Eng B"
    u = admin.post("/import/undo-last", {**ACT, "batch": last["batch"]})
    assert u.status_code == 200 and u.json()["removed"] == 2
    assert [r["name"] for r in admin.get("/records").json()["items"]] == ["UTMN-1"]
    assert admin.get("/import/last").json()["last"] is None and admin.post("/import/undo-last", ACT).status_code == 409
    assert admin.get("/audit-log").json()["items"][0]["action"] == "Import undone"


def test_undo_refused_after_a_change(admin):
    do_import(admin, [row(2), row(3)])
    rec = admin.get("/records").json()["items"][0]
    admin.patch(f"/records/{rec['id']}", {**ACT, "version": 1, "date": "2026-04-04"})
    assert admin.get("/import/last").json()["last"]["can_undo"] is False
    r = admin.post("/import/undo-last", ACT)
    assert r.status_code == 409 and "UTMN-2" in r.json()["message"] and admin.get("/records").json()["total"] == 2


def test_import_matches_honeywell_rule(admin):
    hb = block("SHGCP1-R1", "Honeywell")
    p, c = do_import(admin, [row(4, name="HWYH-1", blk=hb)])
    assert p["with_notes"] == 0 and admin.get("/records").json()["items"][0]["host"] == 4
