from datetime import date

from routemaker.engine import analyze
from routemaker.extract import extract_posting, validate
from routemaker.loader import DATA, load_all
from routemaker.models import Feasibility, MatchStatus

D = load_all()
TEXT = (DATA / "sample_posting_a.txt").read_text(encoding="utf-8")

GOOD = {
    "company": "가상테크", "title": "2026 하반기 백엔드 개발자 신입",
    "deadline": "2026-12-18T17:00:00", "deadline_quote": "2026.11.23(월) ~ 2026.12.18(금) 17:00",
    "requirements": [
        {"type": "required", "category": "degree", "text": "4년제 학사 이상", "source_quote": "4년제 대학 졸업(예정)자", "exam_id": None, "min_score": None},
        {"type": "required", "category": "language", "text": "TOEIC 800 이상", "source_quote": "TOEIC 800점 이상", "exam_id": "toeic", "min_score": 800},
        {"type": "preferred", "category": "certificate", "text": "정보처리기사", "source_quote": "정보처리기사 소지자 우대", "exam_id": "info_engineer", "min_score": None},
        {"type": "preferred", "category": "certificate", "text": "SQLD 보유", "source_quote": "SQLD 자격 보유자 우대", "exam_id": "sqld", "min_score": None},
        {"type": "preferred", "category": "experience", "text": "클라우드 운영 경험", "source_quote": "클라우드 서비스 운영 경험", "exam_id": None, "min_score": None},
    ],
}


def fake(raw):
    return lambda *a, **k: raw


def ex(raw, text=TEXT):
    return extract_posting(text, "p_x", D["exams"], "2026-11-18", caller=fake(raw))


def test_good_extraction_flows_into_engine():
    e = ex(GOOD)
    assert e.deadline_verified and e.warnings == []
    a = analyze(D["profiles"]["u1"], e.to_posting(), D["sessions"], date(2026, 10, 20), D["exams"])
    v = {x.exam_id: x.feasibility for x in a.exams}
    assert v == {"toeic": Feasibility.possible, "sqld": Feasibility.impossible}


def test_hallucinated_quote_becomes_pending():
    raw = {**GOOD, "requirements": GOOD["requirements"] + [
        {"type": "required", "category": "certificate", "text": "ADsP 보유", "source_quote": "ADsP 필수", "exam_id": "adsp", "min_score": None}]}
    e = ex(raw)
    assert not e.requirements[-1].quote_verified
    a = analyze(D["profiles"]["u1"], e.to_posting(), D["sessions"], date(2026, 10, 20), D["exams"])
    assert a.requirements[-1].status == MatchStatus.pending
    assert "adsp" not in {x.exam_id for x in a.exams}


def test_deadline_mismatch_flagged():
    e = ex({**GOOD, "deadline": "2026-12-19T17:00:00"})
    assert not e.deadline_verified
    assert any("다름" in w for w in e.warnings)


def test_missing_deadline_blocks_posting():
    e = ex({**GOOD, "deadline": None, "deadline_quote": None})
    try:
        e.to_posting()
        assert False
    except ValueError:
        pass


def test_unknown_exam_unlinked():
    raw = {**GOOD, "requirements": [{**GOOD["requirements"][1], "exam_id": "made_up"}]}
    e = ex(raw)
    assert e.requirements[0].exam_id is None


def test_year_inferred_warning():
    text = TEXT.replace("2026.11.23(월) ~ 2026.12.18(금) 17:00", "11/23 ~ 12/18 17:00")
    e = ex({**GOOD, "deadline_quote": "11/23 ~ 12/18 17:00"}, text)
    assert e.deadline_verified
    assert any("추정" in w for w in e.warnings)


MULTI = """접수기간: 2026.09.29 ~ 2026.10.13 18:00
- 행정(일반) : 공인어학성적이 TOEIC 기준 850점 이상인 자
- AI·전산 : 정보처리기사 또는 빅데이터분석기사 자격 소지자로서, 공인어학성적이 TOEIC 기준 700점 이상인 자"""


