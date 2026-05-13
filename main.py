from astrbot.api.event import MessageChain, filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.provider import Provider
from astrbot.api.star import StarTools
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
from astrbot.api.event.filter import EventMessageType

from .src.gameplay import judging as judging_module
from .src.images import service as media_module
from .src.core.config import LLM_JUDGE_MAX_RETRIES_HARD_LIMIT, load_settings
from .src.gameplay.service import GuessGameService
from .src.gameplay.judging import (
    LlmJudgeService,
    MatchSettings as JudgeMatchSettings,
    should_skip_plain_answer_message,
)
from .src.competition.service import MatchService
from .src.images.service import ImageDownloader
from .src.gameplay.questions import QuestionPicker
from .src.rendering import (
    QnAStatsRenderer,
    QnAStatsRendererIndustrial,
    QnAStatsRendererRetroWin,
)
from .src.core.runtime import GameRuntime, MatchRuntime
from .src.tool import (
    generate_match_leaderboard_text,
    has_active_game,
    load_operator_aliases,
    load_image_from_bytes,
    mask_image_with_random_blocks,
    merge_alias_maps,
    parse_llm_judge_result,
    parse_aliases,
    parse_aliases_json_text,
    pil_image_to_bytes,
    normalize_compact_fc_command,
    resize_to_target,
    safe_cancel_task,
)
from .src.db.repo import UserQnARepo, MatchRepo
from .src.db.database import DBManager
from .src.handlers import ccl_admin, ccl_leaderboard, ccl_match, fc_handlers

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from urllib.parse import urlparse
from pathlib import Path
from PIL import Image
import numpy as np
import traceback
import ipaddress
import asyncio
import aiohttp
import random
import json
import time
import os
import re


