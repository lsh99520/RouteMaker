import io
import re

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 40
MIN_CHARS = 80


class PdfError(Exception):
    pass


def _looks_broken(text: str) -> bool:
    body = re.sub(r"\s", "", text)
    if not body:
        return True
    bad = sum(1 for ch in body if "\ue000" <= ch <= "\uf8ff" or ch == "\ufffd" or ord(ch) < 32)
    common = sum(1 for ch in body if "가" <= ch <= "힣" or ch.isascii())
    return bad / len(body) > 0.05 or common / len(body) < 0.5


def pdf_to_text(data: bytes) -> tuple[str, list[str]]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if len(data) > MAX_BYTES:
        raise PdfError(f"PDF가 너무 큽니다. {MAX_BYTES // (1024 * 1024)}MB 이하 파일만 올릴 수 있어요.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise PdfError("암호가 걸린 PDF는 읽을 수 없어요. 암호를 풀고 다시 올려 주세요.")
        pages = reader.pages
        notes = []
        if len(pages) > MAX_PAGES:
            notes.append(f"PDF가 {len(pages)}쪽이라 앞 {MAX_PAGES}쪽만 읽었어요 — 뒤쪽 요건은 직접 확인해 주세요")
            pages = pages[:MAX_PAGES]
        text = "\n".join((p.extract_text() or "") for p in pages)
    except PdfError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as err:
        raise PdfError(f"PDF 파일을 열 수 없어요. 파일이 손상됐는지 확인해 주세요. ({type(err).__name__})")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(re.sub(r"\s", "", text)) < MIN_CHARS:
        raise PdfError("PDF에서 글자를 거의 읽지 못했어요. 스캔한 이미지 PDF는 지원하지 않아요. 공고 본문을 복사해 붙여 넣어 주세요.")
    if _looks_broken(text):
        raise PdfError("PDF 글자가 깨져서 읽혀요(글꼴 문제). 공고 본문을 복사해 붙여 넣어 주세요.")
    return text, notes
