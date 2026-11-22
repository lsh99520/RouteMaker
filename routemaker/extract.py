import re
from datetime import datetime
from typing import Callable, Optional

from .models import ExtractedPosting, ReqCategory, ReqOption, ReqType, Requirement

TOOL = "record_posting"

SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": ["string", "null"]},
        "title": {"type": ["string", "null"]},
        "deadline": {"type": ["string", "null"], "description": "지원 마감 일시, YYYY-MM-DDTHH:MM:SS. 시각이 없으면 23:59:59"},
        "deadline_quote": {"type": ["string", "null"], "description": "마감일이 적힌 원문 문구를 글자 그대로"},
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["required", "preferred"]},
                    "category": {"type": "string", "enum": ["certificate", "language", "degree", "experience", "other"]},
                    "text": {"type": "string", "description": "요건을 짧게 요약"},
                    "source_quote": {"type": "string", "description": "근거 원문 문구를 글자 그대로"},
                    "exam_id": {"type": ["string", "null"], "description": "시험 목록의 exam_id 중 하나, 해당 없으면 null. options를 쓰면 null"},
                    "min_score": {"type": ["number", "null"]},
                    "track_list": {
                        "type": "array", "items": {"type": "string"},
                        "description": "이 요건이 해당하는 모집 분야 이름 목록(tracks 표기 그대로). 여러 분야에 해당하면 모두 적고, 모든 분야 공통이면 빈 배열",
                    },
                    "options": {
                        "type": "array",
                        "description": "'A 또는 B'처럼 하나만 있으면 되는 요건의 선택지. 아니면 빈 배열",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "exam_id": {"type": ["string", "null"]},
                                "min_score": {"type": ["number", "null"]},
                            },
                            "required": ["name", "exam_id", "min_score"],
                        },
                    },
                },
                "required": ["type", "category", "text", "source_quote", "exam_id", "min_score", "track_list", "options"],
            },
        },
        "tracks": {
            "type": "array", "items": {"type": "string"},
            "description": "모집 분야마다 자격 요건이 다를 때 분야 이름 목록(공고 표기 그대로). 분야별 차이가 없으면 빈 배열",
        },
    },
    "required": ["company", "title", "deadline", "deadline_quote", "tracks", "requirements"],
}

