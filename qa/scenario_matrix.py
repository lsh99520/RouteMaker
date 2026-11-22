"""시연 점검: 날짜 × 사용자 조건 × 공고 전체 조합을 API로 돌려 목표 동작을 확인한다.

python qa/scenario_matrix.py  →  qa/scenario_report.md
"""
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("ROUTEMAKER_DEMO_DIR", None)

from fastapi.testclient import TestClient  # noqa: E402

from routemaker.api import create_app  # noqa: E402
from routemaker.loader import load_all  # noqa: E402


def no_ai(*a, **k):
    from routemaker.llm import LLMError
    raise LLMError("점검용: AI 호출 안 함")


BASE = json.loads((ROOT / "data" / "profiles.json").read_text(encoding="utf-8"))[0]


def variant(name, **upd):
    p = json.loads(json.dumps(BASE))
    p.update(upd)
    return name, p


TRIP = [{"title": "해외 연수", "start": "2026-12-10", "end": "2026-12-16"}]
ENG = {"exam_id": "info_engineer", "score": None, "acquired_date": "2025-06-13"}
PROFILES = [
    variant("기본(가상 지원자 A)"),
    variant("가족 행사 11/28~30 추가", fixed_schedule=TRIP + [{"title": "가족 행사", "start": "2026-11-28", "end": "2026-11-30"}]),
    variant("고정 일정 없음", fixed_schedule=[]),
    variant("12~1월 내내 바쁨", fixed_schedule=[{"title": "장기 프로젝트", "start": "2026-11-20", "end": "2027-01-31"}]),
    variant("보유 자격 없음", holdings=[], preparing=[]),
    variant("TOEIC 820(유효)", holdings=[ENG, {"exam_id": "toeic", "score": 820, "acquired_date": "2026-05-01"}]),
    variant("TOEIC 900인데 만료(2024-06)", holdings=[ENG, {"exam_id": "toeic", "score": 900, "acquired_date": "2024-06-01"}]),
    variant("TOEIC 860 + SQLD + ADsP", holdings=[ENG, {"exam_id": "toeic", "score": 860, "acquired_date": "2026-05-01"},
                                                 {"exam_id": "sqld", "acquired_date": "2025-09-12"},
                                                 {"exam_id": "adsp", "acquired_date": "2025-09-12"}]),
    variant("정보처리기사 없음", holdings=[{"exam_id": "toeic", "score": 750, "acquired_date": "2026-03-10"}]),
    variant("TOEIC 점수 비움", holdings=[ENG, {"exam_id": "toeic", "score": None, "acquired_date": "2026-03-10"}]),
]

DAYS = sorted({date(2026, 11, 20) + timedelta(days=k) for k in range(18)} | {
    date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 29), date(2026, 11, 30),
    date(2026, 12, 8), date(2026, 12, 13), date(2026, 12, 18), date(2026, 12, 19),
    date(2027, 1, 6), date(2027, 1, 15), date(2027, 1, 16)})
POSTINGS = [("p_a", None), ("p_b", None), ("p_c", None), ("p_d", None), ("p_d", "행정"), ("p_d", "전산")]
STATUSES = {"ready", "possible", "conditional", "impossible", "need_track", "closed", "no_data", "pending", "manual"}

base = load_all()
SESS = defaultdict(list)
for s in base["sessions"]:
    SESS[s.exam_id].append(s)


def busy(d, fixed):
    return any(date.fromisoformat(f["start"]) <= d <= date.fromisoformat(f["end"]) for f in fixed)


def oracle(exam_id, today, deadline, fixed):
    """규칙을 따로 다시 계산: 오늘 접수 가능 · 시험일이 고정 일정과 안 겹침 · 발표가 마감 전 → 가장 이른 회차."""
    ok = []
    for s in SESS[exam_id]:
        last_reg = s.late_reg_end or s.reg_end
        if last_reg < today or s.exam_date <= today or busy(s.exam_date, fixed):
            continue
        if s.result_by > deadline:
            continue
        ok.append(s)
    return min(ok, key=lambda s: s.exam_date).round if ok else None


