# 정확도 측정용 공고 원문은 공개 저장소에서 뺐습니다

정확도 측정(`eval/run_eval.py`)에는 잡알리오 등에 게시된 실제 채용공고 본문을 썼습니다.
공고 본문은 각 기관·기업이 작성한 글이고 담당자 정보가 들어 있을 수 있어, 공개 저장소에는 올리지 않았습니다.

- 정답표(`answers_real.csv`, `holdout/answers.csv`)와 측정 결과(`report*.md`, `results*.csv`)는 그대로 있습니다.
- 공고 원문 링크는 `eval/reference/ai-precheck-2026-11-19/README.md`에 있습니다.
- 다시 측정하려면 원문을 `eval/postings/`(추가 측정은 `eval/holdout/postings/`)에 정답표의 파일 이름으로 넣고 실행합니다.