# 注册插件，指定插件名、作者、描述和版本号
@register("mrfzccl", "Lishining", "你知道的,我一直是明日方舟高手", "1.2.44")
class Mrfzccl(Star):
    _question_candidate_names: np.ndarray
    _question_candidate_urls: List[List[str]]
    _question_candidate_low_idx: np.ndarray
    _question_candidate_normal_idx: np.ndarray
    _question_cache_data_id: Optional[int]
    _question_cache_kw_sig: Optional[tuple]
    _question_rng: np.random.Generator
    recent_characters: List[str]

    # 插件初始化方法
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context, config)  # 调用父类初始化
        self.plugin_dir = Path(__file__).resolve().parent
        self.context = context
        self.settings = load_settings(
            config, self.plugin_dir, self._get_context_config()
        )
        self.game_runtime = GameRuntime()
        self.match_runtime = MatchRuntime(self.game_runtime)
        self.Config = config  # 保存配置对象
        self.player: Dict[str, Dict[str, Any]] = {}  # 存储玩家游戏状态
        self.original_images: Dict[str, Image.Image] = {}  # 保存原始图片对象
        self.is_load = False  # 数据加载标志
        self._shutting_down = False  # 添加关闭标志，用于优雅关闭
        self.game_runtime.player = self.player
        self.game_runtime.original_images = self.original_images

        # 是否对排行榜类进行管理员限制
        self.require_admin = self.Config.get("require_admin", True)

        # 提示信息类型映射字典
        self.fct_key = {
            0: "职业及分支",  # 第一个提示：职业
            1: "星级",  # 第二个提示：星级
            2: "阵营",  # 第三个提示：阵营
            3: "获取方式",  # 第四个提示：获取方式
        }

        # 从配置文件读取相似度阈值
        self.similarity_threshold = self.Config.get("similarity_threshold", 0.5)
        self.enable_similarity_match = self.Config.get("enable_similarity_match", True)
        # 从配置文件读取字符匹配阈值
        self.calculate_threshold = self.Config.get("calculate_threshold", 0.5)
        self.enable_character_coverage_match = self.Config.get(
            "enable_character_coverage_match", True
        )
        # 是否启用同音字匹配
        self.enable_homophone = self.Config.get("enable_homophone", False)
        # 是否启用干员别名精确判题
        self.enable_operator_alias_match = self.Config.get(
            "enable_operator_alias_match", True
        )
        self.enable_other_message_exact_match = self.Config.get(
            "enable_other_message_exact_match", True
        )
        # 下载 bilibili wiki 图片时的重试配置
        image_download_retry = self.Config.get("image_download_retry", {}) or {}
        if not isinstance(image_download_retry, dict):
            image_download_retry = {}
        llm_judge = self.Config.get("llm_judge", {}) or {}
        if not isinstance(llm_judge, dict):
            llm_judge = {}
        self.llm_judge_enabled = bool(llm_judge.get("enabled", False))
        self.llm_judge_provider_id = str(
            llm_judge.get("provider_id", llm_judge.get("model", "")) or ""
        ).strip()
        self.llm_judge_prompt = self.settings.llm_judge.prompt
        self.llm_judge_debug = bool(llm_judge.get("debug", False))
        self.llm_judge_enable_retry = bool(llm_judge.get("enable_retry", False))
        configured_llm_judge_max_retries = int(llm_judge.get("max_retries", 0) or 0)
        if configured_llm_judge_max_retries > LLM_JUDGE_MAX_RETRIES_HARD_LIMIT:
            logger.warning(
                "[llm_judge] max_retries=%s exceeds hard limit %s, clamping",
                configured_llm_judge_max_retries,
                LLM_JUDGE_MAX_RETRIES_HARD_LIMIT,
            )
        self.llm_judge_max_retries = max(
            0,
            min(
                configured_llm_judge_max_retries,
                LLM_JUDGE_MAX_RETRIES_HARD_LIMIT,
            ),
        )
        self.llm_judge_retry_interval_seconds = max(
            0.0,
            float(llm_judge.get("retry_interval_seconds", 0.0) or 0.0),
        )
        self.image_download_max_retries = max(
            0,
            int(
                image_download_retry.get(
                    "max_retries",
                    self.Config.get("image_download_max_retries", 2),
                )
                or 0
            ),
        )
        self.image_download_retry_interval_seconds = max(
            0.0,
            float(image_download_retry.get("retry_interval_seconds", 0.5) or 0.0),
        )

        # 每日限制配置
        self.daily_limit = self.Config.get("daily_game_limit", 10)  # 每日游戏次数限制
        self.daily_usage: dict = {}  # 记录每日使用情况
        self.daily_counter: dict = {}  # 记录每日计数器

        # 比赛状态追踪
        self.match_question_state: dict[
            str, float
        ] = {}  # group_id -> 当前题目开始时间戳
        self.match_next_task: dict[
            str, asyncio.Task
        ] = {}  # group_id -> 当前题目的自动提示任务
        self.match_loop_task: dict[
            str, asyncio.Task
        ] = {}  # group_id -> 比赛结束检测循环任务
        self.match_sessions: dict[
            str, str
        ] = {}  # group_id -> unified_msg_origin（用于主动消息）
        self.match_locks: dict[
            str, asyncio.Lock
        ] = {}  # room_id(group_id/私聊user_id) -> 锁，防止并发触发导致状态错乱
        self._room_lock_last_used: dict[
            str, float
        ] = {}  # room_id -> 最近一次使用时间戳（用于清理长期闲置锁）
        self.match_answer_grace_period = self.settings.match.answer_grace_period
        self.match_runtime.question_state = self.match_question_state
        self.match_runtime.next_task = self.match_next_task
        self.match_runtime.loop_task = self.match_loop_task
        self.match_runtime.sessions = self.match_sessions
        self.match_runtime.locks = self.match_locks
        self.match_runtime.lock_last_used = self._room_lock_last_used

        # 防重复配置
        self.recent_characters: list = []  # 最近出现的干员列表
        self.max_recent_count = 20  # 最大记录数量

        # 别名系统
        self.alias_map: dict = {}  # 干员别名映射
        self.operator_aliases_by_name: dict[str, list[str]] = {}
        self._load_aliases()  # 加载别名配置

        # 低权重干员配置（出现概率较低的干员）
        self.low_weight_keywords = self.Config.get(
            "low_weight_characters", "预备干员,机师,W,SideStory"
        ).split(",")
        self.low_weight_ratio = self.Config.get(
            "low_weight_ratio", 0.2
        )  # 低权重干员出现概率

        # 比赛相关配置
        self.match_question_limit = self.Config.get(
            "match_question_limit", 0
        )  # 比赛题目数量限制
        self.match_time_limit = self.Config.get("match_time_limit", 0)  # 比赛时间限制
        self.match_hint_delay = self.Config.get(
            "match_hint_delay", 0
        )  # 比赛超时自动提示（秒，0关闭）
        self.admin_ids = self.Config.get("admin_ids", [])  # 管理员ID列表

        # 设置默认配置
        self.target_size = self.Config.get("target_size", 128)  # 图片目标尺寸
        self.easy_probability = self.Config.get("easy_probability", 0.6)  # 简单难度概率
        self.medium_probability = self.Config.get(
            "medium_probability", 0.3
        )  # 中等难度概率
        self.hard_probability = self.Config.get("hard_probability", 0.1)  # 困难难度概率

        # 添加 HTTP 会话管理
        self._session: Optional[aiohttp.ClientSession] = None
        self._executor = None  # 线程池执行器

        # 获取存储目录配置
        self.storage_dir = str(StarTools.get_data_dir())
        logger.info(f"[Mrfzccl] 存储目录: {self.storage_dir}")

        # 确保存储目录存在
        os.makedirs(self.storage_dir, exist_ok=True)

        # 构建数据库路径
        self.db_path = os.path.join(self.storage_dir, "mrfzccl.db")
        logger.debug(f"[Mrfzccl] 数据库目录: {self.db_path}")

        # 初始化数据库管理器
        self.db = DBManager(db_path=self.db_path)
        # 初始化用户问答仓库
        self.user_qna_repo = UserQnARepo(self.db)

        # 初始化比赛仓库
        self.match_repo = MatchRepo(self.db)  # 比赛仓库

        # 构建临时图片路径
        self.img_tmp_path = Path(get_astrbot_temp_path())
        self.img_tmp_path.mkdir(parents=True, exist_ok=True)

        # 初始化问答统计渲染器
        renderer_theme = self.Config.get("renderer_theme", "light")
        if renderer_theme in {"retro_win", "retro", "win95", "win"}:
            renderer_cls = QnAStatsRendererRetroWin
        elif renderer_theme in {"industrial", "dark"}:
            renderer_cls = QnAStatsRendererIndustrial
        else:
            renderer_cls = QnAStatsRenderer
        t2i_config = self.settings.t2i
        self.renderer = renderer_cls(
            output_dir=str(self.img_tmp_path),
            t2i_enabled=t2i_config.enabled,
            t2i_max_concurrent=t2i_config.max_concurrent,
            html_render_func=self.html_render,
        )
        logger.info(f"[Mrfzccl] 渲染主题: {renderer_theme}")

        # 构建数据文件路径
        data_path = self.settings.data_path
        try:
            logger.info(f"[Mrfzccl] 数据文件路径: {data_path}")
            if not data_path.exists():
                logger.error(f"[Mrfzccl] 数据文件不存在: {data_path}")
                return
            with data_path.open("r", encoding="utf-8") as file:
                self.data = json.load(file)
            if not isinstance(self.data, dict):
                logger.error("[Mrfzccl] 数据文件格式错误: 应为字典类型")
                return
            self.is_load = True
            logger.info(f"[Mrfzccl] 数据加载成功，共加载 {len(self.data)} 个角色")
        except json.JSONDecodeError as exc:
            logger.error(f"[Mrfzccl] JSON解析错误: {exc}")
            logger.error(traceback.format_exc())
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.error(f"[Mrfzccl] 文件未找到或权限错误: {exc}")
            logger.error(traceback.format_exc())
        except Exception as exc:
            logger.error(f"[Mrfzccl] 加载数据文件时发生未知错误: {exc}")
            logger.error(traceback.format_exc())
        self.question_picker = QuestionPicker(
            self.data if getattr(self, "is_load", False) else {},
            low_weight_keywords=self.low_weight_keywords,
            low_weight_ratio=self.low_weight_ratio,
            max_recent_count=self.max_recent_count,
        )
        self.image_downloader = ImageDownloader(
            lambda: self._get_session(),
            max_retries=self.image_download_max_retries,
            retry_interval_seconds=self.image_download_retry_interval_seconds,
        )
        self.game_service = GuessGameService(
            game_runtime=self.game_runtime,
            question_picker=self.question_picker,
            image_downloader=self.image_downloader,
            target_size=self.target_size,
            easy_probability=self.easy_probability,
            medium_probability=self.medium_probability,
            hard_probability=self.hard_probability,
        )
        self.llm_judge_service = LlmJudgeService(
            self.context,
            enabled=self.llm_judge_enabled,
            provider_id=self.llm_judge_provider_id,
            prompt=self.llm_judge_prompt,
            debug=self.llm_judge_debug,
            enable_retry=self.llm_judge_enable_retry,
            max_retries=self.llm_judge_max_retries,
            retry_interval_seconds=self.llm_judge_retry_interval_seconds,
        )
        self.judge_settings = JudgeMatchSettings(
            similarity_threshold=self.similarity_threshold,
            calculate_threshold=self.calculate_threshold,
            enable_similarity_match=self.enable_similarity_match,
            enable_character_coverage_match=self.enable_character_coverage_match,
            enable_homophone=self.enable_homophone,
            enable_operator_alias_match=self.enable_operator_alias_match,
            match_answer_grace_period=getattr(self, "match_answer_grace_period", 3.0),
        )
        self.match_service = MatchService(
            context=self.context,
            match_repo=self.match_repo,
            renderer=self.renderer,
            game_runtime=self.game_runtime,
            match_runtime=self.match_runtime,
            start_game=self.fc_init,
            next_hint=self._next_hint_text_and_advance,
            shutting_down=lambda: self._shutting_down,
            hint_delay=self.match_hint_delay,
        )

    # ========== 游戏相关指令 ==========
    # 初始化游戏命令
    @filter.command("fc")
    async def fc(self, event: AstrMessageEvent):
        """开始游戏 /fc"""
        # 检查数据是否加载成功
        if not self.is_load:
            yield event.chain_result(
                [
                    Comp.At(qq=event.get_sender_id()),  # @发送者
                    Comp.Plain(" 插件未加载成功，请联系管理员配置数据文件"),
                ]
            )
            return

        # 获取用户ID和群组ID（比赛仅在群聊有效）
        group_id_raw = event.get_group_id()
        sender_id = str(event.get_sender_id())
        is_group = bool(group_id_raw)
        group_id = str(group_id_raw) if is_group else None
        user_id = group_id if is_group else sender_id

        response = None
        room_lock = self._get_match_lock(user_id)
        async with room_lock:
            response = await fc_handlers.handle_fc(
                self,
                event,
                user_id=user_id,
                sender_id=sender_id,
                is_group=is_group,
                group_id=group_id,
            )

        if response is not None:
            yield response

    # 进行猜测命令
    @filter.command("fcc")
    async def fcc(self, event: AstrMessageEvent):
        """进行猜题 /fcc [干员名称]"""
        # 获取群组ID
        group_id_raw = event.get_group_id()
        sender_id = str(event.get_sender_id())
        is_group = bool(group_id_raw)
        group_id = str(group_id_raw) if is_group else None
        user_id = group_id if is_group else sender_id

        room_lock = self._get_match_lock(user_id)
        async with room_lock:
            responses, match_end_payload = await fc_handlers.handle_fcc(
                self,
                event,
                user_id=user_id,
                sender_id=sender_id,
                is_group=is_group,
                group_id=group_id,
            )

        for r in responses:
            yield r

        if match_end_payload:
            async for result in fc_handlers.iter_match_end_leaderboard(
                self, event, match_end_payload
            ):
                yield result

    # 强制结束游戏命令
    @filter.command("fce")
    async def fce(self, event: AstrMessageEvent):
        """强置结束游戏 /fce"""
        group_id_raw = event.get_group_id()
        sender_id = str(event.get_sender_id())
        is_group = bool(group_id_raw)
        group_id = str(group_id_raw) if is_group else None
        user_id = group_id if is_group else sender_id

        room_lock = self._get_match_lock(user_id)
        async with room_lock:
            responses = await fc_handlers.handle_fce(
                self,
                event,
                user_id=user_id,
                sender_id=sender_id,
                is_group=is_group,
                group_id=group_id,
            )

        for r in responses:
            yield r

    # 获取提示命令
    @filter.command("fct")
    async def fct(self, event: AstrMessageEvent):
        """获取提示 /fct"""
        group_id = event.get_group_id()
        sender_id = str(event.get_sender_id())
        is_group = bool(group_id)
        group_id_str = str(group_id) if is_group else None
        user_id = group_id_str if is_group else sender_id

        response = None
        room_lock = self._get_match_lock(user_id)
        async with room_lock:
            response = await fc_handlers.handle_fct(
                self,
                event,
                user_id=user_id,
                sender_id=sender_id,
                is_group=is_group,
                group_id=group_id_str,
            )

        if response is not None:
            yield response

    # 一次性获取三条提示命令
    @filter.command("fcw")
    async def fcw(self, event: AstrMessageEvent):
        """一次性获取三条提示 /fcw"""
        group_id = event.get_group_id()
        sender_id = str(event.get_sender_id())
        is_group = bool(group_id)
        group_id_str = str(group_id) if is_group else None
        user_id = group_id_str if is_group else sender_id

        response = None
        room_lock = self._get_match_lock(user_id)
        async with room_lock:
            response = await fc_handlers.handle_fcw(
                self,
                event,
                user_id=user_id,
                sender_id=sender_id,
                is_group=is_group,
                group_id=group_id_str,
            )

        if response is not None:
            yield response

    # 监听符合fcc的指令,防止误触发
    @filter.regex(r"^fcc\S+$")
    async def fcregex(self, event: AstrMessageEvent):
        if not getattr(event, "is_at_or_wake_command", False):
            return

        # 清理指令
        normalized = normalize_compact_fc_command(event.message_str)
        if not normalized:
            return

        original_message = event.message_str
        event.message_str = normalized
        try:
            async for result in self.fcc(event):
                yield result
        finally:
            event.message_str = original_message

    @filter.event_message_type(EventMessageType.ALL)
    async def other_fcc(self, event: AstrMessageEvent):
        if not getattr(self, "enable_other_message_exact_match", True):
            return

        raw_message = str(event.message_str or "")
        message = re.sub(r"\s+", " ", raw_message.strip())
        if should_skip_plain_answer_message(
            message, is_wake_command=getattr(event, "is_at_or_wake_command", False)
        ):
            return

        group_id_raw = event.get_group_id()
        sender_id = str(event.get_sender_id())
        is_group = bool(group_id_raw)
        group_id = str(group_id_raw) if is_group else None
        user_id = group_id if is_group else sender_id

        if not has_active_game(self.player, user_id):
            return

        player_state = self.player.get(user_id)
        if not isinstance(player_state, dict):
            return

        correct_name = str(player_state.get("name", "") or "")
        if not correct_name or correct_name not in raw_message:
            return

        room_lock = self._get_match_lock(user_id)
        async with room_lock:
            responses, match_end_payload = await fc_handlers.handle_other_fcc(
                self,
                event,
                user_id=user_id,
                sender_id=sender_id,
                is_group=is_group,
                group_id=group_id,
            )

        for r in responses:
            yield r

        if match_end_payload:
            async for result in fc_handlers.iter_match_end_leaderboard(
                self, event, match_end_payload
            ):
                yield result

    # ========== ccl 相关指令 ==========
    # 创建命令组ccl
    @filter.command_group("ccl")
    def ccl(self):
        pass

    # ========== 排行榜相关函数 ==========
    # 获取正确个数的排行榜命令
    @ccl.command("排行榜")
    async def correct_answers_leaderboard(self, event: AstrMessageEvent):
        """获取正确个数的排行榜 /ccl 排行榜"""
        async for r in ccl_leaderboard.handle_correct_answers_leaderboard(self, event):
            yield r

    # 获取错误个数的排行榜命令
    @ccl.command("错误排行榜")
    async def wrong_answers_leaderboard(self, event: AstrMessageEvent):
        """获取错误个数的排行榜 /ccl 错误排行榜"""
        async for r in ccl_leaderboard.handle_wrong_answers_leaderboard(self, event):
            yield r

    # 获取使用提示次数的排行榜命令
    @ccl.command("提示排行榜")
    async def hints_usage_leaderboard(self, event: AstrMessageEvent):
        """获取使用提示次数的排行榜 /ccl 提示排行榜"""
        async for r in ccl_leaderboard.handle_hints_usage_leaderboard(self, event):
            yield r

    # 获取个人信息获取命令
    @ccl.command("名片")
    async def user_profile_retrieval(
        self, event: AstrMessageEvent, user_id: str | None = None
    ):
        """获取个人信息获取 /ccl 名片 [user_id] (如果user_id为空默认为发送人)"""
        async for r in ccl_leaderboard.handle_user_profile_retrieval(
            self, event, user_id=user_id
        ):
            yield r

    # ========== 比赛相关函数 ==========
    # 比赛帮助命令
    @ccl.command("比赛帮助")
    async def match_help(self, event: AstrMessageEvent):
        """比赛模式帮助"""
        async for r in ccl_match.handle_match_help(self, event):
            yield r

    # 创建比赛命令
    @ccl.command("比赛创建")
    async def match_create(
        self,
        event: AstrMessageEvent,
        name: str = "",
        question_limit: int = 0,
        time_limit: int = 0,
    ):
        """创建比赛（仅管理员）用法: /ccl 比赛创建 [名称] [题目限制] [时间限制(分钟)]
        例如: /ccl 比赛创建 春节赛 20 30 表示创建名称为"春节赛"、答完20题自动结束、最多30分钟的比赛
        题目限制填0表示不限制，时间限制填0表示不限制。比赛开始后，参与答题的用户自动成为参赛者"""
        async for r in ccl_match.handle_match_create(
            self,
            event,
            name=name,
            question_limit=question_limit,
            time_limit=time_limit,
        ):
            yield r

    # 比赛游戏循环
    @ccl.command("比赛开始")
    async def match_start(self, event: AstrMessageEvent):
        """使用`/ccl 比赛开始`开始比赛（仅管理员）"""
        ok, group_id, error_resp = await ccl_match.match_start_precheck(self, event)
        if not ok:
            if error_resp is not None:
                yield error_resp
            return

        room_lock = self._get_match_lock(group_id)
        async with room_lock:
            result = await ccl_match.match_start_inlock(self, group_id)

        yield ccl_match.build_match_start_response(event, result)

        # 创建比赛循环任务，用于检查结束条件
        self.match_loop_task[group_id] = asyncio.create_task(
            self._match_game_loop(group_id)
        )

    # 结束比赛命令
    @ccl.command("比赛结束")
    async def match_end(self, event: AstrMessageEvent):
        """使用`/ccl 比赛结束`结束比赛（仅管理员）"""
        ok, group_id, error_resp = await ccl_match.match_end_precheck(self, event)
        if not ok:
            if error_resp is not None:
                yield error_resp
            return

        room_lock = self._get_match_lock(group_id)
        async with room_lock:
            ended, match_name, top_participants = await ccl_match.match_end_inlock(
                self, group_id
            )

        if not ended:
            yield event.plain_result("❌ 当前没有进行中的比赛")
            return

        async for r in ccl_match.iter_match_end_results(
            self, event, match_name, top_participants
        ):
            yield r

    # 比赛排行榜命令
    @ccl.command("比赛排行")
    async def match_leaderboard(self, event: AstrMessageEvent):
        """使用`/ccl 比赛排行`获取比赛排行榜"""
        async for r in ccl_match.handle_match_leaderboard(self, event):
            yield r

    # 清除用户数据命令
    @ccl.command("清除数据")
    async def reset_user_data(self, event: AstrMessageEvent, target_user_id: str = ""):
        """清除用户答题数据（仅管理员）/ccl 清除数据 [user_id]"""
        async for r in ccl_admin.handle_reset_user_data(
            self, event, target_user_id=target_user_id
        ):
            yield r

    # 清除用户荣誉命令
    @ccl.command("清除荣誉")
    async def reset_user_honors_cmd(
        self, event: AstrMessageEvent, target_user_id: str = ""
    ):
        """清除用户荣誉数据（仅管理员）/ccl 清除荣誉 [user_id]"""
        async for r in ccl_admin.handle_reset_user_honors_cmd(
            self, event, target_user_id=target_user_id
        ):
            yield r

    # 清除所有用户数据命令
    @ccl.command("清除所有数据")
    async def reset_all_data_cmd(self, event: AstrMessageEvent):
        """清除所有用户的答题数据（仅管理员）/ccl 清除所有数据"""
        async for r in ccl_admin.handle_reset_all_data_cmd(self, event):
            yield r

    # 清除所有用户荣誉命令
    @ccl.command("清除所有荣誉")
    async def reset_all_honors_cmd(self, event: AstrMessageEvent):
        """清除所有用户的荣誉数据（仅管理员）/ccl 清除所有荣誉"""
        async for r in ccl_admin.handle_reset_all_honors_cmd(self, event):
            yield r

    # 授予用户荣誉命令
    @ccl.command("授予荣誉")
    async def grant_honor_cmd(
        self,
        event: AstrMessageEvent,
        target_user_id: str = "",
        rank: int = 1,
        match_name: str = "",
        correct_count: int = 0,
    ):
        """授予用户特定荣誉（仅管理员）/ccl 授予荣誉 [user_id] [名次] [比赛名称] [答对数量]
        例如: /ccl 授予荣誉 123456 1 测试赛 10"""
        async for r in ccl_admin.handle_grant_honor_cmd(
            self,
            event,
            target_user_id=target_user_id,
            rank=rank,
            match_name=match_name,
            correct_count=correct_count,
        ):
            yield r

    # ========== 工具类相关函数 ==========
    # 发送原始图片
    async def send_original_image(self, user_id: str, event: AstrMessageEvent):
        return await self.game_service.send_original_image(user_id, event)

    def end_game(self, user_id: str) -> None:
        self.game_runtime.end_game(user_id)

    def _get_match_lock(self, room_id: str) -> asyncio.Lock:
        return self.match_runtime.get_room_lock(room_id)

    def _room_has_runtime(self, room_id: str) -> bool:
        return self.match_runtime.room_has_runtime(room_id)

    def _cleanup_stale_room_locks(self, max_idle_hours: int = 24) -> int:
        return self.match_runtime.cleanup_stale_room_locks(max_idle_hours)

    def _clear_match_runtime(self, group_id: str) -> None:
        self.match_runtime.clear_match_runtime(group_id)

    # 获取比赛结束原因
    async def _get_match_end_reason(self, match) -> str | None:
        return await self.match_service.get_match_end_reason(match)

    async def _end_match_and_collect_top(
        self, group_id: str, match
    ) -> tuple[str, int, list]:
        return await self.match_service.end_match_and_collect_top(group_id, match)

    # 生成下一条提示文本并推进提示计数
    def _next_hint_text_and_advance(self, user_id: str) -> tuple[str, bool]:
        """生成下一条提示，并将 fctn +1（不含任何权限/活跃检查）。

        返回:
            (hint_text, has_more)
            has_more=False 表示本题已无更多有效提示（通常为名称已全部揭示）。
        """
        fctn = int(self.player.get(user_id, {}).get("fctn", 0) or 0)
        name = str(self.player.get(user_id, {}).get("name", "") or "")
        has_more = True

        if fctn <= 3:
            key = self.fct_key.get(fctn, "")
            char_data = self.data.get(name, {}) if name else {}

            if key == "职业及分支":
                value = char_data.get(
                    "职业及分支", char_data.get("职业分支", "该干员没有该属性")
                )
            elif fctn == 1:
                star_map = {
                    "1": "一星",
                    "2": "二星",
                    "3": "三星",
                    "4": "四星",
                    "5": "五星",
                    "6": "六星",
                }
                value = star_map.get(
                    str(char_data.get("星级", "")), char_data.get("星级", "")
                )
            elif key == "阵营":
                value = char_data.get(
                    "阵营", char_data.get("所属阵营", "该干员没有该属性")
                )
            else:
                value = char_data.get(key, "该干员没有该属性")

            text = f"这个干员的{key}为:{value}"
        else:
            # 名称提示：每次出现增加 1/3（向上取整）
            if not name:
                text = "无法获取干员名称"
                has_more = False
            else:
                chunk = max(1, (len(name) + 2) // 3)  # ceil(len/3)
                step = max(1, fctn - 3)  # 1,2,3...
                reveal_len = min(len(name), chunk * step)
                text = f"这个干员的前{reveal_len}个字为:{name[:reveal_len]}"
                has_more = reveal_len < len(name)

        # 递增提示计数
        if user_id in self.player:
            self.player[user_id]["fctn"] = fctn + 1

        return text, has_more

    # 为当前题目安排超时自动提示
    def _schedule_match_hint(self, group_id: str) -> None:
        self.match_service.schedule_match_hint(group_id)

    async def _match_hint_after_delay(
        self, group_id: str, session: str, delay: int, token: float
    ) -> None:
        await self.match_service.match_hint_after_delay(group_id, session, delay, token)

    # 加载别名映射
    def _load_aliases(self):
        alias_settings = self.settings.aliases
        self.alias_map = merge_alias_maps(
            parse_aliases(alias_settings.character_aliases),
            parse_aliases_json_text(alias_settings.character_aliases_json),
        )
        self.operator_aliases_by_name = load_operator_aliases(
            alias_settings.operator_aliases_path
        )

    def _build_llm_judge_prompt(self, answer: str, guess: str) -> str:
        return self.llm_judge_service.build_prompt(answer, guess)

    async def judge_answer_with_llm(
        self,
        answer: str,
        guess: str,
        *,
        unified_msg_origin: str | None = None,
    ) -> bool:
        judging_module.Provider = Provider
        judging_module.asyncio = asyncio
        self.llm_judge_service.context = self.context
        return await self.llm_judge_service.judge_answer(
            answer, guess, unified_msg_origin=unified_msg_origin
        )

    async def fc_init(self, user_id: str) -> bytes | str | None:
        return await self.game_service.start_game(user_id)

    async def extract_questions(self) -> Optional[Dict[str, Any]]:
        return self.question_picker.pick()

    async def get_image_from_url(
        self, url: str, timeout: int = 10
    ) -> Optional[Image.Image]:
        media_module.asyncio = asyncio
        self.image_downloader.max_retries = self.image_download_max_retries
        self.image_downloader.retry_interval_seconds = (
            self.image_download_retry_interval_seconds
        )
        return await self.image_downloader.get_image_from_url(url)

    async def _send_match_leaderboard_to_session(
        self,
        session: str,
        match_name: str,
        top_participants: list,
        title: str,
    ) -> None:
        await self.match_service.send_match_leaderboard_to_session(
            session, match_name, top_participants, title
        )

    async def _match_game_loop(self, group_id: str):
        await self.match_service.match_game_loop(group_id)

    # 插件初始化时
    async def initialize(self):
        await self.db.init_db()
        logger.debug(f"[Mrfzccl] 初始化数据库{self.db.db_url}")

    # 插件卸载时的清理钩子
    async def terminate(self):
        self._shutting_down = True
        # 取消比赛相关任务（防止卸载后仍在后台发送消息）
        self.match_runtime.cancel_all_match_tasks()

        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("[Mrfzccl] HTTP session closed")

    # 获取或创建 HTTP 会话
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            connector = aiohttp.TCPConnector(
                limit=10, limit_per_host=5
            )  # 限制连接池大小
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )
            logger.debug("[Mrfzccl] 创建新的HTTP会话")
        return self._session
