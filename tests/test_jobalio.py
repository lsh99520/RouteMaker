import io
from datetime import date

import httpx
import pytest

from routemaker import jobalio


def row(sn, title, inst="가상공단", end="20261130", fields="정보통신", region="대전"):
    return {"recrutPblntSn": sn, "instNm": inst, "recrutPbancTtl": title, "pbancBgngYmd": "20261101",
            "pbancEndYmd": end, "ncsCdNmLst": fields, "hireTypeNmLst": "정규직", "workRgnNmLst": region,
            "recrutSeNm": "신입", "acbgCondNmLst": "학력무관", "recrutNope": 2, "srcUrl": "https://example.org/p"}


ROWS = [row(1, "전산직 신입 채용"), row(2, "사무직 채용", fields="경영.회계.사무", end="20261201"),
        row(3, "지난 공고", end="20261001"), row(4, "데이터 분석 전문가", inst="가상정보원", end="20261120")]

DETAIL = {
    "recrutPblntSn": 1, "instNm": "가상공단", "recrutPbancTtl": "전산직 신입 채용", "pbancBgngYmd": "20261101",
    "pbancEndYmd": "20261130", "ncsCdNmLst": "정보통신", "hireTypeNmLst": "정규직", "workRgnNmLst": "대전",
    "recrutSeNm": "신입", "acbgCondNmLst": "학력무관", "recrutNope": 2, "srcUrl": "https://example.org/p",
    "aplyQlfcCn": "- 정보처리기사 소지자\n- TOEIC 700점 이상",
    "prefCn": "SQLD 소지자 우대",
    "scrnprcdrMthdExpln": "1. 접수기간: 2026. 11. 1.(일) ~ 2026. 11. 30.(월) 16:00\n문의: 인사팀 홍길동 대리 042-123-4567\n접수 방법: 온라인, 문의는 hr@example.org 또는 담당자 김가상 (042-000-1111) 에게 하되 마감 당일 접수가 몰릴 수 있으니 미리 제출하고, 제출 후 수정은 불가하며 접수 번호를 꼭 보관하세요.",
    "files": [{"atchFileNm": "공고문.pdf", "url": "https://files.example.org/a.pdf"}],
}


