# RouteMaker

채용공고 마감에서 거꾸로 계산해, 응시할 시험 회차와 오늘 할 일까지 알려 주는 AI 에이전트
(2026 대한민국 청년 CAREER FAIR AI 해커톤 · 팀 잡파서)

- 서비스: https://jobparser-production.up.railway.app — 로그인 없이 바로 사용. '합성' 표시 공고·사용자는 시연용 가상 데이터
- 시연 영상: [`docs/demo-video/RouteMaker_demo.mp4`](docs/demo-video/RouteMaker_demo.mp4) (70초)
- 정확도 측정: 실제 공고 20건 3회 [`eval/report_run1.md`](eval/report_run1.md)~[`run3`](eval/report_run3.md), 개발에 쓰지 않은 새 공고 7건 [`eval/holdout/report_run1.md`](eval/holdout/report_run1.md)~[`run3`](eval/holdout/report_run3.md)
- 시연 점검: 날짜 25개 × 사용자 조건 10종 × 공고 6종 [`qa/scenario_report.md`](qa/scenario_report.md), 화면 168회 [`qa/ui_report.md`](qa/ui_report.md)
- 실제 공고 원문과 AI 원본 응답은 공개 저장소에서 뺐습니다(정답표·결과표는 포함)

## 개발 메모 (v0.13)

## 구성
- `routemaker/models.py` 데이터 형식
- `routemaker/engine.py` 요건 판정, 시험 회차 역산, 충돌 검사, 대체 회차, 할 일 생성
- `routemaker/extract.py` LLM 공고 추출 + 원문 인용 검사
- `routemaker/llm.py` Claude API 호출 (기본 모델 `claude-haiku-5-5`)
- `routemaker/store.py` JSON 파일 저장소 (`data/store.json`, 처음 실행 시 합성 데이터로 채움)
- `routemaker/api.py` FastAPI 서버
- `data/` 시연 데이터: 가상 공고·가상 사용자 + 공개 자료 기준 2026년 시험 일정(SQLD·ADsP 전 회차, TOEIC 10~12월)

## 실행
```
pip install -r requirements.txt
copy .env.example .env      (Git Bash·Mac은 cp .env.example .env)
.env 파일을 열어 ANTHROPIC_API_KEY= 뒤에 키 입력
uvicorn routemaker.api:app --reload --port 8000
```
- API 문서와 직접 호출 화면: http://localhost:8000/docs
- 설정은 모두 `.env`에서: 날짜 고정 `ROUTEMAKER_TODAY`(비우면 실제 오늘, 한국 시간), 모델 `ROUTEMAKER_MODEL`, 호출 제한 `ROUTEMAKER_RPM`·`ROUTEMAKER_DAILY`
- `.env`는 .gitignore에 포함되어 있음. 저장소나 zip에 넣지 말 것
- 이미 시스템 환경변수로 설정된 값이 있으면 그 값이 우선
- 접속자별 데이터: 서버가 처음 접속한 브라우저에 익명 쿠키(`rm_uid`, HttpOnly, 180일)를 발급하고 쿠키별로 따로 저장. 처음 접속하면 시연 데이터가 복사됨. 다른 기기·시크릿 창에서는 보이지 않고 쿠키를 지우면 사라지며, 화면에 이 내용을 안내함
  - 이전 버전에서 쓰던 `X-RM-User` 헤더(localStorage `rm_user`)가 오면 그 값을 쿠키로 옮겨 기존 데이터를 이어 씀
  - 쿠키는 화면과 API가 같은 주소일 때만 동작하므로, 화면을 다른 도메인(예: Vercel)에 따로 올리지 말고 서버가 화면까지 함께 제공하는 현재 구조로 배포
- 화면 맨 아래 '시연 데이터 처음으로' = `POST /api/reset`
- 저장 데이터 전체 초기화: 서버를 끄고 `data/store.json` 삭제 (v0.8 이전 형식 파일은 자동으로 무시)
- 테스트: `pytest -q`

