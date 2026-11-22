from datetime import date, timedelta

from typing import Optional

from .models import (
    Analysis, Conclusion, ExamSession, ExamVerdict, Feasibility, JobPosting, MatchStatus,
    Profile, ReqCategory, ReqType, Requirement, RequirementResult, ScheduleStatus, SessionCheck, Task,
)

URGENT_DAYS = 3
SUBMIT_BUFFER_DAYS = 1
STALE_DAYS = 30
ANNOUNCE_LEAD_DAYS = 30
EXPECTED_MARGIN_DAYS = 30


def _plus_year(d: Optional[date]) -> Optional[date]:
    if d is None:
        return None
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def _plus_year_practical(p):
    if p is None:
        return None
    return p.model_copy(update={
        "written_result_date": _plus_year(p.written_result_date), "reg_start": _plus_year(p.reg_start),
        "reg_end": _plus_year(p.reg_end), "exam_date": _plus_year(p.exam_date), "exam_end": _plus_year(p.exam_end),
    })


def project_sessions(sessions: list[ExamSession], full_year: Optional[set] = None) -> list[ExamSession]:
    out = list(sessions)
    full_year = full_year if full_year is not None else {s.exam_id for s in sessions}
    for exam_id in {s.exam_id for s in sessions} & full_year:
        confirmed = [s for s in sessions if s.exam_id == exam_id and s.status == ScheduleStatus.confirmed]
        if not confirmed:
            continue
        last = max(s.exam_date for s in confirmed)
        latest_year = last.year
        base_year = sorted((s for s in confirmed if s.exam_date.year == latest_year), key=lambda s: s.exam_date)
        for idx, s in enumerate(base_year, 1):
            nxt = _plus_year(s.exam_date)
            if nxt <= last:
                continue
            out.append(s.model_copy(update={
                "round": f"{nxt.year}년 {idx}회차(예상)",
                "reg_start": _plus_year(s.reg_start), "reg_end": _plus_year(s.reg_end),
                "late_reg_end": _plus_year(s.late_reg_end),
                "exam_date": nxt, "result_date": _plus_year(s.result_date),
                "result_date_latest": _plus_year(s.result_date_latest),
                "practical": _plus_year_practical(s.practical),
                "status": ScheduleStatus.expected,
                "source": f"{latest_year}년 공식 일정 기준 추정 — 공고 전",
            }))
    return out


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def match_requirement(req: Requirement, profile: Profile, today: date,
                      deadline: Optional[date] = None, catalog: Optional[dict] = None) -> RequirementResult:
    def result(status, reason):
        return RequirementResult(requirement_id=req.id, type=req.type, text=req.text, status=status, reason=reason)

    if req.user_confirmed is not None:
        return result(MatchStatus.met if req.user_confirmed else MatchStatus.unmet, "사용자가 직접 확인한 항목")

    if not req.quote_verified:
        return result(MatchStatus.pending, "AI 추출 근거가 공고 원문에서 확인되지 않음 — 사용자 확인 필요")

    if req.options:
        return result(*_match_any(req.options, profile, today, deadline, catalog))

    if req.exam_id is None:
        return result(MatchStatus.pending, "자동 판정 기준이 없는 요건 — 사용자 확인 필요")

    return result(*_match_exam(req.exam_id, req.min_score, profile, today, deadline, catalog))


def _match_any(options, profile: Profile, today: date, deadline: Optional[date], catalog: Optional[dict]):
    known = [o for o in options if o.exam_id]
    unknown = [o.name for o in options if not o.exam_id]
    checks = [(o, *_match_exam(o.exam_id, o.min_score, profile, today, deadline, catalog)) for o in known]
    met = [o for o, st, _ in checks if st == MatchStatus.met]
    if met:
        return MatchStatus.met, f"선택 요건 중 {met[0].name} 충족"
    pend = [(o, why) for o, st, why in checks if st == MatchStatus.pending]
    if pend:
        o, why = pend[0]
        return MatchStatus.pending, f"{o.name}: {why}"
    if unknown:
        msg = f"{', '.join(unknown)}은(는) 자동 판정 목록에 없음 — 보유 여부 직접 확인"
        if known:
            msg += f". 없다면 {', '.join(o.name for o in known)} 취득 필요 — 직접 확인에서 '미충족'을 고르면 취득 일정을 판정"
        return MatchStatus.pending, msg
    detail = "; ".join(f"{o.name} {why}" for o, _, why in checks)
    return MatchStatus.unmet, f"선택 요건 모두 미충족 ({detail})"


