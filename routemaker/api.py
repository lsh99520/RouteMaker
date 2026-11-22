import json
import os
import re
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engine import analyze
from .extract import extract_posting
from .llm import LLMError
from . import planner
from .loader import DATA, load_all
from .models import Analysis, ExtractedPosting, Profile, kst_today
from .store import DEFAULT_USER, Store, clean_user_id

MAX_TEXT = 20000
MAX_PDF_TEXT = 40000
WEB = Path(__file__).resolve().parent.parent / "web"


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int, per_key_day: Optional[int] = None):
        self.per_minute, self.per_day = per_minute, per_day
        self.per_key_day = per_key_day or per_day
        self.hits = defaultdict(deque)
        self.day, self.day_count, self.key_count = kst_today(), 0, defaultdict(int)

    def check(self, key: str):
        now = time.time()
        if kst_today() != self.day:
            self.day, self.day_count, self.key_count = kst_today(), 0, defaultdict(int)
        if self.key_count[key] >= self.per_key_day:
            raise HTTPException(429, "오늘 이 기기에서 쓸 수 있는 AI 분석 횟수를 모두 썼어요. 내일 다시 쓰거나 시연용 샘플 공고를 이용해 주세요.")
        if self.day_count >= self.per_day:
            raise HTTPException(429, "오늘 공고 분석 한도를 모두 사용했습니다. 시연용 샘플 공고를 이용해 주세요.")
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise HTTPException(429, "요청이 너무 잦습니다. 1분 뒤에 다시 시도해 주세요.")
        q.append(now)
        self.day_count += 1
        self.key_count[key] += 1


class ExtractIn(BaseModel):
    text: str


class PdfIn(BaseModel):
    filename: str = ""
    data: str


class BlockIn(BaseModel):
    start: date
    end: date
    difficulty: Optional[str] = None


class DraftIn(BaseModel):
    strategy: str = "deadline"
    use_ai: bool = True


class FeedbackIn(BaseModel):
    action: dict = {}


class DoneIn(BaseModel):
    done: bool


def today() -> date:
    fixed = os.environ.get("ROUTEMAKER_TODAY")
    return date.fromisoformat(fixed) if fixed else kst_today()


COOKIE = "rm_uid"
COOKIE_MAX_AGE = 60 * 60 * 24 * 180