def _multi_raw(**over):
    raw = {
        "company": "가상공사", "title": "신입", "deadline": "2026-10-13T18:00:00",
        "deadline_quote": "2026.09.29 ~ 2026.10.13 18:00", "tracks": ["행정(일반)", "AI·전산", " AI·전산 "],
        "requirements": [
            {"type": "required", "category": "language", "text": "TOEIC 850", "track": "행정(일반)", "options": [],
             "source_quote": "공인어학성적이 TOEIC 기준 850점 이상인 자", "exam_id": "toeic", "min_score": 850},
            {"type": "required", "category": "certificate", "text": "정보처리기사 또는 빅데이터분석기사", "track": "AI·전산",
             "source_quote": "정보처리기사 또는 빅데이터분석기사 자격 소지자로서", "exam_id": "info_engineer", "min_score": None,
             "options": [{"name": "정보처리기사", "exam_id": "info_engineer", "min_score": None},
                         {"name": "빅데이터분석기사", "exam_id": "bigdata", "min_score": None}]},
            {"type": "required", "category": "language", "text": "TOEIC 700", "track": "전산직", "options": [],
             "source_quote": "공인어학성적이 TOEIC 기준 700점 이상인 자", "exam_id": "toeic", "min_score": 700},
            {"type": "required", "category": "language", "text": "TOEIC 700", "track": None,
             "source_quote": "공인어학성적이 TOEIC 기준 700점 이상인 자", "exam_id": None, "min_score": None,
             "options": [{"name": "TOEIC 700점", "exam_id": "toeic", "min_score": 700}]},
        ],
    }
    raw.update(over)
    return raw


def test_tracks_and_options_validated():
    e = validate(_multi_raw(), MULTI, "x", D["exams"])
    assert e.tracks == ["행정(일반)", "AI·전산"]
    r1, r2, r3, r4 = e.requirements
    assert r1.track == "행정(일반)" and not r1.options
    assert r2.track == "AI·전산" and r2.exam_id is None and r2.min_score is None
    assert [(o.name, o.exam_id) for o in r2.options] == [("정보처리기사", "info_engineer"), ("빅데이터분석기사", None)]
    assert r3.track is None and any("전산직" in w for w in e.warnings)
    assert not r4.options and r4.exam_id == "toeic" and r4.min_score == 700


def test_old_style_output_still_works():
    raw = _multi_raw()
    raw.pop("tracks")
    for r in raw["requirements"]:
        r.pop("track"); r.pop("options")
    e = validate(raw, MULTI, "x", D["exams"])
    assert e.tracks == [] and all(r.track is None for r in e.requirements)
    assert all(not r.options for r in e.requirements[:3])
    assert [(o.exam_id, o.min_score) for o in e.requirements[3].options] == [("toeic", 700), (None, None)]


def test_requirement_for_several_tracks_is_split():
    from routemaker.extract import _match_tracks
    tracks = ["정규직 행정 5급_행정", "정규직 공무 4급_보안(보훈,장애)", "기간계약직 전산 5급_전산(광주)", "기간계약직 전산 5급_전산(세종)", "AI·전산"]
    assert _match_tracks("기간계약직 전산 5급_전산(광주), 기간계약직 전산 5급_전산(세종)", tracks) == tracks[2:4]
    assert _match_tracks("정규직", tracks) == tracks[:2]
    assert _match_tracks("정규직 공무 4급_보안(보훈,장애)", tracks) == [tracks[1]]
    assert _match_tracks("없는 분야", tracks) == []
    raw = _multi_raw()
    raw["tracks"] = ["행정(일반)", "AI·전산", "농업"]
    raw["requirements"][0]["track"] = "행정(일반), 농업"
    e = validate(raw, MULTI, "x", D["exams"])
    split = [r for r in e.requirements if r.id.startswith("r1_")]
    assert [r.track for r in split] == ["행정(일반)", "농업"] and all(r.exam_id == "toeic" for r in split)


def test_track_list_assigns_every_listed_track():
    raw = _multi_raw()
    raw["tracks"] = ["행정(일반)", "AI·전산", "농업"]
    for r in raw["requirements"]:
        r.pop("track")
        r["track_list"] = []
    raw["requirements"][0]["track_list"] = ["행정(일반)", "농업"]
    raw["requirements"][1]["track_list"] = ["행정(일반)", "AI·전산", "농업"]
    raw["requirements"][2]["track_list"] = ["없는 분야"]
    e = validate(raw, MULTI, "x", D["exams"])
    assert [(r.id, r.track) for r in e.requirements if r.id.startswith("r1")] == [("r1_1", "행정(일반)"), ("r1_2", "농업")]
    assert next(r for r in e.requirements if r.id == "r2").track is None
    assert next(r for r in e.requirements if r.id == "r3").track is None and any("없는 분야" in w for w in e.warnings)


