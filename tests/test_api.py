from fastapi.testclient import TestClient

from routemaker.api import create_app
from tests.test_extract import GOOD, TEXT


def client(tmp_path, monkeypatch, raw=GOOD):
    monkeypatch.setenv("ROUTEMAKER_TODAY", "2026-10-20")
    return TestClient(create_app(tmp_path / "store.json", caller=lambda *a, **k: raw))


def test_seed_and_dashboard(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    d = c.get("/api/dashboard").json()
    assert {x["posting"]["id"] for x in d["postings"]} == {"p_a", "p_b", "p_c", "p_d"}
    assert d["nearest_deadline"]["id"] == "p_b"
    assert d["today_tasks"]


def test_extract_edit_analyze_check(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    e = c.post("/api/postings/extract", json={"text": TEXT}).json()
    assert e["deadline_verified"] and e["ai_generated"]
    pid = e["id"]
    e["requirements"][0]["user_confirmed"] = True
    c.put(f"/api/postings/{pid}", json=e)
    r = c.post(f"/api/postings/{pid}/analyze").json()
    assert r["analysis"]["requirements"][0]["status"] == "met"
    reg = [t for t in r["analysis"]["tasks"] if t["kind"] == "exam_register"]
    assert any("TOEIC 제583회 접수" in t["title"] for t in reg)
    tid = r["analysis"]["tasks"][0]["id"]
    p = c.patch(f"/api/tasks/{tid}", json={"done": True}).json()
    assert p["progress"]["done"] == 1
    again = c.post(f"/api/postings/{pid}/analyze").json()
    assert next(t for t in again["analysis"]["tasks"] if t["id"] == tid)["done"]


def test_missing_deadline_422_then_fix(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, {**GOOD, "deadline": None, "deadline_quote": None})
    e = c.post("/api/postings/extract", json={"text": TEXT}).json()
    assert c.post(f"/api/postings/{e['id']}/analyze").status_code == 422
    e["deadline"] = "2027-01-29T17:00:00"
    fixed = c.put(f"/api/postings/{e['id']}", json=e).json()
    assert fixed["deadline_verified"]
    assert c.post(f"/api/postings/{e['id']}/analyze").status_code == 200


def test_empty_text_400(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post("/api/postings/extract", json={"text": "  "}).status_code == 400


def test_persists_across_restart(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    e = c.post("/api/postings/extract", json={"text": TEXT}).json()
    c2 = client(tmp_path, monkeypatch)
    c2.cookies.set("rm_uid", c.cookies.get("rm_uid"))
    assert c2.get(f"/api/postings/{e['id']}").status_code == 200
    assert client(tmp_path, monkeypatch).get(f"/api/postings/{e['id']}").status_code == 404


def test_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTEMAKER_RPM", "2")
    c = client(tmp_path, monkeypatch)
    codes = [c.post("/api/postings/extract", json={"text": TEXT}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_visitors_are_isolated_and_reset(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    a, b = {"X-RM-User": "visitor_aaaa1111"}, {"X-RM-User": "visitor_bbbb2222"}
    assert c.delete("/api/postings/p_a", headers=a).status_code == 200
    assert c.get("/api/postings/p_a", headers=a).status_code == 404
    assert c.get("/api/postings/p_a", headers=b).status_code == 200
    prof = c.get("/api/profiles/u1", headers=a).json()
    prof["name"] = "바뀐 이름"
    c.put("/api/profiles/u1", json=prof, headers=a)
    assert c.get("/api/profiles/u1", headers=b).json()["name"] != "바뀐 이름"
    c.post("/api/reset", headers=a)
    assert c.get("/api/postings/p_a", headers=a).status_code == 200
    assert c.get("/api/profiles/u1", headers=a).json()["name"] != "바뀐 이름"


def test_invalid_user_header_falls_back(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.get("/api/postings", headers={"X-RM-User": "../../etc"}).status_code == 200


def test_old_store_format_is_ignored(tmp_path, monkeypatch):
    (tmp_path / "store.json").write_text('{"profiles": {}, "postings": {}, "analyses": {}, "done": {}}', encoding="utf-8")
    c = client(tmp_path, monkeypatch)
    assert {p["id"] for p in c.get("/api/postings").json()} == {"p_a", "p_b", "p_c", "p_d"}


def test_cookie_identifies_visitor(tmp_path):
    from fastapi.testclient import TestClient
    from routemaker.api import create_app
    app = create_app(tmp_path / "s.json")
    a, b = TestClient(app), TestClient(app)
    r = a.get("/api/postings")
    uid = r.cookies.get("rm_uid")
    assert uid and len(uid) >= 8
    r2 = a.get("/api/postings")
    assert "rm_uid" not in r2.headers.get("set-cookie", "")
    assert a.delete("/api/postings/p_a").status_code == 200
    assert a.get("/api/postings/p_a").status_code == 404
    assert b.get("/api/postings/p_a").status_code == 200
    assert b.cookies.get("rm_uid") != uid
    a.post("/api/reset")
    assert a.get("/api/postings/p_a").status_code == 200


def test_legacy_header_moves_to_cookie(tmp_path):
    from fastapi.testclient import TestClient
    from routemaker.api import create_app
    app = create_app(tmp_path / "s.json")
    old = {"X-RM-User": "visitor_legacy01"}
    c = TestClient(app)
    assert c.delete("/api/postings/p_a", headers=old).status_code == 200
    assert c.cookies.get("rm_uid") == "visitor_legacy01"
    assert c.get("/api/postings/p_a").status_code == 404
    assert TestClient(app).get("/api/postings/p_a").status_code == 200


def test_today_fixed_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTEMAKER_TODAY", "2026-10-20")
    c = TestClient(create_app(tmp_path / "s.json"))
    d = c.get("/api/dashboard").json()
    assert d["today_fixed"] is True
    assert d["postings"][0]["analysis"]["today_fixed"] is True
    assert d["postings"][0]["analysis"]["conclusion"]["status"]
    monkeypatch.delenv("ROUTEMAKER_TODAY")
    assert TestClient(create_app(tmp_path / "t.json")).get("/api/health").json()["today_fixed"] is False


def test_analysis_available_on_direct_open(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.get("/api/postings/p_a/analysis")
    assert r.status_code == 200 and r.json()["analysis"]["conclusion"]["status"] == "possible"


def test_track_selection_via_put(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    p = c.get("/api/postings/p_d").json()
    assert p["tracks"] == ["행정", "전산"]
    assert c.get("/api/postings/p_d/analysis").json()["analysis"]["conclusion"]["status"] == "need_track"
    p["selected_track"] = "전산"
    assert c.put("/api/postings/p_d", json=p).json()["selected_track"] == "전산"
    assert c.get("/api/postings/p_d/analysis").json()["analysis"]["conclusion"]["status"] == "ready"
    p["selected_track"] = "없는분야"
    p["requirements"][0]["track"] = "없는분야"
    out = c.put("/api/postings/p_d", json=p).json()
    assert out["selected_track"] is None and out["requirements"][0]["track"] is None


def test_calendar_export(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.get("/api/postings/p_a/calendar.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert body.count("BEGIN:VEVENT") == len(c.get("/api/postings/p_a/analysis").json()["analysis"]["tasks"])
    assert "DTSTART;VALUE=DATE:20261115" in body
    assert all(len(l.encode("utf-8")) <= 75 for l in body.split("\r\n"))
    unfolded = body.replace("\r\n ", "")
    assert "SUMMARY:TOEIC 제583회 응시 (목표 800점 이상\\, 현재 750점)" in unfolded
    tid = c.get("/api/postings/p_a/analysis").json()["analysis"]["tasks"][0]["id"]
    c.patch(f"/api/tasks/{tid}", json={"done": True})
    assert c.get("/api/postings/p_a/calendar.ics").text.count("BEGIN:VEVENT") == body.count("BEGIN:VEVENT") - 1


def test_screen_is_revalidated_every_time(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_profile_rejects_out_of_range_score_and_reversed_schedule(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    p = c.get("/api/profiles/u1").json()
    for bad in (1200, -5, 5):
        h = [{"exam_id": "toeic", "score": bad, "acquired_date": "2026-03-10"}]
        r = c.put("/api/profiles/u1", json={**p, "holdings": h})
        assert r.status_code == 400 and "10~990점" in r.json()["detail"]
    ok = [{"exam_id": "toeic", "score": 990, "acquired_date": "2026-03-10"}]
    assert c.put("/api/profiles/u1", json={**p, "holdings": ok}).status_code == 200
    rev = [{"title": "연수", "start": "2026-12-16", "end": "2026-12-10"}]
    r = c.put("/api/profiles/u1", json={**p, "fixed_schedule": rev})
    assert r.status_code == 400 and "종료일" in r.json()["detail"]
    assert c.get("/api/profiles/u1").json()["holdings"] == ok


def test_posting_edit_rejects_out_of_range_min_score(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    e = c.get("/api/postings/p_a").json()
    r2 = next(r for r in e["requirements"] if r["exam_id"] == "toeic")
    r2["min_score"] = 9000
    r = c.put("/api/postings/p_a", json=e)
    assert r.status_code == 400 and "기준 점수" in r.json()["detail"]
    r2["min_score"] = 850
    assert c.put("/api/postings/p_a", json=e).status_code == 200


def test_llm_failure_shows_friendly_message_not_internal_detail(tmp_path, monkeypatch):
    from routemaker.llm import LLMError, UNAVAILABLE

    def broken(*a, **k):
        raise LLMError(UNAVAILABLE)
    monkeypatch.setenv("ROUTEMAKER_TODAY", "2026-10-20")
    c = TestClient(create_app(tmp_path / "store.json", caller=broken))
    r = c.post("/api/postings/extract", json={"text": TEXT})
    assert r.status_code == 502 and r.json()["detail"] == UNAVAILABLE
    assert ".env" not in r.text and "ANTHROPIC" not in r.text


def test_no_api_key_message_is_for_users(monkeypatch):
    import pytest
    from routemaker import llm
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.LLMError) as e:
        llm.call_tool("s", "u", "t", {"type": "object"})
    assert str(e.value) == llm.UNAVAILABLE


def test_daily_limit_is_per_device_and_global():
    import pytest
    from fastapi import HTTPException
    from routemaker.api import RateLimiter
    lim = RateLimiter(per_minute=100, per_day=5, per_key_day=2)
    lim.check("a"); lim.check("a")
    with pytest.raises(HTTPException) as e:
        lim.check("a")
    assert "이 기기" in e.value.detail
    lim.check("b"); lim.check("b"); lim.check("c")
    with pytest.raises(HTTPException):
        lim.check("d")


def test_first_page_visit_sets_cookie_so_parallel_api_calls_share_one_user(tmp_path, monkeypatch):
    import json
    c = client(tmp_path, monkeypatch)
    r = c.get("/")
    assert "rm_uid" in r.cookies
    for path in ("/api/profiles", "/api/postings", "/api/plan"):
        c.get(path)
    assert len(json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))["users"]) == 1
