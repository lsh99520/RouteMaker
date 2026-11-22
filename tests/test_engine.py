from datetime import date, datetime, timedelta

from routemaker.engine import analyze, project_sessions
from routemaker.loader import load_all
from routemaker.models import Feasibility, MatchStatus, ScheduleStatus

TODAY = date(2026, 10, 20)
D = load_all()


def run(posting_id, profile_id="u1", today=TODAY, posting=None, sessions=None):
    p = posting or D["postings"][posting_id]
    return analyze(D["profiles"][profile_id], p, sessions or D["sessions"], today, D["exams"])


def exams(a):
    return {e.exam_id: e for e in a.exams}


def test_scenario_a_requirements():
    a = run("p_a")
    s = {r.requirement_id: r.status for r in a.requirements}
    assert s == {"r1": MatchStatus.pending, "r2": MatchStatus.unmet, "r3": MatchStatus.met,
                 "r4": MatchStatus.unmet, "r5": MatchStatus.pending}
    assert a.summary["required"] == "0/2 충족, 판단 보류 1건"
    assert a.summary["preferred"] == "1/3 충족, 판단 보류 1건"


def test_conflict_substitutes_next_round():
    v = exams(run("p_a"))["toeic"]
    assert v.feasibility == Feasibility.possible
    assert v.chosen.round == "제583회"
    assert any("해외 연수" in r and "제582회" in r for r in v.reasons)


def test_closed_registration_and_late_result_impossible():
    v = run("p_b").exams[0]
    assert v.feasibility == Feasibility.impossible
    assert any("제51회" in r and "접수 마감" in r for r in v.reasons)
    assert any("결과를 받을 수 있는 회차 없음" in r for r in v.reasons)


def test_reasons_are_short():
    v = run("p_b").exams[0]
    assert len(v.reasons) <= 5
    assert not any("제48회" in r for r in v.reasons)


def test_expected_next_year_is_conditional_with_announce_task():
    a = run("p_c")
    v = a.exams[0]
    assert v.feasibility == Feasibility.conditional
    assert v.chosen.status == ScheduleStatus.expected
    assert v.chosen.round.startswith("2027년 1회차")
    t = [t for t in a.tasks if t.kind == "announce_check"]
    assert t and "dataq" in t[0].title
    assert not [t for t in a.tasks if t.kind == "exam" and t.fixed]


def test_expected_near_miss_is_not_impossible():
    p = D["postings"]["p_c"].model_copy(update={"deadline": datetime(2027, 3, 20, 17)})
    v = run("p_c", posting=p).exams[0]
    assert v.feasibility == Feasibility.conditional
    assert v.chosen is None


def test_expected_far_miss_is_impossible():
    v = exams(run("p_a"))["sqld"]
    assert v.feasibility == Feasibility.impossible
    assert any("예상" in r for r in v.reasons)


def test_partial_year_exam_is_not_projected():
    p = D["postings"]["p_a"].model_copy(update={"deadline": datetime(2027, 3, 20, 17)})
    v = exams(run("p_a", posting=p, today=date(2026, 12, 24)))["toeic"]
    assert v.feasibility == Feasibility.no_data
    assert any("불가능하다는 뜻은 아님" in r for r in v.reasons)


def test_result_range_uses_latest_date():
    ranged = [s.model_copy(update={"result_date_latest": date(2026, 12, 8)})
              if s.exam_id == "sqld" and s.round == "제63회" else s for s in D["sessions"]]
    p = D["postings"]["p_c"].model_copy(update={"deadline": datetime(2026, 12, 6, 17)})
    v = run("p_c", posting=p, today=date(2026, 10, 1), sessions=ranged).exams[0]
    assert v.feasibility != Feasibility.possible or v.chosen.round != "제63회"
    p2 = p.model_copy(update={"deadline": datetime(2026, 12, 18, 17)})
    v2 = run("p_c", posting=p2, today=date(2026, 10, 1), sessions=ranged).exams[0]
    assert v2.chosen.round == "제63회"
    assert any("늦은 날짜 기준" in n for n in v2.chosen.notes)


def test_stale_schedule_adds_recheck_task():
    old = [s.model_copy(update={"checked_at": date(2026, 8, 1)}) for s in D["sessions"]]
    a = run("p_a", sessions=old)
    assert any(t.kind == "recheck" for t in a.tasks)
    assert exams(a)["toeic"].chosen.stale


