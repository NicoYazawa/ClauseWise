"""Contract management service (design doc 3.1): idempotent upload, version chain, archive, download, clause diff."""
import io
from datetime import datetime

from fastapi import HTTPException
from app.core.exceptions import AppError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.contract import Contract, ContractClause, ContractVersion
from app.models.knowledge import Notification
from app.models.user import User
from app.services import knowledge_service
from app.tasks.dispatcher import submit_parse_task
from app.utils.crypto import decrypt_text, encrypt_text
from app.utils.diff import char_diff_summary, text_similarity
from app.utils.files import resolve_storage_path, save_origin_file
from app.utils.mask import mask_id_no, mask_phone

CONTRACT_TYPES = {"purchase", "sales", "labor", "lease", "nda", "other"}

# legal state transitions (3.3.3 state machine)
STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"parsing"},
    "parsing": {"parsed", "parse_failed"},
    "parse_failed": {"parsing"},
    "parsed": {"under_review"},
    "under_review": {"review_passed", "review_blocked", "under_review"},
    "review_blocked": {"under_review"},
    "review_passed": {"in_approval"},
    "in_approval": {"in_approval", "approved", "rejected"},
    "approved": {"archived"},
    "rejected": {"archived"},
    "archived": set(),
}


def transition_status(contract: Contract, to_status: str) -> None:
    cur = contract.status
    if to_status == cur:
        return
    allowed = STATUS_TRANSITIONS.get(cur, set())
    # allow re-entry into the same state (e.g. parsing -> parsing)
    if to_status not in allowed:
        raise AppError("CONTRACT_STATUS_TRANSITION", 400, f"合同状态不允许从 {cur} 变更为 {to_status}")
    contract.status = to_status
    contract.updated_at = datetime.now()


def gen_contract_no(db: Session) -> str:
    year = datetime.now().year
    prefix = f"HT-{year}-"
    last = (
        db.query(Contract)
        .filter(Contract.contract_no.like(prefix + "%"))
        .order_by(Contract.id.desc())
        .first()
    )
    next_seq = 1
    if last:
        try:
            next_seq = int(last.contract_no.rsplit("-", 1)[1]) + 1
        except ValueError:
            next_seq = 1
    return prefix + f"{next_seq:04d}"


def build_contract_out(c: Contract) -> dict:
    """Assemble the frontend Contract struct (counterparty fields masked)."""
    return {
        "id": c.id,
        "contractNo": c.contract_no,
        "title": c.title,
        "contractType": c.contract_type,
        "ownerId": c.owner_id,
        "ownerName": c.owner.real_name if c.owner else "",
        "status": c.status,
        "currentVersion": c.current_version,
        "counterparty": {
            "name": c.counterparty_name or "",
            "idNo": mask_id_no(decrypt_text(c.counterparty_id_no_enc)),
            "phone": mask_phone(decrypt_text(c.counterparty_phone_enc)),
        },
        "amount": c.amount,
        "createdAt": c.created_at.strftime("%Y-%m-%dT%H:%M:%S") if c.created_at else None,
        "updatedAt": c.updated_at.strftime("%Y-%m-%dT%H:%M:%S") if c.updated_at else None,
    }


def get_contract_or_404(db: Session, contract_id: int) -> Contract:
    c = db.get(Contract, contract_id)
    if not c:
        raise AppError("CONTRACT_NOT_FOUND", 404, "合同不存在")
    return c


