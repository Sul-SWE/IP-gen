"""Records API: permissions, validation, duplicates, capacity, 409 on changed preview, trash/restore/purge, edit."""

from tests.conftest import Api

ACT = {"actor": "Eng B"}


def test_viewer_reads_without_login_but_cannot_change(admin, viewer):
    admin.save(1000)
    assert viewer.get("/auth/me").json()["role"] == "viewer"
    assert viewer.get("/config").status_code == 200 and viewer.get("/dashboard").status_code == 200
    assert viewer.get("/records").json()["total"] == 1
    for method, url in [("post", "/generate/preview"), ("post", "/records"), ("patch", "/records/1"), ("delete", "/records/1"),
                        ("post", "/records/1/restore"), ("delete", "/records/1/permanent"), ("post", "/import/confirm"),
                        ("post", "/import/undo-last"), ("post", "/admin/facilities"), ("post", "/admin/gcps"),
                        ("post", "/admin/vendors"), ("post", "/admin/blocks"), ("patch", "/admin/settings"), ("post", "/auth/password")]:
        assert getattr(viewer, method)(url, {}).status_code == 401, url
    for url in ["/audit-log", "/engineers/suggest", "/export", "/admin/rules", "/import/last", "/records/1", "/names/check?name=x"]:
        assert viewer.get(url).status_code == 401, url


def test_generate_and_save(admin):
    p = admin.preview(1000).json()
    assert p["name"] == "UTMN-1000" and p["host"] == 1 and p["ips"]["RTU IP-1"] == "18.1.20.169" and p["skipped"] == []
    assert admin.get("/records").json()["total"] == 0                      # preview stores nothing
    r = admin.save(1000)
    assert r.status_code == 201 and r.json()["ips"]["IES Moxa IP"] == "18.1.10.1" and r.json()["host"] == 1
    assert admin.preview(1001).json()["host"] == 2
    log = admin.get("/audit-log").json()["items"][0]
    assert (log["action"], log["who"], log["name"]) == ("Created", "Eng A", "UTMN-1000")


def test_validation_errors(admin):
    assert admin.preview("12ab").status_code == 400
    assert admin.preview("").status_code == 400
    assert admin.preview(5, facility="ABCD").status_code == 400
    assert admin.preview(5, gcp="NOPE").status_code == 400
    assert admin.preview(5, engineer="X").status_code == 400
    assert admin.post("/generate/preview", {"facility": "UTMN"}).status_code == 422
    assert admin.post("/generate/preview", {"facility": "UTMN", "well": "1", "gcp": "HDGCP1-R1", "vendor": "Yokogawa", "engineer": "Eng A", "extra": 1}).status_code == 422
    body = admin.preview("12ab").json()
    assert set(body) >= {"error", "message", "details"}


def test_duplicate_name_including_case_and_trash(admin):
    rid = admin.save(1000).json()["id"]
    r = admin.preview(1000, facility="utmn")
    assert r.status_code == 409 and "already exists" in r.json()["message"]
    admin.delete(f"/records/{rid}", {**ACT, "version": 1})
    r = admin.preview(1000)
    assert r.status_code == 409 and "trash" in r.json()["message"]


def test_changed_preview_gives_409_with_new_preview(admin, app):
    sig = admin.preview(1000).json()["signature"]
    admin.save(2000)                                              # another change takes host 1
    r = admin.save(1000, signature=sig)
    assert r.status_code == 409 and r.json()["error"] == "preview_changed" and r.json()["preview"]["host"] == 2
    assert admin.get("/records").json()["total"] == 1
    assert admin.save(1000, signature=r.json()["preview"]["signature"]).status_code == 201


def test_repeated_save_creates_one_record(admin):
    sig = admin.preview(1000).json()["signature"]
    codes = [admin.save(1000, signature=sig).status_code for _ in range(3)]
    assert codes == [201, 409, 409] and admin.get("/records").json()["total"] == 1


