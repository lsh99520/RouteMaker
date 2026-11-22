import json
from datetime import date, datetime

import httpx

from routemaker import qnet
from routemaker.engine import analyze
from routemaker.loader import load_all
from routemaker.models import Feasibility, JobPosting, Requirement

ROWS = [
    {"implYy": "2026", "implSeq": "1", "qualgbCd": "T", "qualgbNm": "국가기술자격", "description": "국가기술자격 기사 (2026년도 제1회)",
     "docRegStartDt": "20260112", "docRegEndDt": "20260115", "docExamStartDt": "20260207", "docExamEndDt": "20260303",
     "docPassDt": "20260311", "pracRegStartDt": "20260323", "pracRegEndDt": "20260326", "pracExamStartDt": "20260418",
     "pracExamEndDt": "20260508", "pracPassDt": "20260605"},
    {"implYy": "2026", "implSeq": "4", "qualgbCd": "T", "qualgbNm": "국가기술자격", "description": "국가기술자격 기사 (2026년도 제4회)",
     "docRegStartDt": "20261026", "docRegEndDt": "20261029", "docExamStartDt": "20261121", "docExamEndDt": "20261205",
     "docPassDt": "20261210", "pracRegStartDt": "20261214", "pracRegEndDt": "20261217", "pracExamStartDt": "20270109",
     "pracExamEndDt": "20270122", "pracPassDt": "20270212"},
    {"implYy": "2026", "implSeq": "1", "description": "국가기술자격 산업기사 (2026년도 제1회)",
     "docRegEndDt": "20260115", "docExamStartDt": "20260207", "pracPassDt": "20260605"},
    {"implYy": "2026", "implSeq": "9", "description": "국가기술자격 기사 (2026년도 제9회)", "docRegEndDt": "", "docExamStartDt": ""},
]


def payload(rows, code="00"):
    return {"response": {"header": {"resultCode": code, "resultMsg": "NORMAL SERVICE"},
                         "body": {"items": {"item": rows}, "numOfRows": 50, "pageNo": 1, "totalCount": len(rows)}}}


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_parses_two_stage_and_skips_others():
    seen = {}

    def h(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json=payload(ROWS))

    res = qnet.fetch("info_engineer", 2026, key="k", client=client(h))
    assert res["ok"]
    assert seen["jmCd"] == "1320" and seen["implYy"] == "2026" and seen["dataFormat"] == "json"
    s = res["data"]["sessions"]
    assert [x["round"] for x in s] == ["2026년 제1회", "2026년 제4회"]
    assert s[0]["result_date"] == "2026-06-05"
    assert s[0]["practical"]["reg_end"] == "2026-03-26"
    assert s[0]["practical"]["written_result_date"] == "2026-03-11"
    assert any("제9회" in x for x in res["data"]["skipped"])


def test_fetch_failures_are_returned_not_raised():
    assert qnet.fetch("info_engineer", 2026, key="")["error"]["code"] == "NO_KEY"
    assert qnet.fetch("toeic", 2026, key="k")["error"]["code"] == "UNSUPPORTED_EXAM"
    r = qnet.fetch("info_engineer", 2026, key="k", client=client(lambda req: httpx.Response(500)))
    assert r["error"]["code"] == "HTTP_ERROR"
    xml = "<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    r = qnet.fetch("info_engineer", 2026, key="k", client=client(lambda req: httpx.Response(200, text=xml)))
    assert r["error"]["code"] == "KEY_NOT_REGISTERED"
    r = qnet.fetch("info_engineer", 2026, key="k", client=client(lambda req: httpx.Response(200, json=payload([], "03"))))
    assert r["ok"] and r["data"]["sessions"] == []

    def boom(req):
        raise httpx.ConnectError("down")

    assert qnet.fetch("info_engineer", 2026, key="k", client=client(boom))["error"]["code"] == "NETWORK"


def test_key_not_in_error_messages():
    r = qnet.fetch("info_engineer", 2026, key="SECRET123", client=client(lambda req: httpx.Response(500)))
    assert "SECRET123" not in json.dumps(r)