## 오늘 날짜와 시연 데이터
- 서버는 **실제 오늘(한국 시간)** 기준으로 판정함. 실제 공고(공공기관 공고 찾기·붙여넣기·PDF)와 공식 시험 일정을 쓰므로 날짜를 고정하지 않음
- `ROUTEMAKER_TODAY=YYYY-MM-DD`를 넣으면 그 날짜로 고정(개발·재현용). 고정하면 화면에 "시연 기준일"로 표시
- 시연용 가상 공고·지원자는 **예선 심사(11/24~30)부터 본선(12/7)까지 매일 같은 장면**이 나오도록 짬 (`tests/test_demo_window.py`가 11/20~12/7을 하루씩 검사)
  - 가상테크(마감 2027-01-15, TOEIC 800 필요·현재 750): 11/26까지는 TOEIC 584회 추가 접수(마감 임박 안내 + 586회 대안), 11/27부터는 585회가 해외 연수(12/10~16)와 겹쳐 586회 선택 → 가능
  - 가상데이터(마감 12/18, ADsP 필수): 2026 회차 끝, 2027 1회 결과(예상 3/6)가 마감 뒤 → 불가
  - 가상솔루션(마감 2027-04-16, SQLD 필수): 2027년 미공고 → 작년 기준 예상 회차로 조건부 + 공고 확인 할 일
  - 가상공사(마감 12/18, 행정·전산): 분야 선택 전에는 '모집 분야 선택 필요', 전산은 필수 요건 이미 충족
- 기존 엔진·달력 테스트는 10/20 기준 이전 시연 데이터(`tests/fixtures/demo_1020/`)로 계속 검사

## 요건 판정 규칙
- 어학(`valid_years`): 시험일로부터 유효기간이 지나면 미충족, 지원 마감 전에 만료되면 판단 보류, 시험일이 없으면 판단 보류
- SQLD(`renewal_years`): 취득 2년 경과 시 보수교육 이수 여부 확인으로 판단 보류
- 사용자가 직접 추가한 요건은 원문 근거 대신 '직접 추가'로 표시하고 그대로 판정

## 모집 분야와 'A 또는 B' 요건
- 공공기관 공고처럼 모집 분야마다 요건이 다르면 AI가 분야 목록(`tracks`)과 요건별 분야(`track`, 공통은 null)를 함께 뽑음. 사용자가 지원 분야를 고르면 그 분야와 공통 요건으로만 판정하고, 고르기 전에는 공통 요건만 판정한 뒤 "모집 분야 선택 필요"로 표시
- "정보처리기사 또는 빅데이터분석기사"처럼 하나만 있으면 되는 요건은 선택지(`options`)로 저장. 하나라도 충족하면 충족, 자동 판정 목록에 없는 선택지가 있으면 직접 확인, 모두 미충족이면 가장 빨리 갖출 수 있는 선택지로 일정 판정
- 요건 편집에서 분야 지정, 모집 분야 목록 수정, '또는' 선택지 추가·삭제 가능
- 시연 공고 `p_d`(가상공사): 행정/전산 두 분야, 전산은 '정보처리기사 또는 빅데이터분석기사'

## 출처·라이선스 (화면)
- 글꼴: Pretendard(SIL Open Font License 1.1, jsDelivr CDN). 불러오지 못하면 시스템 글꼴로 표시
- 아이콘: 화면 파일 안에 직접 그린 SVG

## 준비 기간 달력 (달력 중심 진입 · 액션 = 프롬프트)
- 첫 화면은 일정 달력. 판정 결과에서 시험 준비 기간(선택된 응시 회차의 시험일 전날까지)과 지원서 작성 기간(마감 전날까지)을 초록 막대로 표시
- 규칙 초안: 난이도(상·중·하)별 권장 기간(시험 28/21/14일, 서류 10/7/4일), 정렬 기준(마감 임박순·난이도순)에 따라 시험 준비끼리 겹치지 않게 앞당김, 개인 일정과 겹치면 그만큼 일찍 시작
- AI 초안: Claude가 같은 제약 안에서 초안을 짜고, 엔진이 날짜 규칙(오늘 이후, 시험일·마감 전날까지)을 통과한 것만 반영. 실패·키 없음·호출 제한 시 규칙 초안
- 조정: 데스크톱은 막대를 끌어 다른 날짜에 놓기, 휴대폰은 날짜 → ‘조정’. 규칙에 어긋나면 이유와 함께 거절(400)
- 사용자 행동(끌어 옮김, 기간·난이도 조정, 초안 다시 만들기, 개인 일정 추가·삭제)이 곧 AI 요청: 규칙 검사 결과(부담 집중·시험일 겹침·개인 일정 겹침·짧은 기간)와 함께 AI에 보내 연관성·난이도·부담을 고려한 의견과 최대 2개 조정 제안을 받음. 제안도 엔진 검증을 통과한 것만 ‘적용’ 버튼으로 표시
- API: `GET /api/plan`, `PUT /api/plan/blocks/{id}`, `POST /api/plan/draft`, `POST /api/plan/feedback`, `DELETE /api/plan/blocks`. AI 호출 제한: IP당 분당 `ROUTEMAKER_FEEDBACK_RPM`(기본 12), 하루 `ROUTEMAKER_FEEDBACK_DAILY`(기본 600)