def test_full_range_blocks_generation(admin):
    for i in range(39):
        assert admin.save(100 + i).status_code == 201
    r = admin.preview(999)
    assert r.status_code == 409 and r.json()["error"] == "range_full"
    assert admin.preview(999, vendor="Honeywell").json()["host"] == 1      # no overflow, other ranges still work
    p38 = [x for x in admin.get("/ranges").json()["ranges"] if x["gcp"] == "HDGCP1-R1" and x["vendor"] == "Yokogawa"][0]
    assert (p38["used"], p38["max"], p38["state"]) == (39, 39, "full")


def test_capacity_warning(admin):
    for i in range(34):
        admin.save(100 + i)
    assert admin.preview(900).json()["warn"] is False or admin.preview(900).json()["used_after"] >= 35
    assert admin.preview(900).json()["used_after"] == 35 and admin.preview(900).json()["warn"] is False   # 35/39 = 89.7%
    admin.save(900)
    assert admin.preview(901).json()["warn"] is True                                                      # 36/39 = 92%


def test_trash_restore_purge_and_reuse(admin):
    a = admin.save(1).json()
    admin.save(2)
    t = admin.delete(f"/records/{a['id']}", {**ACT, "version": a["version"]})
    assert t.status_code == 200 and t.json()["status"] == "trash" and t.json()["deleted_by"] == "Eng B"
    assert admin.preview(3).json()["host"] == 3                      # host 1 still reserved by the trash
    assert admin.delete(f"/records/{a['id']}/permanent", {**ACT, "version": a["version"]}).status_code == 409   # stale version
    v = t.json()["version"]
    back = admin.post(f"/records/{a['id']}/restore", {**ACT, "version": v})
    assert back.status_code == 200 and back.json()["status"] == "active"
    assert admin.delete(f"/records/{a['id']}/permanent", {**ACT, "version": back.json()["version"]}).status_code == 409  # must be in trash
    t2 = admin.delete(f"/records/{a['id']}", {**ACT, "version": back.json()["version"]}).json()
    assert admin.delete(f"/records/{a['id']}/permanent", {**ACT, "version": t2["version"]}).status_code == 200
    assert admin.preview(3).json()["host"] == 1 and admin.preview(1).status_code == 200    # number and name are free again
    actions = [x["action"] for x in admin.get("/audit-log").json()["items"]]
    assert actions[:4] == ["Deleted forever", "Deleted", "Restored", "Deleted"]


def test_actions_need_actor_name_and_version(admin):
    a = admin.save(1).json()
    assert admin.delete(f"/records/{a['id']}", {"actor": "", "version": 1}).status_code == 400
    assert admin.delete(f"/records/{a['id']}", {"actor": "Eng B"}).status_code == 409
    assert admin.delete("/records/9999", {"actor": "Eng B", "version": 1}).status_code == 404


def test_edit_simple_fields_and_stale(admin):
    a = admin.save(1).json()
    r = admin.patch(f"/records/{a['id']}", {**ACT, "version": 1, "name": "HRDH-77", "engineer": "Eng C", "date": "2026-01-05"})
    assert r.status_code == 200 and r.json()["name"] == "HRDH-77" and r.json()["ips"] == a["ips"] and r.json()["regenerated"] is False
    assert admin.patch(f"/records/{a['id']}", {**ACT, "version": 1, "date": "2026-01-06"}).status_code == 409          # old version
    assert admin.patch(f"/records/{a['id']}", {**ACT, "version": 2, "date": "2026-13-01"}).status_code == 400
    assert admin.patch(f"/records/{a['id']}", {**ACT, "version": 2}).json()["error"] == "nothing_changed"
    assert admin.preview(1).status_code == 200                                                                            # old name is free
    log = admin.get("/audit-log").json()["items"][0]
    assert log["action"] == "Modified" and "Date" in log["details"] and log["who"] == "Eng B"


def test_edit_name_conflict(admin):
    a = admin.save(1).json()
    admin.save(2)
    assert admin.patch(f"/records/{a['id']}", {**ACT, "version": 1, "name": "utmn-2"}).status_code == 409


