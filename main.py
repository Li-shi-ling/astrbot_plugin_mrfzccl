from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig

from .src.mrfzccl_core import MrfzcclCore


@register("mrfzccl", "Lishining", "你知道的,我一直是明日方舟高手", "1.0.0")
class Mrfzccl(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context, config)
        self.Config = config
        self._core = MrfzcclCore(config=config, plugin_dir=Path(__file__).resolve().parent)

    # 插件初始化时
    async def initialize(self):
        await self._core.initialize()

    # 插件卸载时的清理钩子
    async def terminate(self):
        await self._core.terminate()

    # ========== 基础游戏指令 ==========

    @filter.command("fc")
    async def fc(self, event: AstrMessageEvent):
        async for result in self._core.fc(event):
            yield result

    @filter.command("fcc")
    async def fcc(self, event: AstrMessageEvent):
        async for result in self._core.fcc(event):
            yield result

    @filter.command("fce")
    async def fce(self, event: AstrMessageEvent):
        async for result in self._core.fce(event):
            yield result

    @filter.command("fct")
    async def fct(self, event: AstrMessageEvent):
        async for result in self._core.fct(event):
            yield result

    @filter.command("fcw")
    async def fcw(self, event: AstrMessageEvent):
        async for result in self._core.fcw(event):
            yield result

    # ========== 统计/比赛指令组 ==========

    @filter.command_group("ccl")
    def ccl(self):
        pass

    @ccl.command("比赛帮助")
    async def match_help(self, event: AstrMessageEvent):
        async for result in self._core.match_help(event):
            yield result

    @ccl.command("比赛创建")
    async def match_create(self, event: AstrMessageEvent, name: str = "", question_limit: int = 0, time_limit: int = 0):
        async for result in self._core.match_create(event, name=name, question_limit=question_limit, time_limit=time_limit):
            yield result

    @ccl.command("比赛开始")
    async def match_start(self, event: AstrMessageEvent):
        async for result in self._core.match_start(event):
            yield result

    @ccl.command("比赛结束")
    async def match_end(self, event: AstrMessageEvent):
        async for result in self._core.match_end(event):
            yield result

    @ccl.command("比赛排行")
    async def match_leaderboard(self, event: AstrMessageEvent):
        async for result in self._core.match_leaderboard(event):
            yield result

    @ccl.command("排行榜")
    async def correct_answers_leaderboard(self, event: AstrMessageEvent):
        async for result in self._core.correct_answers_leaderboard(event):
            yield result

    @ccl.command("错误排行榜")
    async def wrong_answers_leaderboard(self, event: AstrMessageEvent):
        async for result in self._core.wrong_answers_leaderboard(event):
            yield result

    @ccl.command("提示排行榜")
    async def hints_usage_leaderboard(self, event: AstrMessageEvent):
        async for result in self._core.hints_usage_leaderboard(event):
            yield result

    @ccl.command("名片")
    async def user_profile_retrieval(self, event: AstrMessageEvent, user_id: str | None = None):
        async for result in self._core.user_profile_retrieval(event, user_id=user_id):
            yield result

    @ccl.command("清除数据")
    async def reset_user_data(self, event: AstrMessageEvent, target_user_id: str = ""):
        async for result in self._core.reset_user_data(event, target_user_id=target_user_id):
            yield result

    @ccl.command("清除荣誉")
    async def reset_user_honors_cmd(self, event: AstrMessageEvent, target_user_id: str = ""):
        async for result in self._core.reset_user_honors_cmd(event, target_user_id=target_user_id):
            yield result

    @ccl.command("清除所有数据")
    async def reset_all_data_cmd(self, event: AstrMessageEvent):
        async for result in self._core.reset_all_data_cmd(event):
            yield result

    @ccl.command("清除所有荣誉")
    async def reset_all_honors_cmd(self, event: AstrMessageEvent):
        async for result in self._core.reset_all_honors_cmd(event):
            yield result

    @ccl.command("授予荣誉")
    async def grant_honor_cmd(self, event: AstrMessageEvent, target_user_id: str = "", rank: int = 1, match_name: str = "", correct_count: int = 0):
        async for result in self._core.grant_honor_cmd(
            event,
            target_user_id=target_user_id,
            rank=rank,
            match_name=match_name,
            correct_count=correct_count,
        ):
            yield result
