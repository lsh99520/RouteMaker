import base64
import io

import pytest

pytest.importorskip("reportlab", reason="PDF 테스트용 reportlab이 없으면 건너뜀 (pip install reportlab)")
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from routemaker.pdftext import PdfError, _looks_broken, pdf_to_text
from tests.test_api import client
from tests.test_extract import TEXT

pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))


def make_pdf(lines, pages=1):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for _ in range(pages):
        c.setFont("HYSMyeongJo-Medium", 10)
        for i, line in enumerate(lines):
            c.drawString(40, 800 - 14 * i, line)
        c.showPage()
    c.save()
    return buf.getvalue()


def b64(data):
    return base64.b64encode(data).decode()


def test_korean_pdf_text_is_read():
    text, notes = pdf_to_text(make_pdf(TEXT.splitlines()))
    assert "TOEIC" in text and "지원" in text and notes == []


def test_scanned_or_empty_pdf_is_rejected():
    try:
        pdf_to_text(make_pdf([]))
        assert False
    except PdfError as e:
        assert "스캔" in str(e)


def test_broken_font_text_is_detected():
    assert _looks_broken(" abc ")
    assert not _looks_broken("가상테크 2026 신입 채용 ※ 지원자격: TOEIC 800점 이상 ① 정보처리기사 「우대」")


def test_long_pdf_reads_first_pages_only():
    text, notes = pdf_to_text(make_pdf(TEXT.splitlines(), pages=45))
    assert notes and "앞 40쪽" in notes[0]


def test_extract_pdf_endpoint(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post("/api/postings/extract-pdf", json={"filename": "공고.pdf", "data": b64(make_pdf(TEXT.splitlines()))})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["warnings"][0].startswith("PDF(공고.pdf)에서 읽은 본문으로 분석")
    assert any(q["exam_id"] == "toeic" for q in body["requirements"])
    assert c.get(f"/api/postings/{body['id']}").status_code == 200


def test_extract_pdf_rejects_non_pdf_and_scans(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post("/api/postings/extract-pdf", json={"data": b64(b"hello")}).status_code == 400
    assert c.post("/api/postings/extract-pdf", json={"data": "!!!"}).status_code == 400
    r = c.post("/api/postings/extract-pdf", json={"data": b64(make_pdf([]))})
    assert r.status_code == 400 and "스캔" in r.json()["detail"]