SYSTEM = """너는 한국어 채용공고에서 지원 요건과 마감일을 추출하는 도구다.
규칙:
- 공고에 적힌 내용만 추출한다. 추측해서 요건을 만들지 않는다.
- source_quote와 deadline_quote는 공고 원문의 문구를 한 글자도 바꾸지 않고 그대로 복사한다.
- '필수', '자격요건', '지원자격'은 required, '우대', '가점'은 preferred로 분류한다. 분명하지 않으면 required로 두지 말고 preferred로 둔다.
- 자격증·어학 요건은 아래 시험 목록에 같은 시험이 있을 때만 exam_id를 넣는다.
- 점수 기준이 있으면 min_score에 숫자만 넣는다.
- 마감일이 없거나 '채용 시 마감'처럼 날짜가 없으면 deadline과 deadline_quote를 null로 둔다.
- 마감일에 연도가 없으면 오늘 날짜 기준으로 가장 가까운 미래 날짜의 연도를 쓴다.
- 모집 분야(직무·직렬·분야)마다 자격 요건이 다르면 tracks에 분야 이름을 공고 표기대로 적는다. 특정 분야에만 해당하는 요건은 track_list에 해당 분야 이름을 모두 적는다. '<A, B>'처럼 여러 분야를 묶어 적은 요건이면 묶인 분야를 빠짐없이 적는다. 모든 분야 공통 요건은 track_list를 빈 배열로 둔다. 분야별 요건 차이가 없으면 tracks와 track_list는 모두 빈 배열이다.
- 자격증 이름 없이 분야·등급만 적힌 자격('정보기술분야 기사 이상', '소프트웨어 기술자 등급의 기사 자격', '전산 관련 자격증')이 정보처리기사가 속하는 분야(정보기술·정보처리·전산·소프트웨어)이면 요건 하나로 적고 options에 '정보처리기사'(exam_id info_engineer)와 '그 밖의 해당 자격'(exam_id null)을 넣는다. 정보처리기사가 속하지 않는 분야(건축·안전·기계 등)의 자격은 시험을 연결하지 않는다.
- 'A 또는 B 소지자'처럼 하나만 있으면 되는 요건은 요건 하나로 적고 options에 선택지를 모두 넣는다. 선택지마다 시험 목록에 있으면 exam_id를, 없으면 null을 넣는다. 이때 요건의 exam_id와 min_score는 null이다. 선택지가 하나뿐이면 options는 빈 배열이다.
- 'TOEIC 기준 700점 이상(다른 공인어학은 환산)'처럼 TOEIC을 기준으로 적은 어학 요건은 TOEIC 하나로 적는다.
- '정보처리기사 소지자로서, TOEIC 700점 이상인 자'처럼 자격증과 어학 성적을 함께 요구하면 자격증 요건과 어학 요건을 따로 적고, 각각 exam_id 또는 options로 시험을 연결한다.
- '아래 인정 자격증 중 하나 이상'처럼 목록을 가리키면 목록에 적힌 자격증을 options에 모두 넣는다."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _in_text(quote: Optional[str], text: str) -> bool:
    return bool(quote) and _norm(quote) in _norm(text)


# AI가 원문을 옮기며 흔히 빠뜨리는 것만 허용한다: 공백, 문장부호·괄호, 조사 '의'.
# 숫자와 그 밖의 글자는 원문과 같은 순서로 모두 있어야 하므로 '이상→이하', '700→750',
# '필수→우대'처럼 뜻이 바뀐 인용은 그대로 걸러진다.
_SKIP = r"\s.,·・()\[\]「」『』'\"‘’“”\-–•○●□■◆▶※"
_GAP = rf"(?:[{_SKIP}]|의)*"


def _locate(quote: Optional[str], text: str) -> Optional[str]:
    """인용이 원문에 있으면 원문 쪽 문장을 돌려준다. 없으면 None."""
    if not quote:
        return None
    if _in_text(quote, text):
        return quote
    core = [c for c in quote if not re.match(rf"[{_SKIP}]", c)]
    if len(core) < 6:
        return None
    m = re.search(_GAP.join(re.escape(c) for c in core), text)
    return text[m.start():m.end()].strip() if m else None


def _deadline_matches_quote(dt: datetime, quote: str) -> tuple[bool, bool]:
    nums = [int(n) for n in re.findall(r"\d+", quote)]
    has_md = dt.month in nums and dt.day in nums
    has_year = dt.year in nums or (dt.year % 100) in nums
    return has_md, has_year


def _times_for_date(text: str, month: int, day: int) -> list[tuple[int, int, str]]:
    date = re.compile(rf"(?<!\d)0?{month}\s*(?:[./\-]|월)\s*0?{day}(?!\d)")
    clock = re.compile(r"^[^\n\d~]{0,12}?(\d{1,2})\s*(?::\s*(\d{2})|시(?:\s*(\d{1,2})\s*분)?)")
    out = []
    for line in text.splitlines():
        for m in date.finditer(line):
            c = clock.match(line[m.end():])
            if not c:
                continue
            hh = int(c.group(1))
            mm = int(c.group(2) or c.group(3) or 0)
            if line[m.end():m.end() + c.end()].strip().startswith("~"):
                continue
            if 0 <= hh <= 23 and 0 <= mm <= 59 and not (hh, mm) == (23, 59):
                out.append((hh, mm, line.strip()))
    return out


def build_user_prompt(text: str, exams: list[dict], today: str) -> str:
    catalog = "\n".join(f"- {e['exam_id']}: {e['exam_name']}" for e in exams)
    return f"오늘 날짜: {today}\n\n시험 목록(exam_id: 시험명):\n{catalog}\n\n<공고>\n{text}\n</공고>"


def extract_posting(text: str, posting_id: str, exams: list[dict], today: str,
                    caller: Optional[Callable[..., dict]] = None) -> ExtractedPosting:
    if caller is None:
        from .llm import MODEL, call_tool
        caller, model = call_tool, MODEL
    else:
        model = "test"
    raw = caller(SYSTEM, build_user_prompt(text, exams, today), TOOL, SCHEMA)
    return validate(raw, text, posting_id, exams, model)


def _match_tracks(label: str, tracks: list[str]) -> list[str]:
    parts = [x.strip() for x in re.split(r"[,，/](?![^()]*\))", label) if x.strip()]
    found = []
    for part in parts:
        if part in tracks:
            found.append(part)
        else:
            found += [t for t in tracks if t.startswith(part + " ") or t.startswith(part + "_")]
    return list(dict.fromkeys(found))


ALIASES = {
    "info_engineer": ["정보처리"],
    "toeic": ["toeic", "토익"],
    "sqld": ["sqld", "sql개발자"],
    "adsp": ["adsp", "데이터분석준전문가"],
}


def _names_exam(exam_id: str, quote: Optional[str], names: dict) -> bool:
    q = _norm(quote).lower()
    keys = ALIASES.get(exam_id, []) + [_norm(names.get(exam_id, "")).lower()]
    return any(k and k in q for k in keys)


SCORE = re.compile(r"(?:toeic|토익)[^\d]{0,15}(\d{3})", re.I)


def _recover_exams(r: dict, text: str, names: dict, options: list, i: int, warnings: list):
    body = f"{r.get('source_quote') or ''} {r.get('text') or ''}"
    posting = _norm(text).lower()
    found = [eid for eid in names if _names_exam(eid, body, names)
             and any(k and k in posting for k in ALIASES.get(eid, []) + [_norm(names[eid]).lower()])]
    if not found:
        return options, []
    extra = []
    if "toeic" in found:
        m = SCORE.search(r.get("source_quote") or "") or SCORE.search(r.get("text") or "")
        score = float(m.group(1)) if m else None
        if r.get("category") == "language" and len(found) == 1:
            options = [ReqOption(name=names["toeic"], exam_id="toeic", min_score=score),
                       ReqOption(name="그 밖의 공인어학 성적", exam_id=None, min_score=None)]
        else:
            extra.append(Requirement(
                id=f"r{i}_lang", type=ReqType(r.get("type") if r.get("type") in ("required", "preferred") else "preferred"),
                category=ReqCategory.language, text=f"TOEIC {int(score)}점 이상" if score else "TOEIC",
                source_quote=r.get("source_quote") or "", exam_id="toeic", min_score=score,
                quote_verified=_locate(r.get("source_quote"), text) is not None,
            ))
    certs = [eid for eid in found if eid != "toeic"]
    if certs:
        options = [ReqOption(name=names[e], exam_id=e, min_score=None) for e in certs] + [
            ReqOption(name="그 밖의 해당 자격", exam_id=None, min_score=None)]
    warnings.append(f"요건 r{i}: AI가 연결하지 않은 시험({', '.join(names[e] for e in found)})을 문구에서 찾아 연결")
    return options, extra


def _req_tracks(r: dict, tracks: list[str], i: int, warnings: list[str]) -> list[Optional[str]]:
    labels = r.get("track_list")
    if labels is None:
        labels = [r.get("track")] if r.get("track") else []
    found, unknown = [], []
    for label in labels:
        if not isinstance(label, str) or not label.strip():
            continue
        label = label.strip()
        hit = [label] if label in tracks else _match_tracks(label, tracks)
        found += hit
        if not hit:
            unknown.append(label)
    found = list(dict.fromkeys(found))
    if unknown:
        warnings.append(f"요건 r{i}: 모집 분야 '{', '.join(unknown)}'가 분야 목록에 없음"
                        + ("" if found else " — 공통 요건으로 처리"))
    if not found or (len(tracks) > 1 and len(found) == len(tracks)):
        return [None]
    return found


def validate(raw: dict, text: str, posting_id: str, exams: list[dict], model: str = "") -> ExtractedPosting:
    known = {e["exam_id"] for e in exams}
    names = {e["exam_id"]: e["exam_name"] for e in exams}
    warnings: list[str] = []

    deadline, verified = None, False
    quote = raw.get("deadline_quote")
    if raw.get("deadline"):
        try:
            deadline = datetime.fromisoformat(raw["deadline"])
        except ValueError:
            warnings.append(f"마감일 형식을 읽을 수 없음: {raw['deadline']}")
    if deadline is None:
        warnings.append("마감일을 찾지 못함 — 직접 입력 필요")
    elif _locate(quote, text) is None:
        warnings.append("마감일 근거 문구가 원문에 없음 — 마감일 확인 필요")
    else:
        quote = _locate(quote, text)
        md, yr = _deadline_matches_quote(deadline, quote)
        if not md:
            warnings.append("추출한 마감일이 근거 문구의 날짜와 다름 — 마감일 확인 필요")
        else:
            verified = True
            if not yr:
                warnings.append(f"원문에 연도가 없어 {deadline.year}년으로 추정 — 확인 필요")

    if deadline is not None and (deadline.hour, deadline.minute) == (23, 59):
        found = _times_for_date(text, deadline.month, deadline.day)
        if found:
            hh, mm, q = min(found)
            deadline = deadline.replace(hour=hh, minute=mm, second=0)
            quote, verified = q, True
            warnings.append(f"본문의 다른 문구에 같은 날짜의 마감 시각({hh:02d}:{mm:02d})이 있어 그 시각으로 맞춤 — 확인 필요")

    tracks = list(dict.fromkeys(t.strip() for t in raw.get("tracks") or [] if isinstance(t, str) and t.strip()))[:30]

    reqs = []
    for i, r in enumerate(raw.get("requirements", []), 1):
        try:
            exam_id = r.get("exam_id")
            if exam_id and exam_id not in known:
                warnings.append(f"요건 r{i}: 목록에 없는 시험({exam_id}) — 시험 연결 해제")
                exam_id = None
            min_score = r.get("min_score")
            targets = _req_tracks(r, tracks, i, warnings)
            options = []
            for o in r.get("options") or []:
                name = (o.get("name") or "").strip()
                if not name:
                    continue
                oid = o.get("exam_id")
                options.append(ReqOption(name=name, exam_id=oid if oid in known else None, min_score=o.get("min_score")))
            if len(options) == 1:
                exam_id, min_score, options = options[0].exam_id or exam_id, options[0].min_score or min_score, []
            elif options:
                exam_id, min_score = None, None
            extra = []
            if not exam_id and not any(o.exam_id for o in options):
                options, extra = _recover_exams(r, text, names, options, i, warnings)
            if exam_id and not options and not _names_exam(exam_id, r.get("source_quote"), names):
                other = "그 밖의 공인어학 성적" if r.get("category") == "language" else "그 밖의 해당 자격"
                options = [ReqOption(name=names[exam_id], exam_id=exam_id, min_score=min_score),
                           ReqOption(name=other, exam_id=None, min_score=None)]
                warnings.append(f"요건 r{i}: 근거 문구에 '{names[exam_id]}' 이름이 없어 '{names[exam_id]} 또는 {other}'로 처리")
                exam_id, min_score = None, None
            found_quote = _locate(r.get("source_quote"), text)
            ok = found_quote is not None
            if ok and found_quote != r.get("source_quote"):
                warnings.append(f"요건 r{i}: 근거 문구를 원문 표기로 맞춤 — '{found_quote}'")
                r = {**r, "source_quote": found_quote}
            if not ok:
                warnings.append(f"요건 r{i} '{r.get('text')}': 근거 문구가 원문에 없음 — 판단 보류")
            rtype = r.get("type") if r.get("type") in {t.value for t in ReqType} else "preferred"
            category = r.get("category") if r.get("category") in {c.value for c in ReqCategory} else (
                "degree" if r.get("category") in ("education", "학력") else "other")
            for k, t in enumerate(targets, 1):
                reqs.append(Requirement(
                    id=f"r{i}" if len(targets) == 1 else f"r{i}_{k}", type=ReqType(rtype),
                    category=ReqCategory(category), text=r.get("text") or r.get("source_quote") or "(내용 없음)",
                    source_quote=r.get("source_quote") or "",
                    exam_id=exam_id, min_score=min_score, quote_verified=ok, track=t,
                    options=[o.model_copy() for o in options],
                ))
                for x in extra:
                    reqs.append(x.model_copy(update={"id": f"{x.id}_{k}" if len(targets) > 1 else x.id, "track": t}))
        except (ValueError, TypeError, AttributeError, KeyError) as err:
            warnings.append(f"요건 r{i}: 형식이 올바르지 않아 제외 ({type(err).__name__})")
    if not reqs:
        warnings.append("추출된 요건 없음 — 공고 내용 확인 필요")

    return ExtractedPosting(
        id=posting_id, company=raw.get("company"), title=raw.get("title"), deadline=deadline,
        deadline_quote=quote, deadline_verified=verified, requirements=reqs, tracks=tracks,
        warnings=warnings, model=model,
    )