def create_contract(
    db: Session,
    *,
    owner: User,
    file_name: str,
    file_bytes: bytes,
    title: str,
    contract_type: str,
    counterparty_name: str,
    amount: int,
) -> Contract:
    if contract_type not in CONTRACT_TYPES:
        raise AppError("CONTRACT_INVALID_TYPE", 400, f"非法合同类型：{contract_type}")
    from app.utils.files import sha256_bytes, validate_upload

    validate_upload(file_name, len(file_bytes))
    sha = sha256_bytes(file_bytes)
    # idempotent dedupe: same fingerprint returns the existing record (design doc 3.1.2)
    dup = db.query(Contract).filter(Contract.file_sha256 == sha, Contract.owner_id == owner.id).first()
    if dup:
        return dup

    now = datetime.now()
    contract = Contract(
        contract_no=gen_contract_no(db),
        title=title,
        contract_type=contract_type,
        owner_id=owner.id,
        status="parsing",
        current_version=1,
        file_sha256=sha,
        counterparty_name=counterparty_name,
        counterparty_id_no_enc=encrypt_text("91110100MA00X0Y0Z0"),
        counterparty_phone_enc=encrypt_text("13800000000"),
        amount=amount,
        created_at=now,
        updated_at=now,
    )
    db.add(contract)
    db.flush()

    rel_path, _ = save_origin_file(contract.id, 1, file_name, file_bytes)
    version = ContractVersion(
        contract_id=contract.id,
        version_no=1,
        parent_id=None,
        file_name=f"v1_{file_name}",
        file_path=rel_path,
        file_size_kb=max(1, len(file_bytes) // 1024),
        parse_status="pending",  # pending: set to parsing once the parse task atomically claims it
        created_at=now,
    )
    db.add(version)
    db.commit()
    db.refresh(contract)

    submit_parse_task(version.id)
    return contract


def mark_reports_needing_re_review(db: Session, contract_id: int, reason: str) -> None:
    """After contract content/version changes, existing reports are all flagged "needs re-review" and may no longer serve as approval basis."""
    from app.models.review import ReviewReport

    for report in db.query(ReviewReport).filter(ReviewReport.contract_id == contract_id).all():
        js = dict(report.report_json or {})
        summary = dict(js.get("summary") or {})
        summary["needsReReview"] = True
        summary["needsReReviewReason"] = reason
        js["summary"] = summary
        report.report_json = js


def _materialize_amended_docx(contract: Contract, new_no: int, clauses: list[ContractClause]) -> tuple[str, str, int]:
    """Materialize the amended clause set into the new version's DOCX so the download matches the clauses."""
    from docx import Document

    doc = Document()
    doc.add_heading(f"{contract.title}（第 {new_no} 版 · 修订稿）", level=1)
    for cl in clauses:
        doc.add_paragraph(cl.content)
    buf = io.BytesIO()
    doc.save(buf)
    data = buf.getvalue()
    file_name = f"v{new_no}_amended.docx"
    rel_path, _ = save_origin_file(contract.id, new_no, file_name, data)
    return rel_path, file_name, max(1, len(data) // 1024)


def amend_clause(db: Session, clause: ContractClause, new_content: str) -> ContractVersion:
    """Accept a suggestion to auto-amend: create a new version (old version stays immutable); the old report and approval eligibility become stale with the content change."""
    from app.utils.clause_split import classify_clause

    old_version = db.get(ContractVersion, clause.version_id)
    if not old_version:
        raise AppError("CONTRACT_VERSION_NOT_FOUND", 404, "条款所属版本不存在")
    contract = db.get(Contract, old_version.contract_id)
    if not contract:
        raise AppError("CONTRACT_NOT_FOUND", 404, "合同不存在")
    # Same terminal-state guard as upload_new_version: archived is the final state, and must not be pulled back by an amendment
    if contract.status == "archived":
        raise AppError("CONTRACT_ARCHIVED_NO_AMEND", 400, "已归档合同为终态，不能按建议修订（如需修订请新建合同）")
    # An amendment rewrites the contract body and invalidates the report; doing so mid-approval would leave a running
    # instance whose approvers can still green-light never-reviewed content, so it must be withdrawn first
    if contract.status == "in_approval":
        raise AppError("CONTRACT_IN_APPROVAL_NO_AMEND", 400, "合同正在审批中，请先撤回审批流程再按建议修订")
    latest = (
        db.query(ContractVersion)
        .filter(ContractVersion.contract_id == contract.id)
        .order_by(ContractVersion.version_no.desc())
        .first()
    )
    now = datetime.now()
    new_no = (latest.version_no if latest else old_version.version_no) + 1
    new_version = ContractVersion(
        contract_id=contract.id,
        version_no=new_no,
        parent_id=old_version.id,
        file_name="",
        file_path=None,
        file_size_kb=0,
        parse_status="parsed",  # Clauses are fully copied and revised from the old version, so no re-parsing is needed
        parse_channel="amended",
        created_at=now,
    )
    db.add(new_version)
    db.flush()
    offset = 0
    copied: list[ContractClause] = []
    old_clauses = (
        db.query(ContractClause)
        .filter(ContractClause.version_id == old_version.id)
        .order_by(ContractClause.id)
        .all()
    )
    for cl in old_clauses:
        content = new_content if cl.id == clause.id else cl.content
        new_cl = ContractClause(
            version_id=new_version.id,
            contract_id=contract.id,
            clause_no=cl.clause_no,
            clause_type=classify_clause(content) if cl.id == clause.id else cl.clause_type,
            content=content,
            page_no=cl.page_no,
            char_start=offset,
            char_end=offset + len(content),
        )
        offset += len(content) + 1
        db.add(new_cl)
        copied.append(new_cl)
    db.flush()
    rel_path, file_name, size_kb = _materialize_amended_docx(contract, new_no, copied)
    new_version.file_name = file_name
    new_version.file_path = rel_path
    new_version.file_size_kb = size_kb
    contract.current_version = new_no
    # Content changed: revert to a re-reviewable state; the previous approval eligibility is invalidated
    contract.status = "parsed"
    contract.updated_at = now
    mark_reports_needing_re_review(db, contract.id, "条款已按建议修订，原报告对应旧版本内容")
    db.commit()
    db.refresh(new_version)
    try:
        index_clauses_to_es(db, new_version)
    except Exception:  # noqa: BLE001  indexing failures must not block the amendment
        pass
    return new_version


def upload_new_version(db: Session, contract: Contract, file_name: str, file_bytes: bytes) -> Contract:
    if contract.status == "archived":
        raise AppError("CONTRACT_ARCHIVED_NO_VERSION", 400, "已归档合同为终态，不能上传新版本（如需修订请新建合同）")
    latest = (
        db.query(ContractVersion)
        .filter(ContractVersion.contract_id == contract.id)
        .order_by(ContractVersion.version_no.desc())
        .first()
    )
    if not latest:
        raise AppError("CONTRACT_NO_HISTORY_VERSION", 400, "该合同没有可用的历史版本")

    from app.utils.files import validate_upload

    validate_upload(file_name, len(file_bytes))

    now = datetime.now()
    new_no = latest.version_no + 1
    rel_path, _ = save_origin_file(contract.id, new_no, file_name, file_bytes)
    version = ContractVersion(
        contract_id=contract.id,
        version_no=new_no,
        parent_id=latest.id,
        file_name=f"v{new_no}_{file_name}",
        file_path=rel_path,
        file_size_kb=max(1, len(file_bytes) // 1024),
        parse_status="pending",  # pending: set to parsing once the parse task atomically claims it
        created_at=now,
    )
    db.add(version)
    contract.current_version = new_no
    # old versions are immutable; new version is parsing (parse_failed->parsing / parsed->parsing both allowed)
    contract.status = "parsing"
    contract.updated_at = now
    # A new version upload means content changed: old reports must no longer grant approval
    mark_reports_needing_re_review(db, contract.id, "已上传新版本，原报告对应旧版本内容")
    db.commit()
    db.refresh(contract)

    submit_parse_task(version.id)
    return contract


def retry_parse(db: Session, contract: Contract) -> Contract:
    ver = (
        db.query(ContractVersion)
        .filter(
            ContractVersion.contract_id == contract.id,
            ContractVersion.version_no == contract.current_version,
        )
        .first()
    )
    if not ver:
        raise AppError("CONTRACT_CURRENT_VERSION_MISSING", 400, "当前版本不存在")
    if contract.status not in ("parse_failed", "parsing"):
        raise AppError("CONTRACT_NO_REPARSE", 400, f"状态 {contract.status} 无需重新解析")
    ver.parse_status = "pending"  # pending: set to parsing once the parse task atomically claims it
    ver.parse_error = None
    contract.status = "parsing"
    contract.updated_at = datetime.now()
    db.commit()
    db.refresh(contract)
    submit_parse_task(ver.id)
    return contract


def archive_contract(db: Session, contract: Contract) -> Contract:
    if contract.status not in ("approved", "rejected"):
        raise AppError("CONTRACT_ARCHIVE_REQUIRES_FINAL", 400, "仅已通过或已否决的合同可归档")
    contract.status = "archived"
    contract.updated_at = datetime.now()
    db.commit()
    db.refresh(contract)
    return contract


def download_file_path(db: Session, contract: Contract) -> tuple[str, str]:
    """Return (absolute path, filename); when the original is missing, dynamically generate a clause-text txt as a fallback."""
    ver = (
        db.query(ContractVersion)
        .filter(
            ContractVersion.contract_id == contract.id,
            ContractVersion.version_no == contract.current_version,
        )
        .first()
    )
    fname = ver.file_name if ver else f"{contract.contract_no}.pdf"
    if ver and ver.file_path:
        path = resolve_storage_path(ver.file_path)
        if path.exists():
            return str(path), fname
    # fallback: export the full clause text
    clauses = db.query(ContractClause).filter(ContractClause.version_id == ver.id).all() if ver else []
    lines = [f"{contract.title}（{contract.contract_no}）条款全文", ""]
    for cl in clauses:
        lines.append(f"{cl.clause_no}（{cl.clause_type}）")
        lines.append(cl.content)
        lines.append("")
    fallback = contract_dir_file(contract.id, f"{contract.contract_no}_clauses.txt")
    fallback.write_text("\n".join(lines), encoding="utf-8")
    return str(fallback), f"{contract.contract_no}_clauses.txt"


def contract_dir_file(contract_id: int, name: str):
    d = settings.storage_path / "contracts" / str(contract_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def build_version_diff(
    db: Session,
    base_version: ContractVersion,
    target_version: ContractVersion,
    use_llm: bool = True,
) -> list[dict]:
    """Clause-level semantic diff (3.1.4): match -> pairwise summarize (when LLM similarity in [0.85,0.98] or text differs)."""
    base_clauses = db.query(ContractClause).filter(ContractClause.version_id == base_version.id).all()
    target_clauses = db.query(ContractClause).filter(ContractClause.version_id == target_version.id).all()

    base_map = {c.clause_no: c for c in base_clauses}
    target_map = {c.clause_no: c for c in target_clauses}

    matched: list[tuple[ContractClause, ContractClause]] = []
    added = [t for no, t in target_map.items() if no not in base_map]
    removed = [b for no, b in base_map.items() if no not in target_map]
    for no, b in base_map.items():
        if no in target_map:
            matched.append((b, target_map[no]))

    # try semantic matching for added/removed not matched by clause_no (similarity >= 0.55 treated as a modify pair)
    still_added: list[ContractClause] = []
    for a in added:
        best, best_sim = None, 0.0
        for r in removed:
            sim = text_similarity(a.content, r.content)
            if sim > best_sim:
                best, best_sim = r, sim
        if best is not None and best_sim >= 0.55:
            matched.append((best, a))
            removed.remove(best)
        else:
            still_added.append(a)
    added = still_added

    items: list[dict] = []
    from app.services import diff_llm_service

    for a in added:
        items.append(
            {
                "clauseNo": f"{a.clause_no}（{a.clause_type}）",
                "kind": "added",
                "oldText": "",
                "newText": a.content,
                "summary": "新增条款。",
            }
        )
    for r in removed:
        items.append(
            {
                "clauseNo": f"{r.clause_no}（{r.clause_type}）",
                "kind": "removed",
                "oldText": r.content,
                "newText": "",
                "summary": "删除条款，相关义务约定缺失，建议评估影响。",
            }
        )
    for b, t in matched:
        if b.content.strip() == t.content.strip():
            continue
        if use_llm:
            kind, summary = diff_llm_service.summarize_diff(b.content, t.content)
        else:
            kind, summary = "modified", char_diff_summary(b.content, t.content)
        items.append(
            {
                "clauseNo": f"{b.clause_no}（{b.clause_type}）",
                "kind": kind,
                "oldText": b.content,
                "newText": t.content,
                "summary": summary,
            }
        )
    return items


def push_notification(db: Session, *, ntype: str, title: str, content: str) -> None:
    db.add(Notification(type=ntype, title=title, content=content, created_at=datetime.now()))
    db.commit()


def index_clauses_to_es(db: Session, version: ContractVersion) -> None:
    """Index clauses into contract_index (BM25 full-text) after parsing."""
    contract = version.contract
    es_docs = []
    for cl in version.clauses:
        es_docs.append(
            {
                "contract_id": version.contract_id,
                "version_id": version.id,
                "clause_id": cl.id,
                "contract_no": contract.contract_no if contract else "",
                "title": contract.title if contract else "",
                "clause_no": cl.clause_no,
                "clause_type": cl.clause_type,
                "content": cl.content,
            }
        )
    knowledge_service.bulk_index_contract_clauses(es_docs)