def _match_exam(exam_id: str, min_score: Optional[float], profile: Profile, today: date,
                deadline: Optional[date], catalog: Optional[dict]):
    def result(status, reason):
        return status, reason

    held = [h for h in profile.holdings if h.exam_id == exam_id]
    if not held:
        return result(MatchStatus.unmet, "보유 목록에 없음")
    future = [h for h in held if h.acquired_date and h.acquired_date > today]
    if len(future) == len(held):
        return result(MatchStatus.pending, f"시험일(취득일)이 오늘 이후({min(h.acquired_date for h in future)})로 입력됨 — 날짜 확인 필요")
    held = [h for h in held if h not in future]

    info = (catalog or {}).get(exam_id, {})
    valid_years = info.get("valid_years")
    renewal_years = info.get("renewal_years")
    deadline = deadline or today
    if valid_years:
        dated = [h for h in held if h.acquired_date]
        if not dated:
            return result(MatchStatus.pending, f"시험일(취득일)이 없어 유효기간 확인 불가 — {info.get('validity_note', '')}".rstrip(" —"))
        alive = [h for h in dated if _add_years(h.acquired_date, valid_years) >= today]
        if not alive:
            last = max(dated, key=lambda h: h.acquired_date)
            return result(MatchStatus.unmet, f"보유 성적 만료({_add_years(last.acquired_date, valid_years)}) — 새 성적 필요")
        held = alive
    if renewal_years:
        old = [h for h in held if h.acquired_date and _add_years(h.acquired_date, renewal_years) < deadline]
        if old and len(old) == len(held):
            return result(MatchStatus.pending, f"취득 후 {renewal_years}년 경과 — 보수교육 이수 여부 확인 필요({info.get('validity_note', '')})")

    if min_score is None:
        if valid_years:
            exp = _add_years(max(h.acquired_date for h in held), valid_years)
            if exp < deadline:
                return result(MatchStatus.pending, f"보유 성적이 {exp}에 만료 — 지원 마감({deadline}) 전 만료, 성적 인정 기준 확인 필요")
        return result(MatchStatus.met, "보유 확인")

    scored = [h for h in held if h.score is not None]
    if not scored:
        return result(MatchStatus.pending, "보유는 확인됐으나 점수 정보 없음")
    passing = [h for h in scored if h.score >= min_score]
    if not passing:
        best = max(h.score for h in scored)
        return result(MatchStatus.unmet, f"보유 점수 {best:g} < 기준 {min_score:g}")
    best = max(passing, key=lambda h: h.score)
    if valid_years and best.acquired_date:
        expires = _add_years(best.acquired_date, valid_years)
        if expires < deadline:
            return result(MatchStatus.pending,
                          f"보유 점수 {best.score:g} ≥ 기준이나 {expires}에 만료 — 지원 마감({deadline}) 전 만료, 공고의 성적 인정 기준 확인 필요")
    return result(MatchStatus.met, f"보유 점수 {best.score:g} ≥ 기준 {min_score:g}")


def _overlaps(day: date, start: date, end: date) -> bool:
    return start <= day <= end


def _conflict_text(c) -> str:
    written = [x for x in c.conflicts if not x.endswith("(실기)")]
    prac = [x.removesuffix("(실기)") for x in c.conflicts if x.endswith("(실기)")]
    parts = []
    if written:
        parts.append(f"시험일({c.exam_date})이 개인 일정({', '.join(written)})")
    if prac and c.practical:
        p = c.practical
        period = f"{p.exam_date}" + (f"~{p.exam_end}" if p.exam_end and p.exam_end != p.exam_date else "")
        parts.append(f"실기 시험 기간({period})이 개인 일정({', '.join(prac)})")
    return ", ".join(parts)


