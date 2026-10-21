"""Dual-channel parse service (design doc 3.1.2):

- DOCX -> python-docx text channel
- PDF -> PyMuPDF per-page extraction; a page with < 50 chars is treated as scanned, rendered to PNG and sent to the vision channel (DeepSeek Vision)
- Images (JPG/PNG) -> vision channel directly
- After completion: clause splitting + persist + vectorize into ES
"""
import base64
from datetime import datetime
from pathlib import Path

import pymupdf as fitz  # PyMuPDF (official package name since 2.x; the old 'fitz' alias is deprecated)
from docx import Document as DocxDocument
from loguru import logger
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.ai import llm_client
from app.core.config import settings
from app.models.contract import Contract, ContractClause, ContractVersion
from app.services.contract_service import index_clauses_to_es
from app.utils.clause_split import split_clauses

SCAN_PAGE_THRESHOLD = 50  # pages with fewer chars than this are treated as scanned pages


class ParseError(Exception):
    pass


def _docx_table_text(table) -> str:
    """Table -> plain text lines (" | " joined cells), so tabular clauses enter review."""
    lines: list[str] = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _parse_docx(path: Path) -> tuple[list[str], str]:
    """Extract paragraphs AND tables in document order (tables often hold key commercial terms)."""
    doc = DocxDocument(str(path))
    pages: list[str] = []
    buf: list[str] = []
    count = 0

    def _push(text: str) -> None:
        nonlocal count
        buf.append(text)
        count += len(text)
        if count >= 800:  # approximate pagination
            pages.append("\n".join(buf))
            buf.clear()
            count = 0

    for block in doc.iter_inner_content():
        if hasattr(block, "rows"):  # docx.table.Table
            text = _docx_table_text(block)
            if text:
                _push(text)
            continue
        text = block.text.strip()
        if text:
            _push(text)
    if buf:
        pages.append("\n".join(buf))
    return pages, "text"


def _parse_pdf(path: Path) -> tuple[list[str], list[int], str]:
    """Return (page texts, scanned-page number list, channel)."""
    doc = fitz.open(str(path))
    pages: list[str] = []
    scan_pages: list[int] = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if len(text) < SCAN_PAGE_THRESHOLD:
            scan_pages.append(i)
            pages.append("")
        else:
            pages.append(text)
    doc.close()
    channel = "mixed" if scan_pages and len(scan_pages) < len(pages) else ("vision" if scan_pages else "text")
    return pages, scan_pages, channel


def _render_pdf_page_png(path: Path, page_no: int, dpi: int = 130) -> bytes:
    doc = fitz.open(str(path))
    page = doc[page_no - 1]
    pix = page.get_pixmap(dpi=dpi)
    data = pix.tobytes("png")
    doc.close()
    return data


def _vision_page(path: Path, page_no: int, *, is_image: bool = False) -> list[dict]:
    """Vision channel: DeepSeek Vision OCR + layout understanding; returns a clause list."""
    if is_image:
        img_bytes = path.read_bytes()
    else:
        img_bytes = _render_pdf_page_png(path, page_no)
    b64 = base64.b64encode(img_bytes).decode("ascii")
    result, _tokens = llm_client.vision_extract_clauses(b64)
    clauses = result.get("clauses") or []
    for cl in clauses:
        cl.setdefault("page_no", page_no)
    return clauses


def parse_version(db: Session, version_id: int) -> None:
    """Parse entrypoint (shared by Celery / thread pool): set parsed on success, failed on error."""
    version = db.get(ContractVersion, version_id)
    if not version:
        raise ParseError(f"version {version_id} 不存在")
    # Atomic claim (pending/failed -> parsing): within the dispatch-degrade window the same version may exist in both the Worker queue and thread pool; only one side may execute
    claimed = db.execute(
        update(ContractVersion)
        .where(ContractVersion.id == version_id, ContractVersion.parse_status.in_(("pending", "failed")))  # type: ignore[arg-type]
        .values(parse_status="parsing")
        .execution_options(synchronize_session=False)
    ).rowcount
    if not claimed:
        logger.warning(f"parse version {version_id} already claimed (status={version.parse_status}), skip")
        return
    version.parse_status = "parsing"
    contract = db.get(Contract, version.contract_id)
    db.commit()

    try:
        if not version.file_path:
            raise ParseError("版本文件路径缺失")
        path = settings.storage_path / version.file_path
        if not path.exists():
            raise ParseError(f"原始文件不存在：{version.file_path}")

        ext = path.suffix.lower()
        structured: list[dict] = []
        channel = "text"

        if ext == ".docx":
            pages, channel = _parse_docx(path)
            structured = split_clauses(pages)
        elif ext == ".pdf":
            pages, scan_pages, channel = _parse_pdf(path)
            # Keep placeholders for blank (scanned) pages to preserve the original page mapping; OCR clauses and text clauses are merged and ordered by original page number
            structured = split_clauses(pages)
            for pno in scan_pages:
                structured.extend(_vision_page(path, pno))
            structured.sort(key=lambda cl: int(cl.get("page_no", 1) or 1))
        elif ext in (".jpg", ".jpeg", ".png"):
            channel = "vision"
            structured = _vision_page(path, 1, is_image=True)
        else:
            raise ParseError(f"不支持的文件格式：{ext}")

        if not structured:
            raise ParseError("未解析出任何有效条款（可能为空白或低质量扫描件）")

        # Clear old clauses (retry scenario) and persist new ones
        db.query(ContractClause).filter(ContractClause.version_id == version.id).delete()
        for cl in structured:
            db.add(
                ContractClause(
                    version_id=version.id,
                    contract_id=version.contract_id,
                    clause_no=str(cl.get("clause_no", "未编号"))[:64],
                    clause_type=str(cl.get("clause_type", "其他约定"))[:32],
                    content=str(cl.get("content", "")),
                    page_no=int(cl.get("page_no", 1) or 1),
                )
            )
        version.parse_status = "parsed"
        version.parse_channel = channel
        version.parse_error = None
        # Completing parse of an old version must not overwrite the new version's status (concurrent new-version upload scenario)
        if contract and version.version_no == contract.current_version:
            contract.status = "parsed"
            contract.updated_at = datetime.now()
        db.commit()

        index_clauses_to_es(db, version)
        logger.info(f"version {version_id} parsed ({channel}, {len(structured)} clauses)")
        try:
            from app.core.metrics import PARSE_TASKS

            PARSE_TASKS.labels(status="parsed").inc()
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        db.rollback()
        version = db.get(ContractVersion, version_id)
        version.parse_status = "failed"
        version.parse_error = str(e)[:500]
        # A parse failure on an old version must likewise not overwrite the new version's status
        if contract and version.version_no == contract.current_version:
            contract.status = "parse_failed"
            contract.updated_at = datetime.now()
        db.commit()
        logger.error(f"version {version_id} parse failed: {e}")
        try:
            from app.core.metrics import PARSE_TASKS

            PARSE_TASKS.labels(status="failed").inc()
        except Exception:  # noqa: BLE001
            pass
        # Alert outbound (parse failure usually means the upload path is down; intervene immediately)
        try:
            from app.core.alerting import notify_task_failure

            notify_task_failure(
                "parse",
                version_id,
                f"{contract.title if contract else '-'} v{version.version_no if version else '-'}",
                e,
            )
        except Exception as alert_err:  # noqa: BLE001
            logger.warning(f"parse alert failed: {alert_err}")
        raise
