from __future__ import annotations

import asyncio
import random
import traceback
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger

from ..images.service import mask_image_with_random_blocks, pil_image_to_bytes, resize_to_target


class GuessGameService:
    def __init__(
        self,
        *,
        game_runtime,
        question_picker,
        image_downloader,
        target_size: int,
        easy_probability: float,
        medium_probability: float,
        hard_probability: float,
    ) -> None:
        self.game_runtime = game_runtime
        self.question_picker = question_picker
        self.image_downloader = image_downloader
        self.target_size = target_size
        self.easy_probability = easy_probability
        self.medium_probability = medium_probability
        self.hard_probability = hard_probability

    async def start_game(self, user_id: str) -> bytes | str | None:
        existing = self.game_runtime.player.get(user_id)
        if existing and existing.get("status") in {"active", "loading"}:
            return "already_exists"
        self.game_runtime.set_loading(user_id)
        try:
            question = self.question_picker.pick()
            if not question:
                logger.error("[Mrfzccl][fc_init] 提取题目失败")
                self.game_runtime.end_game(user_id)
                return None

            try:
                image = await self.image_downloader.get_image_from_url(question["url"])
            except Exception as exc:
                logger.error(f"[Mrfzccl][fc_init] 获取图片失败,e:{exc}")
                self.game_runtime.end_game(user_id)
                return None

            self.game_runtime.set_question(user_id, question, image)
            block_count = self._pick_block_count()
            loop = asyncio.get_running_loop()
            result, _ = await loop.run_in_executor(
                None, mask_image_with_random_blocks, image, block_count
            )
            resized = await loop.run_in_executor(
                None, resize_to_target, result, self.target_size
            )
            return pil_image_to_bytes(resized)
        except Exception as exc:
            logger.error(f"[Mrfzccl][fc_init] 初始化失败: {exc}")
            logger.debug(f"[Mrfzccl][fc_init] {traceback.format_exc()}")
            self.game_runtime.end_game(user_id)
            return None

    def _pick_block_count(self) -> int:
        value = random.random()
        if value < self.easy_probability:
            return 5
        if value < self.easy_probability + self.medium_probability:
            return 3
        return 1

    async def send_original_image(self, user_id: str, event: Any) -> Any:
        if user_id not in self.game_runtime.original_images:
            logger.warning(f"[Mrfzccl][send_original_image] 用户 {user_id} 没有原始图片")
            return event.plain_result("无法获取正确答案图片")

        try:
            original_image = self.game_runtime.original_images[user_id]
            loop = asyncio.get_running_loop()
            resized_original = await loop.run_in_executor(
                None, resize_to_target, original_image, self.target_size
            )
            img_bytes = pil_image_to_bytes(resized_original)
            output_data = event.chain_result(
                [Comp.Plain("正确答案的完整立绘"), Comp.Image.fromBytes(img_bytes)]
            )
            self.game_runtime.end_game(user_id)
            return output_data
        except Exception as exc:
            logger.error(f"[Mrfzccl][send_original_image] 发送原始图片失败: {exc}")
            self.game_runtime.end_game(user_id)
            return event.plain_result("发送正确答案图片失败")