def check_session(s: ExamSession, profile: Profile, deadline: date, today: date) -> SessionCheck:
    conflicts = [e.title for e in profile.fixed_schedule if _overlaps(s.exam_date, e.start, e.end)]
    p = s.practical
    if p:
        days = [p.exam_date + timedelta(days=i) for i in range(((p.exam_end or p.exam_date) - p.exam_date).days + 1)]
        conflicts += [f"{e.title}(실기)" for e in profile.fixed_schedule if any(_overlaps(d, e.start, e.end) for d in days)]
    notes = []
    usable = True
    result_by = s.result_by
    expected = s.status == ScheduleStatus.expected
    if expected:
        notes.append("공고 전 예상 일정 — 실제 날짜는 공고 후 확정")
    reg_end, late = s.reg_end, False
    if s.reg_end < today and s.late_reg_end and s.late_reg_end >= today:
        reg_end, late = s.late_reg_end, True
        notes.append(f"정기 접수 마감({s.reg_end}) — 추가 접수 {s.late_reg_end}까지 가능({s.late_reg_note or '응시료가 더 비쌀 수 있음'})")
    elif s.reg_end < today:
        usable = False
        notes.append(f"접수 마감 지남({s.late_reg_end or s.reg_end})")
    elif s.late_reg_end and s.late_reg_end > s.reg_end:
        notes.append(f"정기 접수 {s.reg_end} 마감, 놓치면 추가 접수 {s.late_reg_end}까지" + (f"({s.late_reg_note})" if s.late_reg_note else ""))
    if result_by > deadline:
        usable = False
        notes.append(f"결과 발표({result_by})가 지원 마감({deadline}) 이후")
    elif result_by == deadline:
        notes.append("결과 발표일이 지원 마감일과 같음 — 발표 시각 확인 필요")
    if s.result_date_latest and s.result_date_latest != s.result_date:
        notes.append(f"출처마다 발표일이 다름({s.result_date}~{s.result_date_latest}) — 늦은 날짜 기준으로 판정")
    if usable and s.reg_start and s.reg_start > today:
        notes.append(f"접수 시작 전 — {s.reg_start}부터 접수 가능")
    stale = not expected and (today - s.checked_at).days > STALE_DAYS
    if stale:
        notes.append(f"일정 확인 후 {(today - s.checked_at).days}일 지남 — 공식 사이트 재확인 필요")
    if s.is_synthetic:
        notes.append("합성 일정 — 실제 일정 아님")
    if p:
        period = f"{p.exam_date}" + (f"~{p.exam_end}" if p.exam_end and p.exam_end != p.exam_date else "")
        notes.append(f"필기 합격 발표 {p.written_result_date} → 실기 접수 {p.reg_start or ''}~{p.reg_end} → 실기 {period} → 최종 발표 {s.result_date} (필기·실기 모두 합격해야 취득)")
    return SessionCheck(
        exam_id=s.exam_id, round=s.round, exam_date=s.exam_date, reg_start=s.reg_start, reg_end=reg_end,
        regular_reg_end=s.reg_end, late_reg_end=s.late_reg_end, late_reg_note=s.late_reg_note, late=late,
        result_date=s.result_date, result_date_latest=s.result_date_latest, status=s.status, stale=stale,
        usable=usable, conflicts=conflicts, notes=notes, practical=p,
    )


