"""사업보고서 원문(DART XML/HTML, PDF, TXT)에서 'II. 사업의 내용'을 잘라 문단 단위 문서로 만든다.

파일명은 사업연도로 시작해야 한다: raw/2016.xml, raw/2017.pdf, ...
"""
import html, os, re

SECTION_START = re.compile(r"I\s*I\s*\.\s*사\s*업\s*의\s*내\s*용")
SECTION_END = re.compile(r"I\s*I\s*I\s*\.\s*재\s*무\s*에\s*관\s*한\s*사\s*항")
BLOCK_TAGS = re.compile(r"</?(P|BR|TR|TITLE|SECTION-\d|LIBRARY|DIV|LI|H\d)\b[^>]*>", re.I)


def _decode(raw):
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "ignore")


def load_text(path, keep_tables=False):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    with open(path, "rb") as f:
        text = _decode(f.read())
    if ext in (".xml", ".html", ".htm"):
        if not keep_tables:   # 표는 대부분 숫자 — 문장 텍스트만 남긴다
            text = re.sub(r"<TABLE\b.*?</TABLE>", "\n", text, flags=re.I | re.S)
        text = BLOCK_TAGS.sub("\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    return text


def business_section(text):
    """목차에도 같은 제목이 나오므로, 시작~끝 구간 중 가장 긴 것을 본문으로 본다."""
    best = ""
    for m in SECTION_START.finditer(text):
        e = SECTION_END.search(text, m.end())
        seg = text[m.end(): e.start() if e else len(text)]
        if len(seg) > len(best):
            best = seg
    return best or text


def paragraphs(text, min_chars=40, max_chars=500):
    paras, buf = [], []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            if buf:
                paras.append(" ".join(buf)); buf = []
            continue
        buf.append(line)
    if buf:
        paras.append(" ".join(buf))
    out = []
    for p in paras:
        hangul = len(re.findall(r"[가-힣]", p))
        if len(p) < min_chars or hangul < 0.3 * len(p):   # 제목·숫자 행 제거
            continue
        if len(p) <= max_chars:
            out.append(p); continue
        chunk = ""                                   # 긴 문단은 문장 경계로 쪼갠다
        for s in re.split(r"(?<=[다요음함])\.\s+", p):
            if chunk and len(chunk) + len(s) > max_chars:
                out.append(chunk); chunk = ""
            chunk = f"{chunk} {s}".strip()
        if len(chunk) >= min_chars:
            out.append(chunk)
    return out


def load_corpus(raw_dir, keep_tables=False, whole=False):
    """-> list of (year, paragraph)."""
    docs = []
    for name in sorted(os.listdir(raw_dir)):
        m = re.match(r"(\d{4})", name)
        if not m or os.path.splitext(name)[1].lower() not in (".xml", ".html", ".htm", ".pdf", ".txt"):
            continue
        text = load_text(os.path.join(raw_dir, name), keep_tables)
        if not whole:
            text = business_section(text)
        docs += [(int(m.group(1)), p) for p in paragraphs(text)]
    return docs
