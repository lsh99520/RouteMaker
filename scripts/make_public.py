"""공개 제출용 저장소 만들기.

git에 올라간 파일 중 scripts/public_exclude.txt에 적힌 경로를 빼고 out 폴더로 복사한 뒤,
API 키·비밀번호·전화번호·이메일 같은 값이 남아 있는지 검사한다.
기록(history) 없이 새 저장소로 올려야 뺀 파일이 과거 커밋으로 새지 않는다.

    python scripts/make_public.py            # out/public 에 만들고 검사
    python scripts/make_public.py --check    # 복사 없이 현재 저장소에서 공개될 파일만 검사
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_FILE = ROOT / "scripts" / "public_exclude.txt"

PATTERNS = [
    ("Anthropic API 키", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("키 값이 들어간 환경변수", re.compile(r"(?i)\b[A-Z_]*(API_KEY|SECRET|TOKEN|PASSWORD|REST_KEY|GO_KR_KEY)\s*[=:]\s*['\"]?(?!\$\{)[A-Za-z0-9+/%=_\-]{12,}")),
    ("공공데이터 서비스키", re.compile(r"(?i)serviceKey=(?!\{)[^&\s\"'<>]{20,}")),
    ("긴 16진수 키", re.compile(r"\b[0-9a-f]{32,64}\b")),
    ("이메일", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("전화번호", re.compile(r"(?<![\d.])0\d{1,2}[-. ]\d{3,4}[-. ]\d{4}(?!\d)")),
    ("주민등록번호", re.compile(r"\b\d{6}-[1-4]\d{6}\b")),
]
ALLOW = [
    re.compile(r"noreply@anthropic\.com"),
    re.compile(r"@example\.(com|org)"),
    re.compile(r"git@github\.com"),
    re.compile(r"^0\d{1,2}-(123-4567|000-1111)$"),  # 테스트용 가짜 번호
]
NOTION_LINK = re.compile(r"\[([^\]]+)\]\(https://(?:app\.notion\.com|www\.notion\.so)/[^)]+\)")
TEXT_EXT = {".py", ".md", ".txt", ".csv", ".json", ".html", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".example", ""}


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def excludes() -> list[str]:
    lines = EXCLUDE_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def is_excluded(path: str, rules: list[str]) -> bool:
    return any(path == r or (r.endswith("/") and path.startswith(r)) for r in rules)


def mask(s: str) -> str:
    return s if len(s) <= 8 else s[:4] + "…" + s[-2:]


def scan(files: list[tuple[str, Path]]) -> list[str]:
    found = []
    for rel, path in files:
        name = Path(rel).name
        if name == ".env" or (name.startswith(".env") and name != ".env.example"):
            found.append(f"{rel}: 비밀값 파일(.env)이 포함됨")
            continue
        if Path(rel).suffix.lower() not in TEXT_EXT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for no, line in enumerate(text.splitlines(), 1):
            for label, pat in PATTERNS:
                for m in pat.finditer(line):
                    if any(a.search(m.group(0)) for a in ALLOW):
                        continue
                    found.append(f"{rel}:{no}: {label} — {mask(m.group(0))}")
    return found


NOTE = """# 정확도 측정용 공고 원문은 공개 저장소에서 뺐습니다

정확도 측정(`eval/run_eval.py`)에는 잡알리오 등에 게시된 실제 채용공고 본문을 썼습니다.
공고 본문은 각 기관·기업이 작성한 글이고 담당자 정보가 들어 있을 수 있어, 공개 저장소에는 올리지 않았습니다.

- 정답표(`answers_real.csv`, `holdout/answers.csv`)와 측정 결과(`report*.md`, `results*.csv`)는 그대로 있습니다.
- 공고 원문 링크는 `eval/reference/ai-precheck-2026-11-19/README.md`에 있습니다.
- 다시 측정하려면 원문을 `eval/postings/`(추가 측정은 `eval/holdout/postings/`)에 정답표의 파일 이름으로 넣고 실행합니다.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out" / "public"))
    ap.add_argument("--check", action="store_true", help="복사하지 않고 공개될 파일만 검사")
    args = ap.parse_args()

    rules = excludes()
    files = tracked()
    keep = [f for f in files if not is_excluded(f, rules)]
    dropped = [f for f in files if is_excluded(f, rules)]

    if args.check:
        targets = [(f, ROOT / f) for f in keep]
    else:
        out = Path(args.out)
        if out.exists():
            shutil.rmtree(out)
        for f in keep:
            dst = out / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, dst)
            if dst.suffix == ".md":
                txt = dst.read_text(encoding="utf-8")
                new = NOTION_LINK.sub(r"\1(팀 내부 Notion)", txt)
                if new != txt:
                    dst.write_text(new, encoding="utf-8")
        for d in ("eval/postings", "eval/holdout/postings"):
            (out / d).mkdir(parents=True, exist_ok=True)
            (out / d / "README.md").write_text(NOTE, encoding="utf-8")
        targets = [(str(p.relative_to(out)), p) for p in out.rglob("*") if p.is_file()]

    print(f"git 파일 {len(files)}개 중 공개 {len(keep)}개, 제외 {len(dropped)}개")
    for top in sorted({d.split('/')[0] if '/' not in d[:-1] else '/'.join(d.split('/')[:2]) for d in dropped}):
        n = sum(1 for d in dropped if d.startswith(top))
        print(f"  - 제외: {top} ({n}개)")
    found = scan(targets)
    if found:
        print(f"\n검사에서 확인이 필요한 값 {len(found)}건:")
        for f in found:
            print("  " + f)
        return 1
    print("\n검사 통과: 키·비밀번호·이메일·전화번호·주민번호가 발견되지 않았습니다.")
    if not args.check:
        print(f"결과 폴더: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