def snapshot(tmp_path):
    sessions, _ = qnet.to_sessions(ROWS, "info_engineer", date(2026, 11, 20))
    path = tmp_path / "qnet.json"
    path.write_text(json.dumps({"fetched_at": "2026-11-20T10:00:00", "sessions": [s.model_dump(mode="json") for s in sessions]}), encoding="utf-8")
    return path


def test_broken_snapshot_is_ignored(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert qnet.load_snapshot(p) == []
    assert qnet.load_snapshot(tmp_path / "none.json") == []


def posting(deadline):
    return JobPosting(id="p_q", company="가상공사", title="전산직", deadline=deadline, deadline_quote="마감",
                      requirements=[Requirement(id="r1", type="required", category="certificate", text="정보처리기사",
                                                source_quote="정보처리기사", exam_id="info_engineer")])


def test_engine_uses_final_result_and_practical_tasks(tmp_path):
    d = load_all(snapshot(tmp_path))
    assert next(e for e in d["exams"] if e["exam_id"] == "info_engineer")["full_year_schedule"]
    prof = d["profiles"]["u1"].model_copy(update={"holdings": [], "fixed_schedule": []})
    a = analyze(prof, posting(datetime(2027, 3, 2, 17)), d["sessions"], date(2026, 10, 20), d["exams"])
    v = next(e for e in a.exams if e.exam_id == "info_engineer")
    assert v.feasibility == Feasibility.possible
    assert v.chosen.round == "2026년 제4회"
    assert any("실기" in n and "최종 발표 2027-02-12" in n for n in v.chosen.notes)
    titles = [t.title for t in a.tasks]
    assert any("실기 접수" in t and "2026-12-17" in t for t in titles)
    assert any("실기 응시" in t for t in titles)
    assert len({t.id for t in a.tasks}) == len(a.tasks)


def test_final_result_after_deadline_is_not_possible(tmp_path):
    d = load_all(snapshot(tmp_path))
    prof = d["profiles"]["u1"].model_copy(update={"holdings": [], "fixed_schedule": []})
    a = analyze(prof, posting(datetime(2026, 12, 18, 17)), d["sessions"], date(2026, 10, 20), d["exams"])
    v = next(e for e in a.exams if e.exam_id == "info_engineer")
    assert v.feasibility != Feasibility.possible


def test_practical_exam_conflict_is_detected(tmp_path):
    from routemaker.models import FixedEvent
    d = load_all(snapshot(tmp_path))
    trip = FixedEvent(title="해외 연수", start=date(2027, 1, 5), end=date(2027, 1, 12))
    prof = d["profiles"]["u1"].model_copy(update={"holdings": [], "fixed_schedule": [trip]})
    a = analyze(prof, posting(datetime(2027, 3, 2, 17)), d["sessions"], date(2026, 10, 20), d["exams"])
    v = next(e for e in a.exams if e.exam_id == "info_engineer")
    assert v.feasibility == Feasibility.impossible
    assert any("실기 시험 기간(2027-01-09~2027-01-22)이 개인 일정(해외 연수)" in r for r in v.reasons)


def test_regular_and_vacancy_rows_merge_into_one_round():
    rows = [dict(ROWS[0]), dict(ROWS[0], docRegStartDt="20260124", docRegEndDt="20260125")]
    s, _ = qnet.to_sessions(rows, "info_engineer", date(2026, 11, 20))
    assert len(s) == 1
    assert (s[0].reg_start, s[0].reg_end, s[0].late_reg_end) == (date(2026, 1, 12), date(2026, 1, 15), date(2026, 1, 25))
    assert "빈자리" in s[0].late_reg_note


def test_real_snapshot_has_three_rounds_in_2026():
    s = [x for x in qnet.load_snapshot() if x.round.startswith("2026")]
    assert [x.round for x in s] == ["2026년 제1회", "2026년 제2회", "2026년 제3회"]
    assert all(x.late_reg_end and x.practical for x in s)