def main():
    problems, notes = [], []
    counts = Counter()
    status_table = defaultdict(dict)
    tmp = tempfile.mkdtemp()
    app = create_app(Path(tmp) / "store.json", caller=no_ai)
    c = TestClient(app)

    def bad(where, msg):
        problems.append(f"{where}: {msg}")

    for day in DAYS:
        os.environ["ROUTEMAKER_TODAY"] = day.isoformat()
        h = c.get("/api/health").json()
        if h["today"] != day.isoformat():
            bad(day, f"health today={h['today']}")
        for pname, prof in PROFILES:
            hdr = {"x-rm-user": f"qa-{abs(hash(pname))}-{day}"}
            c.post("/api/reset", headers=hdr)
            r = c.put("/api/profiles/u1", json=prof, headers=hdr)
            if r.status_code != 200:
                bad(f"{day} {pname}", f"프로필 저장 {r.status_code} {r.text[:120]}")
                continue
            for pid, track in POSTINGS:
                where = f"{day} | {pname} | {pid}{'·' + track if track else ''}"
                posting = c.get(f"/api/postings/{pid}", headers=hdr).json()
                if track:
                    posting["selected_track"] = track
                    rr = c.put(f"/api/postings/{pid}", json=posting, headers=hdr)
                    if rr.status_code != 200:
                        bad(where, f"트랙 저장 {rr.status_code}")
                        continue
                r = c.post(f"/api/postings/{pid}/analyze", headers=hdr)
                counts["analyze"] += 1
                if r.status_code != 200:
                    bad(where, f"판정 API {r.status_code} {r.text[:150]}")
                    continue
                a = r.json()["analysis"]
                deadline = date.fromisoformat(posting["deadline"][:10])
                st = a["conclusion"]["status"] if a.get("conclusion") else None
                status_table[(pname, pid + ("·" + track if track else ""))][day] = st
                if st not in STATUSES:
                    bad(where, f"알 수 없는 결론 상태 {st}")
                if not (a.get("conclusion") or {}).get("headline"):
                    bad(where, "결론 문장이 비어 있음")
                if day > deadline and st not in ("closed", "impossible"):
                    bad(where, f"공고 마감({deadline}) 지났는데 결론={st} / {a['conclusion']['headline'][:60]}")
                for t in a["tasks"]:
                    if date.fromisoformat(t["due"]) < day and not t["done"] and day <= deadline:
                        bad(where, f"할 일 기한이 이미 지남: {t['title']} ({t['due']})")
                    if date.fromisoformat(t["due"]) > deadline and t["kind"] != "result":
                        notes.append(f"{where}: 공고 마감 뒤 할 일 {t['title']} ({t['due']})")
                for e in a["exams"]:
                    ch = e.get("chosen")
                    fixed = prof["fixed_schedule"]
                    if e["feasibility"] == "impossible" and ch:
                        bad(where, f"{e['exam_name']} 불가인데 회차 선택됨")
                    if e["feasibility"] == "impossible" and not e["reasons"]:
                        bad(where, f"{e['exam_name']} 불가 이유 없음")
                    if ch:
                        reg = date.fromisoformat(ch["reg_end"])
                        ex = date.fromisoformat(ch["exam_date"])
                        res = date.fromisoformat(ch.get("result_date_latest") or ch["result_date"])
                        if reg < day:
                            bad(where, f"{e['exam_name']} {ch['round']} 접수 이미 끝남({reg})")
                        if ex <= day:
                            bad(where, f"{e['exam_name']} {ch['round']} 시험일이 오늘 이전({ex})")
                        if busy(ex, fixed):
                            bad(where, f"{e['exam_name']} {ch['round']} 시험일이 고정 일정과 겹침({ex})")
                        if res > deadline and ch.get("status") == "confirmed":
                            bad(where, f"{e['exam_name']} {ch['round']} 발표({res})가 마감({deadline}) 뒤")
                    if day <= deadline and e["exam_id"] in SESS and ch and ch.get("status") == "confirmed":
                        want = oracle(e["exam_id"], day, deadline, prof["fixed_schedule"])
                        if want and want != ch["round"]:
                            notes.append(f"{where}: {e['exam_name']} 선택 {ch['round']} / 단순 규칙상 최단 {want}")
                for rq in a["requirements"]:
                    if rq["status"] not in ("met", "unmet", "pending"):
                        bad(where, f"요건 상태 이상 {rq}")
                ics = c.get(f"/api/postings/{pid}/calendar.ics", headers=hdr)
                if ics.status_code != 200 or "BEGIN:VCALENDAR" not in ics.text:
                    bad(where, f"캘린더 내보내기 {ics.status_code}")
            plan = c.get("/api/plan", headers=hdr)
            counts["plan"] += 1
            if plan.status_code != 200:
                bad(f"{day} {pname}", f"계획 API {plan.status_code} {plan.text[:150]}")
                continue
            for b in plan.json()["blocks"]:
                s, e = date.fromisoformat(b["start"]), date.fromisoformat(b["end"])
                if s > e:
                    bad(f"{day} {pname}", f"준비 기간 시작>끝 {b['title']}")
                if s < day:
                    bad(f"{day} {pname}", f"준비 기간이 과거에서 시작 {b['title']} {s}")
                if e > date.fromisoformat(b["max_end"]):
                    bad(f"{day} {pname}", f"준비 기간이 허용 끝 넘음 {b['title']}")
            d = c.post("/api/plan/draft", json={"strategy": "difficulty", "use_ai": True}, headers=hdr)
            if d.status_code != 200 or d.json()["ai"]:
                bad(f"{day} {pname}", f"AI 실패 시 규칙 초안 대체 안 됨 {d.status_code}")
            fb = c.post("/api/plan/feedback", json={"action": {}}, headers=hdr)
            if fb.status_code != 200:
                bad(f"{day} {pname}", f"계획 점검 API {fb.status_code}")
    os.environ.pop("ROUTEMAKER_TODAY", None)
    return problems, notes, counts, status_table


