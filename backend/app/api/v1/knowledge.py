"""Knowledge-base endpoints (design doc 3.4): law CRUD / expire / Excel import, template management."""
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from app.core.exceptions import AppError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.request_ctx import client_info as _client_info
from app.core.security import get_current_user, require_perm
from app.db.session import get_db
from app.models.knowledge import ContractTemplate, LawRegulation
from app.models.user import User
from app.schemas.knowledge import SaveLawRequest, SaveTemplateRequest
from app.services import knowledge_service
from app.tasks.dispatcher import submit_index_law_task

router = APIRouter(tags=["Knowledge Base"])

VALID_LEVELS = {"required", "recommended", "optional"}


def _law_out(law: LawRegulation) -> dict:
    return {
        "id": law.id,
        "docType": law.doc_type,
        "title": law.title,
        "content": law.content,
        "sourceRef": law.source_ref,
        "effectiveDate": law.effective_date.isoformat() if law.effective_date else None,
        "expiryDate": law.expiry_date.isoformat() if law.expiry_date else None,
        "status": law.status,
        "vectorized": bool(law.vectorized),
        "hitCount": law.hit_count,
    }


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


@router.get("/laws")
def fetch_laws(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]):
    laws = db.query(LawRegulation).order_by(LawRegulation.hit_count.desc(), LawRegulation.id).all()
    return [_law_out(law) for law in laws]


@router.post("/laws")
def save_law(
    payload: SaveLawRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perm("knowledge:manage"))],
):
    if not (payload.title or "").strip() or not (payload.content or "").strip():
        raise AppError("LAW_FIELDS_REQUIRED", 400, "标题与内容不能为空")
    if payload.id:
        law = db.get(LawRegulation, payload.id)
        if not law:
            raise AppError("LAW_NOT_FOUND", 404, "法条不存在")
        law.doc_type = payload.doc_type if payload.doc_type in ("law", "case") else law.doc_type
        law.title = payload.title
        law.content = payload.content
        law.source_ref = payload.source_ref
        law.effective_date = _parse_date(payload.effective_date)
        law.expiry_date = _parse_date(payload.expiry_date)
        law.status = payload.status if payload.status in ("active", "expired") else law.status
        law.vectorized = False  # re-vectorize on next task
        db.commit()
        db.refresh(law)
        knowledge_service.delete_law_from_es(law)
        submit_index_law_task(law.id)
        return _law_out(law)
    law = LawRegulation(
        doc_type=payload.doc_type if payload.doc_type in ("law", "case") else "law",
        title=payload.title,
        content=payload.content,
        source_ref=payload.source_ref,
        effective_date=_parse_date(payload.effective_date),
        expiry_date=_parse_date(payload.expiry_date),
        status=payload.status if payload.status in ("active", "expired") else "active",
        hit_count=0,
        vectorized=False,
        created_at=datetime.now(),
    )
    db.add(law)
    db.commit()
    db.refresh(law)
    submit_index_law_task(law.id)
    return _law_out(law)


@router.post("/laws/{law_id}/expire")
def mark_expired(
    law_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perm("knowledge:manage"))],
):
    law = db.get(LawRegulation, law_id)
    if not law:
        raise AppError("LAW_NOT_FOUND", 404, "法条不存在")
    law.status = "expired"
    law.expiry_date = date.today()
    db.commit()
    db.refresh(law)
    knowledge_service.delete_law_from_es(law)  # also remove from ES (search filters by status as a second guard)
    return _law_out(law)