def test_projection_only_after_last_confirmed():
    proj = [s for s in project_sessions(D["sessions"], {"sqld"}) if s.status == ScheduleStatus.expected]
    assert proj and all(s.exam_id == "sqld" and s.exam_date.year == 2027 for s in proj)


def test_deadline_change_recomputes():
    before = run("p_c", today=date(2026, 10, 1)).exams[0]
    assert before.chosen.round == "제63회"
    p = D["postings"]["p_c"].model_copy(update={"deadline": datetime(2026, 12, 3, 17)})
    after = run("p_c", posting=p, today=date(2026, 10, 1)).exams[0]
    assert after.feasibility == Feasibility.impossible


def test_conflict_with_fixed_schedule_excludes_round():
    p = D["postings"]["p_b"].model_copy(update={"deadline": datetime(2026, 11, 25, 18)})
    v = run("p_b", posting=p, today=date(2026, 9, 25)).exams[0]
    assert v.feasibility == Feasibility.impossible
    assert any("해외 연수" in r for r in v.reasons)


def test_registration_urgent_is_conditional():
    v = exams(run("p_a", today=date(2026, 10, 31)))["toeic"]
    assert v.chosen.round == "제583회"
    assert v.feasibility == Feasibility.conditional


def test_no_data_for_unknown_exam():
    p = D["postings"]["p_b"].model_copy(deep=True)
    p.requirements[0].exam_id = "unknown"
    assert run("p_b", posting=p).exams[0].feasibility == Feasibility.no_data


def test_tasks_sorted_and_today():
    a = run("p_a")
    dues = [t.due for t in a.tasks]
    assert dues == sorted(dues)
    titles = {t.id: t.title for t in a.tasks}
    assert any("요건 확인" in titles[i] for i in a.today_tasks)


def test_blocked_submit_flag():
    a = run("p_b")
    assert "재검토" in a.tasks[-1].title


def _profile_with(holdings):
    return D["profiles"]["u1"].model_copy(update={"holdings": holdings})


def _req_status(holdings, rid="r2", today=TODAY, posting="p_a"):
    from routemaker.models import Holding
    prof = _profile_with([Holding(**h) for h in holdings])
    a = analyze(prof, D["postings"][posting], D["sessions"], today, D["exams"])
    return next(r for r in a.requirements if r.requirement_id == rid)


def test_expired_toeic_is_unmet():
    r = _req_status([{"exam_id": "toeic", "score": 900, "acquired_date": "2024-01-10"}])
    assert r.status == MatchStatus.unmet and "만료" in r.reason


def test_toeic_expiring_before_deadline_is_pending():
    r = _req_status([{"exam_id": "toeic", "score": 900, "acquired_date": "2024-11-30"}])
    assert r.status == MatchStatus.pending and "만료" in r.reason


def test_valid_toeic_is_met():
    r = _req_status([{"exam_id": "toeic", "score": 900, "acquired_date": "2026-03-10"}])
    assert r.status == MatchStatus.met


def test_toeic_without_date_is_pending():
    r = _req_status([{"exam_id": "toeic", "score": 900, "acquired_date": None}])
    assert r.status == MatchStatus.pending


def test_old_sqld_needs_renewal_check():
    r = _req_status([{"exam_id": "sqld", "score": None, "acquired_date": "2023-06-01"}], rid="r4")
    assert r.status == MatchStatus.pending and "보수교육" in r.reason


def test_expired_toeic_triggers_exam_schedule():
    from routemaker.models import Holding
    prof = _profile_with([Holding(exam_id="toeic", score=900, acquired_date="2024-01-10")])
    a = analyze(prof, D["postings"]["p_a"], D["sessions"], TODAY, D["exams"])
    assert "toeic" in {e.exam_id for e in a.exams}


def test_conclusion_possible_with_plan_backup_and_confirm():
    a = run("p_a")
    c = a.conclusion
    assert c.status == "possible"
    assert any("제583회" in p and "800점 이상" in p and "현재 750점" in p for p in c.points)
    assert any("대안" in p and "제584회" in p and "추가 접수" in p for p in c.points)
    assert any(p.startswith("직접 확인 필요") and "학사" in p for p in c.points)
    assert any(p.startswith("우대 요건") and "SQLD 마감 전 취득 어려움" in p for p in c.points)


