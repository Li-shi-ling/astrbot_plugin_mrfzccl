from __future__ import annotations

import asyncio
import time
from typing import Any

from PIL import Image

from ..tool import safe_cancel_task


class GameRuntime:
    def __init__(self) -> None:
        self.player: dict[str, dict[str, Any]] = {}
        self.original_images: dict[str, Image.Image] = {}

    def has_active_game(self, user_id: str) -> bool:
        data = self.player.get(user_id)
        return bool(data and data.get("status") == "active")

    def set_loading(self, user_id: str) -> None:
        self.player[user_id] = {"status": "loading"}

    def set_question(
        self, user_id: str, question: dict[str, Any], original_image: Image.Image
    ) -> None:
        self.original_images[user_id] = original_image.copy()
        question["status"] = "active"
        self.player[user_id] = question

    def end_game(self, user_id: str) -> None:
        self.player.pop(user_id, None)
        self.original_images.pop(user_id, None)


class MatchRuntime:
    def __init__(self, game_runtime: GameRuntime) -> None:
        self.game_runtime = game_runtime
        self.question_state: dict[str, float] = {}
        self.next_task: dict[str, asyncio.Task] = {}
        self.loop_task: dict[str, asyncio.Task] = {}
        self.sessions: dict[str, str] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.lock_last_used: dict[str, float] = {}

    def get_room_lock(self, room_id: str) -> asyncio.Lock:
        self.lock_last_used[room_id] = time.time()
        lock = self.locks.get(room_id)
        if lock is None:
            lock = asyncio.Lock()
            self.locks[room_id] = lock
        return lock

    def room_has_runtime(self, room_id: str) -> bool:
        data = self.game_runtime.player.get(room_id)
        if isinstance(data, dict) and data.get("status") in {"active", "loading"}:
            return True
        return (
            room_id in self.question_state
            or room_id in self.next_task
            or room_id in self.loop_task
            or room_id in self.sessions
        )

    def cleanup_stale_room_locks(self, max_idle_hours: int = 24) -> int:
        try:
            cutoff = time.time() - float(max_idle_hours) * 3600
        except Exception:
            cutoff = time.time() - 24 * 3600

        removed = 0
        for room_id, lock in list(self.locks.items()):
            last_used = float(self.lock_last_used.get(room_id, 0) or 0)
            if last_used and last_used > cutoff:
                continue
            if lock.locked() or self.room_has_runtime(room_id):
                continue
            self.locks.pop(room_id, None)
            self.lock_last_used.pop(room_id, None)
            removed += 1
        return removed

    def clear_match_runtime(self, group_id: str) -> None:
        self.question_state.pop(group_id, None)
        safe_cancel_task(self.next_task.pop(group_id, None))

        loop_task = self.loop_task.pop(group_id, None)
        try:
            current_task = asyncio.current_task()
        except Exception:
            current_task = None
        if loop_task is not current_task:
            safe_cancel_task(loop_task)

        self.sessions.pop(group_id, None)
        self.game_runtime.end_game(group_id)

    def cancel_all_match_tasks(self) -> None:
        for task in list(self.next_task.values()):
            safe_cancel_task(task)
        for task in list(self.loop_task.values()):
            safe_cancel_task(task)
        self.next_task.clear()
        self.loop_task.clear()
        self.sessions.clear()
        self.question_state.clear()
