"""HWP(한글 5.x)·HWPX 공고문에서 본문 글자만 꺼낸다. 공공기관 공고문은 대부분 HWP라서 필요하다.

HWP 5.x: OLE 복합 파일 안의 BodyText/Section* 스트림(압축 시 raw deflate)에 레코드가 이어져 있고,
문단 글자는 HWPTAG_PARA_TEXT(태그 67) 레코드에 UTF-16LE로 들어 있다. 표 안의 글자도 같은 레코드라 함께 나온다.
HWPX: zip 안의 Contents/section*.xml 의 <hp:t> 글자.
"""
import io
import re
import struct
import zipfile
import zlib

MAX_BYTES = 8 * 1024 * 1024
PARA_TEXT = 67
CHAR_CONTROLS = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


class HwpError(Exception):
    pass


def _records(data: bytes):
    i, n = 0, len(data)
    while i + 4 <= n:
        (h,) = struct.unpack_from("<I", data, i)
        i += 4
        tag, size = h & 0x3FF, (h >> 20) & 0xFFF
        if size == 0xFFF:
            if i + 4 > n:
                return
            (size,) = struct.unpack_from("<I", data, i)
            i += 4
        yield tag, data[i:i + size]
        i += size


def _para_text(raw: bytes) -> str:
    out, i, n = [], 0, len(raw) - len(raw) % 2
    while i < n:
        (c,) = struct.unpack_from("<H", raw, i)
        if c < 32:
            if c in CHAR_CONTROLS:
                if c == 10:
                    out.append("\n")
                i += 2
            else:
                if c == 9:
                    out.append("\t")
                i += 16
            continue
        out.append(chr(c))
        i += 2
    return "".join(out)


def section_text(stream: bytes, compressed: bool) -> str:
    if compressed:
        try:
            stream = zlib.decompress(stream, -15)
        except zlib.error as e:
            raise HwpError("한글 파일 본문 압축을 풀지 못했어요") from e
    lines = [_para_text(body).strip() for tag, body in _records(stream) if tag == PARA_TEXT]
    return "\n".join(x for x in lines if x)


def _hwp5(data: bytes) -> str:
    import olefile
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except OSError as e:
        raise HwpError("한글(HWP) 파일을 열지 못했어요") from e
    try:
        if not ole.exists("FileHeader"):
            raise HwpError("한글(HWP) 파일 형식이 아니에요")
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0] if len(header) >= 40 else 0
        if flags & 0x2:
            raise HwpError("암호가 걸린 한글 파일이라 읽을 수 없어요")
        if flags & 0x4:
            raise HwpError("배포용(보기 전용) 한글 파일이라 본문을 읽을 수 없어요")
        sections = sorted((e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
                          key=lambda e: int(re.sub(r"\D", "", e[1]) or 0))
        if not sections:
            raise HwpError("한글 파일에서 본문을 찾지 못했어요")
        return "\n".join(section_text(ole.openstream(list(e)).read(), bool(flags & 0x1)) for e in sections)
    finally:
        ole.close()


def _hwpx(data: bytes) -> str:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise HwpError("한글(HWPX) 파일을 열지 못했어요") from e
    names = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                   key=lambda n: int(re.sub(r"\D", "", n.rsplit("/", 1)[-1]) or 0))
    if not names:
        raise HwpError("한글(HWPX) 파일에서 본문을 찾지 못했어요")
    out = []
    for name in names:
        xml = z.read(name).decode("utf-8", "ignore")
        for para in re.findall(r"<hp:p\b.*?</hp:p>", xml, flags=re.S):
            t = "".join(re.findall(r"<hp:t\b[^>]*>(.*?)</hp:t>", para, flags=re.S))
            t = re.sub(r"<[^>]+>", "", t)
            t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&").strip()
            if t:
                out.append(t)
    return "\n".join(out)


def hwp_to_text(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise HwpError("한글 파일이 8MB를 넘어요")
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        text = _hwp5(data)
    elif data.startswith(b"PK"):
        text = _hwpx(data)
    else:
        raise HwpError("한글(HWP·HWPX) 파일이 아니에요")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 80:
        raise HwpError("한글 파일에서 읽은 글자가 너무 적어요")
    return text