def test_conclusion_impossible_uses_key_reason():
    c = run("p_b").conclusion
    assert c.status == "impossible"
    assert c.points[0].startswith("ADsP: 마감 전에 결과를 받을 수 있는 회차 없음")
    assert "작년 일정" not in c.points[0]


def test_conclusion_conditional_for_expected_schedule():
    c = run("p_c").conclusion
    assert c.status == "conditional"
    assert "공고 전 예상 일정" in c.points[0]


def test_conclusion_ready_when_all_met():
    from routemaker.models import Holding
    prof = _profile_with([Holding(exam_id="toeic", score=850, acquired_date=date(2026, 3, 10)),
                          Holding(exam_id="info_engineer", acquired_date=date(2025, 6, 13))])
    a = analyze(prof, D["postings"]["p_a"], D["sessions"], TODAY, D["exams"])
    assert a.conclusion.status == "ready"
    assert "직접 확인할 요건 1개" in a.conclusion.headline


def test_target_score_and_backup_task():
    a = run("p_a")
    v = exams(a)["toeic"]
    assert v.min_score == 800 and v.current_score == 750
    assert v.backup is not None and v.backup.round == "제584회"
    titles = [t.title for t in a.tasks]
    assert "TOEIC 제583회 응시 (목표 800점 이상, 현재 750점)" in titles
    backup = [t for t in a.tasks if t.kind == "backup_register"]
    assert len(backup) == 1 and backup[0].title.startswith("(선택)") and not backup[0].fixed


def test_expired_score_not_counted_as_current():
    from routemaker.models import Holding
    prof = _profile_with([Holding(exam_id="toeic", score=900, acquired_date=date(2024, 1, 10))])
    a = analyze(prof, D["postings"]["p_a"], D["sessions"], TODAY, D["exams"])
    assert exams(a)["toeic"].current_score is None
    assert "현재" not in next(t.title for t in a.tasks if t.kind == "exam")


def _track(t):
    return run("p_d", posting=D["postings"]["p_d"].model_copy(update={"selected_track": t}))


def test_track_not_selected_judges_common_only():
    a = _track(None)
    assert a.conclusion.status == "need_track" and a.track is None
    assert {r.requirement_id for r in a.requirements} == {"r4"}


def test_track_switch_changes_verdict():
    it = _track("전산")
    assert it.conclusion.status == "ready" and it.track == "전산"
    assert {r.requirement_id for r in it.requirements} == {"r2", "r3", "r4"}
    adm = _track("행정")
    assert adm.conclusion.status == "possible"
    assert exams(adm)["toeic"].min_score == 850


def test_or_requirement_met_by_any_option():
    r2 = next(r for r in _track("전산").requirements if r.requirement_id == "r2")
    assert r2.status == MatchStatus.met and "정보처리기사" in r2.reason


def test_or_with_unlisted_option_goes_to_confirm():
    from routemaker.models import Holding
    prof = _profile_with([Holding(exam_id="toeic", score=750, acquired_date=date(2026, 3, 10))])
    p = D["postings"]["p_d"].model_copy(update={"selected_track": "전산"})
    a = analyze(prof, p, D["sessions"], TODAY, D["exams"])
    r2 = next(r for r in a.requirements if r.requirement_id == "r2")
    assert r2.status == MatchStatus.pending and "빅데이터분석기사" in r2.reason


def test_or_unmet_after_user_denies_picks_listed_option():
    from routemaker.models import Holding
    prof = _profile_with([Holding(exam_id="toeic", score=750, acquired_date=date(2026, 3, 10))])
    base = D["postings"]["p_d"]
    reqs = [r.model_copy(update={"user_confirmed": False}) if r.id == "r2" else r for r in base.requirements]
    a = analyze(prof, base.model_copy(update={"selected_track": "전산", "requirements": reqs}), D["sessions"], TODAY, D["exams"])
    assert "info_engineer" in exams(a)


def test_or_both_impossible_wording():
    v = exams(_track("전산"))["sqld"]
    assert v.option_names == ["SQLD", "ADsP"]
    assert "어느 선택지도" in v.reasons[0]
    assert any("SQLD 또는 ADsP 마감 전 취득 어려움" in p for p in _track("전산").conclusion.points)


