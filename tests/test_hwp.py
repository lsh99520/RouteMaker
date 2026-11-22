import io
import struct
import zipfile
import zlib

import pytest

from routemaker.hwptext import HwpError, _para_text, hwp_to_text, section_text


def rec(tag, body):
    size = len(body)
    if size < 0xFFF:
        return struct.pack("<I", tag | (size << 20)) + body
    return struct.pack("<I", tag | (0xFFF << 20)) + struct.pack("<I", size) + body


def para(text, extended=False):
    raw = b""
    if extended:
        raw += struct.pack("<H", 11) + b"\x00" * 14
    raw += text.encode("utf-16-le") + struct.pack("<H", 13)
    return rec(67, raw)


def test_para_text_skips_controls():
    raw = struct.pack("<H", 2) + b"\x00" * 14 + "지원 자격".encode("utf-16-le") + struct.pack("<H", 9) + b"\x00" * 14 + "TOEIC".encode("utf-16-le") + struct.pack("<H", 13)
    assert _para_text(raw) == "지원 자격\tTOEIC"


def test_section_text_compressed_and_long_record():
    body = rec(66, b"\x00" * 22) + para("가상공단 채용 공고") + para("정보처리기사 소지자", extended=True) + para("가" * 3000)
    raw = zlib.compressobj(9, zlib.DEFLATED, -15)
    comp = raw.compress(body) + raw.flush()
    t = section_text(comp, True)
    assert t.splitlines()[:2] == ["가상공단 채용 공고", "정보처리기사 소지자"]
    assert len(t.splitlines()[2]) == 3000
    with pytest.raises(HwpError):
        section_text(b"not deflate", True)


def test_hwpx_text():
    xml = ('<hs:sec xmlns:hp="x" xmlns:hs="y"><hp:p><hp:run><hp:t>가상공단 2027 채용 공고</hp:t></hp:run></hp:p>'
           '<hp:p><hp:run><hp:t>지원 자격: TOEIC 700점 이상 &amp; </hp:t><hp:t>정보처리기사 소지자</hp:t></hp:run></hp:p>'
           + "".join(f"<hp:p><hp:run><hp:t>전형 절차 안내 {i}</hp:t></hp:run></hp:p>" for i in range(10)) + "</hs:sec>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", xml)
    t = hwp_to_text(buf.getvalue())
    assert "지원 자격: TOEIC 700점 이상 & 정보처리기사 소지자" in t


def test_rejects_non_hwp():
    with pytest.raises(HwpError):
        hwp_to_text(b"%PDF-1.4 nope")
    with pytest.raises(HwpError):
        hwp_to_text(b"\xd0\xcf\x11\xe0" + b"\x00" * 100)
