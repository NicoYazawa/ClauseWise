"""Prompt orchestration (design doc 3.2.7): versioned template management + variable injection; review tasks record prompt_version."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.knowledge import PromptTemplate

SCENE_REVIEW = "条款合规审查"
SCENE_VISION = "扫描件视觉解析"
SCENE_DIFF = "版本差异归纳"

# fallback default template (used when the prompt_template table is empty; version default-v1)
_DEFAULT_REVIEW_PROMPT = (
    "[角色]\n"
    "你是资深企业法务合规审查专家，熟悉《民法典》合同编及中国合同实务。\n\n"
    "[审查对象]\n"
    "合同类型：{contract_type}\n"
    "待审条款：\n{clause_text}\n\n"
    "[参考依据]（检索自知识库，仅供引用，不得编造）\n{rag_context}\n\n"
    "[输出要求]\n"
    "仅输出 JSON，不要输出任何其他文字，结构如下：\n"
    "{{\n"
    '  "risk_level": "high | medium | low | none",\n'
    '  "risk_type": "风险类型（如 违约责任失衡/条款缺失/违法无效）",\n'
    '  "risk_points": [\n'
    "    {{\n"
    '      "original_text": "原文摘录",\n'
    '      "issue": "风险描述",\n'
    '      "legal_basis": "引用上述参考依据的条文编号，未命中则填 null",\n'
    '      "suggestion": "具体改写建议",\n'
    '      "suggested_text": "按建议改写后的完整条款文本"\n'
    "    }}\n"
    "  ]\n"
    "}}"
)


def get_active_prompt(db: Session, scene: str) -> PromptTemplate:
    """Get the currently active template for a scene; return an in-memory fallback when none exists."""
    tpl = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.scene == scene, PromptTemplate.is_active == 1)  # type: ignore[arg-type]
        .order_by(PromptTemplate.id.desc())
        .first()
    )
    if tpl:
        return tpl
    return PromptTemplate(
        id=0, version="default-v1", scene=scene, content=_DEFAULT_REVIEW_PROMPT, is_active=True,
        updated_at=datetime.now(),
    )


def render_prompt(template_content: str, variables: dict) -> str:
    """Variable injection (unprovided {var} placeholders are left as-is to avoid KeyError)."""
    out = template_content
    for key, value in variables.items():
        out = out.replace("{" + key + "}", str(value))
    return out
