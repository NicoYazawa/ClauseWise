"""Contract management API (design doc 3.1.1): list / detail / version / clause / diff / upload / re-parse / archive / download."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from app.core.exceptions import AppError
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.access import contract_scope, get_contract_for_user
from app.core.request_ctx import client_info as _client_info
from app.core.security import get_current_user, require_perm
from app.db.session import get_db
from app.models.contract import Contract, ContractClause, ContractVersion
from app.models.user import User
from app.services import contract_service

router = APIRouter(prefix="/contracts", tags=["合同管理"])


def _version_out(v: ContractVersion) -> dict:
    return {
        "id": v.id,
        "contractId": v.contract_id,
        "versionNo": v.version_no,
        "parentId": v.parent_id,
        "fileName": v.file_name,
        "fileSizeKb": v.file_size_kb,
        "parseStatus": v.parse_status,
        "parseChannel": v.parse_channel,
        "createdAt": v.created_at.strftime("%Y-%m-%dT%H:%M:%S") if v.created_at else None,
    }


def _clause_out(c: ContractClause) -> dict:
    return {
        "id": c.id,
        "versionId": c.version_id,
        "contractId": c.contract_id,
        "clauseNo": c.clause_no,
        "clauseType": c.clause_type,
        "content": c.content,
        "pageNo": c.page_no,
    }


@router.get("")
def fetch_contracts(
    keyword: str | None = None,
    contractType: str | None = None,
    status: str | None = None,
    db: Annotated[Session, Depends(get_db)] = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    q = db.query(Contract).filter(contract_scope(user))
    if keyword and keyword.strip():
        kw = keyword.strip()
        q = q.filter(
            Contract.title.contains(kw)
            | Contract.contract_no.contains(kw)
            | Contract.counterparty_name.contains(kw)
        )
    if contractType:
        q = q.filter(Contract.contract_type == contractType)
    if status:
        q = q.filter(Contract.status == status)
    items = q.order_by(Contract.id.desc()).all()
    return [contract_service.build_contract_out(c) for c in items]


@router.get("/{contract_id}")
def fetch_contract(
    contract_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    c = get_contract_for_user(db, user, contract_id)
    return contract_service.build_contract_out(c)


@router.get("/{contract_id}/versions")
def fetch_versions(
    contract_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    get_contract_for_user(db, user, contract_id)
    versions = (
        db.query(ContractVersion)
        .filter(ContractVersion.contract_id == contract_id)
        .order_by(ContractVersion.version_no.desc())
        .all()
    )
    return [_version_out(v) for v in versions]


@router.get("/{contract_id}/versions/{version_id}/clauses")
def fetch_clauses(
    contract_id: int,
    version_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    get_contract_for_user(db, user, contract_id)
    clauses = (
        db.query(ContractClause)
        .filter(ContractClause.contract_id == contract_id, ContractClause.version_id == version_id)
        .order_by(ContractClause.id)
        .all()
    )
    return [_clause_out(c) for c in clauses]


@router.get("/versions/{version_id}/clauses")
def fetch_clauses_by_version(
    version_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Fetch clauses directly by version id (the frontend often only holds a versionId)."""
    version = db.get(ContractVersion, version_id)
    if version is None:
        raise AppError("CONTRACT_VERSION_NOT_FOUND", 404, "版本不存在")
    get_contract_for_user(db, user, version.contract_id)
    clauses = (
        db.query(ContractClause)
        .filter(ContractClause.version_id == version_id)
        .order_by(ContractClause.id)
        .all()
    )
    return [_clause_out(c) for c in clauses]


