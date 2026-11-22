import re
import json
from datetime import date, timedelta
from typing import Callable, Optional

from pydantic import BaseModel, Field

from .models import Analysis, Feasibility, FixedEvent, JobPosting

STUDY_DAYS = {"상": 28, "중": 21, "하": 14}
DOCS_DAYS = {"상": 10, "중": 7, "하": 4}
WEIGHT = {"상": 3, "중": 2, "하": 1}
RANK = {"상": 0, "중": 1, "하": 2}
EXAM_DIFFICULTY = {"info_engineer": "상", "sqld": "중", "adsp": "중", "toeic": "중"}
MAX_DAYS = 120
OVERLOAD = 4
STRATEGIES = {"deadline": "마감 임박순", "difficulty": "난이도순"}


class Block(BaseModel):
    id: str
    kind: str
    title: str
    start: date
    end: date
    difficulty: str
    source: str = "rule"
    exam_id: Optional[str] = None
    anchor: date
    min_start: date
    max_end: date
    posting_ids: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    note: str = ""
    reset_reason: Optional[str] = None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def default_days(self) -> int:
        return (STUDY_DAYS if self.kind == "study" else DOCS_DAYS)[self.difficulty]


class LoadWarning(BaseModel):
    kind: str
    message: str
    block_ids: list[str] = Field(default_factory=list)
    start: Optional[date] = None
    end: Optional[date] = None


class Plan(BaseModel):
    today: date
    strategy: str
    blocks: list[Block]
    warnings: list[LoadWarning]


def _short(company: str) -> str:
    return (company or "").replace("(합성)", "").strip()


def candidates(cards: list[tuple[JobPosting, Analysis]], today: date) -> dict[str, Block]:
    out: dict[str, Block] = {}
    for posting, a in cards:
        for v in a.exams:
            c = v.chosen
            if not c or v.feasibility not in (Feasibility.possible, Feasibility.conditional) or c.exam_date <= today:
                continue
            bid = f"study:{v.exam_id}:{c.round}"
            if bid not in out:
                diff = EXAM_DIFFICULTY.get(v.exam_id, "중")
                if v.min_score is not None and v.current_score is not None and v.min_score - v.current_score >= 100:
                    diff = "상"
                out[bid] = Block(id=bid, kind="study", title=f"{v.exam_name} {c.round} 준비", start=today, end=today,
                                 difficulty=diff, exam_id=v.exam_id, anchor=c.exam_date, min_start=today,
                                 max_end=c.exam_date - timedelta(days=1))
            b = out[bid]
            if posting.id not in b.posting_ids:
                b.posting_ids.append(posting.id)
                b.companies.append(_short(posting.company))
        dl = posting.deadline.date()
        status = a.conclusion.status if a.conclusion else None
        if dl - timedelta(days=1) > today and status not in ("impossible", "need_track"):
            bid = f"docs:{posting.id}"
            out[bid] = Block(id=bid, kind="docs", title=f"{_short(posting.company)} 지원서 작성", start=today, end=today,
                             difficulty="중", anchor=dl, min_start=today, max_end=dl - timedelta(days=1),
                             posting_ids=[posting.id], companies=[_short(posting.company)])
    return out


def _overlaps(a: Block, b: Block) -> bool:
    return a.start <= b.end and b.start <= a.end


def _ideal(b: Block) -> tuple[date, date]:
    end = b.max_end
    start = max(b.min_start, end - timedelta(days=b.default_days() - 1))
    return start, end


def _personal_days(start: date, end: date, fixed: list[FixedEvent]) -> int:
    days = set()
    for f in fixed:
        s, e = max(start, f.start), min(end, f.end)
        d = s
        while d <= e:
            days.add(d)
            d += timedelta(days=1)
    return len(days)


