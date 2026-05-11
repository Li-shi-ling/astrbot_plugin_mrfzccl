from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from astrbot.api import logger
from astrbot.api.event import MessageChain

from ..stats.service import generate_match_leaderboard_text
from ..tool import has_active_game


class MatchService:
    def __init__(
        self,
        *,
        context: Any,
        match_repo: Any,
        renderer: Any,
        game_runtime: Any,
        match_runtime: Any,
        start_game,
        next_hint,
        shutting_down,
        hint_delay: int,
    ) -> None:
        self.context = context
        self.match_repo = match_repo
        self.renderer = renderer
        self.game_runtime = game_runtime
        self.match_runtime = match_runtime
        self.start_game = start_game
        self.next_hint = next_hint
        self.shutting_down = shutting_down
        self.hint_delay = hint_delay

    async def get_match_end_reason(self, match: Any) -> str | None:
        if not match:
            return None

        try:
            time_limit_min = int(getattr(match, "time_limit", 0) or 0)
        except Exception:
            time_limit_min = 0
        if time_limit_min > 0:
            started_at = getattr(match, "started_at", None)
            if started_at:
                try:
                    if datetime.now() - started_at >= timedelta(minutes=time_limit_min):
                        return "time_limit"
                except Exception:
                    pass

        try:
            question_limit = int(getattr(match, "question_limit", 0) or 0)
        except Exception:
            question_limit = 0
        if question_limit > 0:
            participants = await self.match_repo.get_participants(match.match_id)
            solved = sum(int(getattr(p, "correct_count", 0) or 0) for p in participants)
            if solved >= question_limit:
                return "question_limit"
        return None

    async def end_match_and_collect_top(
        self, group_id: str, match: Any
    ) -> tuple[str, int, list]:
        match_name = getattr(match, "match_name", "比赛")
        match_id = int(getattr(match, "match_id", 0) or 0)
        await self.match_repo.end_match(match_id)
        self.match_runtime.clear_match_runtime(group_id)

        participants = await self.match_repo.get_participants(match_id)
        participants.sort(key=lambda p: p.score, reverse=True)
        top_participants = participants[:10]
        for index, participant in enumerate(top_participants, 1):
            await self.match_repo.save_honor(
                participant.user_id,
                match_id,
                match_name,
                index,
                participant.correct_count,
                participant.wrong_count,
                participant.score,
            )
        return match_name, match_id, top_participants

    def schedule_match_hint(self, group_id: str) -> None:
        try:
            delay = int(self.hint_delay or 0)
        except Exception:
            delay = 0
        if delay <= 0:
            return

        session = self.match_runtime.sessions.get(group_id)
        token = self.match_runtime.question_state.get(group_id)
        if not session or not token:
            return

        from ..tool import safe_cancel_task

        if group_id in self.match_runtime.next_task:
            safe_cancel_task(self.match_runtime.next_task.pop(group_id, None))
        self.match_runtime.next_task[group_id] = asyncio.create_task(
            self.match_hint_after_delay(group_id, session, delay, float(token))
        )

    async def match_hint_after_delay(
        self, group_id: str, session: str, delay: int, token: float
    ) -> None:
        try:
            interval = max(1, int(delay))
            while True:
                await asyncio.sleep(interval)
                if self.shutting_down():
                    return
                if self.match_runtime.question_state.get(group_id) != token:
                    return
                match = await self.match_repo.get_active_match(group_id)
                if not match or not match.is_active:
                    return
                if not has_active_game(self.game_runtime.player, group_id):
                    return

                lock = self.match_runtime.get_room_lock(group_id)
                async with lock:
                    if self.match_runtime.question_state.get(group_id) != token:
                        return
                    match2 = await self.match_repo.get_active_match(group_id)
                    if not match2 or not match2.is_active:
                        return
                    if not has_active_game(self.game_runtime.player, group_id):
                        return
                    hint_text, has_more = self.next_hint(group_id)

                await self.context.send_message(
                    session, MessageChain().message(f"💡 超时提示：{hint_text}")
                )
                if not has_more:
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning(f"[match] 自动提示任务异常 group_id={group_id}: {exc}")

    async def send_match_leaderboard_to_session(
        self, session: str, match_name: str, top_participants: list, title: str
    ) -> None:
        if self.shutting_down():
            return
        try:
            image_path = await self.renderer.generate_match_leaderboard_image(
                match_name, top_participants, title=title
            )
            import os

            if image_path and os.path.exists(image_path):
                try:
                    await self.context.send_message(
                        session, MessageChain().file_image(image_path)
                    )
                    return
                except Exception as exc:
                    logger.warning(f"[match] 主动发送排行榜图片失败，回退文本: {exc}")
        except Exception as exc:
            logger.warning(f"[match] 比赛排行榜图片发送失败，回退文本: {exc}")

        text = generate_match_leaderboard_text(match_name, top_participants, ended=True)
        try:
            await self.context.send_message(session, MessageChain().message(text))
        except Exception as exc:
            logger.warning(f"[match] 主动发送排行榜文本失败: {exc}")

    async def match_game_loop(self, group_id: str) -> None:
        await asyncio.sleep(2)
        while not self.shutting_down():
            await asyncio.sleep(5)
            match = await self.match_repo.get_active_match(group_id)
            if not match or not match.is_active:
                return
            end_reason = await self.get_match_end_reason(match)
            if not end_reason:
                continue

            lock = self.match_runtime.get_room_lock(group_id)
            async with lock:
                match2 = await self.match_repo.get_active_match(group_id)
                if not match2 or not match2.is_active:
                    return
                session = self.match_runtime.sessions.get(group_id)
                reason_text = (
                    f"⏰ 已达到时间限制，比赛「{match2.match_name}」自动结束！"
                    if end_reason == "time_limit"
                    else f"📑 已达到题目上限，比赛「{match2.match_name}」自动结束！"
                )
                match_name, _, top_participants = await self.end_match_and_collect_top(
                    group_id, match2
                )
                if not session:
                    logger.warning(
                        f"[match] 缺少 session，无法主动发送比赛结束消息 group_id={group_id}"
                    )
                    return

            try:
                await self.context.send_message(session, MessageChain().message(reason_text))
                await self.send_match_leaderboard_to_session(
                    session=session,
                    match_name=match_name,
                    top_participants=top_participants,
                    title=f"比赛「{match_name}」已结束排行榜",
                )
            except Exception as exc:
                logger.warning(
                    f"[match] 主动发送比赛结束消息失败 group_id={group_id}: {exc}"
                )
            return
