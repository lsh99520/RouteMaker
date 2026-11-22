import csv

from eval.run_eval import score_one, summarize
from routemaker.extract import validate
from routemaker.loader import load_all
from tests.test_extract import GOOD, TEXT

D = load_all()


def test_score_sample_perfect():
    e = validate(GOOD, TEXT, "sample_a", D["exams"])
    ans = next(csv.DictReader(open("eval/sample_answers.csv", encoding="utf-8-sig")))
    r = score_one(e, ans)
    assert r["deadline_ok"] and r["required_exam_hit"] == 1 and r["preferred_exam_hit"] == 2
    assert r["required_exam_extra"] == 0 and r["unverified_quotes"] == 0
    s = summarize([r])
    assert s["마감일 정확"] == "1/1" and s["시험·어학 요건 찾음(재현)"] == "3/3"


def test_score_detects_errors():
    bad = {**GOOD, "deadline": "2026-12-19T17:00:00",
           "requirements": [x for x in GOOD["requirements"] if x["exam_id"] != "toeic"]}
    e = validate(bad, TEXT, "sample_a", D["exams"])
    r = score_one(e, {"file": "x", "deadline": "2026-12-18 17:00", "exams_required": "toeic>=800",
                      "exams_preferred": "info_engineer;sqld", "count_required": "2", "count_preferred": "3"})
    assert not r["deadline_ok"] and r["required_exam_missed"] == "toeic>=800"


def test_optional_answer_is_neither_missed_nor_extra():
    e = validate(GOOD, TEXT, "sample_a", D["exams"])
    base = {"file": "x", "deadline": "2026-12-18 17:00", "exams_required": "toeic>=800",
            "count_required": "", "count_preferred": ""}
    with_opt = score_one(e, {**base, "exams_preferred": "sqld;info_engineer?"})
    assert with_opt["preferred_exam_answer"] == 1 and with_opt["preferred_exam_hit"] == 1
    assert with_opt["preferred_exam_extra"] == 0 and with_opt["preferred_exam_missed"] == ""
    without = score_one(e, {**base, "exams_preferred": "sqld"})
    assert without["preferred_exam_extra"] == 1
