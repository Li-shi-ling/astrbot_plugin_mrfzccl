from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from astrbot.api import logger
from astrbot.api.provider import Provider

from ..tool import (
    calculate_char_coverage_set,
    check_homophone,
    is_exact_operator_alias_match,
    parse_llm_judge_result,
    resolve_alias,
)


@dataclass(frozen=True)
class MatchSettings:
    similarity_threshold: float
    calculate_threshold: float
    enable_similarity_match: bool
    enable_character_coverage_match: bool
    enable_homophone: bool
    enable_operator_alias_match: bool
    match_answer_grace_period: float = 3.0


def get_answer_match_details(
    answer: str, guess: str, settings: MatchSettings
) -> tuple[float, float, bool, bool]:
    similarity = SequenceMatcher(None, answer, guess).ratio()
    coverage = calculate_char_coverage_set(answer, guess)
    exact_match = answer == guess
    homophone_match = check_homophone(
        answer, guess, enable_homophone=settings.enable_homophone
    )
    similarity_match = settings.enable_similarity_match and (
        similarity > settings.similarity_threshold
    )
    coverage_match = settings.enable_character_coverage_match and (
        coverage > settings.calculate_threshold
    )
    is_correct = exact_match or similarity_match or coverage_match or homophone_match
    return similarity, coverage, homophone_match, is_correct


def is_matching_answer(
    answer: str,
    guess: str,
    *,
    aliases_by_name: Mapping[str, list[str]],
    settings: MatchSettings,
) -> bool:
    if settings.enable_operator_alias_match and is_exact_operator_alias_match(
        answer, guess, aliases_by_name
    ):
        return True
    _, _, _, is_correct = get_answer_match_details(answer, guess, settings)
    return is_correct


def should_skip_plain_answer_message(
    raw_message: str, *, is_wake_command: bool
) -> bool:
    message = re.sub(r"\s+", " ", str(raw_message or "").strip())
    if not message:
        return True
    if is_wake_command:
        return True
    if message.startswith(("/", "\\")):
        return True
    return message.startswith(("fc ", "fcc", "fce", "fct", "fcw"))


def is_recent_previous_match_answer(
    player_state: dict[str, Any],
    guess: str,
    *,
    alias_map: Mapping[str, str],
    aliases_by_name: Mapping[str, list[str]],
    settings: MatchSettings,
) -> bool:
    previous_answer = player_state.get("previous_answer")
    switched_at = player_state.get("previous_answer_switched_at")
    if not previous_answer or switched_at is None:
        return False

    grace_period = max(0.0, float(settings.match_answer_grace_period or 0.0))
    if grace_period <= 0:
        return False

    try:
        switched_at_ts = float(switched_at)
    except (TypeError, ValueError):
        return False

    if time.time() - switched_at_ts > grace_period:
        return False

    previous_answer_text = str(previous_answer)
    if is_matching_answer(
        previous_answer_text,
        guess,
        aliases_by_name=aliases_by_name,
        settings=settings,
    ):
        return True

    normalized_guess = resolve_alias(guess, alias_map)
    if normalized_guess == guess:
        return False

    return is_matching_answer(
        previous_answer_text,
        normalized_guess,
        aliases_by_name=aliases_by_name,
        settings=settings,
    )


def can_check_recent_previous_match_answer(
    player_state: dict[str, Any], settings: MatchSettings
) -> bool:
    previous_answer = player_state.get("previous_answer")
    switched_at = player_state.get("previous_answer_switched_at")
    if not previous_answer or switched_at is None:
        return False

    grace_period = max(0.0, float(settings.match_answer_grace_period or 0.0))
    if grace_period <= 0:
        return False

    try:
        switched_at_ts = float(switched_at)
    except (TypeError, ValueError):
        return False

    return time.time() - switched_at_ts <= grace_period


class LlmJudgeService:
    def __init__(
        self,
        context: Any,
        *,
        enabled: bool,
        provider_id: str,
        prompt: str,
        debug: bool,
        enable_retry: bool,
        max_retries: int,
        retry_interval_seconds: float,
    ) -> None:
        self.context = context
        self.enabled = enabled
        self.provider_id = provider_id
        self.prompt = prompt
        self.debug = debug
        self.enable_retry = enable_retry
        self.max_retries = max_retries
        self.retry_interval_seconds = retry_interval_seconds

    def build_prompt(self, answer: str, guess: str) -> str:
        prompt = self.prompt or (
            "你是明日方舟猜题判题器。已知标准答案：{answer}。用户回答：{guess}。"
            "请只判断用户回答是否可以视为该标准答案。只能输出 True 或 False，不要输出其他任何内容。"
        )
        try:
            return prompt.format(answer=answer, guess=guess)
        except Exception:
            return (
                f"{prompt}\n标准答案：{answer}\n用户回答：{guess}\n"
                "只能输出 True 或 False，不要输出其他任何内容。"
            )

    async def judge_answer(
        self,
        answer: str,
        guess: str,
        *,
        unified_msg_origin: str | None = None,
    ) -> bool:
        if not self.enabled or not self.provider_id:
            return False

        provider = self.context.get_provider_by_id(self.provider_id)
        if not isinstance(provider, Provider):
            logger.warning(f"[llm_judge] 未找到 Provider: {self.provider_id}")
            return False

        prompt = self.build_prompt(answer, guess)
        msg_origin = str(unified_msg_origin or "").strip() or "unknown"
        session_id = f"mrfzccl-judge-{msg_origin}-{time.time_ns()}"
        max_attempts = 1 + max(
            0, int(self.max_retries or 0) if self.enable_retry else 0
        )

        for attempt in range(1, max_attempts + 1):
            try:
                response = await provider.text_chat(
                    prompt=prompt, session_id=session_id
                )
                completion_text = str(getattr(response, "completion_text", "") or "")
                result = parse_llm_judge_result(completion_text)
                if result is None:
                    raise ValueError(f"LLM 判题输出不合法: {completion_text}")
                return result
            except Exception as exc:
                if attempt >= max_attempts:
                    logger.warning(f"[llm_judge] 判题失败: {exc}")
                    return False
                logger.warning(
                    f"[llm_judge] 判题失败，准备重试({attempt}/{max_attempts}): {exc}"
                )
                if self.retry_interval_seconds > 0:
                    await asyncio.sleep(self.retry_interval_seconds)

        return False


async def is_recent_previous_match_answer_with_llm(
    player_state: dict[str, Any],
    guess: str,
    *,
    alias_map: Mapping[str, str],
    aliases_by_name: Mapping[str, list[str]],
    settings: MatchSettings,
    llm_judge,
    unified_msg_origin: str | None = None,
) -> bool:
    if is_recent_previous_match_answer(
        player_state,
        guess,
        alias_map=alias_map,
        aliases_by_name=aliases_by_name,
        settings=settings,
    ):
        return True
    if not can_check_recent_previous_match_answer(player_state, settings):
        return False

    previous_answer = player_state.get("previous_answer")
    if not previous_answer:
        return False

    previous_answer_text = str(previous_answer)
    if await llm_judge(
        previous_answer_text, guess, unified_msg_origin=unified_msg_origin
    ):
        return True

    normalized_guess = resolve_alias(guess, alias_map)
    if normalized_guess == guess:
        return False

    return await llm_judge(
        previous_answer_text, normalized_guess, unified_msg_origin=unified_msg_origin
    )