def verify_exam(req: Requirement, profile: Profile, posting: JobPosting,
                sessions: list[ExamSession], today: date, full_year: Optional[set] = None) -> ExamVerdict:
    deadline = posting.deadline.date()
    mine = sorted([s for s in project_sessions(sessions, full_year) if s.exam_id == req.exam_id],
                  key=lambda s: (s.exam_date, s.status != ScheduleStatus.confirmed))
    name = mine[0].exam_name if mine else req.exam_id

    def verdict(f, reasons, chosen=None, alts=()):
        return ExamVerdict(requirement_id=req.id, exam_id=req.exam_id, exam_name=name,
                           feasibility=f, chosen=chosen, alternatives=list(alts), reasons=reasons)

    if not mine:
        return verdict(Feasibility.no_data, ["등록된 시험 일정 데이터 없음 — 판정 보류"])

    checks = [check_session(s, profile, deadline, today) for s in mine]
    usable = [c for c in checks if c.usable]
    known_until = max(s.exam_date for s in mine)
    if not usable:
        if known_until < deadline:
            return verdict(Feasibility.no_data, [
                f"확인된 마지막 회차는 {known_until} 시험 — 그 이후 지원 마감({deadline}) 전 회차 일정 데이터 없음",
                "일정이 없을 뿐 불가능하다는 뜻은 아님 — 공식 일정 확인 필요",
            ])
        reasons = _impossible_reasons(checks, today, deadline)
        upcoming = [c for c in checks if c.reg_end >= today]
        if upcoming and upcoming[0].status == ScheduleStatus.expected:
            gap = ((upcoming[0].result_date_latest or upcoming[0].result_date) - deadline).days
            if gap <= EXPECTED_MARGIN_DAYS:
                return verdict(Feasibility.conditional, [
                    f"{upcoming[0].round} 결과 발표가 예상 기준 마감보다 {gap}일 늦음",
                    "공고 전 예상 일정이라 실제 일정이 앞당겨지면 가능할 수 있음 — 공고 후 재판정 필요",
                ])
        if any(c.status == ScheduleStatus.expected for c in checks):
            reasons.append("공고 전 회차는 작년 일정 기준 예상 — 공고 후 재확인 필요")
        return verdict(Feasibility.impossible, reasons)

    clear = [c for c in usable if not c.conflicts]
    if not clear:
        reasons = [f"{c.round} {_conflict_text(c)}과 겹침" for c in usable]
        reasons.append("마감 전 결과가 나오는 회차가 모두 개인 일정과 충돌 — 일정 조정 필요")
        return verdict(Feasibility.impossible, reasons, alts=usable)

    chosen = clear[0]
    result_by = chosen.result_date_latest or chosen.result_date
    reasons = [f"{chosen.round} 응시 시 결과 발표 {result_by}, 지원 마감 {deadline}"]
    skipped = [c for c in usable if c.conflicts and c.exam_date < chosen.exam_date]
    for c in skipped:
        reasons.append(f"{c.round} {_conflict_text(c)}과 겹쳐 제외 → {chosen.round} 선택")
    expected = chosen.status == ScheduleStatus.expected
    urgent = (chosen.reg_end - today).days <= URGENT_DAYS
    conditional = result_by == deadline or urgent or expected
    if urgent:
        reasons.append(f"{'추가 ' if chosen.late else ''}접수 마감 임박({chosen.reg_end})")
    if expected:
        reasons.append("아직 공고되지 않은 회차 — 작년 일정 기준 예상이므로 공고 후 날짜 확인 필요")
    alts = [c for c in clear[1:]]
    backup = alts[0] if alts else None
    if backup:
        reasons.append(_backup_reason(chosen, backup))
    v = verdict(Feasibility.conditional if conditional else Feasibility.possible, reasons, chosen, alts)
    v.backup = backup
    return v


def _result_by(c: SessionCheck) -> date:
    return c.result_date_latest or c.result_date


def _late_ok(b: SessionCheck, chosen: SessionCheck) -> bool:
    return bool(b.late_reg_end and b.late_reg_end >= _result_by(chosen))


def _backup_reason(chosen: SessionCheck, b: SessionCheck) -> str:
    tag = " — 공고 전 예상 일정" if b.status == ScheduleStatus.expected else ""
    if b.reg_end < _result_by(chosen) and _late_ok(b, chosen):
        return (f"대안: {chosen.round} 결과가 기준에 못 미치면 {b.round}"
                f"(시험 {b.exam_date}, 결과 {_result_by(b)})로 한 번 더 가능{tag}. 정기 접수는 {b.reg_end}에 끝나지만 "
                f"추가 접수({b.late_reg_end}까지)로 {chosen.round} 결과({_result_by(chosen)})를 보고 접수할 수 있음({b.late_reg_note or '응시료가 더 비쌀 수 있음'})")
    if b.reg_end < _result_by(chosen):
        return (f"대안: {b.round}(시험 {b.exam_date}, 결과 {_result_by(b)})도 마감 전에 결과가 나옴{tag}. "
                f"다만 {chosen.round} 결과({_result_by(chosen)}) 전에 접수가 마감({b.reg_end})되므로, "
                f"한 번에 기준을 넘기기 어렵다면 미리 접수해 두는 것이 안전")
    return (f"대안: {chosen.round} 결과가 기준에 못 미치면 {b.round}"
            f"(접수 마감 {b.reg_end}, 시험 {b.exam_date}, 결과 {_result_by(b)})로 한 번 더 가능{tag}")


