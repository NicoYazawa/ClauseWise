"""Clause structural splitting (design doc 3.1.1 extract_clauses):

- Split into a clause tree by "第X条 / 第X章 / N.N" structure (chapter/clause two levels merged into clause list);
- Classify clause type by keywords (breach liability / payment / confidentiality / dispute resolution, etc.);
- Record page number and full-text char offsets for highlight playback.
"""
import re

# Clause-type keyword mapping (order = priority)
CLAUSE_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("争议解决", ["争议", "管辖", "仲裁", "诉讼"]),
    ("违约责任", ["违约", "赔偿", "违约金"]),
    ("保密", ["保密", "商业秘密"]),
    ("知识产权", ["知识产权", "著作权", "专利", "商标"]),
    ("付款", ["付款", "支付", "价款", "费用", "报酬", "发票", "结算"]),
    ("交付与验收", ["交付", "验收", "交货", "送达"]),
    ("解除与终止", ["解除", "终止", "解除合同"]),
    ("不可抗力", ["不可抗力"]),
    ("保险", ["保险"]),
    ("通知与送达", ["通知", "送达"]),
    ("质量与质保", ["质量", "质保", "保修", "标准"]),
    ("期限", ["期限", "有效期", "合同期", "生效"]),
]

# Match clause-number headings such as "第一条" / "第十二条" / "第1条" / "5.1.2"
_CLAUSE_NO_RE = re.compile(r"(?=第[零一二三四五六七八九十百千\d]+条|\n\s*\d+(\.\d+)*\s*[、．.]?\s*\S)")


def classify_clause(text: str) -> str:
    """Classify clause type: prefer matching the clause title (before the first "：") — title semantics are most reliable;
    fall back to the first 120 chars of the body only if the title misses, to avoid mislabeling from incidental
    keywords in the body (e.g. a warranty clause mislabeled "交付与验收" because of "自验收合格之日起算",
    or an effective-date clause mislabeled "付款" because of "质保金支付完毕")."""
    head = text.split("：", 1)[0]
    if head != text:
        for ctype, keywords in CLAUSE_TYPE_RULES:
            for kw in keywords:
                if kw in head:
                    return ctype
    for ctype, keywords in CLAUSE_TYPE_RULES:
        for kw in keywords:
            if kw in text[:120]:
                return ctype
    return "其他约定"


def _split_pages(pages: list[str]) -> list[tuple[int, str, int, int]]:
    """[(page_no, clause_text, char_start, char_end)]: simple concat handling for clauses spanning pages."""
    full_text = "\n".join(pages)
    # Locate all clause-number start positions (with page mapping)
    starts: list[tuple[int, int]] = []  # (char_offset, page_no)
    page_offsets = []
    off = 0
    for idx, page in enumerate(pages, start=1):
        page_offsets.append((off, off + len(page), idx))
        off += len(page) + 1  # the joined \n

    for m in re.finditer(r"第[零一二三四五六七八九十百千\d]+条", full_text):
        starts.append((m.start(), _page_of(page_offsets, m.start())))

    clauses: list[tuple[int, str, int, int]] = []
    if not starts:
        text = full_text.strip()
        if text:
            return [(1, text, 0, len(full_text))]
        return []

    # Preface before the first clause number is merged into the first clause
    first_start = starts[0][0]
    preamble = full_text[:first_start].strip()
    for i, (s, page) in enumerate(starts):
        e = starts[i + 1][0] if i + 1 < len(starts) else len(full_text)
        text = full_text[s:e].strip()
        if i == 0 and preamble:
            text = (preamble + "\n" + text)[:2000]
        if len(text) >= 8:  # drop noise
            clauses.append((page, text, s, e))
    return clauses


def _page_of(page_offsets: list[tuple[int, int, int]], char_offset: int) -> int:
    for s, e, no in page_offsets:
        if s <= char_offset < e:
            return no
    return page_offsets[-1][2] if page_offsets else 1


def extract_clause_no(clause_text: str) -> str:
    m = re.match(r"(第[零一二三四五六七八九十百千\d]+条|\d+(\.\d+)*)", clause_text.strip())
    if m:
        no = m.group(1)
        # Normalize numeric clause numbers (keep the 5.1.2 form)
        return no[:32]
    return "未编号"


def split_clauses(pages: list[str]) -> list[dict]:
    """Page text -> clause list [{clause_no, clause_type, content, page_no, char_start, char_end}]"""
    results = []
    for page_no, text, cs, ce in _split_pages(pages):
        # If a clause on a single page is too long (>1200 chars), split by sentence end to avoid exceeding LLM context
        if len(text) > 1200:
            segments = re.split(r"(?<=[。；])", text)
            buf, buf_len = "", 0
            for seg in segments:
                if buf_len + len(seg) > 1200 and buf:
                    results.append(_mk_clause(buf, page_no, cs, ce))
                    buf, buf_len = seg, len(seg)
                else:
                    buf += seg
                    buf_len += len(seg)
            if buf.strip():
                results.append(_mk_clause(buf, page_no, cs, ce))
        else:
            results.append(_mk_clause(text, page_no, cs, ce))
    return results


def _mk_clause(text: str, page_no: int, cs: int, ce: int) -> dict:
    text = text.strip()
    return {
        "clause_no": extract_clause_no(text),
        "clause_type": classify_clause(text[:120]),
        "content": text,
        "page_no": page_no,
        "char_start": cs,
        "char_end": ce,
    }
