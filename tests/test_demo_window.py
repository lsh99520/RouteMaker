from datetime import date, timedelta

import pytest

from routemaker.engine import analyze
from routemaker.loader import DATA, JobPosting, Profile, _load, load_all

DAYS = [date(2026, 11, 20) + timedelta(days=k) for k in range((date(2026, 12, 7) - date(2026, 11, 20)).days + 1)]


@pytest.fixture(scope="module")
def real():
    d = load_all()
    d["profiles"] = {p.id: p for p in _load("profiles.json", Profile, DATA)}
    d["postings"] = {p.id: p for p in _load("postings.json", JobPosting, DATA)}
    return d


def run(d, pid, today, track=None):
    p = d["postings"][pid]
    if track:
        p = p.model_copy(update={"selected_track": track})
    return analyze(d["profiles"]["u1"], p, d["sessions"], today, d["exams"])


@pytest.mark.parametrize("today", DAYS, ids=str)
def test_demo_scenarios_hold_every_day_of_judging(real, today):
    for p in real["postings"].values():
        assert p.deadline.date() > date(2026, 12, 7)
    a = run(real, "p_a", today)
    toeic = next(e for e in a.exams if e.exam_id == "toeic")
    assert toeic.feasibility.value in ("possible", "conditional") and toeic.chosen
    assert toeic.chosen.result_date <= date(2027, 1, 15)
    if today >= date(2026, 11, 27):
        assert toeic.chosen.round == "제586회"
        assert any("제585회" in r and "해외 연수" in r for r in toeic.reasons)
    else:
        assert toeic.chosen.round == "제584회"
        assert "추가 접수" in " ".join(t.title for t in a.tasks)
    assert run(real, "p_b", today).conclusion.status == "impossible"
    c = run(real, "p_c", today)
    assert c.conclusion.status == "conditional" and c.exams[0].chosen.round.endswith("(예상)")
    assert run(real, "p_d", today, "전산").conclusion.status == "ready"
    assert run(real, "p_d", today).conclusion.status == "need_track"


def test_urgent_late_registration_headline(real):
    a = run(real, "p_a", date(2026, 11, 24))
    assert a.conclusion.headline.startswith("접수 마감이 임박했어요 — 2026-11-26까지 접수하면")
    assert "확정되지 않은" not in a.conclusion.headline
