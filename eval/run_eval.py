import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from routemaker.extract import extract_posting
from routemaker.llm import LLMError
from routemaker.loader import load_all


def parse_exams(cell: str, optional: bool = False) -> set:
    out = set()
    for part in (cell or "").replace(" ", "").split(";"):
        if not part or part.endswith("?") != optional:
            continue
        part = part.rstrip("?")
        if ">=" in part:
            eid, score = part.split(">=")
            out.add((eid, float(score)))
        else:
            out.add((part, None))
    return out


def extracted_exams(e, typ: str) -> set:
    return {(o.exam_id, o.min_score) for r in e.requirements if r.type.value == typ
            for o in r.choices() if o.exam_id}


def score_one(e, ans: dict) -> dict:
    want_dl = (ans["deadline"] or "").strip()
    got_dl = e.deadline.strftime("%Y-%m-%d %H:%M") if e.deadline else "없음"
    if want_dl in ("", "없음"):
        dl_ok = e.deadline is None
    elif len(want_dl) == 10:
        dl_ok = e.deadline is not None and got_dl[:10] == want_dl
    else:
        dl_ok = got_dl == want_dl
    row = {"file": ans["file"], "deadline_answer": want_dl or "없음", "deadline_extracted": got_dl, "deadline_ok": dl_ok}
    for typ, col in (("required", "exams_required"), ("preferred", "exams_preferred")):
        want, got = parse_exams(ans.get(col, "")), extracted_exams(e, typ)
        allowed = {x[0] for x in parse_exams(ans.get(col, ""), optional=True)}
        got = {g for g in got if g[0] not in allowed or g in want}
        row[f"{typ}_exam_hit"] = len(want & got)
        row[f"{typ}_exam_answer"] = len(want)
        row[f"{typ}_exam_extra"] = len(got - want)
        row[f"{typ}_exam_missed"] = ";".join(f"{a}>={b:g}" if b else a for a, b in sorted(want - got, key=str))
    for typ, col in (("required", "count_required"), ("preferred", "count_preferred")):
        got_n = sum(r.type.value == typ for r in e.requirements)
        row[f"{typ}_count_answer"] = int(ans[col]) if ans.get(col, "").strip() else ""
        row[f"{typ}_count_extracted"] = got_n
    row["unverified_quotes"] = sum(not r.quote_verified for r in e.requirements)
    row["warnings"] = " | ".join(e.warnings)
    return row


def summarize(rows: list) -> dict:
    n = len(rows)
    dl = sum(r["deadline_ok"] for r in rows)
    hit = sum(r["required_exam_hit"] + r["preferred_exam_hit"] for r in rows)
    ans = sum(r["required_exam_answer"] + r["preferred_exam_answer"] for r in rows)
    extra = sum(r["required_exam_extra"] + r["preferred_exam_extra"] for r in rows)
    reqs = sum(r["required_count_extracted"] + r["preferred_count_extracted"] for r in rows)
    unv = sum(r["unverified_quotes"] for r in rows)
    return {
        "공고 수": n,
        "마감일 정확": f"{dl}/{n}",
        "시험·어학 요건 찾음(재현)": f"{hit}/{ans}",
        "정답에 없는 시험 연결(오탐)": extra,
        "원문에 없는 근거로 판단 보류된 요건": f"{unv}/{reqs}",
    }


def write_report(rows, summary, model, out: Path, holdout: bool = False):
    lines = [f"# 공고 추출 정확도 측정 결과", "", f"- 측정일: {date.today().isoformat()}", f"- 모델: {model}", ""]
    lines += ["## 요약", "", "| 항목 | 결과 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary.items()]
    lines += ["", "## 틀린 항목", ""]
    bad = [r for r in rows if not r["deadline_ok"] or r["required_exam_missed"] or r["preferred_exam_missed"]
           or r["required_exam_extra"] or r["preferred_exam_extra"] or r["unverified_quotes"]]
    if not bad:
        lines.append("없음")
    for r in bad:
        lines.append(f"- **{r['file']}**")
        if not r["deadline_ok"]:
            lines.append(f"  - 마감일: 정답 {r['deadline_answer']} / 추출 {r['deadline_extracted']}")
        for typ, label in (("required", "필수"), ("preferred", "우대")):
            if r[f"{typ}_exam_missed"]:
                lines.append(f"  - {label} 시험 놓침: {r[f'{typ}_exam_missed']}")
            if r[f"{typ}_exam_extra"]:
                lines.append(f"  - {label} 시험 오탐 {r[f'{typ}_exam_extra']}건")
        if r["unverified_quotes"]:
            lines.append(f"  - 원문에 없는 근거 {r['unverified_quotes']}건")
    lines += ["", "## 측정 방법", "",
              (f"- 공고: 개발 중 보지 않은 새 실제 채용공고 {len(rows)}건(공공기관·사기업, 본문 텍스트, 담당자 정보 삭제)" if holdout
               else f"- 공고: 잡알리오 공공기관 실제 채용공고 {len(rows)}건(본문 텍스트, 담당자 정보 삭제)"),
              ("- 정답표: 공고를 모은 팀원이 원문을 보고 작성하고, AI가 원문과 대조해 검토(본문에 적힌 내용만 정답으로 인정)" if holdout
               else "- 정답표: AI가 만든 초안을 팀원 2명이 공고 원문과 한 건씩 대조해 검수(본문에 적힌 내용만 정답으로 인정)"),
              "- 자격증 이름 없이 분야만 적힌 자격('정보기술분야 기사 이상' 등)의 정보처리기사는 허용(`info_engineer?`): 뽑아도 안 뽑아도 맞음으로 처리, 재현·오탐 집계에서 제외",
              "- 마감일: 정답과 날짜(시각이 적힌 경우 시각까지) 일치 여부",
              "- 시험·어학 요건: 정답표의 시험 코드·최저 점수와 추출 결과 비교",
              "- 요건 개수는 참고용으로 results.csv에만 기록"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", action="store_true", help="API를 다시 부르지 않고 저장된 추출 결과로 채점")
    ap.add_argument("--set", default="", help="holdout: 개발 중 보지 않은 새 공고(eval/holdout)만 채점")
    args = ap.parse_args()
    d = load_all()
    answers = []
    base = ROOT / args.set if args.set else ROOT
    for f in sorted(base.glob("answers*.csv")):
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            if (row.get("file") or "").strip():
                answers.append(row)
    raw_dir = base / "raw"
    raw_dir.mkdir(exist_ok=True)
    rows, model = [], ""
    from routemaker.models import ExtractedPosting
    for ans in answers:
        path = base / "postings" / ans["file"].strip()
        if not path.exists():
            print(f"[건너뜀] 공고 파일 없음: {ans['file']}")
            continue
        cache = raw_dir / (path.stem + ".json")
        if args.cached and cache.exists():
            e = ExtractedPosting.model_validate_json(cache.read_text(encoding="utf-8"))
        else:
            text = path.read_text(encoding="utf-8")
            try:
                e = extract_posting(text, path.stem, d["exams"], date.today().isoformat())
            except LLMError as err:
                print(f"[실패] {ans['file']}: {err}")
                continue
            cache.write_text(e.model_dump_json(indent=2), encoding="utf-8")
        model = e.model
        rows.append(score_one(e, ans))
        print(f"[완료] {ans['file']}")
    if not rows:
        print("채점할 결과가 없습니다.")
        return
    with open(base / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    summary = summarize(rows)
    write_report(rows, summary, model, base / "report.md", holdout=args.set == "holdout")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print("상세: eval/results.csv, eval/report.md")


if __name__ == "__main__":
    main()