def _impossible_reasons(checks: list[SessionCheck], today: date, deadline: date) -> list[str]:
    reasons = []
    closed = [c for c in checks if c.reg_end < today]
    if closed:
        last = closed[-1]
        reasons.append(f"접수 가능한 회차가 지남 — 가장 최근 {last.round} 접수 마감 {last.reg_end}" + (f"(추가 접수 {last.late_reg_end})" if last.late_reg_end else ""))
        if (last.result_date_latest or last.result_date) > deadline:
            reasons.append(f"{last.round}에 응시했더라도 결과 발표({last.result_date_latest or last.result_date})가 마감 이후")
    upcoming = [c for c in checks if c.reg_end >= today]
    if upcoming:
        nxt = upcoming[0]
        reasons.append(f"다음 회차 {nxt.round} 결과 발표({nxt.result_date_latest or nxt.result_date})가 지원 마감({deadline}) 이후")
    reasons.append("지원 마감 전에 결과를 받을 수 있는 회차 없음")
    return reasons


def build_tasks(posting: JobPosting, verdicts: list[ExamVerdict],
                reqs: list[RequirementResult], today: date, hints: Optional[dict] = None) -> list[Task]:
    hints = hints or {}
    deadline = posting.deadline.date()
    tasks: list[Task] = []

    def add(key, title, due, kind, fixed, tid=None):
        tasks.append(Task(id=f"{posting.id}:{kind}:{tid or key}", title=title, due=due, kind=kind, priority=0, fixed=fixed))

    for v in verdicts:
        c = v.chosen
        if c is None and v.feasibility in (Feasibility.no_data, Feasibility.conditional):
            hint = hints.get(v.exam_id)
            add(v.exam_id, f"{v.exam_name} 공식 일정 확인 후 다시 판정" + (f" ({hint})" if hint else ""), today, "announce_check", False)
        if c is None:
            continue
        key = f"{v.exam_id}:{c.round}"
        expected = c.status == ScheduleStatus.expected
        if expected:
            first = c.reg_start or c.reg_end
            due = max(today, first - timedelta(days=ANNOUNCE_LEAD_DAYS))
            hint = hints.get(v.exam_id)
            add(key, f"{v.exam_name} 공식 일정 공고 확인" + (f" ({hint})" if hint else ""), due, "announce_check", False)
        elif c.stale:
            add(key, f"{v.exam_name} {c.round} 일정 공식 사이트 재확인", today, "recheck", False)
        reg = f"{v.exam_name} {c.round} 접수 (마감 {c.reg_end})"
        if c.late:
            reg = f"{v.exam_name} {c.round} 추가 접수 (마감 {c.reg_end}, 정기 접수는 {c.regular_reg_end} 마감)"
        if c.reg_start and c.reg_start > today:
            reg = f"{v.exam_name} {c.round} 접수 ({c.reg_start} 시작 ~ {c.reg_end} 마감)"
        add(key, reg, c.reg_end, "exam_register", not expected)
        if c.practical:
            pr = c.practical
            add(key, f"{v.exam_name} {c.round} 필기 응시", c.exam_date, "exam", not expected)
            add(key, f"{v.exam_name} {c.round} 실기 접수 (필기 합격 발표 {pr.written_result_date}, 마감 {pr.reg_end})", pr.reg_end, "exam_register", not expected, key + ":실기")
            add(key, f"{v.exam_name} {c.round} 실기 응시", pr.exam_date, "exam", not expected, key + ":실기")
            add(key, f"{v.exam_name} {c.round} 최종 결과 확인", c.result_date_latest or c.result_date, "exam_result", not expected)
        else:
            add(key, f"{v.exam_name} {c.round} 응시{_target_text(v)}", c.exam_date, "exam", not expected)
            add(key, f"{v.exam_name} {c.round} 결과 확인", c.result_date_latest or c.result_date, "exam_result", not expected)
        b = v.backup
        if b and b.reg_end >= today:
            bkey = f"{v.exam_id}:{b.round}"
            if b.reg_end < _result_by(c) and _late_ok(b, c):
                btitle = f"(선택) {c.round} 결과가 기준 미달이면 {v.exam_name} {b.round} 추가 접수 (마감 {b.late_reg_end}, 정기 접수는 {b.reg_end} 마감)"
                add(bkey, btitle, b.late_reg_end, "backup_register", False)
            else:
                if b.reg_end < _result_by(c):
                    btitle = f"(선택) {v.exam_name} {b.round} 접수 (마감 {b.reg_end}) — {c.round} 결과 전에 마감되는 대비용 회차"
                else:
                    btitle = f"(선택) {c.round} 결과가 기준 미달이면 {v.exam_name} {b.round} 접수 (마감 {b.reg_end})"
                add(bkey, btitle, b.reg_end, "backup_register", False)

    for r in reqs:
        if r.status == MatchStatus.pending:
            add(r.requirement_id, f"요건 확인: {r.text}", today, "confirm", False)

    submit = max(today, deadline - timedelta(days=SUBMIT_BUFFER_DAYS))
    blocked = [v for v in verdicts if v.feasibility == Feasibility.impossible
               and any(r.requirement_id == v.requirement_id and r.type == ReqType.required for r in reqs)]
    title = f"{posting.company} 지원서 제출(마감 {posting.deadline:%Y-%m-%d %H:%M})"
    if blocked:
        title += " — 필수 요건 충족 불가, 지원 여부 재검토"
    add("main", title, submit, "submit", False)

    tasks.sort(key=lambda t: (t.due, not t.fixed))
    for i, t in enumerate(tasks, 1):
        t.priority = i
    return tasks