def make_pdf(text):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text.splitlines():
        c.drawString(40, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def handler(calls, pages=(ROWS,), detail=DETAIL, pdf=None):
    def h(req):
        calls.append(req.url)
        if req.url.path.endswith("/list"):
            p = int(req.url.params["pageNo"])
            rows = pages[p - 1] if p <= len(pages) else []
            return httpx.Response(200, json={"resultCode": 200, "resultMsg": "ok",
                                             "totalCount": sum(len(x) for x in pages), "result": rows})
        if req.url.path.endswith("/detail"):
            if detail is None:
                return httpx.Response(200, json={"resultCode": 200, "result": None})
            return httpx.Response(200, json={"resultCode": 200, "result": detail})
        if req.url.host == "files.example.org":
            return httpx.Response(200, content=pdf or b"<html>error</html>")
        if req.url.host == "www.alio.go.kr":
            return httpx.Response(200, content=b"<html>not here</html>")
        return httpx.Response(404)
    return h


@pytest.fixture(autouse=True)
def fresh_cache():
    jobalio._cache.update(at=0.0, items=None)
    yield
    jobalio._cache.update(at=0.0, items=None)


def mk(calls, **kw):
    return httpx.Client(transport=httpx.MockTransport(handler(calls, **kw)))


def test_search_pages_caches_and_filters():
    calls = []
    c = mk(calls, pages=(ROWS[:2], ROWS[2:]))
    today = date(2026, 11, 20)
    r = jobalio.search("", key="k", client=c, today=today)
    assert r["ok"] and r["data"]["total"] == 3
    assert [x["sn"] for x in r["data"]["items"]] == [1, 2, 4]
    assert r["data"]["items"][-1]["days_left"] == 0
    assert len([u for u in calls if u.path.endswith("/list")]) == 2
    r2 = jobalio.search("전산", key="k", client=c, today=today)
    assert [x["sn"] for x in r2["data"]["items"]] == [1]
    assert r2["data"]["cached"]
    assert len([u for u in calls if u.path.endswith("/list")]) == 2
    r3 = jobalio.search("", it_only=True, key="k", client=c, today=today)
    assert {x["sn"] for x in r3["data"]["items"]} == {1, 4}


def test_no_key_and_network_failures_are_returned():
    assert jobalio.search("", key="")["error"]["code"] == "NO_KEY"

    def boom(req):
        raise httpx.ConnectError("down")

    r = jobalio.search("", key="k", client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert r["error"]["code"] == "NETWORK"
    r = jobalio.search("", key="SECRET", client=httpx.Client(transport=httpx.MockTransport(lambda q: httpx.Response(500))))
    assert r["error"]["code"] == "HTTP_ERROR" and "SECRET" not in str(r)
    assert jobalio.detail_text("abc", key="k")["error"]["code"] == "INVALID_INPUT"


def test_scrub_removes_contacts_but_keeps_deadline():
    text, n = jobalio.scrub(DETAIL["scrnprcdrMthdExpln"])
    assert "2026. 11. 30.(월) 16:00" in text
    assert "042-123-4567" not in text and "홍길동" not in text
    assert "hr@example.org" not in text and "042-000-1111" not in text and "김가상" not in text
    assert "미리 제출" in text
    assert n >= 2


def test_detail_text_includes_fields_pdf_and_notes():
    calls = []
    pdf = make_pdf("Attachment body: NCS written test, interview\n" * 6)
    r = jobalio.detail_text(1, key="k", client=mk(calls, pdf=pdf))
    assert r["ok"]
    t = r["data"]["text"]
    assert "정보처리기사 소지자" in t and "SQLD 소지자 우대" in t and "16:00" in t
    assert "Attachment body" in t
    assert "042-123-4567" not in t
    assert any("첨부 공고문(공고문.pdf)도 함께 읽었어요" in n for n in r["data"]["notes"])
    assert any("개인정보" in n for n in r["data"]["notes"])


def test_detail_without_pdf_or_missing():
    calls = []
    d = dict(DETAIL, files=[{"atchFileNm": "공고문.zip", "url": "https://files.example.org/a.zip"}])
    r = jobalio.detail_text(1, key="k", client=mk(calls, detail=d))
    assert r["ok"] and any("PDF·한글 파일이 아니라" in n for n in r["data"]["notes"])
    r = jobalio.detail_text(1, key="k", client=mk(calls, pdf=b"<html>error</html>"))
    assert r["ok"] and any("내려받지 못해" in n and "HTML" in n for n in r["data"]["notes"])
    r = jobalio.detail_text(9, key="k", client=mk(calls, detail=None))
    assert r["error"]["code"] == "NOT_FOUND"


def test_api_endpoints(tmp_path, monkeypatch):
    from tests.test_api import client
    calls = []
    real = httpx.Client
    monkeypatch.setattr(jobalio.httpx, "Client", lambda *a, **k: real(transport=httpx.MockTransport(handler(calls))))
    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    c = client(tmp_path, monkeypatch)
    j = c.get("/api/jobs", params={"q": "전산"}).json()
    assert [x["sn"] for x in j["items"]] == [1]
    e = c.post("/api/jobs/1/analyze")
    assert e.status_code == 200
    e = e.json()
    assert e["source"] == "잡알리오 공고 1" and e["source_url"] == "https://example.org/p"
    assert e["warnings"][0].startswith("공공기관 채용정보 API")
    assert c.get(f"/api/postings/{e['id']}").status_code == 200
    assert c.post("/api/jobs/abc/analyze").status_code == 400


def test_api_without_key_says_what_to_do(tmp_path, monkeypatch):
    from tests.test_api import client
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    c = client(tmp_path, monkeypatch)
    r = c.get("/api/jobs")
    assert r.status_code == 503 and "붙여 넣" in r.json()["detail"]


def test_pick_notice_skips_reference_files():
    files = [{"atchFileNm": "[참고1] 채용분야 직무설명자료.pdf"}, {"atchFileNm": "식품안전정보원 2026년 제3차 채용 공고.hwp"},
             {"atchFileNm": "[참고2] 이의신청서 양식.hwp"}]
    assert jobalio.pick_notice(files)["atchFileNm"].endswith("채용 공고.hwp")
    assert jobalio.pick_notice([{"atchFileNm": "[참고1] 직무설명자료.pdf"}]) is None
    assert jobalio.pick_notice([{"atchFileNm": "채용안내.pdf"}, {"atchFileNm": "입사지원서.hwp"}])["atchFileNm"] == "채용안내.pdf"


def test_download_prefers_alio_url_then_api_url():
    pdf = make_pdf("Notice body line for download test\n" * 6)
    seen = []

    def h(req):
        seen.append(req.url.host)
        if req.url.host == "www.alio.go.kr":
            assert req.url.params["fileNo"] == "777"
            return httpx.Response(200, content=pdf)
        return httpx.Response(404)

    c = httpx.Client(transport=httpx.MockTransport(h))
    data, why = jobalio._download(c, {"recrutAtchFileNo": 777, "url": "https://opendata.example/x"})
    assert data.startswith(b"%PDF") and seen == ["www.alio.go.kr"]

    def h2(req):
        if req.url.host == "www.alio.go.kr":
            return httpx.Response(200, content=b"<html>login</html>")
        return httpx.Response(200, content=pdf)

    data, why = jobalio._download(httpx.Client(transport=httpx.MockTransport(h2)), {"recrutAtchFileNo": 1, "url": "https://opendata.example/x"})
    assert data.startswith(b"%PDF")
