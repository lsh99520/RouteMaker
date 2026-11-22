#!/usr/bin/env bash
# 마감일(11/23) 코드 동결 뒤 한 번 실행: 검사 → 공개 저장소 최종 교체 → 마감 태그
#   bash scripts/deadline.sh          # 실제 실행
#   bash scripts/deadline.sh --dry    # push 없이 검사·공개본 만들기까지만
set -euo pipefail

DRY=0
[ "${1:-}" = "--dry" ] && DRY=1
TAG="submit-20261123"
PUBLIC_REPO="https://github.com/lsh99520/RouteMaker.git"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "1) main 최신·깨끗한지 확인"
git fetch -q origin main
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || { echo "main 브랜치가 아닙니다"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "커밋하지 않은 변경이 있습니다"; git status -s; exit 1; }
git merge --ff-only -q origin/main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "origin/main과 다릅니다(push 안 한 커밋)"; exit 1; }
BASE="$(git rev-parse --short HEAD)"
echo "   기준 커밋: $BASE $(git log -1 --format=%s)"

echo "2) 테스트"
python -m pytest -q | tail -1

echo "3) 공개본 만들기 + 키·개인정보 검사"
rm -rf out/public
python scripts/make_public.py | tail -2

if [ "$DRY" = 1 ]; then
  echo "(--dry) 여기서 멈춥니다. 공개본: out/public"
  exit 0
fi

echo "4) 공개 저장소를 1커밋으로 교체"
cd out/public
git init -q -b main
git add -A
git -c user.name="lsh99520" -c user.email="lsh99520@users.noreply.github.com" \
  commit -q -m "RouteMaker 제출본 (기준: JobParser $BASE, 2026-11-23 마감)

2026 CAREER FAIR AI 해커톤 팀 잡파서. 실제 공고 원문·AI 원본 응답·팀 내부 파일은 제외."
git remote add origin "$PUBLIC_REPO"
git push -q -f origin main || true
REMOTE="$(git ls-remote origin main | cut -c1-7)"
LOCAL="$(git rev-parse --short=7 HEAD)"
[ "$REMOTE" = "$LOCAL" ] || { echo "공개 저장소 push 확인 실패 (원격 $REMOTE / 로컬 $LOCAL)"; exit 1; }
echo "   공개 저장소: $LOCAL"
cd "$ROOT"

echo "5) 마감 태그 $TAG"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "   태그가 이미 있습니다: $(git rev-parse --short "$TAG")"
else
  git tag -a "$TAG" -m "11/23 제출본 (공개 저장소 $LOCAL). 이후 기능·프롬프트·데이터 변경 금지"
  git push -q origin "$TAG"
fi

echo "완료: JobParser $BASE · 태그 $TAG · RouteMaker $LOCAL"
echo "남은 확인: 배포 서비스 접속, 나영 님께 PDF·메일 초안 전달"