def _target_text(v: ExamVerdict) -> str:
    if v.min_score is None:
        return ""
    cur = f", 현재 {v.current_score:g}점" if v.current_score is not None else ""
    return f" (목표 {v.min_score:g}점 이상{cur})"


def _current_score(profile: Profile, exam_id: str, catalog: dict, today: date) -> Optional[float]:
    valid_years = (catalog.get(exam_id) or {}).get("valid_years")
    scores = []
    for h in profile.holdings:
        if h.exam_id != exam_id or h.score is None:
            continue
        if valid_years and h.acquired_date and _add_years(h.acquired_date, valid_years) < today:
            continue
        scores.append(h.score)
    return max(scores) if scores else None


def _plan_text(v: ExamVerdict) -> str:
    c = v.chosen
    goal = f"{v.min_score:g}점 이상 필요" if v.min_score is not None else "합격 필요"
    if v.current_score is not None and v.min_score is not None:
        goal += f"(현재 {v.current_score:g}점)"
    return f"{v.exam_name}: {c.round} 응시(시험 {c.exam_date}), {goal} — 결과 발표 {_result_by(c)}"


def _backup_text(v: ExamVerdict) -> Optional[str]:
    b = v.backup
    if not b:
        return None
    text = f"{v.exam_name} 대안: {v.chosen.round}에서 기준에 못 미쳐도 {b.round}(결과 {_result_by(b)})로 마감 전 재도전 가능"
    if b.reg_end < _result_by(v.chosen) and _late_ok(b, v.chosen):
        text += f" — 정기 접수({b.reg_end})는 결과 전에 끝나지만 추가 접수({b.late_reg_end}까지)로 결과를 보고 접수 가능"
    elif b.reg_end < _result_by(v.chosen):
        text += f" — 단, 접수 마감({b.reg_end})이 {v.chosen.round} 결과 발표 전이라 미리 접수해야 함"
    return text


def _block_text(v: ExamVerdict) -> str:
    nxt = next((r for r in v.reasons if r.startswith("다음 회차")), None)
    clash = next((r for r in v.reasons if "충돌" in r), None)
    if clash:
        return f"{_label(v)}: {clash}"
    return f"{_label(v)}: 마감 전에 결과를 받을 수 있는 회차 없음" + (f" — {nxt}" if nxt else "")


_COND_TEXT = {"urgent": "접수 마감 임박 — {c.reg_end}까지 접수", "expected": "공고 전 예상 일정 — 공고 후 날짜 확인",
              "same_day": "결과 발표일이 지원 마감일과 같음 — 발표 시각 확인"}


def _cond_why(v, deadline: date) -> list[str]:
    c, out = v.chosen, []
    if c.status == ScheduleStatus.expected:
        out.append("expected")
    if any(r.startswith(("접수 마감 임박", "추가 접수 마감 임박")) for r in v.reasons):
        out.append("urgent")
    if (c.result_date_latest or c.result_date) == deadline:
        out.append("same_day")
    return out


