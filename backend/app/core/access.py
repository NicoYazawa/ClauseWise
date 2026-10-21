"""Shared object authorization. Apply to queries before pagination and to every ID lookup."""
from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models.contract import Contract
from app.models.user import User


def contract_scope(user: User):
    """Roles grant the union of self/dept/all; unknown scopes never widen access."""
    if any(role.code == "admin" or role.data_scope == "all" for role in user.roles):
        return true()
    own = Contract.owner_id == user.id
    if any(role.data_scope == "dept" for role in user.roles) and user.dept_name not in (None, "", "未分配"):
        owners = select(User.id).where(User.dept_name == user.dept_name)
        return or_(own, Contract.owner_id.in_(owners))
    return own


def visible_contract_ids(user: User):
    return select(Contract.id).where(contract_scope(user))


def get_contract_for_user(db: Session, user: User, contract_id: int) -> Contract:
    contract = db.get(Contract, contract_id)
    if contract is None:
        raise AppError("CONTRACT_NOT_FOUND", 404, "合同不存在")
    allowed = db.query(Contract.id).filter(Contract.id == contract_id, contract_scope(user)).first()
    if allowed is None:
        raise AppError("DATA_SCOPE_DENIED", 403, "无权访问该合同")
    return contract