def test_edit_with_regeneration_releases_old_ips(admin):
    a = admin.save(1).json()
    pv = admin.post(f"/records/{a['id']}/edit-preview", {"gcp": "HDGCP1-R1", "vendor": "Honeywell"}).json()
    assert pv["regen"] and pv["ips"]["RTU IP-1"] == "18.1.100.1" and pv["old_ips"]["RTU IP-1"] == "18.1.20.169"
    assert admin.patch(f"/records/{a['id']}", {**ACT, "version": 1, "vendor": "Honeywell"}).status_code == 409          # no confirmation
    r = admin.patch(f"/records/{a['id']}", {**ACT, "version": 1, "vendor": "Honeywell", "signature": pv["signature"]})
    assert r.status_code == 200 and r.json()["regenerated"] and r.json()["ips"]["RTU IP-1"] == "18.1.100.1"
    assert "RTU Internal IP-1" not in r.json()["ips"]
    assert admin.preview(2).json()["host"] == 1                      # the old Yokogawa host is free again
    assert admin.post(f"/records/{a['id']}/edit-preview", {"gcp": "NOPE", "vendor": "Honeywell"}).status_code == 400


def test_search_and_pagination(admin):
    for i in range(5):
        admin.save(10 + i, engineer="Eng A" if i % 2 else "Eng Z")
    assert admin.get("/records?q=utmn-12").json()["total"] == 1
    assert admin.get("/records?q=18.1.20.170&field=ip").json()["items"][0]["name"] == "UTMN-11"
    assert admin.get("/records?q=eng z&field=engineer").json()["total"] == 3
    assert admin.get("/records?q=18.1.21").json()["total"] == 5                     # all-fields search covers IPs
    assert admin.get("/records?q=%25").json()["total"] == 0                         # wildcard characters are literal
    page = admin.get("/records?size=2&page=3").json()
    assert (page["pages"], len(page["items"]), page["counts"]["active"]) == (3, 1, 5)
    assert admin.get("/records?field=bogus").status_code == 422
    assert admin.get("/engineers/suggest?q=eng").json()["names"] == ["Eng A", "Eng Z"]


def test_sql_injection_and_markup_are_plain_text(admin):
    assert admin.get("/records?q=' OR 1=1 --").json()["total"] == 0
    a = admin.save(1, engineer="O'Brien").json()
    assert a["engineer"] == "O'Brien"
    assert admin.preview(2, engineer="<script>alert(1)</script>").status_code == 400
    assert admin.get("/records?q=o'brien&field=engineer").json()["total"] == 1


def test_dashboard_numbers(admin):
    admin.save(1)
    b = admin.save(2).json()
    admin.delete(f"/records/{b['id']}", {**ACT, "version": 1})
    d = admin.get("/dashboard").json()
    assert (d["kpis"]["active"], d["kpis"]["trash"], d["kpis"]["used"], d["kpis"]["total"]) == (1, 1, 2, 404)
    rng = [x for x in d["ranges"] if x["gcp"] == "HDGCP1-R1" and x["vendor"] == "Yokogawa"][0]
    assert (rng["used"], rng["next"], rng["next_rtu"]) == (2, 3, "18.1.20.171")     # trash counts as used
    assert d["months"][-1]["count"] == 1 and len(d["months"]) == 6 and d["recent"][0]["action"] == "Deleted"
    assert [a for a in d["areas"] if a["area"] == "UTMN"][0]["total"] == 1


def test_viewer_worksheet_flag(db_url):
    from fastapi.testclient import TestClient

    from app.db import make_engine
    from app.main import create_app
    from app.models import Base
    from tests.conftest import make_settings

    eng = make_engine(db_url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    application = create_app(make_settings(db_url, viewer_can_see_worksheet=False), eng)
    with TestClient(application):
        assert Api(application, login=False).get("/records").status_code == 403
        assert Api(application).get("/records").status_code == 200
    Base.metadata.drop_all(eng)
    eng.dispose()
