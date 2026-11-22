"""Q-Net 국가자격 시험일정 공식 API(한국산업인력공단, 공공데이터포털 15074408) 연동.

서버는 화면 요청마다 API를 부르지 않는다. `python -m routemaker.qnet` 으로 받아
data/qnet_sessions.json 에 저장해 두고, 판정은 저장한 일정으로 한다.
(공공데이터포털 장애·호출 한도와 무관하게 동작하고, 판정에 쓴 일정을 기록으로 남기기 위함)
"""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx

from .models import ExamSession, PracticalStage, kst_today

URL = os.environ.get("QNET_URL", "https://apis.data.go.kr/B490007/qualExamSchd/getQualExamSchdList")
SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "qnet_sessions.json"
SOURCE = "Q-Net 국가자격 시험일정 공식 API (한국산업인력공단, 공공데이터포털)"

EXAMS = {
    "info_engineer": {"jm_cd": "1320", "name": "정보처리기사", "grade": "기사"},
}

ERRORS = {
    "01": "APPLICATION_ERROR", "02": "DB_ERROR", "03": "NO_DATA", "04": "HTTP_ERROR",
    "05": "SERVICE_TIMEOUT", "10": "INVALID_PARAMETER", "12": "NO_SERVICE", "20": "ACCESS_DENIED",
    "22": "LIMIT_EXCEEDED", "30": "KEY_NOT_REGISTERED", "31": "KEY_EXPIRED",
}


def ok(data) -> dict:
    return {"ok": True, "data": data}