@router.get("/{contract_id}/versions/diff")
def fetch_diff(
    contract_id: int,
    base: int,
    target: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    get_contract_for_user(db, user, contract_id)
    if base == target:
        raise AppError("CONTRACT_SAME_VERSION", 400, "基准版本与目标版本不能相同")
    base_ver = (
        db.query(ContractVersion)
        .filter(ContractVersion.contract_id == contract_id, ContractVersion.version_no == base)
        .first()
    )
    target_ver = (
        db.query(ContractVersion)
        .filter(ContractVersion.contract_id == contract_id, ContractVersion.version_no == target)
        .first()
    )
    if not base_ver or not target_ver:
        raise AppError("CONTRACT_VERSION_NOT_FOUND", 404, "版本不存在")
    if base_ver.parse_status != "parsed" or target_ver.parse_status != "parsed":
        raise AppError("CONTRACT_VERSIONS_NOT_PARSED", 400, "两个版本均需完成解析后才能比对")
    return contract_service.build_version_diff(db, base_ver, target_ver)


@router.post("/upload")
async def upload_contract(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    contractType: str = Form(...),
    counterpartyName: str = Form(""),
    amount: int = Form(0),
    db: Annotated[Session, Depends(get_db)] = None,
    owner: Annotated[User, Depends(require_perm("contract:upload"))] = None,
):
    ip, ua = _client_info(request)
    data = await file.read()
    contract = contract_service.create_contract(
        db,
        owner=owner,
        file_name=file.filename or "unnamed",
        file_bytes=data,
        title=title,
        contract_type=contractType,
        counterparty_name=counterpartyName,
        amount=amount,
    )
    write_audit(db, user_id=owner.id, username=owner.username, action="contract.upload",
                resource_type="合同", resource_id=contract.contract_no, ip=ip, ua=ua,
                extra=f"文件大小 {max(1, len(data)//1024)}KB，SHA-256 指纹 {contract.file_sha256[:16]}…")
    return contract_service.build_contract_out(contract)


@router.post("/{contract_id}/versions")
async def upload_contract_version(
    contract_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Annotated[Session, Depends(get_db)] = None,
    operator: Annotated[User, Depends(require_perm("contract:upload"))] = None,
):
    ip, ua = _client_info(request)
    contract = get_contract_for_user(db, operator, contract_id)
    data = await file.read()
    contract = contract_service.upload_new_version(db, contract, file.filename or "unnamed", data)
    write_audit(db, user_id=operator.id, username=operator.username, action="contract.upload",
                resource_type="合同", resource_id=contract.contract_no, ip=ip, ua=ua,
                extra=f"上传修订版 v{contract.current_version}（{max(1, len(data)//1024)}KB）")
    return contract_service.build_contract_out(contract)


@router.post("/{contract_id}/retry-parse")
def retry_parse(
    contract_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("contract:upload"))],
):
    ip, ua = _client_info(request)
    contract = get_contract_for_user(db, operator, contract_id)
    contract = contract_service.retry_parse(db, contract)
    write_audit(db, user_id=operator.id, username=operator.username, action="contract.retryParse",
                resource_type="合同", resource_id=contract.contract_no, ip=ip, ua=ua,
                extra="解析失败后重新发起解析")
    return contract_service.build_contract_out(contract)


@router.post("/{contract_id}/archive")
def archive_contract(
    contract_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("contract:delete"))],
):
    ip, ua = _client_info(request)
    contract = get_contract_for_user(db, operator, contract_id)
    contract = contract_service.archive_contract(db, contract)
    write_audit(db, user_id=operator.id, username=operator.username, action="contract.archive",
                resource_type="合同", resource_id=contract.contract_no, ip=ip, ua=ua,
                extra="归档（软删除语义，文件按策略保留）")
    return contract_service.build_contract_out(contract)


@router.get("/{contract_id}/download")
def download_contract(
    contract_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    operator: Annotated[User, Depends(require_perm("contract:download"))],
):
    ip, ua = _client_info(request)
    contract = get_contract_for_user(db, operator, contract_id)
    path, fname = contract_service.download_file_path(db, contract)
    write_audit(db, user_id=operator.id, username=operator.username, action="contract.download",
                resource_type="合同", resource_id=contract.contract_no, ip=ip, ua=ua,
                extra=f"版本 v{contract.current_version}（RBAC 鉴权与路径校验通过）")
    return FileResponse(path, filename=fname)