def draft(cands: dict[str, Block], strategy: str = "deadline", fixed: Optional[list[FixedEvent]] = None) -> list[Block]:
    blocks = [b.model_copy(deep=True) for b in cands.values()]
    for b in blocks:
        b.start, b.end = _ideal(b)
        b.source, b.note = "rule", ""
    if strategy == "difficulty":
        order = sorted(blocks, key=lambda b: (RANK[b.difficulty], b.anchor))
    else:
        order = sorted(blocks, key=lambda b: (b.anchor, RANK[b.difficulty]))
    placed: list[Block] = []
    for b in order:
        if b.kind == "study":
            start, end = b.start, b.end
            for _ in range(10):
                clash = [p for p in placed if p.kind == "study" and p.start <= end and start <= p.end]
                if not clash:
                    break
                end = min(p.start for p in clash) - timedelta(days=1)
                start = max(b.min_start, end - timedelta(days=b.default_days() - 1))
            if end >= start and (end - start).days + 1 >= max(7, b.default_days() // 2) and not any(
                    p.kind == "study" and p.start <= end and start <= p.end for p in placed):
                b.start, b.end = start, end
                if (b.start, b.end) != _ideal(b):
                    b.note = f"{STRATEGIES.get(strategy, '')} 기준으로 다른 준비와 겹치지 않게 앞당김"
        n = _personal_days(b.start, b.end, fixed or [])
        if n and b.kind == "study":
            new_start = max(b.min_start, b.start - timedelta(days=n))
            if new_start < b.start:
                b.note = (b.note + " · " if b.note else "") + f"개인 일정과 겹치는 {n}일만큼 일찍 시작"
                b.start = new_start
        placed.append(b)
    return sorted(blocks, key=lambda b: (b.start, b.anchor))


def validate(b: Block, start: date, end: date, today: date) -> Optional[str]:
    if start > end:
        return "시작일이 종료일보다 늦어요"
    if start < max(b.min_start, today):
        return f"오늘({today}) 이전으로는 옮길 수 없어요"
    if end > b.max_end:
        what = "시험일" if b.kind == "study" else "지원 마감"
        return f"{what}({b.anchor}) 전날({b.max_end})까지 끝나야 해요"
    if (end - start).days + 1 > MAX_DAYS:
        return f"한 번에 {MAX_DAYS}일보다 길게 잡을 수 없어요"
    return None


def apply_overrides(blocks: list[Block], overrides: dict, today: date) -> list[Block]:
    for b in blocks:
        o = overrides.get(b.id)
        if not o:
            continue
        try:
            start, end = date.fromisoformat(o["start"]), date.fromisoformat(o["end"])
        except (KeyError, ValueError):
            continue
        diff = o.get("difficulty") if o.get("difficulty") in WEIGHT else b.difficulty
        err = validate(b, start, end, today)
        if err:
            b.reset_reason = f"저장해 둔 조정이 바뀐 일정과 맞지 않아 초안으로 돌렸어요 ({err})"
            continue
        b.start, b.end, b.difficulty = start, end, diff
        b.source = o.get("source", "user")
        b.note = o.get("note", "")
    return sorted(blocks, key=lambda b: (b.start, b.anchor))