def build_conclusion(reqs: list[RequirementResult], verdicts: list[ExamVerdict], deadline: date,
                     exam_reqs: Optional[set] = None) -> Conclusion:
    by_req = {v.requirement_id: v for v in verdicts}
    plans, conds, blocks, unknown, confirm = [], [], [], [], []
    rush, conds_req = [], []
    for r in reqs:
        if r.type != ReqType.required or r.status == MatchStatus.met:
            continue
        if r.status == MatchStatus.pending:
            confirm.append(r.text)
            continue
        v = by_req.get(r.requirement_id)
        if v is None:
            unknown.append(f"{r.text}: 자동으로 일정을 판정할 수 없는 요건 — 직접 확인 필요")
        elif v.feasibility == Feasibility.possible:
            plans.append(_plan_text(v))
            if _backup_text(v):
                plans.append(_backup_text(v))
        elif v.feasibility == Feasibility.conditional:
            if v.chosen:
                why = _cond_why(v, deadline)
                conds_req.append(v)
                if why == ["urgent"]:
                    rush.append(v.chosen.reg_end)
                conds.append(_plan_text(v) + f" ({', '.join(_COND_TEXT[w].format(c=v.chosen) for w in why) or '일정 확인 필요'})")
                if _backup_text(v):
                    conds.append(_backup_text(v))
            else:
                conds_req.append(v)
                conds.append(f"{_label(v)}: {v.reasons[0]}")
        elif v.feasibility == Feasibility.impossible:
            blocks.append(_block_text(v))
        else:
            unknown.append(f"{_label(v)}: 마감 전 시험 일정 데이터 없음 — 공식 일정 확인 필요")

    points = []
    if blocks:
        status = "impossible"
        headline = "이번 공고는 마감 전에 필수 요건을 갖추기 어렵습니다"
        points += blocks + plans + conds + unknown
    elif conds and not unknown and len(rush) == len(conds_req):
        status = "conditional"
        headline = f"접수 마감이 임박했어요 — {min(rush)}까지 접수하면 마감({deadline}) 전에 필수 요건을 갖출 수 있습니다"
        points += plans + conds
    elif conds or unknown:
        status = "conditional"
        headline = "아직 확정되지 않은 일정이 있어 공식 일정 확인 후 다시 판정해야 합니다"
        points += plans + conds + unknown
    elif plans:
        status = "possible"
        headline = f"아래 시험을 마치면 마감({deadline}) 전에 필수 요건을 갖출 수 있습니다"
        points += plans
    else:
        status = "ready"
        headline = "자동 판정한 필수 요건은 이미 갖췄습니다"
    required = [r for r in reqs if r.type == ReqType.required]
    if status == "ready" and (not required or all(r.status == MatchStatus.pending for r in required)):
        status = "manual"
        headline = ("시험·자격처럼 일정으로 판정할 필수 요건이 없는 공고예요 — 아래 요건을 직접 확인해 주세요"
                    if required else "필수 요건을 찾지 못했어요 — 공고 원문을 확인해 주세요")
        if any(r.requirement_id in (exam_reqs or set()) for r in required):
            headline = "보유 자격·성적 정보만으로는 판정을 끝내지 못했어요 — 아래 '직접 확인 필요' 요건을 확인하거나 내 정보에 점수·날짜를 채워 주세요"
    if confirm:
        points.append("직접 확인 필요: " + ", ".join(confirm))
        if status == "ready":
            headline += f" — 직접 확인할 요건 {len(confirm)}개만 남았습니다"

    pref = [r for r in reqs if r.type == ReqType.preferred]
    if pref:
        met = [r.text for r in pref if r.status == MatchStatus.met]
        ok = [by_req[r.requirement_id].exam_name for r in pref if r.requirement_id in by_req
              and by_req[r.requirement_id].feasibility in (Feasibility.possible, Feasibility.conditional)]
        hard = [_label(by_req[r.requirement_id]) for r in pref if r.requirement_id in by_req
                and by_req[r.requirement_id].feasibility == Feasibility.impossible]
        parts = []
        if met:
            parts.append(", ".join(met) + " 충족")
        if ok:
            parts.append(", ".join(ok) + " 마감 전 취득 가능")
        if hard:
            parts.append(", ".join(hard) + " 마감 전 취득 어려움")
        if parts:
            points.append("우대 요건: " + " / ".join(parts))
    return Conclusion(status=status, headline=headline, points=points)


def _in_track(r: Requirement, posting: JobPosting) -> bool:
    if not posting.tracks or r.track is None or r.track not in posting.tracks:
        return True
    return r.track == posting.selected_track