@router.post("/laws/import")
async def import_laws(
    request: Request,
    file: UploadFile = File(...),
    db: Annotated[Session, Depends(get_db)] = None,
    operator: Annotated[User, Depends(require_perm("knowledge:manage"))] = None,
):
    """Excel bulk import (3.4.1): structured parse into DB + batch vectorization (real call)."""
    ip, ua = _client_info(request)
    if not (file.filename or "").lower().endswith((".xlsx", ".xls")):
        raise AppError("LAW_IMPORT_FORMAT", 400, "请上传 Excel 文件（.xlsx / .xls），表头需包含 docType/title/content 等列")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise AppError("LAW_IMPORT_TOO_LARGE", 400, "文件过大（>10MB）")

    tmp = Path(tempfile.gettempdir()) / f"law_import_{datetime.now().strftime('%H%M%S')}.xlsx"
    tmp.write_bytes(data)
    try:
        rows = knowledge_service.read_law_excel(str(tmp))
    finally:
        tmp.unlink(missing_ok=True)
    laws = knowledge_service.parse_law_rows(rows)
    if not laws:
        raise AppError("LAW_IMPORT_NO_ROWS", 400, "未解析到有效数据行（需 title 与 content 非空）")

    imported = 0
    for law in laws:
        law.source_ref = law.source_ref or f"Excel 批量导入（{file.filename}）"
        db.add(law)
    db.commit()
    imported = len(laws)

    # vectorization is async: return the count of submitted tasks (real results are written back via the vectorized flag)
    submitted = 0
    for law in laws:
        db.refresh(law)
        submit_index_law_task(law.id)
        submitted += 1

    write_audit(db, user_id=operator.id, username=operator.username, action="knowledge.import",
                resource_type="法律法规", resource_id=file.filename or "-", ip=ip, ua=ua,
                extra=f"Excel 批量导入 {imported} 条，已提交向量化任务 {submitted} 条")
    return {"imported": imported, "vectorized": submitted}


@router.get("/templates")
def fetch_templates(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(get_current_user)]):
    items = db.query(ContractTemplate).order_by(ContractTemplate.id).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "contractType": t.contract_type,
            "clauseLevel": t.clause_level,
            "content": t.content,
            "version": t.version,
        }
        for t in items
    ]


@router.post("/templates")
def save_template(
    payload: SaveTemplateRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perm("knowledge:manage"))],
):
    if not (payload.name or "").strip() or not (payload.content or "").strip():
        raise AppError("TEMPLATE_FIELDS_REQUIRED", 400, "条款名称与内容不能为空")
    if payload.clause_level not in VALID_LEVELS:
        raise AppError("TEMPLATE_INVALID_LEVEL", 400, "非法条款级别")
    if payload.id:
        t = db.get(ContractTemplate, payload.id)
        if not t:
            raise AppError("TEMPLATE_NOT_FOUND", 404, "模板条款不存在")
        knowledge_service.delete_template_from_es(t)
        t.name = payload.name
        t.contract_type = payload.contract_type
        t.clause_level = payload.clause_level
        t.content = payload.content
        t.version += 1  # immutable change: publish a new version
        t.updated_at = datetime.now()
        db.commit()
        db.refresh(t)
        knowledge_service.index_template(db, t)
        return {"id": t.id, "name": t.name, "contractType": t.contract_type,
                "clauseLevel": t.clause_level, "content": t.content, "version": t.version}
    dup = (
        db.query(ContractTemplate)
        .filter(ContractTemplate.contract_type == payload.contract_type, ContractTemplate.name == payload.name)
        .first()
    )
    if dup:
        raise AppError("TEMPLATE_DUP_NAME", 400, "该合同类型下已存在同名条款，请更换名称")
    t = ContractTemplate(
        name=payload.name,
        contract_type=payload.contract_type,
        clause_level=payload.clause_level,
        content=payload.content,
        version=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    knowledge_service.index_template(db, t)
    return {"id": t.id, "name": t.name, "contractType": t.contract_type,
            "clauseLevel": t.clause_level, "content": t.content, "version": t.version}


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perm("knowledge:manage"))],
):
    t = db.get(ContractTemplate, template_id)
    if not t:
        raise AppError("TEMPLATE_NOT_FOUND", 404, "模板条款不存在")
    knowledge_service.delete_template_from_es(t)
    db.delete(t)
    db.commit()
    return {"message": "已删除"}