## 캘린더 내보내기
- 로드맵의 남은 할 일을 `.ics` 파일로 내려받아 구글·아이폰·아웃룩 캘린더에 추가 (`GET /api/postings/{id}/calendar.ics`)

## 판정 결론
- 공고마다 필수 요건 기준으로 결론 하나를 냄: 필수 요건 갖춤 / 일정상 지원 가능 / 조건부(확정 안 된 일정) / 마감 전 충족 어려움
- 결론에는 응시할 회차·목표 점수·현재 점수·결과 발표일, 대안 회차, 직접 확인할 요건, 우대 요건 요약을 함께 표시
- 대안 회차: 선택 회차 다음으로 마감 전 결과가 나오는 회차. 대안 회차의 접수 마감이 선택 회차 결과 발표보다 빠르면 "미리 접수 필요"를 알리고, 로드맵에 '(선택)' 할 일로 추가
- 목표 점수가 있는 시험은 로드맵 응시 할 일에 "목표 N점 이상, 현재 M점"을 표시 (유효기간 지난 점수는 현재 점수로 보지 않음)
- `ROUTEMAKER_TODAY`로 날짜를 고정하면 화면에 "시연 기준일"로 표시

## 일정 데이터 규칙
- `status`: confirmed(공고된 일정) / expected(엔진이 작년 일정으로 만든 예상, 직접 입력하지 않음)
- `exams.json`의 `full_year_schedule: true`인 시험만 예상 일정을 만듦. 일부 회차만 있는 시험은 데이터 범위를 벗어나면 "일정 확인 필요"로 판정(불가로 단정하지 않음)
- 예상 일정 결과가 마감보다 30일 이내로 늦으면 "불가"가 아니라 "조건부 — 공고 후 재판정"
- 출처마다 발표일이 다르면 `result_date_latest`에 늦은 날짜를 넣음 → 늦은 날짜 기준 판정
- `checked_at`이 30일 넘게 지나면 "공식 사이트 재확인" 할 일 추가
- `reg_start`를 모르면 비워 둠