def _week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def warnings(blocks: list[Block], fixed: list[FixedEvent], exam_days: dict[str, date]) -> list[LoadWarning]:
    out: list[LoadWarning] = []
    if blocks:
        first, last = _week(min(b.start for b in blocks)), max(b.end for b in blocks)
        runs: list[tuple[date, date, tuple]] = []
        w = first
        while w <= last:
            active = [b for b in blocks if b.start <= w + timedelta(days=6) and w <= b.end]
            load = sum(WEIGHT[b.difficulty] if b.kind == "study" else 1 for b in active)
            key = tuple(sorted(b.id for b in active)) if len(active) >= 2 and load >= OVERLOAD else ()
            if key and runs and runs[-1][2] == key and runs[-1][1] + timedelta(days=1) == w:
                runs[-1] = (runs[-1][0], w + timedelta(days=6), key)
            elif key:
                runs.append((w, w + timedelta(days=6), key))
            w += timedelta(days=7)
        by_id = {b.id: b for b in blocks}
        for s, e, key in runs:
            names = ", ".join(by_id[i].title for i in key)
            out.append(LoadWarning(kind="overload", start=s, end=e, block_ids=list(key),
                                   message=f"{s.month}/{s.day}~{e.month}/{e.day}: {names} 기간이 겹쳐 부담이 커요"))
    for b in blocks:
        for other_id, day in exam_days.items():
            if other_id != b.id and b.start <= day <= b.end and b.kind == "study":
                ob = next((x for x in blocks if x.id == other_id), None)
                label = ob.title.replace(" 준비", "") if ob else other_id
                out.append(LoadWarning(kind="exam_day", start=day, end=day, block_ids=[b.id, other_id],
                                       message=f"{b.title} 기간 중 {day.month}/{day.day}에 {label} 시험이 있어요"))
        for f in fixed:
            s, e = max(b.start, f.start), min(b.end, f.end)
            if s <= e:
                n = (e - s).days + 1
                if n >= 3 or n * 10 >= b.days * 3:
                    out.append(LoadWarning(kind="personal", start=s, end=e, block_ids=[b.id],
                                           message=f"{b.title} 기간이 '{f.title}' 기간과 {n}일 겹쳐 실제 준비 시간이 {max(0, b.days - n)}일로 줄어요"))
        if b.days < max(3, b.default_days() // 2):
            out.append(LoadWarning(kind="short", start=b.start, end=b.end, block_ids=[b.id],
                                   message=f"{b.title} 기간이 {b.days}일로 짧아요 (난이도 {b.difficulty} 기준 권장 {b.default_days()}일)"))
    return out


def build(cards, today: date, fixed: list[FixedEvent], overrides: dict, strategy: str) -> Plan:
    cands = candidates(cards, today)
    blocks = apply_overrides(draft(cands, strategy, fixed), overrides, today)
    exam_days = {b.id: b.anchor for b in blocks if b.kind == "study"}
    return Plan(today=today, strategy=strategy, blocks=blocks, warnings=warnings(blocks, fixed, exam_days))


# ---------- AI ----------

DRAFT_TOOL = "record_schedule"
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "초안을 이렇게 짠 이유 한두 문장"},
        "blocks": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "start": {"type": "string", "description": "YYYY-MM-DD"},
            "end": {"type": "string", "description": "YYYY-MM-DD"}, "reason": {"type": "string"}},
            "required": ["id", "start", "end", "reason"]}},
    },
    "required": ["summary", "blocks"],
}
DRAFT_SYSTEM = """너는 취업 준비생의 준비 기간 일정을 짜는 도우미다.
규칙:
- 주어진 블록마다 start와 end를 정한다. 반드시 earliest_start 이상, latest_end 이하의 날짜만 쓴다.
- 기간 길이는 default_days 근처로 잡는다.
- 시험 준비(kind=study)끼리는 가능하면 같은 기간에 겹치지 않게 한다. 지원서 작성(kind=docs)은 겹쳐도 된다.
- 개인 일정 기간에는 준비를 몰아넣지 않는다.
- 사용자가 고른 정렬 기준(strategy)을 우선한다. 마감 임박순이면 마감이 가까운 블록을, 난이도순이면 난이도가 높은 블록을 먼저 좋은 자리에 둔다.
- 합격률·효과 같은 근거 없는 수치나 사실을 지어내지 않는다. reason과 summary는 한국어 해요체로 짧게 쓴다."""

FEEDBACK_TOOL = "record_feedback"
JUDGMENTS = ["분산 필요", "묶어서 진행 가능", "주의만 필요", "문제 적음"]
BASES = ["난이도 높음", "같은 공고", "시험 직전", "개인 일정으로 준비 시간 감소", "준비 기간 짧음"]
OVERALL = ["문제 없음", "주의 필요", "조정 권장"]
JUDGE_TEXT = {
    "분산 필요": "부담이 한쪽으로 몰려 있어 나눠서 진행하는 편이 좋아요.",
    "묶어서 진행 가능": "같은 공고를 위한 준비라 함께 진행하면 효율적일 수 있어요.",
    "주의만 필요": "당장 바꿀 필요는 없지만 진행 상황을 지켜보세요.",
    "문제 적음": "부담이 크지 않아 그대로 두어도 괜찮아요.",
}
OVERALL_TEXT = {
    "문제 없음": "지금 일정은 무리가 없어 보여요.",
    "주의 필요": "몇 군데 지켜볼 곳이 있어요.",
    "조정 권장": "부담이 몰린 곳이 있어 조정을 권해요.",
}
FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "overall": {"type": "string", "enum": OVERALL},
        "judgments": {"type": "array", "items": {"type": "object", "properties": {
            "finding_id": {"type": "string"},
            "judgment": {"type": "string", "enum": JUDGMENTS},
            "basis": {"type": "array", "items": {"type": "string", "enum": BASES}}},
            "required": ["finding_id", "judgment", "basis"]}},
        "suggestions": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}},
            "required": ["id", "start", "end"]}, "description": "일정 조정 제안, 최대 2개. 필요 없으면 빈 배열"},
    },
    "required": ["overall", "judgments", "suggestions"],
}
FEEDBACK_SYSTEM = """너는 취업 준비 일정 코치다. 사용자가 달력에서 한 행동, 현재 일정(blocks), 엔진이 찾은 확인할 점(findings)을 받는다.
너는 문장을 쓰지 않고, 정해진 선택지에서 고른다.
- overall: 전체 판단.
- judgments: findings 각각에 대해 judgment와 basis를 고른다. basis는 findings와 blocks에 실제로 있는 사실만 고른다.
  - '같은 공고'는 그 finding의 same_posting이 true일 때만. 두 블록의 postings가 다르면 고르지 않는다.
  - '난이도 높음'은 관련 블록의 difficulty가 '상'일 때만.
  - '시험 직전'은 kind가 exam_inside이거나, 관련 블록이 시험일 바로 앞에 끝날 때.
  - '개인 일정으로 준비 시간 감소'는 kind가 personal일 때만. '준비 기간 짧음'은 kind가 short일 때만.
  - '묶어서 진행 가능'은 같은 공고를 위한 두 준비가 겹칠 때만 고른다.
  - 고난도 준비가 몰리거나 시험 직전에 다른 준비가 겹치면 '분산 필요'를 고른다.
- suggestions: 부담을 줄이는 날짜 조정을 최대 2개. 각 블록의 earliest_start~latest_end 안의 날짜만, 고정 일정(시험일, 마감)은 옮기지 않는다. 엔진이 적용해 보고 부담이 실제로 줄어드는 것만 사용자에게 보여 준다.
- findings가 비어 있으면 overall은 '문제 없음', judgments와 suggestions는 빈 배열."""


