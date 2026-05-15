from __future__ import annotations

import traceback
from typing import Any, Callable

import astrbot.api.message_components as Comp
from astrbot.api import logger

from ..tool import (
    generate_correct_leaderboard_text,
    generate_hints_leaderboard_text,
    generate_match_leaderboard_text,
    generate_user_profile_text,
    generate_wrong_leaderboard_text,
)


async def generate_image_or_fallback(
    event: Any,
    generate_image_func: Callable[..., Any],
    generate_text_func: Callable[..., str],
    *args,
    **kwargs,
):
    try:
        image_path = await generate_image_func(*args, **kwargs)
        import os

        if image_path and os.path.exists(image_path):
            yield event.chain_result([Comp.Image.fromFileSystem(image_path)])
            return

        text_message = generate_text_func(*args, **kwargs)
        yield event.plain_result(f"图片生成失败，使用文本模式显示\n\n{text_message}")
    except Exception as render_error:
        logger.error(f"[Mrfzccl] 图片渲染失败: {render_error}")
        logger.debug(f"[Mrfzccl] {traceback.format_exc()}")
        text_message = generate_text_func(*args, **kwargs)
        yield event.plain_result(
            f"图片生成失败，使用文本模式显示\n错误: {str(render_error)}\n\n{text_message}"
        )


class LeaderboardTextService:
    generate_correct_leaderboard_text = staticmethod(generate_correct_leaderboard_text)
    generate_wrong_leaderboard_text = staticmethod(generate_wrong_leaderboard_text)
    generate_hints_leaderboard_text = staticmethod(generate_hints_leaderboard_text)
    generate_match_leaderboard_text = staticmethod(generate_match_leaderboard_text)
    generate_user_profile_text = staticmethod(generate_user_profile_text)