## 공식 시험 일정 API (정보처리기사)
- 출처: 한국산업인력공단 국가자격 시험일정 조회 서비스 (공공데이터포털 https://www.data.go.kr/data/15074408/openapi.do), 무료, 이용허락범위 제한 없음
- `routemaker/qnet.py`: 시험일정 조회 Tool. 모든 결과를 `{"ok": true, "data": ...}` 또는 `{"ok": false, "error": {"code", "message"}}`로 돌려주고 예외를 밖으로 던지지 않음. 실패 코드: NO_KEY, UNSUPPORTED_EXAM, NETWORK, HTTP_ERROR, BAD_RESPONSE, KEY_NOT_REGISTERED, KEY_EXPIRED, LIMIT_EXCEEDED 등
- 받는 값: 필기 원서접수(시작·종료), 필기 시험일, 필기 합격 발표일, 실기 원서접수(시작·종료), 실기 시험 기간, 실기 합격 발표일. **판정은 최종(실기) 발표일 기준**이고, 할 일에 필기 응시 → 실기 접수 → 실기 응시 → 최종 결과 확인이 생김. 실기 시험 기간이 개인 일정과 겹치면 그 회차를 제외
- 갱신: `.env`에 `DATA_GO_KR_KEY=공공데이터포털 인증키(Decoding)`를 넣고 `python -m routemaker.qnet` (기본: 올해·내년). 결과는 `data/qnet_sessions.json`에 저장되고, 서버는 화면 요청마다 API를 부르지 않고 이 저장본으로 판정함 — 공공데이터포털 장애·호출 한도와 무관하게 동작, 판정에 쓴 일정이 기록으로 남음, 마감 후 데이터가 바뀌지 않음
- 갱신이 한 해라도 실패하면 기존 저장본을 그대로 둠. 저장본이 없거나 깨져 있으면 정보처리기사는 이전처럼 '직접 확인'
- 저장본에 있는 시험은 1년 일정 전체가 있다고 보고, 다음 해 공고 전이면 올해 일정 기준 예상 회차로 '조건부' 판정
- 서버(Railway)에는 키가 필요 없음. `GET /api/health`의 `official_schedule`에 저장 시각과 회차 수 표시
- 한계: 필기 합격 후 다음 회차 실기에 응시하는 경로(필기 면제 기간)는 계산하지 않음. 응시 자격(학력·경력)은 판정하지 않음

## 공공기관 공고 찾기 (채용정보 API)
- 출처: 재정경제부 공공기관 채용정보 조회서비스(잡알리오, 공공데이터포털 https://www.data.go.kr/data/15125273/openapi.do), 무료, 이용허락범위 제한 없음, 개발계정 하루 1,000회
- `routemaker/jobalio.py`: 목록(`/1051000/recruitment/list`, 진행 중 공고 전체를 받아 30분 보관 — 검색할 때마다 부르지 않음)·상세(`/detail?sn=공고번호`) 조회 Tool. 결과는 qnet과 같은 ok/error 형식, 실패 코드: NO_KEY, NETWORK, HTTP_ERROR, ACCESS_DENIED, LIMIT_EXCEEDED, KEY_NOT_REGISTERED, BAD_RESPONSE, NOT_FOUND, INVALID_INPUT
- 분석 본문: 기관·제목·접수 기간·채용 구분·NCS 분야 + 응시자격(`aplyQlfcCn`)·우대사항(`prefCn`)·전형 절차와 접수 방법(`scrnprcdrMthdExpln`), 첨부가 PDF면 공고문 본문까지(8MB 이하). 첨부가 HWP 등이면 읽지 않았다고 경고
- **AI에 보내기 전 개인정보 제거**: 전화번호·이메일, '담당자/문의/연락처'가 있는 줄의 사람 이름(대회 규정: 실제 개인정보를 외부 AI로 보내지 않음). 줄 자체는 지우지 않아 같은 줄의 마감 시각·접수 방법은 남김. 지운 곳 수를 경고로 표시
- API: `GET /api/jobs?q=검색어&it=true&limit=30`(마감 가까운 순), `POST /api/jobs/{공고번호}/analyze`(추출 결과를 내 공고에 저장, `source`·`source_url` 포함). 키가 없거나 API 장애면 503과 "본문을 붙여 넣거나 PDF로 올려 주세요" 안내
- 서버에 `DATA_GO_KR_KEY` 환경변수가 있어야 동작(Railway 변수). 화면: 새 공고 분석 → '공공기관 공고 찾기'

## 추출 정확도 측정
- `eval/README.md` 참고. 실제 공고와 사람이 작성한 정답표로 `python eval/run_eval.py` 실행

## 배포
- Docker: `docker build -t routemaker .` → `docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... -v routemaker-data:/data routemaker`
- 호스팅 서비스는 `PORT` 환경변수를 자동으로 읽음
- 서버는 프록시 뒤에서 실제 접속자 IP를 읽도록 `--proxy-headers`로 실행 (안 하면 모든 접속자가 같은 IP로 보여 분당 호출 제한을 함께 씀). 하루 호출 한도는 서버 전체 합계라 비용 상한은 그대로
- Railway 배포 순서
  1. https://railway.com/new → GitHub 저장소 배포 → `lsh99520/JobParser` 선택 (Dockerfile 자동 인식)
  2. 서비스 Variables: `ANTHROPIC_API_KEY`, `DATA_GO_KR_KEY` (`ROUTEMAKER_TODAY`는 넣지 않음 — 실제 날짜로 판정)
  3. 서비스에 Volume 추가, 마운트 경로 `/data` (없으면 재배포마다 데이터 초기화)
  4. Settings → Networking → Generate Domain으로 주소 발급, Settings → Deploy의 Replicas는 1 (저장 파일을 서버 한 대가 씀)
  5. `주소/api/health`가 `{"ok": true, ...}`이면 완료
- 화면 `web/index.html`: 홈(다음 할 일·요약·앞으로 7일·마감 순 공고), 내 공고(AI 분석·요건 확인/편집·모집 분야·판정·할 일), 일정(월·주·목록, 개인 일정 추가 시 재판정, 확인 필요 알림), 내 정보. 디자인은 팀원 이태인의 v6 시안(`design/v6-web-demo` 브랜치)을 실제 API에 연결한 것. 화면 파일은 `web/` 폴더에 넣으면 서버 주소(`/`)에서 바로 열림. API는 같은 주소의 `/api/...`라 CORS 설정 없이 호출 가능
- 공고 추출 호출 제한: 같은 IP당 분당 `ROUTEMAKER_RPM`(기본 5회), 서버 전체 하루 `ROUTEMAKER_DAILY`(기본 300회). 초과 시 429
- 저장 데이터는 `/data/store.json`. 볼륨을 붙이지 않으면 재시작할 때 합성 데이터로 초기화됨

## API
| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | /api/health | 서버 상태, 기준 날짜 |
| POST | /api/reset | 내 데이터를 시연 데이터로 되돌리기 |
| GET | /api/dashboard?profile_id=u1 | 홈: 오늘 할 일, 가장 임박한 마감, 공고별 진행률 |
| GET | /api/profiles/{id} | 프로필 조회 |
| PUT | /api/profiles/{id} | 프로필 저장 (전체 교체) |
| GET | /api/exams | 시험 목록과 회차 일정 |
| POST | /api/postings/extract | 공고 텍스트 → AI 추출 결과 저장 `{"text": "..."}` |
| POST | /api/postings/extract-pdf | 글자가 든 PDF 공고 → 본문을 읽어 같은 방식으로 추출 `{"filename": "공고.pdf", "data": "<base64>"}`. 스캔 PDF·깨진 글꼴·암호 PDF는 이유와 함께 400 |
| GET | /api/postings | 공고 목록 |
| GET | /api/postings/{id} | 공고 추출 결과 |
| PUT | /api/postings/{id} | 사용자 확인·수정 저장 (전체 교체) |
| DELETE | /api/postings/{id} | 공고 삭제 |
| POST | /api/postings/{id}/analyze?profile_id=u1 | 판정 실행 → `{analysis, progress}` |
| GET | /api/postings/{id}/analysis | 현재 기준으로 다시 계산한 판정 결과 |
| GET | /api/postings/{id}/calendar.ics | 남은 할 일 캘린더 파일 |
| PATCH | /api/tasks/{task_id} | 할 일 체크 `{"done": true}` → `{analysis, progress}` |

## 화면 흐름
1. 공고 붙여넣기 → `POST /api/postings/extract`
2. `warnings`, `deadline_verified`, 요건별 `quote_verified`를 보여 주고 사용자가 수정
   - 자동 판정이 안 되는 요건(학위·경험 등)은 `user_confirmed`를 true/false로 설정
3. 수정본 `PUT /api/postings/{id}` → `POST /api/postings/{id}/analyze`
4. 할 일 체크 `PATCH /api/tasks/{task_id}` (체크 상태는 재분석해도 유지)

## 오류 응답
- 400 빈 공고, 너무 긴 공고(2만 자 초과), id 불일치
- 404 없는 공고·프로필·할 일
- 429 공고 추출 호출 한도 초과
- 422 마감일이 없어 판정 불가 → 사용자에게 마감일 입력 요청
- 502 LLM 호출 실패(키 없음 포함) → 안내 문구 표시

## 추출 검증 규칙
- 요건 근거 문구가 원문에 없으면 `quote_verified=false` → 판단 보류
- 마감일 근거 문구가 원문에 없거나 날짜가 다르면 `deadline_verified=false` + 경고
- 원문에 연도가 없으면 추정 연도 경고
- 목록에 없는 exam_id는 연결 해제
- `ai_generated=true`인 결과는 화면에 "AI가 추출한 결과" 표시

## 팀 작업 올리는 법
GitHub에 올리면 Notion **진행 공유 게시판**에 자동으로 기록됩니다. 커밋 메시지가 게시판 글 제목이 되므로 무엇을 했는지 구체적으로 적어 주세요.

- 웹: 저장소에서 폴더로 이동 → **Add file** → **Upload files** → 커밋 메시지 입력 → **Commit changes**
- 명령어: `git pull` → 파일 수정 → `git add .` → `git commit -m "무엇을 했는지"` → `git push`
- `.env`(API 키)는 절대 올리지 않습니다.

## 공개 제출용 저장소 만들기

정확도 측정에 쓴 실제 공고 원문, 팀 내부 규칙·Notion 자동 기록을 뺀 공개용 사본을 만듭니다.

```
python scripts/make_public.py
```

- 뺄 경로는 `scripts/public_exclude.txt`에 있습니다.
- 복사한 뒤 API 키·비밀번호·이메일·전화번호·주민번호가 남았는지 검사하고, 하나라도 나오면 실패로 끝납니다.
- 결과는 `out/public`에 생깁니다. 뺀 파일이 과거 기록으로 새지 않도록 **기록 없이 새 저장소로** 올립니다.