def overlap_days(a: Block, b: Block) -> int:
    s, e = max(a.start, b.start), min(a.end, b.end)
    return (e - s).days + 1 if s <= e else 0


def load_score(blocks: list[Block], fixed: list[FixedEvent]) -> int:
    if not blocks:
        return 0
    personal = set()
    for f in fixed:
        d = f.start
        while d <= f.end:
            personal.add(d)
            d += timedelta(days=1)
    score, d, last = 0, min(b.start for b in blocks), max(b.end for b in blocks)
    while d <= last:
        active = [b for b in blocks if b.start <= d <= b.end]
        load = sum(WEIGHT[b.difficulty] if b.kind == "study" else 1 for b in active)
        score += max(0, load - 2)
        if d in personal:
            score += sum(WEIGHT[b.difficulty] for b in active if b.kind == "study")
        d += timedelta(days=1)
    return score


def facts(plan: Plan, fixed: list[FixedEvent]) -> dict:
    bs = plan.blocks
    pairs = []
    for i, a in enumerate(bs):
        for b in bs[i + 1:]:
            n = overlap_days(a, b)
            if n:
                pairs.append({"a": a.id, "b": b.id, "overlap_days": n,
                              "same_posting": bool(set(a.posting_ids) & set(b.posting_ids))})
    personal = []
    for b in bs:
        n = _personal_days(b.start, b.end, fixed)
        if n:
            personal.append({"id": b.id, "days": n, "effective_days": b.days - n})
    inside = [{"id": b.id, "exam_of": o.id, "date": str(o.anchor)} for b in bs for o in bs
              if o.kind == "study" and o.id != b.id and b.kind == "study" and b.start <= o.anchor <= b.end]
    return {"overlaps": pairs, "personal_overlaps": personal, "exam_days_inside": inside,
            "load_score": load_score(bs, fixed)}


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def findings(plan: Plan, fixed: list[FixedEvent]) -> list[dict]:
    bs, out = plan.blocks, []
    for i, a in enumerate(bs):
        for b in bs[i + 1:]:
            n = overlap_days(a, b)
            if n:
                s, e = max(a.start, b.start), min(a.end, b.end)
                out.append({"kind": "overlap", "block_ids": [a.id, b.id], "same_posting": bool(set(a.posting_ids) & set(b.posting_ids)),
                            "text": f"{a.title} · {b.title} 두 기간이 {_md(s)}~{_md(e)}, {n}일 겹쳐요"})
    for b in bs:
        for o in bs:
            if b.kind == "study" and o.kind == "study" and o.id != b.id and b.start <= o.anchor <= b.end:
                out.append({"kind": "exam_inside", "block_ids": [b.id, o.id],
                            "text": f"{b.title} 기간({_md(b.start)}~{_md(b.end)}) 중 {_md(o.anchor)}에 {o.title.replace(' 준비', '')} 시험이 있어요"})
    for b in bs:
        for f in fixed:
            s, e = max(b.start, f.start), min(b.end, f.end)
            if s <= e:
                out.append({"kind": "personal", "block_ids": [b.id],
                            "text": f"{b.title} 기간이 '{f.title}' 기간과 {_md(s)}~{_md(e)}, {(e - s).days + 1}일 겹쳐요"})
        if b.days < max(3, b.default_days() // 2):
            out.append({"kind": "short", "block_ids": [b.id],
                        "text": f"{b.title} 기간이 {b.days}일로 짧아요 (난이도 {b.difficulty} 권장 {b.default_days()}일)"})
    for i, x in enumerate(out):
        x["id"] = f"f{i + 1}"
    return out


NUM = re.compile(r"[0-9０-９]|하루|이틀|사흘|나흘|닷새|엿새|열흘|보름|일주일|며칠|[한두세네]\s*(주|달|번째\s*주)")
MOVE = re.compile(r"당기|당겨|당길|미루|미뤄|미룰|옮기|옮겨|옮길|늦추|늦춰|늦출|앞당|바꾸면|바꿔|바꿀|조정하면|조정해|조정할|시작하면|끝내면|줄이면|늘리면")


def _clean(text: str, no_moves: bool = False) -> tuple[str, int]:
    parts = [p for p in re.split(r"(?<=[.!?요다])\s+", str(text or "").strip()) if p]
    kept = [p for p in parts if not NUM.search(p) and not (no_moves and MOVE.search(p))]
    return " ".join(kept)[:300], len(parts) - len(kept)


def _block_brief(b: Block) -> dict:
    return {"id": b.id, "title": b.title, "kind": b.kind, "difficulty": b.difficulty, "start": str(b.start), "end": str(b.end),
            "default_days": b.default_days(), "earliest_start": str(b.min_start), "latest_end": str(b.max_end),
            "fixed_anchor": f"{'시험일' if b.kind == 'study' else '지원 마감'} {b.anchor}", "postings": b.companies}


def _parse_moves(raw_items, blocks: list[Block], today: date) -> tuple[list[dict], int]:
    by_id = {b.id: b for b in blocks}
    ok, bad = [], 0
    for it in raw_items or []:
        b = by_id.get(it.get("id"))
        try:
            s, e = date.fromisoformat(str(it.get("start"))), date.fromisoformat(str(it.get("end")))
        except ValueError:
            bad += 1
            continue
        if not b or validate(b, s, e, today):
            bad += 1
            continue
        ok.append({"id": b.id, "title": b.title, "start": s, "end": e, "reason": str(it.get("reason", ""))[:200]})
    return ok, bad


def ai_draft(plan: Plan, fixed: list[FixedEvent], strategy: str, caller: Callable) -> tuple[dict, str]:
    user = json.dumps({"today": str(plan.today), "strategy": STRATEGIES.get(strategy, strategy),
                       "blocks": [_block_brief(b) for b in plan.blocks],
                       "personal_schedule": [{"title": f.title, "start": str(f.start), "end": str(f.end)} for f in fixed]},
                      ensure_ascii=False)
    raw = caller(DRAFT_SYSTEM, user, DRAFT_TOOL, DRAFT_SCHEMA)
    moves, bad = _parse_moves(raw.get("blocks"), plan.blocks, plan.today)
    by_id = {b.id: b for b in plan.blocks}
    kept = []
    for m in moves:
        b = by_id[m["id"]]
        if _personal_days(m["start"], m["end"], fixed) > _personal_days(b.start, b.end, fixed):
            bad += 1
            continue
        kept.append(m)
    moves = kept
    overrides = {m["id"]: {"start": str(m["start"]), "end": str(m["end"]), "source": "ai",
                           "note": f"AI 초안 ({STRATEGIES.get(strategy, '')} 기준, 날짜 규칙은 엔진이 확인)"} for m in moves}
    msg = f"AI가 {STRATEGIES.get(strategy, '')} 기준으로 준비 기간 {len(moves)}개를 배치했어요."
    if bad:
        msg += f" (AI 제안 중 {bad}개는 날짜 규칙에 맞지 않거나 개인 일정과 겹쳐 규칙 초안을 그대로 썼어요)"
    return overrides, msg.strip()


def rule_feedback(plan: Plan, fixed: Optional[list[FixedEvent]] = None) -> dict:
    fs = findings(plan, fixed or [])
    summary = "겹치거나 무리한 구간이 없어요." if not fs and not plan.warnings else f"엔진이 찾은 확인할 점 {len(fs)}개를 아래에 정리했어요."
    return {"summary": summary, "findings": fs, "cautions": [], "suggestions": []}


def _total_overlap(blocks: list[Block]) -> int:
    return sum(overlap_days(a, b) for i, a in enumerate(blocks) for b in blocks[i + 1:])


def _basis_ok(basis: str, f: dict, by: dict) -> bool:
    blocks = [by[i] for i in f["block_ids"] if i in by]
    if basis == "같은 공고":
        return f["kind"] == "overlap" and f.get("same_posting", False)
    if basis == "난이도 높음":
        return any(b.difficulty == "상" for b in blocks)
    if basis == "시험 직전":
        if f["kind"] == "exam_inside":
            return True
        return f["kind"] == "overlap" and any(b.kind == "study" and (b.anchor - b.end).days <= 1 for b in blocks)
    if basis == "개인 일정으로 준비 시간 감소":
        return f["kind"] == "personal"
    if basis == "준비 기간 짧음":
        return f["kind"] == "short"
    return False


def ai_feedback(plan: Plan, fixed: list[FixedEvent], action: dict, caller: Callable) -> dict:
    fs = findings(plan, fixed)
    by = {b.id: b for b in plan.blocks}
    user = json.dumps({"today": str(plan.today), "user_action": action,
                       "blocks": [_block_brief(b) | {"posting_ids": b.posting_ids} for b in plan.blocks],
                       "findings": fs,
                       "personal_schedule": [{"title": x.title, "start": str(x.start), "end": str(x.end)} for x in fixed]},
                      ensure_ascii=False)
    raw = caller(FEEDBACK_SYSTEM, user, FEEDBACK_TOOL, FEEDBACK_SCHEMA)
    corrected = 0
    by_f = {x["id"]: x for x in fs}
    for j in raw.get("judgments") or []:
        f = by_f.get(str(j.get("finding_id")))
        judgment = j.get("judgment")
        if not f or judgment not in JUDGMENTS:
            corrected += 1
            continue
        basis = [x for x in dict.fromkeys(j.get("basis") or []) if x in BASES]
        valid = [x for x in basis if _basis_ok(x, f, by)]
        corrected += len(basis) - len(valid)
        if judgment == "묶어서 진행 가능" and "같은 공고" not in valid:
            judgment = "주의만 필요"
            corrected += 1
        if judgment == "분산 필요" and not valid:
            judgment = "주의만 필요"
            corrected += 1
        f["judgment"], f["basis"], f["advice"] = judgment, valid, JUDGE_TEXT[judgment]
    overall = raw.get("overall") if raw.get("overall") in OVERALL else ("문제 없음" if not fs else "주의 필요")
    if not fs:
        overall = "문제 없음"
    summary = OVERALL_TEXT[overall]
    moves, bad = _parse_moves(raw.get("suggestions"), plan.blocks, plan.today)

    def personal_total(bl):
        return sum(_personal_days(b.start, b.end, fixed) for b in bl)

    before = (load_score(plan.blocks, fixed), _total_overlap(plan.blocks), personal_total(plan.blocks))
    kept = []
    for m in moves:
        trial = [b.model_copy(update={"start": m["start"], "end": m["end"]}) if b.id == m["id"] else b for b in plan.blocks]
        after = (load_score(trial, fixed), _total_overlap(trial), personal_total(trial))
        if after[2] > before[2]:
            bad += 1
            continue
        if after[0] < before[0] or (after[0] == before[0] and after[1] < before[1]):
            m["reason"] = "AI가 제안하고 엔진이 효과를 확인한 조정이에요."
            m["effect"] = {"score_before": before[0], "score_after": after[0], "overlap_before": before[1],
                           "overlap_after": after[1], "personal_before": before[2], "personal_after": after[2]}
            kept.append(m)
        else:
            bad += 1
    return {"summary": summary, "overall": overall, "findings": fs, "cautions": [], "suggestions": kept[:2],
            "dropped": bad, "dropped_claims": corrected}
