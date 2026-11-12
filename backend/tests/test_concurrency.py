"""Simultaneous saves must never give two records the same host number or IP."""

import threading

from fastapi.testclient import TestClient

from app import engine as E
from tests.conftest import Api


def _clone(app, admin: Api) -> Api:
    other = Api(app, login=False)
    other.c = TestClient(app)
    other.c.cookies.update(admin.c.cookies)
    other.csrf = admin.csrf
    return other


def test_parallel_saves_same_range(app, admin):
    n = 12
    results: list[int] = []

    def worker(i: int):
        api = _clone(app, admin)
        for _ in range(40):                       # like the UI: on 409 take the new preview and confirm again
            p = api.preview(500 + i)
            if p.status_code != 200:
                continue
            r = api.save(500 + i, signature=p.json()["signature"])
            if r.status_code == 201:
                results.append(r.json()["host"])
                return
        results.append(-1)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == list(range(1, n + 1))            # one record per host number, none lost
    items = admin.get("/records?size=500").json()["items"]
    ips = [ip for r in items for f, ip in r["ips"].items() if f in E.UNIQ]
    assert len(items) == n and len(ips) == len(set(ips))


def test_two_saves_with_the_same_preview(app, admin):
    sig = {w: admin.preview(w).json()["signature"] for w in (1, 2)}      # both previews show host 1
    codes: dict[int, int] = {}

    def worker(w: int):
        codes[w] = _clone(app, admin).save(w, signature=sig[w]).status_code

    threads = [threading.Thread(target=worker, args=(w,)) for w in (1, 2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes.values()) == [201, 409]
    assert admin.get("/records").json()["total"] == 1