def _ics_text(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 73:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return out


def ics(a, company: str, now: datetime) -> str:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobParser//RouteMaker//KO", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_text('RouteMaker ' + company)}"]
    for t in a.tasks:
        if t.done:
            continue
        uid = re.sub(r"[^A-Za-z0-9._-]", "-", t.id)
        lines += ["BEGIN:VEVENT", f"UID:{uid}@routemaker", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{t.due:%Y%m%d}", f"DTEND;VALUE=DATE:{t.due + timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_ics_text(t.title)}",
                  f"DESCRIPTION:{_ics_text(f'RouteMaker · {company}' + (' · 고정 일정' if t.fixed else ''))}",
                  "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(x for line in lines for x in _fold(line)) + "\r\n"


def today_fixed() -> bool:
    return bool(os.environ.get("ROUTEMAKER_TODAY"))


def create_app(store_path: Optional[Path] = None, caller=None) -> FastAPI:
    app = FastAPI(title="RouteMaker API", version="0.13")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    base = load_all()

    def seed() -> dict:
        postings = {}
        for p in base["postings"].values():
            e = ExtractedPosting(
                id=p.id, company=p.company, title=p.title, deadline=p.deadline,
                deadline_quote=p.deadline_quote, deadline_verified=True,
                requirements=p.requirements, tracks=p.tracks, selected_track=p.selected_track,
                ai_generated=False, model="시연용 가상 공고",
            )
            postings[p.id] = e.model_dump(mode="json")
        return {
            "profiles": {p.id: p.model_dump(mode="json") for p in base["profiles"].values()},
            "postings": postings, "analyses": {}, "done": {},
        }

    store = Store(store_path or Path(os.environ.get("ROUTEMAKER_STORE", DATA / "store.json")), seed)
    app.state.store, app.state.caller = store, caller
    limiter = RateLimiter(int(os.environ.get("ROUTEMAKER_RPM", "5")), int(os.environ.get("ROUTEMAKER_DAILY", "300")),
                          int(os.environ.get("ROUTEMAKER_DAILY_PER_IP", "40")))
    feedback_limiter = RateLimiter(int(os.environ.get("ROUTEMAKER_FEEDBACK_RPM", "12")), int(os.environ.get("ROUTEMAKER_FEEDBACK_DAILY", "600")),
                                   int(os.environ.get("ROUTEMAKER_FEEDBACK_DAILY_PER_IP", "120")))

    @app.middleware("http")
    async def visitor(request: Request, call_next):
        cookie = request.cookies.get(COOKIE)
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        if not request.url.path.startswith("/api/"):
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-cache"
            if clean_user_id(cookie) == DEFAULT_USER and response.headers.get("content-type", "").startswith("text/html"):
                response.set_cookie(COOKIE, secrets.token_urlsafe(24), max_age=COOKIE_MAX_AGE, httponly=True,
                                    samesite="lax", secure=https)
            return response
        header = request.headers.get("x-rm-user")
        if clean_user_id(header) != DEFAULT_USER:
            uid = header
        elif clean_user_id(cookie) != DEFAULT_USER:
            uid = cookie
        else:
            uid = secrets.token_urlsafe(24)
        request.state.uid = uid
        response = await call_next(request)
        if cookie != uid:
            response.set_cookie(COOKIE, uid, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", secure=https)
        return response

    def uid_of(request: Request) -> str:
        return getattr(request.state, "uid", DEFAULT_USER)

    def us(request: Request):
        return store.user(uid_of(request))

    def need_profile(s, pid):
        p = s.get_profile(pid)
        if p is None:
            raise HTTPException(404, f"프로필 없음: {pid}")
        return p

    def need_posting(s, pid):
        p = s.get_posting(pid)
        if p is None:
            raise HTTPException(404, f"공고 없음: {pid}")
        return p

    def run(store, posting: ExtractedPosting, profile: Profile) -> Analysis:
        try:
            job = posting.to_posting()
        except ValueError as e:
            raise HTTPException(422, str(e))
        a = analyze(profile, job, base["sessions"], today(), base["exams"])
        a.today_fixed = today_fixed()
        done = store.done_set()
        for t in a.tasks:
            t.done = t.id in done
        a.today_tasks = [t.id for t in a.tasks if not t.done and (t.due - a.today).days <= 3]
        store.put_analysis(a)
        return a

    def progress(a: Analysis) -> dict:
        total = len(a.tasks)
        done = sum(t.done for t in a.tasks)
        return {"done": done, "total": total, "percent": round(done * 100 / total) if total else 0}

    @app.get("/api/health")
    def health():
        from . import qnet
        snap = qnet.SNAPSHOT
        fetched = None
        if snap.exists():
            try:
                fetched = json.loads(snap.read_text(encoding="utf-8")).get("fetched_at")
            except ValueError:
                fetched = None
        return {"ok": True, "today": today().isoformat(), "today_fixed": today_fixed(),
                "official_schedule": {"source": qnet.SOURCE, "fetched_at": fetched,
                                      "sessions": sum(1 for s in base["sessions"] if s.source.startswith(qnet.SOURCE))}}

    @app.get("/api/exams")
    def exams():
        return {"exams": base["exams"], "sessions": [s.model_dump(mode="json") for s in base["sessions"]]}

    @app.post("/api/reset")
    def reset(request: Request):
        store.reset(uid_of(request))
        return {"reset": True}

    @app.get("/api/profiles")
    def profiles(request: Request):
        return us(request).profiles()

    @app.get("/api/profiles/{pid}")
    def get_profile(pid: str, request: Request):
        return need_profile(us(request), pid)

    catalog = {e["exam_id"]: e for e in base["exams"]}

    def check_score(exam_id, score, what="점수"):
        if score is None:
            return
        e = catalog.get(exam_id, {})
        lo, hi = e.get("score_range") or (0, None)
        if score < lo or (hi is not None and score > hi):
            rng = f"{lo:g}~{hi:g}점 사이로" if hi is not None else f"{lo:g}점 이상으로"
            raise HTTPException(400, f"{e.get('exam_name', exam_id)} {what}는 {rng} 입력해 주세요 (입력값 {score:g})")

    @app.put("/api/profiles/{pid}")
    def put_profile(pid: str, body: Profile, request: Request):
        if body.id != pid:
            raise HTTPException(400, "경로의 id와 본문 id가 다릅니다.")
        for h in body.holdings:
            check_score(h.exam_id, h.score)
        for f in body.fixed_schedule:
            if f.end < f.start:
                raise HTTPException(400, f"개인 일정 '{f.title}'의 종료일이 시작일보다 빨라요")
        us(request).put_profile(body)
        return body

    @app.post("/api/postings/extract", response_model=ExtractedPosting)
    def extract(body: ExtractIn, request: Request):
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "공고 내용이 비어 있습니다.")
        if len(text) > MAX_TEXT:
            raise HTTPException(400, f"공고가 너무 깁니다. {MAX_TEXT}자 이하로 넣어 주세요.")
        limiter.check(request.client.host if request.client else "unknown")
        pid = "p_" + uuid.uuid4().hex[:8]
        try:
            e = extract_posting(text, pid, base["exams"], today().isoformat(), caller=app.state.caller)
        except LLMError as err:
            raise HTTPException(502, str(err))
        us(request).put_posting(e)
        return e

    @app.post("/api/postings/extract-pdf", response_model=ExtractedPosting)
    def extract_pdf(body: PdfIn, request: Request):
        import base64, binascii
        from .pdftext import MAX_BYTES, PdfError, pdf_to_text
        try:
            raw = base64.b64decode(body.data.split(",")[-1], validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "파일을 읽지 못했어요. PDF 파일을 다시 올려 주세요.")
        if not raw.startswith(b"%PDF"):
            raise HTTPException(400, "PDF 파일만 올릴 수 있어요.")
        try:
            text, notes = pdf_to_text(raw)
        except PdfError as err:
            raise HTTPException(400, str(err))
        if len(text) > MAX_PDF_TEXT:
            notes.append(f"본문이 길어 앞 {MAX_PDF_TEXT:,}자만 분석했어요 — 뒤쪽 요건은 직접 확인해 주세요")
            text = text[:MAX_PDF_TEXT]
        limiter.check(request.client.host if request.client else "unknown")
        pid = "p_" + uuid.uuid4().hex[:8]
        try:
            e = extract_posting(text, pid, base["exams"], today().isoformat(), caller=app.state.caller)
        except LLMError as err:
            raise HTTPException(502, str(err))
        e.warnings = [f"PDF({body.filename or '파일'})에서 읽은 본문으로 분석 — 표가 많은 공고는 문장이 끊겨 근거 확인이 안 될 수 있어요"] + notes + e.warnings
        us(request).put_posting(e)
        return e

    @app.get("/api/jobs")
    def jobs(q: str = "", it: bool = False, limit: int = 30):
        from . import jobalio
        res = jobalio.search(q[:50], it, max(1, min(limit, 50)), today=today())
        if not res["ok"]:
            code = res["error"]["code"]
            msg = ("공공기관 공고 검색이 아직 설정되지 않았어요. 공고 본문을 붙여 넣거나 PDF로 올려 주세요." if code == "NO_KEY"
                   else f"공공기관 공고를 불러오지 못했어요({code}). 잠시 후 다시 시도하거나 공고 본문을 붙여 넣어 주세요.")
            raise HTTPException(503, msg)
        return res["data"]

    @app.post("/api/jobs/{sn}/analyze", response_model=ExtractedPosting)
    def analyze_job(sn: str, request: Request):
        from . import jobalio
        res = jobalio.detail_text(sn, max_chars=MAX_PDF_TEXT)
        if not res["ok"]:
            code = res["error"]["code"]
            status = 404 if code == "NOT_FOUND" else 400 if code == "INVALID_INPUT" else 503
            raise HTTPException(status, res["error"]["message"] if status != 503 else
                                f"공공기관 공고를 불러오지 못했어요({code}). 잠시 후 다시 시도하거나 공고 본문을 붙여 넣어 주세요.")
        d = res["data"]
        pid = "p_" + uuid.uuid4().hex[:8]
        try:
            e = extract_posting(d["text"], pid, base["exams"], today().isoformat(), caller=app.state.caller)
        except LLMError as err:
            raise HTTPException(502, str(err))
        e.source = f"잡알리오 공고 {sn}"
        e.source_url = d["summary"].get("url") or None
        e.company = e.company or d["summary"]["institution"]
        e.warnings = [f"공공기관 채용정보 API(잡알리오 공고 {sn})에서 받은 응시자격·우대사항·전형 절차로 분석했어요"] + d["notes"] + e.warnings
        us(request).put_posting(e)
        return e

    @app.get("/api/postings")
    def postings(request: Request):
        return us(request).postings()

    @app.get("/api/postings/{pid}", response_model=ExtractedPosting)
    def get_posting(pid: str, request: Request):
        return need_posting(us(request), pid)

    @app.put("/api/postings/{pid}", response_model=ExtractedPosting)
    def put_posting(pid: str, body: ExtractedPosting, request: Request):
        s = us(request)
        old = need_posting(s, pid)
        if body.id != pid:
            raise HTTPException(400, "경로의 id와 본문 id가 다릅니다.")
        for r in body.requirements:
            for o in r.choices():
                if o.exam_id:
                    check_score(o.exam_id, o.min_score, "기준 점수")
        body.tracks = list(dict.fromkeys(t.strip() for t in body.tracks if t and t.strip()))
        if body.selected_track not in body.tracks:
            body.selected_track = None
        for r in body.requirements:
            if r.track is not None and r.track not in body.tracks:
                r.track = None
        if body.deadline is not None and body.deadline != old.deadline:
            body.deadline_verified = True
            body.warnings = [w for w in body.warnings if "마감일" not in w] + ["마감일을 사용자가 직접 수정함"]
        s.put_posting(body)
        return body

    @app.delete("/api/postings/{pid}")
    def delete_posting(pid: str, request: Request):
        s = us(request)
        need_posting(s, pid)
        s.delete_posting(pid)
        return {"deleted": pid}

    @app.post("/api/postings/{pid}/analyze")
    def analyze_posting(pid: str, request: Request, profile_id: str = "u1"):
        s = us(request)
        a = run(s, need_posting(s, pid), need_profile(s, profile_id))
        return {"analysis": a, "progress": progress(a)}

    @app.get("/api/postings/{pid}/analysis")
    def get_analysis(pid: str, request: Request, profile_id: str = "u1"):
        s = us(request)
        posting = need_posting(s, pid)
        if posting.deadline is None:
            raise HTTPException(404, "마감일을 입력하고 판정하면 결과가 나옵니다.")
        a = run(s, posting, need_profile(s, profile_id))
        return {"analysis": a, "progress": progress(a)}

    def cards_of(s, profile):
        out = []
        for p in s.postings():
            if p.deadline is None:
                continue
            out.append((p.to_posting(), run(s, p, profile)))
        return out

    def plan_of(s, profile_id="u1", strategy=None, overrides=None):
        profile = need_profile(s, profile_id)
        st = strategy or s.plan_strategy()
        ov = s.plan_overrides() if overrides is None else overrides
        return planner.build(cards_of(s, profile), today(), profile.fixed_schedule, ov, st), profile

    def llm_caller():
        if caller is not None:
            return caller
        from .llm import call_tool
        return call_tool

    @app.get("/api/plan")
    def get_plan(request: Request, profile_id: str = "u1"):
        plan, _ = plan_of(us(request), profile_id)
        return plan

    @app.put("/api/plan/blocks/{bid:path}")
    def put_block(bid: str, body: BlockIn, request: Request, profile_id: str = "u1"):
        s = us(request)
        plan, _ = plan_of(s, profile_id)
        b = next((x for x in plan.blocks if x.id == bid), None)
        if b is None:
            raise HTTPException(404, "없는 준비 기간입니다. 화면을 새로고침해 주세요.")
        if body.difficulty is not None and body.difficulty not in planner.WEIGHT:
            raise HTTPException(400, "난이도는 상·중·하 중 하나입니다.")
        err = planner.validate(b, body.start, body.end, today())
        if err:
            raise HTTPException(400, err)
        s.put_plan_block(bid, {"start": str(body.start), "end": str(body.end),
                               "difficulty": body.difficulty or b.difficulty, "source": "user"})
        plan, _ = plan_of(s, profile_id)
        return plan

    @app.post("/api/plan/draft")
    def make_draft(body: DraftIn, request: Request, profile_id: str = "u1"):
        s = us(request)
        if body.strategy not in planner.STRATEGIES:
            raise HTTPException(400, "정렬 기준은 deadline 또는 difficulty입니다.")
        base_plan, profile = plan_of(s, profile_id, body.strategy, {})
        overrides, ai_used, message = {}, False, "규칙으로 초안을 만들었어요."
        if body.use_ai:
            try:
                feedback_limiter.check(request.client.host if request.client else "?")
                overrides, message = planner.ai_draft(base_plan, profile.fixed_schedule, body.strategy, llm_caller())
                ai_used = True
            except LLMError as e:
                message = f"AI 초안을 만들지 못해 규칙 초안을 보여 드려요. ({e})"
            except HTTPException as e:
                message = f"AI 초안을 만들지 못해 규칙 초안을 보여 드려요. ({e.detail})"
        s.set_plan(overrides, body.strategy)
        plan, _ = plan_of(s, profile_id)
        return {"plan": plan, "ai": ai_used, "message": message}

    @app.delete("/api/plan/blocks")
    def reset_plan(request: Request, profile_id: str = "u1"):
        s = us(request)
        s.set_plan({}, s.plan_strategy())
        plan, _ = plan_of(s, profile_id)
        return plan

    @app.post("/api/plan/feedback")
    def plan_feedback(body: FeedbackIn, request: Request, profile_id: str = "u1"):
        s = us(request)
        plan, profile = plan_of(s, profile_id)
        result = planner.rule_feedback(plan, profile.fixed_schedule)
        result.update({"ai": False, "message": ""})
        try:
            feedback_limiter.check(request.client.host if request.client else "?")
            fb = planner.ai_feedback(plan, profile.fixed_schedule, body.action, llm_caller())
            result.update(fb)
            result["ai"] = True
        except LLMError as e:
            result["message"] = f"AI 의견을 받지 못해 규칙 검사 결과만 보여 드려요. ({e})"
        except HTTPException as e:
            result["message"] = f"AI 의견을 받지 못해 규칙 검사 결과만 보여 드려요. ({e.detail})"
        result["warnings"] = [w.model_dump(mode="json") for w in plan.warnings]
        return result

    @app.get("/api/postings/{pid}/calendar.ics")
    def calendar(pid: str, request: Request, profile_id: str = "u1"):
        s = us(request)
        posting = need_posting(s, pid)
        if posting.deadline is None:
            raise HTTPException(404, "마감일을 입력하고 판정하면 캘린더를 받을 수 있습니다.")
        a = run(s, posting, need_profile(s, profile_id))
        body = ics(a, posting.company or "", datetime.now(timezone.utc))
        return Response(body, media_type="text/calendar; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="routemaker-{pid}.ics"'})

    @app.patch("/api/tasks/{task_id:path}")
    def set_task(task_id: str, body: DoneIn, request: Request):
        store = us(request)
        pid = task_id.split(":", 1)[0]
        a = store.get_analysis(pid)
        if a is None or task_id not in {t.id for t in a.tasks}:
            raise HTTPException(404, f"할 일 없음: {task_id}")
        store.set_done(task_id, body.done)
        for t in a.tasks:
            if t.id == task_id:
                t.done = body.done
        a.today_tasks = [t.id for t in a.tasks if not t.done and (t.due - a.today).days <= 3]
        store.put_analysis(a)
        return {"analysis": a, "progress": progress(a)}

    @app.get("/api/dashboard")
    def dashboard(request: Request, profile_id: str = "u1"):
        s = us(request)
        profile = need_profile(s, profile_id)
        cards, today_list = [], []
        for p in s.postings():
            if p.deadline is None:
                cards.append({"posting": p, "analysis": None, "progress": None, "needs_input": True})
                continue
            a = run(s, p, profile)
            cards.append({"posting": p, "analysis": a, "progress": progress(a), "needs_input": False})
            by_id = {t.id: t for t in a.tasks}
            today_list += [{"posting_id": p.id, "company": p.company, **by_id[i].model_dump(mode="json")} for i in a.today_tasks]
        dated = [c for c in cards if c["posting"].deadline]
        nearest = min(dated, key=lambda c: c["posting"].deadline)["posting"] if dated else None
        today_list.sort(key=lambda t: t["due"])
        return {"today": today().isoformat(), "today_fixed": today_fixed(), "today_tasks": today_list, "nearest_deadline": nearest, "postings": cards}

    if (WEB / "index.html").exists():
        app.mount("/", StaticFiles(directory=WEB, html=True), name="web")

    return app


app = create_app()
