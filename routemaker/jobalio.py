"""공공기관 채용정보(잡알리오) 공식 API 연동 (재정경제부, 공공데이터포털 15125273).

- 목록: 진행 중 공고 전체를 받아 30분 동안 메모리에 보관하고, 검색은 그 안에서 한다(호출 한도 절약).
- 상세: 공고 번호로 응시자격·우대사항·전형 절차·접수 기간을 받고, PDF 공고문이 있으면 본문도 읽는다.
- AI에 보내기 전에 전화번호·이메일·담당자/문의 줄을 지운다(대회 규정: 실제 개인정보를 외부 AI로 보내지 않음).
모든 함수는 예외를 밖으로 던지지 않고 {"ok": true, "data"} 또는 {"ok": false, "error": {"code", "message"}} 로 답한다.
"""
import os
import re
import threading
import time
from datetime import date, datetime
from typing import Optional

import httpx

from .models import kst_today

BASE = os.environ.get("JOBALIO_URL", "https://apis.data.go.kr/1051000/recruitment")
SOURCE = "공공기관 채용정보 공식 API (재정경제부 잡알리오, 공공데이터포털)"
CACHE_SECONDS = 30 * 60
PAGE_SIZE = 100
MAX_PAGES = 15
MAX_PDF_BYTES = 8 * 1024 * 1024

_cache = {"at": 0.0, "items": None}
FILE_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
                "Accept": "application/pdf,application/octet-stream,*/*", "Referer": "https://job.alio.go.kr/"}
_lock = threading.Lock()


def ok(data) -> dict:
    return {"ok": True, "data": data}