def test_unknown_track_value_treated_as_common():
    base = D["postings"]["p_a"]
    reqs = [r.model_copy(update={"track": "없는분야"}) for r in base.requirements]
    a = analyze(D["profiles"]["u1"], base.model_copy(update={"requirements": reqs}), D["sessions"], TODAY, D["exams"])
    assert len(a.requirements) == len(base.requirements)


def test_no_auto_judgeable_required_is_manual_not_ready():
    from routemaker.models import JobPosting, Requirement
    reqs = [Requirement(id="r1", type="required", category="degree", text="졸업 예정자", source_quote="졸업 예정자"),
            Requirement(id="r2", type="required", category="experience", text="AI 활용 역량", source_quote="AI 활용 역량")]
    p = JobPosting(id="x", company="c", title="t", deadline=datetime(2026, 11, 24, 23, 59), deadline_quote="11. 24.", requirements=reqs)
    c = analyze(D["profiles"]["u1"], p, D["sessions"], TODAY, D["exams"]).conclusion
    assert c.status == "manual" and "직접 확인" in c.headline
    confirmed = [r.model_copy(update={"user_confirmed": True}) for r in reqs]
    c2 = analyze(D["profiles"]["u1"], p.model_copy(update={"requirements": confirmed}), D["sessions"], TODAY, D["exams"]).conclusion
    assert c2.status == "ready"


def test_late_registration_keeps_round_open():
    p = D["postings"]["p_a"].model_copy(update={"deadline": datetime(2026, 12, 31, 17)})
    a = run("p_a", posting=p, today=date(2026, 11, 19))
    v = exams(a)["toeic"]
    assert v.chosen.round == "제584회" and v.chosen.late
    assert v.chosen.reg_end == date(2026, 11, 26) and v.chosen.regular_reg_end == date(2026, 11, 16)
    assert any("추가 접수" in n for n in v.chosen.notes)
    assert any(t.kind == "exam_register" and "추가 접수" in t.title for t in a.tasks)


def test_after_late_registration_round_closes():
    p = D["postings"]["p_a"].model_copy(update={"deadline": datetime(2026, 12, 31, 17)})
    v = exams(run("p_a", posting=p, today=date(2026, 11, 27)))["toeic"]
    assert v.chosen.round != "제584회"


def test_backup_uses_late_registration_after_result():
    a = run("p_a")
    v = exams(a)["toeic"]
    assert v.chosen.round == "제583회" and v.backup.round == "제584회"
    assert any("추가 접수(2026-11-26까지)" in r and "결과(2026-11-24)를 보고" in r for r in v.reasons)
    t = next(t for t in a.tasks if t.kind == "backup_register")
    assert "추가 접수" in t.title and t.due == date(2026, 11, 26)


def _with_holdings(holdings):
    return D["profiles"]["u1"].model_copy(update={"holdings": holdings})


def test_blank_score_does_not_claim_no_exam_requirement():
    from routemaker.models import Holding
    prof = _with_holdings([Holding(exam_id="toeic", score=None, acquired_date=date(2026, 3, 10))])
    a = analyze(prof, D["postings"]["p_a"], D["sessions"], TODAY, D["exams"])
    assert a.conclusion.status == "manual"
    assert "일정으로 판정할 필수 요건이 없는" not in a.conclusion.headline
    assert "점수·날짜" in a.conclusion.headline


def test_future_acquired_date_is_not_counted_as_held():
    from routemaker.models import Holding
    prof = _with_holdings([Holding(exam_id="toeic", score=900, acquired_date=TODAY + timedelta(days=30))])
    a = analyze(prof, D["postings"]["p_a"], D["sessions"], TODAY, D["exams"])
    r2 = next(r for r in a.requirements if r.requirement_id == "r2")
    assert r2.status == MatchStatus.pending and "오늘 이후" in r2.reason


def test_closed_posting_says_deadline_passed_and_has_no_tasks():
    p = D["postings"]["p_a"]
    a = run("p_a", today=p.deadline.date() + timedelta(days=1))
    assert a.conclusion.status == "impossible"
    assert a.conclusion.headline.startswith(f"지원 마감({p.deadline.date()})이 지난 공고")
    assert a.tasks == [] and a.today_tasks == []
    on_day = run("p_a", today=p.deadline.date())
    assert "지난 공고" not in on_day.conclusion.headline
