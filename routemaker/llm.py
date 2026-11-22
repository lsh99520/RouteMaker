import logging
import os

import anthropic

MODEL = os.environ.get("ROUTEMAKER_MODEL", "claude-haiku-5-5")
log = logging.getLogger("routemaker.llm")

UNAVAILABLE = "지금은 AI 분석을 쓸 수 없어요. 샘플 공고로 체험하거나 잠시 뒤 다시 시도해 주세요."
BUSY = "AI 요청이 몰려 잠시 처리하지 못했어요. 1분 뒤 다시 시도해 주세요."
SLOW = "AI 응답이 늦어 중단했어요. 잠시 뒤 다시 시도해 주세요."
FORMAT = "AI가 결과를 형식에 맞게 돌려주지 않았어요. 다시 시도해 주세요."


class LLMError(Exception):
    pass


def user_message(e: Exception) -> str:
    if isinstance(e, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
        return SLOW
    if isinstance(e, anthropic.RateLimitError):
        return BUSY
    status = getattr(e, "status_code", None)
    if status in (429, 503, 529):
        return BUSY
    return UNAVAILABLE


def call_tool(system: str, user: str, tool_name: str, schema: dict, max_tokens: int = 4096) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY 없음 — .env 또는 서버 환경변수에 넣고 다시 실행")
        raise LLMError(UNAVAILABLE)
    client = anthropic.Anthropic(timeout=60.0, max_retries=2)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            tools=[{"name": tool_name, "description": "추출 결과를 기록한다.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIError as e:
        log.warning("LLM 호출 실패: %s", e)
        raise LLMError(user_message(e)) from e
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    log.warning("LLM 응답에 %s 결과 없음", tool_name)
    raise LLMError(FORMAT)
