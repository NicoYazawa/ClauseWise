"""LangGraph agent model factory: build ChatOpenAI (OpenAI-compatible protocol) from the current vendor endpoint.

Division of labor with app/ai/llm_client.py:
- llm_client: direct SDK wrapper (OCR / diff summarization / non-agent chains), with built-in semaphore rate limiting
- agents/llm: ChatModel for LangGraph nodes and ReAct sub-agents;
  concurrency is still bounded by llm_client.llm_concurrency's thread pool (clause reviewers are driven via run_parallel)

Switching vendors only requires editing .env (see app/ai/providers.py); this module needs no change.
"""
from langchain_openai import ChatOpenAI

from app.ai.providers import ModelConfigError, llm_endpoint


def get_chat_model(temperature: float = 0.1) -> ChatOpenAI:
    """Build a fresh instance each time (graphs are built per task; model instances aren't reused across tasks)."""
    try:
        endpoint = llm_endpoint()
    except ModelConfigError as e:
        raise RuntimeError(f"对话模型配置错误：{e}") from e
    if endpoint.requires_api_key and not endpoint.api_key:
        raise RuntimeError(
            f"未配置 {endpoint.api_key_env or 'LLM_API_KEY'}（当前厂商 {endpoint.provider}），无法构建审查模型"
        )
    return ChatOpenAI(
        api_key=endpoint.key_or_placeholder,
        base_url=endpoint.base_url,
        model=endpoint.model,
        temperature=temperature,
        timeout=120,
        max_retries=3,
        # some vendors don't support stream_options.include_usage; set LLM_STREAM_USAGE=false to disable
        stream_usage=endpoint.stream_usage,
    )
