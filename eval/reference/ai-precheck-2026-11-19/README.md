# AI 사전 조사 · 평가 참고 자료

2026년 11월 19일에 AI가 공개 채용공고를 수집하고, 본문에 적힌 접수 마감일과 시험·어학 요건을 대조해 정답표 초안을 작성했습니다. 사람 검토가 필요한 참고 자료입니다. RouteMaker 추출 정확도 측정은 아직 진행하지 않았습니다.

## 파일 구성

- `postings/`에 실제 채용공고의 공개 텍스트 21건이 있습니다. 각 파일 끝에서 원문을 열 수 있습니다. 후보에는 이미 접수가 종료된 공고도 포함됩니다.
- `ai_draft_answers_mh.csv`, `ai_draft_answers_ti.csv`, `ai_draft_answers_ny.csv`에 각 7건의 정답 초안이 있습니다. 접두어는 최초 수집 목록에서 사용한 파일 식별자입니다.
- 공고 21건 중 16건에 TOEIC, 정보처리기사, SQLD, ADsP 중 하나 이상의 필수 또는 우대 요건이 있습니다. 채용 시 마감 공고는 `mh07.txt` 1건입니다.
- 텍스트 검색으로 확인한 공식 공고 후보 36건 중 본문 전체가 이미지여서 제외한 건은 0건입니다. 이 수치는 확인한 후보의 범위에 해당합니다.

## 검토할 항목

