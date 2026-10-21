"""Clause diff summarization (design doc 3.1.4 / prompt scene "version diff summary"): DeepSeek decides added/removed/modified/drift."""
from loguru import logger

from app.ai import llm_client
from app.utils.diff import char_diff_summary


def summarize_diff(old_text: str, new_text: str) -> tuple[str, str]:
    """Return (kind, summary). On LLM failure, fall back to a difflib character-level description (modified)."""
    prompt = (
        "对比以下新旧条款，归纳差异类型并输出一句话差异说明：\n"
        f"旧条款：{old_text[:800]}\n"
        f"新条款：{new_text[:800]}\n"
        '仅输出 JSON：{"kind": "added | removed | modified | drift", "summary": "..."}，'
        "其中 drift 指措辞接近但权利义务实质变化的语义漂移。"
    )
    try:
        result, _ = llm_client.chat_json(
            "你是合同版本比对专家，仅输出 JSON。", prompt
        )
        kind = str(result.get("kind", "modified"))
        if kind not in ("added", "removed", "modified", "drift"):
            kind = "modified"
        summary = str(result.get("summary", "")).strip() or char_diff_summary(old_text, new_text)
        return kind, summary[:300]
    except Exception as e:
        logger.warning(f"diff summarize fallback to difflib: {e}")
        return "modified", char_diff_summary(old_text, new_text)