def test_exam_not_named_in_quote_becomes_or_other():
    raw = _multi_raw()
    text = MULTI + "\n전산초급: 기사 자격을 취득한 자\n어학: 공인어학성적 800점 이상"
    raw["requirements"].append({"type": "required", "category": "certificate", "text": "기사 자격", "track": None,
                                "source_quote": "기사 자격을 취득한 자", "exam_id": "info_engineer", "min_score": None})
    raw["requirements"].append({"type": "required", "category": "language", "text": "어학 800", "track": None,
                                "source_quote": "공인어학성적 800점 이상", "exam_id": "toeic", "min_score": 800})
    e = validate(raw, text, "x", D["exams"])
    cert, lang = e.requirements[-2], e.requirements[-1]
    assert cert.exam_id is None and [(o.name, o.exam_id) for o in cert.options] == [("정보처리기사", "info_engineer"), ("그 밖의 해당 자격", None)]
    assert lang.exam_id is None and lang.options[0].min_score == 800 and lang.options[1].name == "그 밖의 공인어학 성적"
    named = e.requirements[0]
    assert named.exam_id == "toeic" and not named.options


def test_unknown_enum_values_do_not_crash():
    raw = _multi_raw()
    raw["requirements"][0]["category"] = "education"
    raw["requirements"][1]["category"] = "skill"
    raw["requirements"][2]["type"] = "nice_to_have"
    e = validate(raw, MULTI, "x", D["exams"])
    assert e.requirements[0].category.value == "degree"
    assert e.requirements[1].category.value == "other"
    assert e.requirements[2].type.value == "preferred"


def test_malformed_requirement_is_skipped_not_fatal():
    raw = _multi_raw()
    raw["requirements"].append({"type": "required", "category": "language", "text": "이상한 요건",
                                "source_quote": "x", "exam_id": "toeic", "min_score": "칠백"})
    raw["requirements"].append("문자열 요건")
    e = validate(raw, MULTI, "x", D["exams"])
    assert len(e.requirements) == 4 and sum("형식이 올바르지 않아" in w for w in e.warnings) == 2


def test_unlinked_exams_in_requirement_are_recovered():
    text = MULTI + "\n하단의 공단 인정 자격증 중 하나 이상을 취득한 자\n인정 자격증: 정보처리기사, SQLD, ADsP"
    raw = _multi_raw()
    raw["requirements"] = [
        {"type": "required", "category": "certificate", "track": "AI·전산", "options": [], "exam_id": None, "min_score": None,
         "text": "정보처리기사 또는 빅데이터분석기사 자격 소지 및 TOEIC 700점 이상",
         "source_quote": "정보처리기사 또는 빅데이터분석기사 자격 소지자로서, 공인어학성적이 TOEIC 기준 700점 이상인 자"},
        {"type": "required", "category": "certificate", "track": None, "options": [], "exam_id": None, "min_score": None,
         "text": "공단 인정 자격증 중 하나 이상 취득(정보처리기사, SQLD, ADsP 등)",
         "source_quote": "하단의 공단 인정 자격증 중 하나 이상을 취득한 자"},
    ]
    e = validate(raw, text, "x", D["exams"])
    cert, lang, listed = e.requirements
    assert [o.exam_id for o in cert.options] == ["info_engineer", None] and cert.track == "AI·전산"
    assert lang.exam_id == "toeic" and lang.min_score == 700 and lang.track == "AI·전산" and lang.type.value == "required"
    assert {o.exam_id for o in listed.options} == {"info_engineer", "sqld", "adsp", None}
    assert sum("AI가 연결하지 않은 시험" in w for w in e.warnings) == 2