- 잡알리오 공고는 사이트에 게시된 텍스트 본문을 사용했습니다. 기관 공고나 첨부파일에 접수 시각 혹은 모집 분야별 추가 요건이 있는지 원문에서 확인해 주세요. 날짜만 공개 텍스트에 있는 경우 초안에는 날짜를 적었습니다. [잡알리오 공공데이터 이용 안내](https://job.alio.go.kr/right.do)
- 여러 모집 분야의 TOEIC 최소 점수가 다르게 적힌 경우 확인된 점수를 각각 넣었습니다. 동일한 우대 요건에 가점 구간이 여러 개일 때는 첫 가점을 받는 최저 점수를 넣었습니다. 필수·우대 요건 개수 칸은 비워 두었습니다.
- KTV 채널 데이터 관리 공고는 공공누리 제1유형 자료이며, 담당자 이름과 전화번호를 지운 뒤 보관했습니다. [KTV 원문과 이용 조건](https://www.ktv.go.kr/ktvnews/recruit/view?board_num=201262&pageIndex=17)
- 검토가 끝난 항목을 실제 측정에 쓰려면 공식 공고 폴더와 정답표에 반영합니다. 평가 스크립트는 `eval/` 바로 아래의 `answers*.csv`를 읽습니다. [평가 절차](../../README.md)

## 공고별 원문 링크

| 참고 파일 | 게시 기관 | 원문 공고 |
| --- | --- | --- |
| [`mh01.txt`](postings/mh01.txt) | 공무원연금공단 | [2026년 하반기 신입직원(전산직 및 장애·보훈) 채용 공고](https://job.alio.go.kr/recruitview.do?idx=306244) |
| [`mh02.txt`](postings/mh02.txt) | 건강보험심사평가원 | [2026년 하반기 건강보험심사평가원 체험형 청년인턴 채용 공고](https://job.alio.go.kr/recruitview.do?idx=305539) |
| [`mh03.txt`](postings/mh03.txt) | 국립중앙의료원 | [무기계약직 전산행정(정보운영팀) 채용 공고](https://job.alio.go.kr/recruitview.do?idx=306704) |
| [`mh04.txt`](postings/mh04.txt) | 한국농수산식품유통공사 | [2026년 신입직원 채용공고](https://job.alio.go.kr/recruitview.do?idx=305395) |
| [`mh05.txt`](postings/mh05.txt) | 한국사회보장정보원 | [한국사회보장정보원 2026년도 제4차 직원 채용공고](https://job.alio.go.kr/recruitview.do?idx=306406) |
| [`mh06.txt`](postings/mh06.txt) | 한국에너지공단 | [한국에너지공단 신입직원(채용형 인턴) 채용 공고](https://job.alio.go.kr/recruitview.do?idx=305072) |
| [`mh07.txt`](postings/mh07.txt) | KTV 국민방송 | [2025년 유튜브 온라인 콘텐츠 제작 팀원(CG/채널관리) 모집](https://www.ktv.go.kr/ktvnews/recruit/view?board_num=201262&pageIndex=17) |
| [`ti01.txt`](postings/ti01.txt) | 한국고용정보원 | [2026년도 한국고용정보원 2차 직원 채용 공고](https://job.alio.go.kr/recruitview.do?idx=304653) |
| [`ti02.txt`](postings/ti02.txt) | 정보통신기획평가원 | [2026년 정보통신기획평가원 직원채용(전문직) 공고](https://job.alio.go.kr/recruitview.do?idx=302772) |
| [`ti03.txt`](postings/ti03.txt) | 한국전력공사 | [2026년도 하반기 4직급 대졸수준 신입사원 채용공고](https://job.alio.go.kr/recruitview.do?idx=304551) |
| [`ti04.txt`](postings/ti04.txt) | 한국수자원공사 | [\[한국수자원공사\] 2026년 하반기 일반직 신입사원 공채](https://job.alio.go.kr/recruitview.do?idx=305290) |
| [`ti05.txt`](postings/ti05.txt) | 한국청소년정책연구원 | [\[채용공고 2026-11호\] 휴직 대체인력 채용 공고](https://job.alio.go.kr/recruitview.do?idx=305037) |
| [`ti06.txt`](postings/ti06.txt) | 건강보험심사평가원 | [2026년 하반기 건강보험심사평가원 정규직 채용 공고](https://job.alio.go.kr/recruitview.do?idx=303961) |
| [`ti07.txt`](postings/ti07.txt) | 한국전력기술주식회사 | [2026년도 하반기 정규직(신입사원) 채용공고](https://job.alio.go.kr/recruitview.do?idx=304717) |
| [`ny01.txt`](postings/ny01.txt) | 한국사학진흥재단 | [한국사학진흥재단 2026년 1차 직원 채용 (일반경쟁채용 및 제한경쟁채용)](https://job.alio.go.kr/recruitview.do?idx=297877) |
| [`ny02.txt`](postings/ny02.txt) | 한국공항공사 | [2026년 한국공항공사 체험형 인턴 공개 채용](https://job.alio.go.kr/recruitview.do?idx=303125) |
| [`ny03.txt`](postings/ny03.txt) | 근로복지공단 | [\[근로복지공단\] '26년 2차 신규직원(행정직) 채용 공고](https://job.alio.go.kr/recruitview.do?idx=303549) |
| [`ny04.txt`](postings/ny04.txt) | 경북대학교병원 | [2026년 1월 제4차 임시직원 모집 공고(미화청소, 보건의료정보관리, 행정, 전산)](https://job.alio.go.kr/recruitview.do?idx=296216) |
| [`ny05.txt`](postings/ny05.txt) | 한국직업능력연구원 | [\[한국직업능력연구원\] 2026년도 제2차 직원(전문원) 채용 공고](https://job.alio.go.kr/recruitview.do?idx=300830) |
| [`ny06.txt`](postings/ny06.txt) | (재)한국보건의료정보원 | [2026년 제6차 직원채용 공고](https://job.alio.go.kr/recruitview.do?idx=306965) |
| [`ny07.txt`](postings/ny07.txt) | (재)우체국시설관리단 | [(재)우체국시설관리단 (본사)일반계약직(전산직) 채용 재공고](https://job.alio.go.kr/recruitview.do?idx=295901) |

## 출처 확인에 사용한 자료

- 잡알리오의 공개 공시 텍스트 이용 범위를 확인했습니다. [잡알리오 저작권 정책](https://job.alio.go.kr/right.do)
- 재정경제부가 개방한 공공기관 채용정보의 제공 범위와 이용 조건을 대조했습니다. [공공데이터포털 채용정보](https://www.data.go.kr/data/15050508/fileData.do)
- 마감일 없는 공고의 출처와 공공누리 이용 조건을 확인했습니다. [KTV 국민방송 공고](https://www.ktv.go.kr/ktvnews/recruit/view?board_num=201262&pageIndex=17)