RANK = {Feasibility.possible: 0, Feasibility.conditional: 1, Feasibility.no_data: 2, Feasibility.impossible: 3}


def _best_verdict(req: Requirement, profile: Profile, posting: JobPosting, sessions, today: date, full_year):
    opts = [o for o in req.choices() if o.exam_id]
    if not opts:
        return None
    cands = []
    for o in opts:
        v = verify_exam(req.model_copy(update={"exam_id": o.exam_id, "min_score": o.min_score}),
                        profile, posting, sessions, today, full_year)
        v.min_score = o.min_score
        cands.append(v)
    far = date.max
    cands.sort(key=lambda v: (RANK[v.feasibility], _result_by(v.chosen) if v.chosen else far))
    best = cands[0]
    if len(cands) > 1:
        best.option_names = [c.exam_name for c in cands]
        others = ", ".join(c.exam_name for c in cands[1:])
        if best.feasibility == Feasibility.impossible:
            best.reasons.insert(0, f"선택 요건({', '.join(best.option_names)} 중 하나) — 어느 선택지도 마감 전에 결과를 받을 수 없음. 아래는 {best.exam_name} 기준")
        else:
            best.reasons.insert(0, f"선택 요건이라 하나만 있으면 됨 — 가장 빨리 갖출 수 있는 {best.exam_name} 기준으로 판정 (다른 선택지: {others})")
    return best


def _label(v: ExamVerdict) -> str:
    return " 또는 ".join(v.option_names) if v.option_names else v.exam_name


def analyze(profile: Profile, posting: JobPosting, sessions: list[ExamSession], today: date,
            exams: Optional[list[dict]] = None) -> Analysis:
    hints = {e["exam_id"]: e.get("announce_hint") for e in (exams or []) if e.get("announce_hint")}
    full_year = {e["exam_id"] for e in exams if e.get("full_year_schedule")} if exams is not None else None
    catalog = {e["exam_id"]: e for e in (exams or [])}
    need_track = bool(posting.tracks) and posting.selected_track not in posting.tracks
    active = [r for r in posting.requirements if _in_track(r, posting)]
    reqs = [match_requirement(r, profile, today, posting.deadline.date(), catalog) for r in active]
    by_id = {r.id: r for r in active}
    verdicts = []
    for r in reqs:
        req = by_id[r.requirement_id]
        if r.status != MatchStatus.unmet or req.category not in (ReqCategory.certificate, ReqCategory.language):
            continue
        v = _best_verdict(req, profile, posting, sessions, today, full_year)
        if v:
            v.current_score = _current_score(profile, v.exam_id, catalog, today)
            verdicts.append(v)
    tasks = build_tasks(posting, verdicts, reqs, today, hints)

    def count(t):
        rs = [r for r in reqs if r.type == t]
        met = sum(r.status == MatchStatus.met for r in rs)
        pend = sum(r.status == MatchStatus.pending for r in rs)
        return f"{met}/{len(rs)} 충족, 판단 보류 {pend}건"

    summary = {"required": count(ReqType.required), "preferred": count(ReqType.preferred)}
    today_tasks = [t.id for t in tasks if not t.done and (t.due - today).days <= URGENT_DAYS]
    exam_reqs = {r.id for r in active if r.category in (ReqCategory.certificate, ReqCategory.language)
                 and any(o.exam_id for o in r.choices())}
    conclusion = build_conclusion(reqs, verdicts, posting.deadline.date(), exam_reqs)
    if need_track:
        conclusion = Conclusion(
            status="need_track",
            headline=f"지원할 모집 분야를 고르면 그 분야 요건까지 판정합니다 (모집 분야 {len(posting.tracks)}개)",
            points=["지금은 모든 분야에 공통인 요건만 판정했습니다."] + conclusion.points)
    if today > posting.deadline.date():
        conclusion = Conclusion(
            status="impossible",
            headline=f"지원 마감({posting.deadline.date()})이 지난 공고예요 — 아래 판정은 다음 채용 준비용 참고 자료입니다",
            points=conclusion.points)
        tasks, today_tasks = [], []
    return Analysis(posting_id=posting.id, profile_id=profile.id, today=today, summary=summary,
                    requirements=reqs, exams=verdicts, tasks=tasks, today_tasks=today_tasks,
                    conclusion=conclusion, track=None if need_track else posting.selected_track)