def fail(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def _day(v) -> Optional[date]:
    v = str(v or "").strip().replace("-", "").replace(".", "")
    if len(v) != 8 or not v.isdigit():
        return None
    try:
        return datetime.strptime(v, "%Y%m%d").date()
    except ValueError:
        return None


def _items(payload: dict) -> list:
    root = payload.get("response", payload)
    body = root.get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items if isinstance(items, list) else []


def _header(payload: dict) -> dict:
    root = payload.get("response", payload)
    return root.get("header") or {}


def _grade_ok(description: str, grade: Optional[str]) -> bool:
    if not grade or not description:
        return True
    if grade == "기사":
        return "기사" in description and not any(w in description for w in ("산업기사", "기능사", "기술사", "기능장"))
    return grade in description


def to_sessions(items: list, exam_id: str, checked_at: date) -> tuple[list[ExamSession], list[str]]:
    meta = EXAMS[exam_id]
    out, skipped = [], []
    for it in items:
        desc = str(it.get("description") or "")
        if not _grade_ok(desc, meta.get("grade")):
            continue
        yy, seq = it.get("implYy"), it.get("implSeq")
        reg_start, reg_end = _day(it.get("docRegStartDt")), _day(it.get("docRegEndDt"))
        exam_date, written_result = _day(it.get("docExamStartDt")), _day(it.get("docPassDt"))
        p_reg_start, p_reg_end = _day(it.get("pracRegStartDt")), _day(it.get("pracRegEndDt"))
        p_exam, p_exam_end, final = _day(it.get("pracExamStartDt")), _day(it.get("pracExamEndDt")), _day(it.get("pracPassDt"))
        label = desc or f"{yy}년 제{seq}회"
        if not (reg_end and exam_date and final):
            skipped.append(f"{label}: 필기 접수 마감·필기 시험일·최종 발표일 중 비어 있는 값이 있어 제외")
            continue
        practical = None
        if p_reg_end and p_exam and written_result:
            practical = PracticalStage(written_result_date=written_result, reg_start=p_reg_start, reg_end=p_reg_end,
                                       exam_date=p_exam, exam_end=p_exam_end)
        out.append(ExamSession(
            exam_id=exam_id, exam_name=meta["name"], round=f"{yy}년 제{seq}회",
            reg_start=reg_start, reg_end=reg_end, exam_date=exam_date, result_date=final,
            source=f"{SOURCE} — {label}", checked_at=checked_at, practical=practical,
        ))
    return merge(out), skipped


LATE_NOTE = "빈자리 추가 접수 — 정기 접수 취소로 남은 자리만 접수 가능"


def merge(sessions: list[ExamSession]) -> list[ExamSession]:
    """같은 회차가 정기 접수·빈자리 추가 접수 두 행으로 오면 한 회차로 합친다."""
    groups: dict = {}
    for s in sessions:
        groups.setdefault((s.exam_id, s.round), []).append(s)
    out = []
    for rows in groups.values():
        rows.sort(key=lambda s: (s.reg_start or s.reg_end, s.reg_end))
        base = rows[0]
        later = [r.reg_end for r in rows[1:] if r.reg_end > base.reg_end]
        if later:
            base = base.model_copy(update={"late_reg_end": max(later), "late_reg_note": LATE_NOTE})
        out.append(base)
    out.sort(key=lambda s: s.exam_date)
    return out


def fetch(exam_id: str, year: int, key: Optional[str] = None, client: Optional[httpx.Client] = None) -> dict:
    """시험일정 조회 Tool. 예외를 던지지 않고 ok/data 또는 ok=false/error 로 답한다."""
    if exam_id not in EXAMS:
        return fail("UNSUPPORTED_EXAM", f"공식 API로 일정을 받지 않는 시험입니다: {exam_id}")
    key = (key or os.environ.get("DATA_GO_KR_KEY") or "").strip()
    if not key:
        return fail("NO_KEY", "공공데이터포털 인증키가 없습니다. .env 에 DATA_GO_KR_KEY=키 를 넣어 주세요.")
    params = {"serviceKey": key, "numOfRows": 50, "pageNo": 1, "dataFormat": "json",
              "implYy": year, "qualgbCd": "T", "jmCd": EXAMS[exam_id]["jm_cd"]}
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        r = client.get(URL, params=params)
    except httpx.HTTPError as e:
        return fail("NETWORK", f"Q-Net 일정 API에 연결하지 못했습니다 ({type(e).__name__})")
    finally:
        if own:
            client.close()
    if r.status_code != 200:
        return fail("HTTP_ERROR", f"Q-Net 일정 API 응답 오류 (HTTP {r.status_code})")
    try:
        payload = r.json()
    except ValueError:
        text = r.text
        for code, name in ERRORS.items():
            if f"<returnReasonCode>{code}</returnReasonCode>" in text or f"<resultCode>{code}</resultCode>" in text:
                return fail(name, f"Q-Net 일정 API 오류 ({name})")
        return fail("BAD_RESPONSE", "Q-Net 일정 API 응답을 읽지 못했습니다")
    code = str(_header(payload).get("resultCode", "00"))
    if code not in ("00", "0"):
        name = ERRORS.get(code, "API_ERROR")
        if name == "NO_DATA":
            return ok({"exam_id": exam_id, "year": year, "sessions": [], "skipped": []})
        return fail(name, f"Q-Net 일정 API 오류 ({name})")
    sessions, skipped = to_sessions(_items(payload), exam_id, kst_today())
    return ok({"exam_id": exam_id, "year": year, "sessions": [s.model_dump(mode="json") for s in sessions], "skipped": skipped})


def load_snapshot(path: Path = SNAPSHOT) -> list[ExamSession]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return merge([ExamSession.model_validate(x) for x in raw.get("sessions", [])])
    except (ValueError, TypeError, AttributeError):
        return []


def refresh(years: list[int], path: Path = SNAPSHOT, key: Optional[str] = None) -> dict:
    """공식 API에서 받아 저장. 한 해라도 실패하면 기존 저장본을 그대로 둔다."""
    sessions, log = [], []
    for exam_id in EXAMS:
        for y in years:
            res = fetch(exam_id, y, key)
            if not res["ok"]:
                return fail(res["error"]["code"], f"{exam_id} {y}년: {res['error']['message']} — 기존 저장본 유지")
            sessions += res["data"]["sessions"]
            log.append({"exam_id": exam_id, "year": y, "count": len(res["data"]["sessions"]), "skipped": res["data"]["skipped"]})
    snap = {"fetched_at": datetime.now().isoformat(timespec="seconds"), "source": SOURCE,
            "url": URL, "log": log, "sessions": sessions}
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return ok(snap)


def main(argv: list[str]) -> int:
    from .config import load_env
    load_env()
    this = kst_today().year
    years = [int(a) for a in argv] or [this, this + 1]
    res = refresh(years)
    if not res["ok"]:
        print(f"[실패] {res['error']['code']}: {res['error']['message']}")
        return 1
    for row in res["data"]["log"]:
        print(f"{row['exam_id']} {row['year']}년: {row['count']}회차")
        for s in row["skipped"]:
            print(f"  - {s}")
    for s in res["data"]["sessions"]:
        p = s.get("practical") or {}
        print(f"  {s['round']}: 필기 접수 ~{s['reg_end']}, 필기 {s['exam_date']}, 실기 접수 ~{p.get('reg_end')}, 실기 {p.get('exam_date')}, 최종 발표 {s['result_date']}")
    print(f"저장: {SNAPSHOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