ABBR = {"ready": "준비됨", "possible": "가능", "conditional": "조건부", "impossible": "불가",
        "need_track": "분야선택", "closed": "마감", None: "-"}


def report(problems, notes, counts, table):
    out = ["# 시연 점검 결과 (날짜 × 사용자 조건 × 공고)", "",
           f"- 날짜 {len(DAYS)}개({DAYS[0]}~{DAYS[-1]}), 사용자 조건 {len(PROFILES)}종, 공고·분야 {len(POSTINGS)}종",
           f"- 판정 호출 {counts['analyze']}회, 계획 호출 {counts['plan']}회 (AI는 꺼진 상태로 규칙 대체 확인)",
           f"- 규칙 위반 {len(problems)}건, 참고 {len(notes)}건", ""]
    out += ["## 규칙 위반", ""] + ([f"- {p}" for p in problems[:200]] or ["- 없음"]) + [""]
    out += ["## 참고(사람 검토)", ""] + ([f"- {n}" for n in sorted(set(notes))[:200]] or ["- 없음"]) + [""]
    out += ["## 결론 변화 (날짜가 바뀌는 지점만)", ""]
    for (pname, pid), row in sorted(table.items()):
        prev, seg = object(), []
        for d in DAYS:
            v = row.get(d)
            if v != prev:
                seg.append(f"{d:%m/%d}~ {ABBR.get(v, v)}")
                prev = v
        out.append(f"- {pname} / {pid}: " + " → ".join(seg))
    (ROOT / "qa" / "scenario_report.md").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    p, n, c, t = main()
    report(p, n, c, t)
    print(f"위반 {len(p)} / 참고 {len(set(n))} / 판정 {c['analyze']}")
    for x in p[:40]:
        print(" !", x)
    for x in sorted(set(n))[:40]:
        print(" ?", x)
