from datetime import date

from fastapi.testclient import TestClient

from routemaker.api import create_app

TOEIC = "study:toeic:제583회"
SQLD = "study:sqld:2027년 1회차(예상)"


def fake(responses):
    calls = []

    def caller(system, user, tool, schema):
        calls.append(tool)
        r = responses.get(tool)
        if isinstance(r, Exception):
            raise r
        return r
    caller.calls = calls
    return caller


def client(tmp_path, monkeypatch, caller=None):
    monkeypatch.setenv("ROUTEMAKER_TODAY", "2026-10-20")
    return TestClient(create_app(tmp_path / "s.json", caller=caller))


def test_rule_draft_respects_constraints(tmp_path, monkeypatch):
    p = client(tmp_path, monkeypatch).get("/api/plan").json()
    by = {b["id"]: b for b in p["blocks"]}
    assert TOEIC in by and SQLD in by and "docs:p_a" in by
    t = by[TOEIC]
    assert t["end"] == "2026-11-14" and t["start"] >= "2026-10-20"
    assert "개인 일정" in t["note"]
    assert "docs:p_b" not in by and "docs:p_d" not in by
    assert any(w["kind"] == "personal" for w in p["warnings"])


def test_move_validation_and_warnings(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.put(f"/api/plan/blocks/{TOEIC}", json={"start": "2026-11-01", "end": "2026-11-20"})
    assert r.status_code == 400 and "11-14" in r.json()["detail"]
    r = c.put(f"/api/plan/blocks/{TOEIC}", json={"start": "2026-10-01", "end": "2026-10-30"})
    assert r.status_code == 400 and "이전" in r.json()["detail"]
    r = c.put(f"/api/plan/blocks/{SQLD}", json={"start": "2026-11-01", "end": "2026-11-20", "difficulty": "상"})
    assert r.status_code == 200
    kinds = {w["kind"] for w in r.json()["warnings"]}
    assert {"overload", "exam_day"} <= kinds
    moved = next(b for b in c.get("/api/plan").json()["blocks"] if b["id"] == SQLD)
    assert moved["start"] == "2026-11-01" and moved["source"] == "user" and moved["difficulty"] == "상"
    assert c.delete("/api/plan/blocks").status_code == 200
    back = next(b for b in c.get("/api/plan").json()["blocks"] if b["id"] == SQLD)
    assert back["source"] == "rule"


def test_strategy_changes_order_when_competing(tmp_path, monkeypatch):
    from datetime import timedelta
    from routemaker.planner import Block, draft
    t = date(2026, 10, 20)
    a = Block(id="a", kind="study", title="A", start=t, end=t, difficulty="하", anchor=date(2026, 12, 1),
              min_start=t, max_end=date(2026, 11, 30))
    b = Block(id="b", kind="study", title="B", start=t, end=t, difficulty="상", anchor=date(2026, 12, 5),
              min_start=t, max_end=date(2026, 12, 4))
    by_deadline = {x.id: x for x in draft({"a": a, "b": b}, "deadline")}
    by_diff = {x.id: x for x in draft({"a": a, "b": b}, "difficulty")}
    assert by_deadline["a"].end == date(2026, 11, 30)
    assert by_diff["b"].end == date(2026, 12, 4) and by_diff["a"].end < by_diff["b"].start
    assert "난이도순" in by_diff["a"].note


def test_ai_draft_validated_and_fallback(tmp_path, monkeypatch):
    caller = fake({"record_schedule": {"summary": "시험 준비가 겹치지 않게 나눴어요.", "blocks": [
        {"id": TOEIC, "start": "2026-10-21", "end": "2026-11-14", "reason": "시험 직전까지"},
        {"id": SQLD, "start": "2027-01-01", "end": "2027-04-01", "reason": "규칙 위반"},
        {"id": "없는블록", "start": "2027-01-01", "end": "2027-01-05", "reason": "x"}]}})
    c = client(tmp_path, monkeypatch, caller)
    r = c.post("/api/plan/draft", json={"strategy": "difficulty", "use_ai": True}).json()
    assert r["ai"] is True and "2개는" in r["message"]
    by = {b["id"]: b for b in r["plan"]["blocks"]}
    assert by[TOEIC]["source"] == "ai" and by[TOEIC]["start"] == "2026-10-21"
    assert by[SQLD]["source"] == "rule"
    assert r["plan"]["strategy"] == "difficulty"


def test_ai_draft_without_key_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client(tmp_path, monkeypatch).post("/api/plan/draft", json={"strategy": "deadline", "use_ai": True}).json()
    assert r["ai"] is False and "규칙 초안" in r["message"]
    assert all(b["source"] == "rule" for b in r["plan"]["blocks"])


def test_ai_feedback_suggestions_validated(tmp_path, monkeypatch):
    caller = fake({"record_feedback": {"summary": "SQLD를 TOEIC 시험 뒤로 미루면 부담이 줄어요.", "advice": [],
                                       "suggestions": [{"id": SQLD, "start": "2026-11-16", "end": "2026-12-06", "reason": "TOEIC 이후로"},
                                                       {"id": TOEIC, "start": "2026-11-10", "end": "2026-11-30", "reason": "규칙 위반"}]}})
    c = client(tmp_path, monkeypatch, caller)
    c.put(f"/api/plan/blocks/{SQLD}", json={"start": "2026-11-01", "end": "2026-11-20"})
    r = c.post("/api/plan/feedback", json={"action": {"type": "move", "block_id": SQLD}}).json()
    assert r["ai"] is True and len(r["suggestions"]) == 1 and r["suggestions"][0]["id"] == SQLD
    assert r["dropped"] == 1 and r["warnings"] and r["findings"]


def test_feedback_without_key_returns_rule_result(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client(tmp_path, monkeypatch).post("/api/plan/feedback", json={"action": {}}).json()
    assert r["ai"] is False and r["summary"] and "규칙 검사" in r["message"]


def test_stale_override_resets_to_draft(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    c.put(f"/api/plan/blocks/{TOEIC}", json={"start": "2026-10-25", "end": "2026-11-14"})
    prof = c.get("/api/profiles/u1").json()
    prof["fixed_schedule"].append({"title": "가족 행사", "start": "2026-11-15", "end": "2026-11-15"})
    c.put("/api/profiles/u1", json=prof)
    ids = {b["id"] for b in c.get("/api/plan").json()["blocks"]}
    assert TOEIC not in ids and "study:toeic:제584회" in ids


def _finding(r, kind):
    return [x for x in r["findings"] if x["kind"] == kind]


def test_ai_picks_choices_and_engine_checks_basis(tmp_path, monkeypatch):
    caller = fake({"record_feedback": {
        "overall": "조정 권장",
        "judgments": [{"finding_id": "f1", "judgment": "묶어서 진행 가능", "basis": ["같은 공고", "난이도 높음"]},
                      {"finding_id": "f2", "judgment": "분산 필요", "basis": ["시험 직전"]},
                      {"finding_id": "f99", "judgment": "문제 적음", "basis": []}],
        "suggestions": [{"id": "docs:p_a", "start": "2026-12-01", "end": "2026-12-10"}]}})
    c = client(tmp_path, monkeypatch, caller)
    c.put(f"/api/plan/blocks/{SQLD}", json={"start": "2026-11-01", "end": "2026-11-20", "difficulty": "상"})
    r = c.post("/api/plan/feedback", json={"action": {"type": "edit"}}).json()
    f = {x["id"]: x for x in r["findings"]}
    assert f["f1"]["kind"] == "overlap" and not f["f1"]["same_posting"]
    assert f["f1"]["judgment"] == "주의만 필요" and f["f1"]["basis"] == ["난이도 높음"]
    assert f["f2"]["kind"] == "exam_inside" and f["f2"]["judgment"] == "분산 필요" and f["f2"]["basis"] == ["시험 직전"]
    assert r["summary"] == "부담이 몰린 곳이 있어 조정을 권해요."
    assert r["dropped_claims"] >= 3
    assert r["suggestions"] == [] and r["dropped"] == 1


def test_overlap_finding_has_exact_range(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, fake({"record_feedback": {"summary": "", "advice": [], "suggestions": []}}))
    c.put(f"/api/plan/blocks/{TOEIC}", json={"start": "2026-10-20", "end": "2026-11-14"})
    c.put(f"/api/plan/blocks/{SQLD}", json={"start": "2026-11-05", "end": "2026-11-20"})
    r = c.post("/api/plan/feedback", json={"action": {}}).json()
    ov = _finding(r, "overlap")[0]
    assert "11/5~11/14, 10일" in ov["text"]
    assert r["summary"] == "몇 군데 지켜볼 곳이 있어요."


def test_no_overlap_means_no_overlap_finding(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, fake({"record_feedback": {"summary": "두 준비가 겹쳐요.", "advice": [], "suggestions": []}}))
    c.put(f"/api/plan/blocks/{TOEIC}", json={"start": "2026-10-20", "end": "2026-10-29"})
    c.put(f"/api/plan/blocks/{SQLD}", json={"start": "2026-11-01", "end": "2026-11-20"})
    r = c.post("/api/plan/feedback", json={"action": {}}).json()
    assert not any(TOEIC in x["block_ids"] and SQLD in x["block_ids"] for x in _finding(r, "overlap"))
    assert any(x["kind"] == "exam_inside" for x in r["findings"])


def test_improving_suggestion_reports_effect(tmp_path, monkeypatch):
    caller = fake({"record_feedback": {"summary": "SQLD를 TOEIC 시험 뒤로 미뤄요.", "advice": [],
                                       "suggestions": [{"id": SQLD, "start": "2026-11-16", "end": "2026-12-06", "reason": "TOEIC 이후로"}]}})
    c = client(tmp_path, monkeypatch, caller)
    c.put(f"/api/plan/blocks/{SQLD}", json={"start": "2026-11-01", "end": "2026-11-20", "difficulty": "상"})
    s = c.post("/api/plan/feedback", json={"action": {}}).json()["suggestions"][0]
    assert s["effect"]["score_after"] < s["effect"]["score_before"]


def test_bundle_allowed_only_for_same_posting(tmp_path, monkeypatch):
    caller = fake({"record_feedback": {"overall": "주의 필요", "suggestions": [],
                                       "judgments": [{"finding_id": "f1", "judgment": "묶어서 진행 가능", "basis": ["같은 공고"]}]}})
    c = client(tmp_path, monkeypatch, caller)
    c.put(f"/api/plan/blocks/{TOEIC}", json={"start": "2026-11-10", "end": "2026-11-14"})
    c.put("/api/plan/blocks/docs:p_a", json={"start": "2026-11-12", "end": "2026-11-20"})
    r = c.post("/api/plan/feedback", json={"action": {}}).json()
    f1 = next(x for x in r["findings"] if x["id"] == "f1")
    assert f1["same_posting"] is True and f1["judgment"] == "묶어서 진행 가능" and f1["basis"] == ["같은 공고"]


def test_effect_reports_personal_overlap_and_unchanged_bar_overlap(tmp_path, monkeypatch):
    caller = fake({"record_feedback": {"summary": "", "advice": [],
                                       "suggestions": [{"id": TOEIC, "start": "2026-11-10", "end": "2026-11-14", "reason": "겹침이 해결돼요"}]}})
    c = client(tmp_path, monkeypatch, caller)
    c.put(f"/api/plan/blocks/{TOEIC}", json={"start": "2026-11-03", "end": "2026-11-14"})
    c.put(f"/api/plan/blocks/{SQLD}", json={"start": "2026-11-10", "end": "2026-11-20"})
    r = c.post("/api/plan/feedback", json={"action": {}}).json()
    s = r["suggestions"][0]
    assert s["effect"]["personal_after"] < s["effect"]["personal_before"]
    assert s["effect"]["overlap_after"] == s["effect"]["overlap_before"]
    assert "해결" not in s["reason"]


def test_ai_suggestion_into_personal_schedule_is_dropped():
    from datetime import date
    from routemaker.models import FixedEvent
    from routemaker.planner import Block, Plan, ai_feedback
    trip = [FixedEvent(title="해외 연수", start=date(2026, 12, 10), end=date(2026, 12, 16))]
    study = Block(id="study:toeic:584", kind="study", title="TOEIC 준비", start=date(2026, 11, 21), end=date(2026, 11, 28),
                  difficulty="중", anchor=date(2026, 11, 29), min_start=date(2026, 11, 21), max_end=date(2026, 11, 28))
    docs = Block(id="docs:p_a", kind="docs", title="가상테크 지원서 작성", start=date(2026, 11, 22), end=date(2026, 11, 28),
                 difficulty="중", anchor=date(2027, 1, 15), min_start=date(2026, 11, 21), max_end=date(2027, 1, 14))
    plan = Plan(today=date(2026, 11, 21), strategy="deadline", blocks=[study, docs], warnings=[])

    def caller(*a, **k):
        return {"overall": "주의 필요", "judgments": [], "suggestions": [
            {"id": "docs:p_a", "start": "2026-12-13", "end": "2026-12-19", "reason": "겹침 해소"},
            {"id": "docs:p_a", "start": "2026-12-17", "end": "2026-12-23", "reason": "겹침 해소"}]}

    out = ai_feedback(plan, trip, {}, caller)
    assert [str(m["start"]) for m in out["suggestions"]] == ["2026-12-17"]
    assert out["dropped"] == 1