def test_exam_name_only_in_ai_text_but_not_posting_is_ignored():
    raw = _multi_raw()
    raw["requirements"] = [{"type": "required", "category": "certificate", "track": None, "options": [], "exam_id": None,
                            "min_score": None, "text": "SQLD 등 데이터 자격", "source_quote": "정보처리기사 또는 빅데이터분석기사 자격 소지자로서"}]
    e = validate(raw, MULTI, "x", D["exams"])
    assert {o.exam_id for o in e.requirements[0].options} == {"info_engineer", None}


def test_deadline_time_found_in_other_line_is_used():
    text = "채용기간: 26.11.12 ~ 26.11.26\n자격: TOEIC 700점 이상\n1. 지원서 접수 : ‘26.11.12.(목) ~’26.11.26.(목) 14:00"
    raw = {**GOOD, "deadline": "2026-11-26T23:59:59", "deadline_quote": "채용기간: 26.11.12 ~ 26.11.26",
           "requirements": [], "tracks": []}
    e = validate(raw, text, "x", D["exams"])
    assert e.deadline.hour == 14 and e.deadline.minute == 0 and e.deadline_verified
    assert e.deadline_quote.endswith("14:00") and any("14:00" in w for w in e.warnings)


def test_time_of_start_date_is_not_taken_for_deadline():
    text = "접수기간: 11.26.(목) ~ 12.3.(목) 14:00\n자격: 학력 무관"
    raw = {**GOOD, "deadline": "2026-11-26T23:59:59", "deadline_quote": "11.26.(목)", "requirements": [], "tracks": []}
    e = validate(raw, text, "x", D["exams"])
    assert (e.deadline.hour, e.deadline.minute) == (23, 59)


TEXT_Q = (
    "응시자격\n4년제 학사 이상의 학력 보유자\n"
    "[필수]\n- TOEIC 700점 이상 (최근 2년 이내)\n"
    "[우대]\n- 데이터 관련 자격증 소지자\n  (OCP/빅데이터분석기사/ADP/ADsP/SQLD/SQLP 등)\n"
    "의료기관 근무 경험자 우대\n"
    "접수기간 : 2026년 04월 17일 (금) 14:00 ~ 2026년 04월 27일 (월) 23:00\n"
)


def test_locate_tolerates_dropped_particle_and_punctuation():
    from routemaker.extract import _locate
    assert _locate("4년제 학사 이상 학력 보유자", TEXT_Q) == "4년제 학사 이상의 학력 보유자"
    assert _locate("TOEIC 700점 이상(최근 2년 이내)", TEXT_Q)
    assert _locate("응시자격 4년제 학사 이상 학력", TEXT_Q) == "응시자격\n4년제 학사 이상의 학력"
    assert _locate("데이터 관련 자격증 소지자 OCP/빅데이터분석기사/ADP/ADsP/SQLD/SQLP 등", TEXT_Q)


def test_locate_still_rejects_changed_meaning():
    from routemaker.extract import _locate
    assert _locate("TOEIC 750점 이상", TEXT_Q) is None
    assert _locate("TOEIC 700점 이하", TEXT_Q) is None
    assert _locate("[우대] - TOEIC 700점 이상", TEXT_Q) is None
    assert _locate("4년제 학사 이상의 학력 필수", TEXT_Q) is None
    assert _locate("치료기관 근무 경험자 우대", TEXT_Q) is None
    assert _locate("의 학력", TEXT_Q) == "의 학력"
    assert _locate("학사이상학", "학사 이상 의학") is None


def test_dropped_particle_quote_is_verified_and_shown_as_original():
    raw = {"company": "가상", "title": "공고", "deadline": "2026-04-27T23:00:00",
           "deadline_quote": "2026년 04월 27일(월) 23:00",
           "requirements": [
               {"type": "required", "category": "degree", "text": "4년제 학사 이상",
                "source_quote": "4년제 학사 이상 학력 보유자", "exam_id": None, "min_score": None},
               {"type": "required", "category": "language", "text": "TOEIC 700점 이상",
                "source_quote": "TOEIC 700점 이상(최근 2년 이내)", "exam_id": "toeic", "min_score": 700}]}
    e = ex(raw, TEXT_Q)
    assert e.deadline_verified
    assert all(r.quote_verified for r in e.requirements)
    assert e.requirements[0].source_quote == "4년제 학사 이상의 학력 보유자"
    assert any("원문 표기로 맞춤" in w for w in e.warnings)