def fail(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def _key(key: Optional[str]) -> str:
    return (key or os.environ.get("DATA_GO_KR_KEY") or "").strip()


def _day(v) -> Optional[date]:
    v = re.sub(r"\D", "", str(v or ""))
    if len(v) != 8:
        return None
    try:
        return datetime.strptime(v, "%Y%m%d").date()
    except ValueError:
        return None


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    try:
        r = client.get(f"{BASE}/{path}", params=params)
    except httpx.HTTPError as e:
        return fail("NETWORK", f"공공기관 채용정보 API에 연결하지 못했습니다 ({type(e).__name__})")
    if r.status_code == 401 or r.status_code == 403:
        return fail("ACCESS_DENIED", "공공기관 채용정보 API 인증에 실패했습니다")
    if r.status_code == 429:
        return fail("LIMIT_EXCEEDED", "공공기관 채용정보 API 호출 한도를 넘었습니다")
    if r.status_code != 200:
        return fail("HTTP_ERROR", f"공공기관 채용정보 API 응답 오류 (HTTP {r.status_code})")
    try:
        body = r.json()
    except ValueError:
        if "SERVICE_KEY_IS_NOT_REGISTERED" in r.text or "<returnReasonCode>30</returnReasonCode>" in r.text:
            return fail("KEY_NOT_REGISTERED", "공공데이터포털 인증키가 등록되지 않았습니다")
        if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in r.text or "<returnReasonCode>22</returnReasonCode>" in r.text:
            return fail("LIMIT_EXCEEDED", "공공기관 채용정보 API 호출 한도를 넘었습니다")
        return fail("BAD_RESPONSE", "공공기관 채용정보 API 응답을 읽지 못했습니다")
    code = str(body.get("resultCode", "200"))
    if code not in ("200", "00", "0"):
        return fail("API_ERROR", f"공공기관 채용정보 API 오류 ({code})")
    return ok(body)


def summarize(it: dict, today: Optional[date] = None) -> dict:
    end = _day(it.get("pbancEndYmd"))
    today = today or kst_today()
    return {
        "sn": it.get("recrutPblntSn"),
        "institution": it.get("instNm") or "",
        "title": it.get("recrutPbancTtl") or "",
        "start": str(_day(it.get("pbancBgngYmd")) or ""),
        "end": str(end or ""),
        "days_left": (end - today).days if end else None,
        "fields": it.get("ncsCdNmLst") or "",
        "hire_type": it.get("hireTypeNmLst") or "",
        "region": it.get("workRgnNmLst") or "",
        "recruit_type": it.get("recrutSeNm") or "",
        "education": it.get("acbgCondNmLst") or "",
        "headcount": it.get("recrutNope"),
        "url": it.get("srcUrl") or "",
    }


def fetch_all(key: Optional[str] = None, client: Optional[httpx.Client] = None, force: bool = False) -> dict:
    """진행 중 공고 전체(최대 1,500건). 30분 캐시."""
    with _lock:
        if not force and _cache["items"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
            return ok({"items": _cache["items"], "cached": True})
        k = _key(key)
        if not k:
            return fail("NO_KEY", "공공데이터포털 인증키가 없습니다 (DATA_GO_KR_KEY)")
        own = client is None
        client = client or httpx.Client(timeout=15.0)
        items = []
        try:
            for page in range(1, MAX_PAGES + 1):
                res = _get(client, "list", {"serviceKey": k, "numOfRows": PAGE_SIZE, "pageNo": page,
                                            "ongoingYn": "Y", "resultType": "json"})
                if not res["ok"]:
                    if items:
                        break
                    return res
                rows = res["data"].get("result") or []
                items += rows
                total = int(res["data"].get("totalCount") or 0)
                if not rows or len(items) >= total:
                    break
        finally:
            if own:
                client.close()
        _cache.update(at=time.time(), items=items)
        return ok({"items": items, "cached": False})


IT_WORDS = ("정보통신", "전산", "IT", "정보기술", "데이터", "소프트웨어", "SW", "개발", "정보보호", "정보화")


def search(keyword: str = "", it_only: bool = False, limit: int = 30, key: Optional[str] = None,
           client: Optional[httpx.Client] = None, today: Optional[date] = None) -> dict:
    res = fetch_all(key, client)
    if not res["ok"]:
        return res
    words = [w for w in re.split(r"\s+", keyword.strip()) if w]
    out = []
    for it in res["data"]["items"]:
        s = summarize(it, today)
        if s["days_left"] is not None and s["days_left"] < 0:
            continue
        hay = " ".join([s["institution"], s["title"], s["fields"], s["region"], s["hire_type"]])
        if words and not all(w.lower() in hay.lower() for w in words):
            continue
        if it_only and not any(w in hay for w in IT_WORDS):
            continue
        out.append(s)
    # 오늘 마감인 공고는 준비할 시간이 없으므로 남은 기간이 있는 공고 뒤로 보낸다.
    out.sort(key=lambda s: (s["days_left"] is None, s["days_left"] == 0,
                            s["days_left"] if s["days_left"] is not None else 0))
    return ok({"total": len(out), "items": out[:limit], "cached": res["data"]["cached"], "source": SOURCE})


PHONE = re.compile(r"(?<!\d)(?:0\d{1,2}|1\d{3})[)\-.\s]?\d{3,4}[\-.\s]?\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CONTACT_LINE = re.compile(r"(담당자|문의처|문의\s*[:：]|연락처|전화\s*[:：]|☎|Tel\b|E-?mail)", re.I)
TITLES = "대리|주무관|과장|차장|팀장|부장|사원|주임|선임|책임|실장|담당"
PERSON_AFTER = re.compile(r"(담당자|담당|문의처|문의|연락처)\s*[:：]?\s*(?:[가-힣]{1,10}(?:팀|부|과|실|처|센터)\s+)?[가-힣]{2,4}(?=\s|[,)(/·]|$)")
PERSON_BEFORE = re.compile(r"[가-힣]{2,4}\s*(?:" + TITLES + r")(?=\s|[,)(/·]|$)")


def scrub(text: str) -> tuple[str, int]:
    """전화번호·이메일·담당자 이름 제거. 줄은 지우지 않는다(같은 줄의 마감일·접수 방법을 잃지 않도록)."""
    out, removed = [], 0
    for line in (text or "").splitlines():
        new = PHONE.sub("[연락처 삭제]", EMAIL.sub("[이메일 삭제]", line))
        if CONTACT_LINE.search(new):
            new = PERSON_BEFORE.sub("[담당자 삭제]", new)
            new = PERSON_AFTER.sub(lambda m: m.group(1) + " [담당자 삭제]", new)
        removed += new != line
        out.append(new)
    return "\n".join(out), removed


ALIO_FILE = "https://www.alio.go.kr/download/download.json?fileNo={}"
READABLE = (".pdf", ".hwp", ".hwpx")


def pick_notice(files: list) -> Optional[dict]:
    """첨부 중 본 공고문 하나를 고른다. '[참고]' 자료(직무설명서·양식 등)는 요건으로 잘못 읽힐 수 있어 쓰지 않는다."""
    def name(f):
        return str(f.get("atchFileNm") or "")

    main = [f for f in files or [] if name(f) and not re.match(r"\s*[\[(【]?\s*(참고|별첨|붙임|첨부|서식|양식)", name(f))]
    readable = [f for f in main if name(f).lower().endswith(READABLE)]
    for f in readable:
        if "공고" in name(f):
            return f
    if readable:
        return readable[0]
    return next((f for f in main if "공고" in name(f)), None)


def _download(client: httpx.Client, f: dict) -> tuple[Optional[bytes], str]:
    urls = []
    if f.get("recrutAtchFileNo"):
        urls.append(ALIO_FILE.format(f["recrutAtchFileNo"]))
    if f.get("url"):
        urls.append(f["url"])
    why = "다운로드 주소 없음"
    for u in urls:
        try:
            r = client.get(u, follow_redirects=True, headers=FILE_HEADERS)
        except httpx.HTTPError as e:
            why = f"연결 실패: {type(e).__name__}"
            continue
        if r.status_code != 200:
            why = f"HTTP {r.status_code}"
            continue
        if len(r.content) > MAX_PDF_BYTES:
            return None, "파일이 8MB 초과"
        head = r.content[:8]
        if head.startswith((b"%PDF", b"\xd0\xcf\x11\xe0", b"PK")):
            return r.content, ""
        why = "파일 대신 HTML 화면을 받음" if b"<" in r.content[:200] else "알 수 없는 형식"
    return None, why


def _attachment_text(client: httpx.Client, files: list) -> tuple[str, list[str]]:
    from .hwptext import HwpError, hwp_to_text
    from .pdftext import PdfError, pdf_to_text
    f = pick_notice(files)
    miss = "API 항목만으로 분석했어요 — 공고문에만 있는 요건은 원문에서 확인해 주세요"
    if f is None:
        names = ", ".join(str(x.get("atchFileNm", "")) for x in files or [] if x.get("atchFileNm"))
        return "", ([f"첨부 중 본 공고문을 찾지 못해 {miss} (첨부: {names})"] if names else ["첨부 공고문이 없어 API 항목만으로 분석했어요"])
    nm = str(f.get("atchFileNm"))
    if not nm.lower().endswith(READABLE):
        return "", [f"공고문({nm})이 PDF·한글 파일이 아니라 읽지 못해 {miss}"]
    data, why = _download(client, f)
    if data is None:
        return "", [f"공고문({nm})을 내려받지 못해 {miss} ({why})"]
    try:
        if data.startswith(b"%PDF"):
            text, notes = pdf_to_text(data)
        else:
            text, notes = hwp_to_text(data), []
    except (PdfError, HwpError) as e:
        return "", [f"공고문({nm})을 읽지 못해 {miss} ({e})"]
    return text, [f"첨부 공고문({nm})도 함께 읽었어요"] + notes


def detail_text(sn, key: Optional[str] = None, client: Optional[httpx.Client] = None,
                with_pdf: bool = True, max_chars: int = 40000) -> dict:
    """상세 조회 → AI에 보낼 본문 조립(개인정보 제거)."""
    k = _key(key)
    if not k:
        return fail("NO_KEY", "공공데이터포털 인증키가 없습니다 (DATA_GO_KR_KEY)")
    if not re.fullmatch(r"\d{1,12}", str(sn)):
        return fail("INVALID_INPUT", "공고 번호가 올바르지 않습니다")
    own = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        res = _get(client, "detail", {"serviceKey": k, "sn": sn, "resultType": "json"})
        if not res["ok"]:
            return res
        it = res["data"].get("result")
        if isinstance(it, list):
            it = it[0] if it else None
        if not it:
            return fail("NOT_FOUND", "공고를 찾지 못했습니다 (마감·삭제되었을 수 있어요)")
        s = summarize(it)
        parts = [
            f"[{s['institution']}] {s['title']}",
            f"접수 기간: {s['start']} ~ {s['end']}",
            f"채용 구분: {s['recruit_type']} / 고용 형태: {s['hire_type']} / 근무 지역: {s['region']} / 학력: {s['education']} / 채용 인원: {s['headcount']}",
            f"직무 분야(NCS): {s['fields']}",
            "■ 응시 자격", str(it.get("aplyQlfcCn") or "(없음)"),
            "■ 우대 사항", str(it.get("prefCn") or it.get("prefCondCn") or "(없음)"),
            "■ 전형 절차·접수 방법", str(it.get("scrnprcdrMthdExpln") or "(없음)"),
        ]
        notes = []
        if with_pdf:
            body, notes = _attachment_text(client, it.get("files") or [])
            if body:
                parts += ["■ 첨부 공고문 본문", body]
    finally:
        if own:
            client.close()
    text, removed = scrub("\n".join(parts))
    if removed:
        notes.append(f"담당자 연락처 등 개인정보로 보이는 {removed}곳을 지우고 AI에 보냈어요")
    if len(text) > max_chars:
        text = text[:max_chars]
        notes.append(f"본문이 길어 앞 {max_chars:,}자만 분석했어요 — 뒤쪽 요건은 직접 확인해 주세요")
    return ok({"summary": s, "text": text, "notes": notes})
