"""Permission catalog shared by bootstrap and the additive security upgrade."""
PERMISSIONS = [
    ("contract:upload", "合同上传/重新解析", "合同管理"),
    ("contract:download", "合同下载", "合同管理"),
    ("contract:delete", "合同归档", "合同管理"),
    ("review:rerun", "发起/重跑审查", "AI 审查"),
    ("review:resolve", "风险处置", "AI 审查"),
    ("review:export", "导出审查报告", "AI 审查"),
    ("workflow:start", "发起审批/催办", "审批工作流"),
    ("workflow:define", "流程定义编排", "审批工作流"),
    ("workflow:approve", "审批操作", "审批工作流"),
    ("knowledge:manage", "知识库维护", "知识库"),
    ("system:user", "用户管理", "系统管理"),
    ("system:role", "角色权限管理", "系统管理"),
    ("system:audit", "审计日志查看", "系统管理"),
    ("system:prompt", "Prompt 管理", "系统管理"),
    ("system:model", "模型管理", "系统管理"),
]

# Applied once when upgrading built-in roles. Custom roles are never widened;
# subsequent startup must not restore permissions an administrator revoked.
UPGRADE_GRANTS = {
    "admin": {code for code, _, _ in PERMISSIONS},
    "legal_manager": {"review:resolve", "workflow:start"},
    "legal_reviewer": {"review:resolve", "workflow:start"},
    "business_owner": {"review:rerun", "workflow:start", "contract:delete"},
}
