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
from .src.rendering import QnAStatsRenderer
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

# 娉ㄥ唽鎻掍欢锛屾寚瀹氭彃浠跺悕銆佷綔鑰呫€佹弿杩板拰鐗堟湰鍙?
@register("mrfzccl", "Lishining", "浣犵煡閬撶殑,鎴戜竴鐩存槸鏄庢棩鏂硅垷楂樻墜", "1.0.0")
class Mrfzccl(Star):
    _question_candidate_names: np.ndarray
    _question_candidate_urls: List[List[str]]
    _question_candidate_low_idx: np.ndarray
    _question_candidate_normal_idx: np.ndarray
    _question_cache_data_id: Optional[int]
    _question_cache_kw_sig: Optional[tuple]
    _question_rng: np.random.Generator
    recent_characters: List[str]

    # 鎻掍欢鍒濆鍖栨柟娉?
    def __init__(self, context: Context, config: AstrBotConfig):
        self.plugin_dir = Path(__file__).resolve().parent
        self.settings = load_settings(config, self.plugin_dir)
        self.game_runtime = GameRuntime()
        self.match_runtime = MatchRuntime(self.game_runtime)
        super().__init__(context, config)  # 璋冪敤鐖剁被鍒濆鍖?
        self.context = context
        self.Config = config  # 淇濆瓨閰嶇疆瀵硅薄
        self.player: Dict[str, Dict[str, Any]] = {}  # 瀛樺偍鐜╁娓告垙鐘舵€?
        self.original_images: Dict[str, Image.Image] = {}  # 淇濆瓨鍘熷鍥剧墖瀵硅薄
        self.is_load = False  # 鏁版嵁鍔犺浇鏍囧織
        self._shutting_down = False  # 娣诲姞鍏抽棴鏍囧織锛岀敤浜庝紭闆呭叧闂?
        self.game_runtime.player = self.player
        self.game_runtime.original_images = self.original_images

        # 鏄惁瀵规帓琛屾绫昏繘琛岀鐞嗗憳闄愬埗
        self.require_admin = self.Config.get("require_admin", True)

        # 鎻愮ず淇℃伅绫诲瀷鏄犲皠瀛楀吀
        self.fct_key = {
            0: "\u804c\u4e1a\u53ca\u5206\u652f",
            1: "\u661f\u7ea7",
            2: "\u9635\u8425",
            3: "\u83b7\u53d6\u65b9\u5f0f",
        }

        # 浠庨厤缃枃浠惰鍙栫浉浼煎害闃堝€?
        self.similarity_threshold = self.Config.get("similarity_threshold", 0.5)
        self.enable_similarity_match = self.Config.get("enable_similarity_match", True)
        # 浠庨厤缃枃浠惰鍙栧瓧绗﹀尮閰嶉槇鍊?
        self.calculate_threshold = self.Config.get("calculate_threshold", 0.5)
        self.enable_character_coverage_match = self.Config.get(
            "enable_character_coverage_match", True
        )
        # 鏄惁鍚敤鍚岄煶瀛楀尮閰?
        self.enable_homophone = self.Config.get("enable_homophone", False)
        # 鏄惁鍚敤骞插憳鍒悕绮剧‘鍒ら
        self.enable_operator_alias_match = self.Config.get(
            "enable_operator_alias_match", True
        )
        self.enable_other_message_exact_match = self.Config.get(
            "enable_other_message_exact_match", True
        )
        # 涓嬭浇 bilibili wiki 鍥剧墖鏃剁殑閲嶈瘯閰嶇疆
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

        # 姣忔棩闄愬埗閰嶇疆
        self.daily_limit = self.Config.get("daily_game_limit", 10)  # 姣忔棩娓告垙娆℃暟闄愬埗
        self.daily_usage: dict = {}  # 璁板綍姣忔棩浣跨敤鎯呭喌
        self.daily_counter: dict = {}  # 璁板綍姣忔棩璁℃暟鍣?

        # 姣旇禌鐘舵€佽拷韪?
        self.match_question_state: dict[
            str, float
        ] = {}  # group_id -> 褰撳墠棰樼洰寮€濮嬫椂闂存埑
        self.match_next_task: dict[
            str, asyncio.Task
        ] = {}  # group_id -> 褰撳墠棰樼洰鐨勮嚜鍔ㄦ彁绀轰换鍔?
        self.match_loop_task: dict[
            str, asyncio.Task
        ] = {}  # group_id -> 姣旇禌缁撴潫妫€娴嬪惊鐜换鍔?
        self.match_sessions: dict[
            str, str
        ] = {}  # group_id -> unified_msg_origin锛堢敤浜庝富鍔ㄦ秷鎭級
        self.match_locks: dict[
            str, asyncio.Lock
        ] = {}  # room_id(group_id/绉佽亰user_id) -> 閿侊紝闃叉骞跺彂瑙﹀彂瀵艰嚧鐘舵€侀敊涔?
        self._room_lock_last_used: dict[
            str, float
        ] = {}  # room_id -> 鏈€杩戜竴娆′娇鐢ㄦ椂闂存埑锛堢敤浜庢竻鐞嗛暱鏈熼棽缃攣锛?
        self.match_runtime.question_state = self.match_question_state
        self.match_runtime.next_task = self.match_next_task
        self.match_runtime.loop_task = self.match_loop_task
        self.match_runtime.sessions = self.match_sessions
        self.match_runtime.locks = self.match_locks
        self.match_runtime.lock_last_used = self._room_lock_last_used

        # 闃查噸澶嶉厤缃?
        self.recent_characters: list = []  # 鏈€杩戝嚭鐜扮殑骞插憳鍒楄〃
        self.max_recent_count = 20  # 鏈€澶ц褰曟暟閲?

        # 鍒悕绯荤粺
        self.alias_map: dict = {}  # 骞插憳鍒悕鏄犲皠
        self.operator_aliases_by_name: dict[str, list[str]] = {}
        self._load_aliases()  # 鍔犺浇鍒悕閰嶇疆

        # 浣庢潈閲嶅共鍛橀厤缃紙鍑虹幇姒傜巼杈冧綆鐨勫共鍛橈級
        self.low_weight_keywords = self.Config.get(
            "low_weight_characters", "棰勫骞插憳,鏈哄笀,W,SideStory"
        ).split(",")
        self.low_weight_ratio = self.Config.get(
            "low_weight_ratio", 0.2
        )  # 浣庢潈閲嶅共鍛樺嚭鐜版鐜?

        # 姣旇禌鐩稿叧閰嶇疆
        self.match_question_limit = self.Config.get(
            "match_question_limit", 0
        )  # 姣旇禌棰樼洰鏁伴噺闄愬埗
        self.match_time_limit = self.Config.get("match_time_limit", 0)  # 姣旇禌鏃堕棿闄愬埗
        self.match_hint_delay = self.Config.get(
            "match_hint_delay", 0
        )  # 姣旇禌瓒呮椂鑷姩鎻愮ず锛堢锛?鍏抽棴锛?
        self.match_answer_grace_period = self.settings.match.answer_grace_period
        self.admin_ids = self.Config.get("admin_ids", [])  # 绠＄悊鍛業D鍒楄〃

        # 璁剧疆榛樿閰嶇疆
        self.target_size = self.Config.get("target_size", 128)  # 鍥剧墖鐩爣灏哄
        self.easy_probability = self.Config.get("easy_probability", 0.6)  # 绠€鍗曢毦搴︽鐜?
        self.medium_probability = self.Config.get(
            "medium_probability", 0.3
        )  # 涓瓑闅惧害姒傜巼
        self.hard_probability = self.Config.get("hard_probability", 0.1)  # 鍥伴毦闅惧害姒傜巼

        # 娣诲姞 HTTP 浼氳瘽绠＄悊
        self._session: Optional[aiohttp.ClientSession] = None
        self._executor = None  # 绾跨▼姹犳墽琛屽櫒

        # 鑾峰彇瀛樺偍鐩綍閰嶇疆
        self.storage_dir = str(StarTools.get_data_dir())
        logger.info(f"[Mrfzccl] 瀛樺偍鐩綍: {self.storage_dir}")

        # 纭繚瀛樺偍鐩綍瀛樺湪
        os.makedirs(self.storage_dir, exist_ok=True)

        # 鏋勫缓鏁版嵁搴撹矾寰?
        self.db_path = os.path.join(self.storage_dir, "mrfzccl.db")
        logger.debug(f"[Mrfzccl] 鏁版嵁搴撶洰褰? {self.db_path}")

        # 鍒濆鍖栨暟鎹簱绠＄悊鍣?
        self.db = DBManager(db_path=self.db_path)
        # 鍒濆鍖栫敤鎴烽棶绛斾粨搴?
        self.user_qna_repo = UserQnARepo(self.db)

        # 鍒濆鍖栨瘮璧涗粨搴?
        self.match_repo = MatchRepo(self.db)  # 姣旇禌浠撳簱

        # 鏋勫缓涓存椂鍥剧墖璺緞
        self.img_tmp_path = Path(get_astrbot_temp_path())
        self.img_tmp_path.mkdir(parents=True, exist_ok=True)

        # 鍒濆鍖栭棶绛旂粺璁℃覆鏌撳櫒
        renderer_theme = self.Config.get("renderer_theme", "light")
        self.renderer = QnAStatsRenderer(
            output_dir=str(self.img_tmp_path), theme=renderer_theme
        )
        logger.info(f"[Mrfzccl] 娓叉煋涓婚: {renderer_theme}")

        # 鏋勫缓鏁版嵁鏂囦欢璺緞
        data_path = self.settings.data_path
        try:
            logger.info(f"[Mrfzccl] ??????: {data_path}")
            if not data_path.exists():
                logger.error(f"[Mrfzccl] ???????: {data_path}")
                return
            with data_path.open("r", encoding="utf-8") as file:
                self.data = json.load(file)
            if not isinstance(self.data, dict):
                logger.error("[Mrfzccl] ????????: ??????")
                return
            self.is_load = True
            logger.info(f"[Mrfzccl] ?????????? {len(self.data)} ???")
        except json.JSONDecodeError as exc:
            logger.error(f"[Mrfzccl] JSON????: {exc}")
            logger.error(traceback.format_exc())
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.error(f"[Mrfzccl] ????????: {exc}")
            logger.error(traceback.format_exc())
        except Exception as exc:
            logger.error(f"[Mrfzccl] ?????????????: {exc}")
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

    # ========== 娓告垙鐩稿叧鎸囦护 ==========
    # 鍒濆鍖栨父鎴忓懡浠?
    @filter.command("fc")
    async def fc(self, event: AstrMessageEvent):
        """寮€濮嬫父鎴?/fc"""
        # 妫€鏌ユ暟鎹槸鍚﹀姞杞芥垚鍔?
        if not self.is_load:
            yield event.chain_result(
                [
                    Comp.At(qq=event.get_sender_id()),  # @鍙戦€佽€?
                    Comp.Plain(" 鎻掍欢鏈姞杞芥垚鍔燂紝璇疯仈绯荤鐞嗗憳閰嶇疆鏁版嵁鏂囦欢"),
                ]
            )
            return

        # 鑾峰彇鐢ㄦ埛ID鍜岀兢缁処D锛堟瘮璧涗粎鍦ㄧ兢鑱婃湁鏁堬級
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

    # 杩涜鐚滄祴鍛戒护
    @filter.command("fcc")
    async def fcc(self, event: AstrMessageEvent):
        """杩涜鐚滈 /fcc [骞插憳鍚嶇О]"""
        # 鑾峰彇缇ょ粍ID
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

    # 寮哄埗缁撴潫娓告垙鍛戒护
    @filter.command("fce")
    async def fce(self, event: AstrMessageEvent):
        """寮虹疆缁撴潫娓告垙 /fce"""
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

    # 鑾峰彇鎻愮ず鍛戒护
    @filter.command("fct")
    async def fct(self, event: AstrMessageEvent):
        """鑾峰彇鎻愮ず /fct"""
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

    # 涓€娆℃€ц幏鍙栦笁鏉℃彁绀哄懡浠?
    @filter.command("fcw")
    async def fcw(self, event: AstrMessageEvent):
        """涓€娆℃€ц幏鍙栦笁鏉℃彁绀?/fcw"""
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

    # 鐩戝惉绗﹀悎fcc鐨勬寚浠?闃叉璇Е鍙?
    @filter.regex(r"^fcc\S+$")
    async def fcregex(self, event: AstrMessageEvent):
        if not getattr(event, "is_at_or_wake_command", False):
            return

        # 娓呯悊鎸囦护
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

    # ========== ccl 鐩稿叧鎸囦护 ==========
    # 鍒涘缓鍛戒护缁刢cl
    @filter.command_group("ccl")
    def ccl(self):
        pass

    # ========== 鎺掕姒滅浉鍏冲嚱鏁?==========
    # 鑾峰彇姝ｇ‘涓暟鐨勬帓琛屾鍛戒护
    @ccl.command("\u6392\u884c\u699c")
    async def correct_answers_leaderboard(self, event: AstrMessageEvent):
        """Command adapter."""
        async for r in ccl_leaderboard.handle_correct_answers_leaderboard(self, event):
            yield r

    # 鑾峰彇閿欒涓暟鐨勬帓琛屾鍛戒护
    @ccl.command("\u9519\u8bef\u6392\u884c\u699c")
    async def wrong_answers_leaderboard(self, event: AstrMessageEvent):
        """Command adapter."""
        async for r in ccl_leaderboard.handle_wrong_answers_leaderboard(self, event):
            yield r

    # 鑾峰彇浣跨敤鎻愮ず娆℃暟鐨勬帓琛屾鍛戒护
    @ccl.command("\u63d0\u793a\u6392\u884c\u699c")
    async def hints_usage_leaderboard(self, event: AstrMessageEvent):
        """Command adapter."""
        async for r in ccl_leaderboard.handle_hints_usage_leaderboard(self, event):
            yield r

    # 鑾峰彇涓汉淇℃伅鑾峰彇鍛戒护
    @ccl.command("\u540d\u7247")
    async def user_profile_retrieval(
        self, event: AstrMessageEvent, user_id: str | None = None
    ):
        """鑾峰彇涓汉淇℃伅鑾峰彇 /ccl 鍚嶇墖 [user_id] (濡傛灉user_id涓虹┖榛樿涓哄彂閫佷汉)"""
        async for r in ccl_leaderboard.handle_user_profile_retrieval(
            self, event, user_id=user_id
        ):
            yield r

    # ========== 姣旇禌鐩稿叧鍑芥暟 ==========
    # 姣旇禌甯姪鍛戒护
    @ccl.command("\u6bd4\u8d5b\u5e2e\u52a9")
    async def match_help(self, event: AstrMessageEvent):
        """姣旇禌妯″紡甯姪"""
        async for r in ccl_match.handle_match_help(self, event):
            yield r

    # 鍒涘缓姣旇禌鍛戒护
    @ccl.command("\u6bd4\u8d5b\u521b\u5efa")
    async def match_create(
        self,
        event: AstrMessageEvent,
        name: str = "",
        question_limit: int = 0,
        time_limit: int = 0,
    ):
        """Command adapter."""
        async for r in ccl_match.handle_match_create(
            self,
            event,
            name=name,
            question_limit=question_limit,
            time_limit=time_limit,
        ):
            yield r

    # 姣旇禌娓告垙寰幆
    @ccl.command("\u6bd4\u8d5b\u5f00\u59cb")
    async def match_start(self, event: AstrMessageEvent):
        """Command adapter."""
        ok, group_id, error_resp = await ccl_match.match_start_precheck(self, event)
        if not ok:
            if error_resp is not None:
                yield error_resp
            return

        room_lock = self._get_match_lock(group_id)
        async with room_lock:
            result = await ccl_match.match_start_inlock(self, group_id)

        yield ccl_match.build_match_start_response(event, result)

        # 鍒涘缓姣旇禌寰幆浠诲姟锛岀敤浜庢鏌ョ粨鏉熸潯浠?
        self.match_loop_task[group_id] = asyncio.create_task(
            self._match_game_loop(group_id)
        )

    # 缁撴潫姣旇禌鍛戒护
    @ccl.command("\u6bd4\u8d5b\u7ed3\u675f")
    async def match_end(self, event: AstrMessageEvent):
        """浣跨敤`/ccl 姣旇禌缁撴潫`缁撴潫姣旇禌锛堜粎绠＄悊鍛橈級"""
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
            yield event.plain_result("鉂?褰撳墠娌℃湁杩涜涓殑姣旇禌")
            return

        async for r in ccl_match.iter_match_end_results(
            self, event, match_name, top_participants
        ):
            yield r

    # 姣旇禌鎺掕姒滃懡浠?
    @ccl.command("\u6bd4\u8d5b\u6392\u884c")
    async def match_leaderboard(self, event: AstrMessageEvent):
        """Command adapter."""
        async for r in ccl_match.handle_match_leaderboard(self, event):
            yield r

    # 娓呴櫎鐢ㄦ埛鏁版嵁鍛戒护
    @ccl.command("\u6e05\u9664\u6570\u636e")
    async def reset_user_data(self, event: AstrMessageEvent, target_user_id: str = ""):
        """娓呴櫎鐢ㄦ埛绛旈鏁版嵁锛堜粎绠＄悊鍛橈級/ccl 娓呴櫎鏁版嵁 [user_id]"""
        async for r in ccl_admin.handle_reset_user_data(
            self, event, target_user_id=target_user_id
        ):
            yield r

    # 娓呴櫎鐢ㄦ埛鑽ｈ獕鍛戒护
    @ccl.command("\u6e05\u9664\u8363\u8a89")
    async def reset_user_honors_cmd(
        self, event: AstrMessageEvent, target_user_id: str = ""
    ):
        """娓呴櫎鐢ㄦ埛鑽ｈ獕鏁版嵁锛堜粎绠＄悊鍛橈級/ccl 娓呴櫎鑽ｈ獕 [user_id]"""
        async for r in ccl_admin.handle_reset_user_honors_cmd(
            self, event, target_user_id=target_user_id
        ):
            yield r

    # 娓呴櫎鎵€鏈夌敤鎴锋暟鎹懡浠?
    @ccl.command("\u6e05\u9664\u6240\u6709\u6570\u636e")
    async def reset_all_data_cmd(self, event: AstrMessageEvent):
        """Command adapter."""
        async for r in ccl_admin.handle_reset_all_data_cmd(self, event):
            yield r

    # 娓呴櫎鎵€鏈夌敤鎴疯崳瑾夊懡浠?
    @ccl.command("\u6e05\u9664\u6240\u6709\u8363\u8a89")
    async def reset_all_honors_cmd(self, event: AstrMessageEvent):
        """Command adapter."""
        async for r in ccl_admin.handle_reset_all_honors_cmd(self, event):
            yield r

    # 鎺堜簣鐢ㄦ埛鑽ｈ獕鍛戒护
    @ccl.command("\u6388\u4e88\u8363\u8a89")
    async def grant_honor_cmd(
        self,
        event: AstrMessageEvent,
        target_user_id: str = "",
        rank: int = 1,
        match_name: str = "",
        correct_count: int = 0,
    ):
        """Command adapter."""
        async for r in ccl_admin.handle_grant_honor_cmd(
            self,
            event,
            target_user_id=target_user_id,
            rank=rank,
            match_name=match_name,
            correct_count=correct_count,
        ):
            yield r

    # ========== 宸ュ叿绫荤浉鍏冲嚱鏁?==========
    # 鍙戦€佸師濮嬪浘鐗?
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

    async def _get_match_end_reason(self, match) -> str | None:
        return await self.match_service.get_match_end_reason(match)

    async def _end_match_and_collect_top(
        self, group_id: str, match
    ) -> tuple[str, int, list]:
        return await self.match_service.end_match_and_collect_top(group_id, match)

    def _next_hint_text_and_advance(self, user_id: str) -> tuple[str, bool]:
        player_state = self.player.get(user_id, {})
        fctn = int(player_state.get("fctn", 0) or 0)
        name = str(player_state.get("name", "") or "")
        has_more = True

        if fctn <= 3:
            key = self.fct_key.get(fctn, "")
            char_data = self.data.get(name, {}) if name else {}
            if key == "职业及分支":
                value = char_data.get(
                    "职业及分支",
                    char_data.get("职业分支", "该干员没有该属性"),
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
            if not name:
                text = "无法获取干员名称"
                has_more = False
            else:
                chunk = max(1, (len(name) + 2) // 3)
                step = max(1, fctn - 3)
                reveal_len = min(len(name), chunk * step)
                text = f"这个干员的前{reveal_len}个字为:{name[:reveal_len]}"
                has_more = reveal_len < len(name)

        if user_id in self.player:
            self.player[user_id]["fctn"] = fctn + 1
        return text, has_more

    def _schedule_match_hint(self, group_id: str) -> None:
        self.match_service.schedule_match_hint(group_id)

    async def _match_hint_after_delay(
        self, group_id: str, session: str, delay: int, token: float
    ) -> None:
        await self.match_service.match_hint_after_delay(group_id, session, delay, token)

    def _load_aliases(self):
        alias_settings = self.settings.aliases
        self.alias_map = merge_alias_maps(
            parse_aliases(alias_settings.character_aliases),
            parse_aliases_json_text(alias_settings.character_aliases_json),
        )
        self.operator_aliases_by_name = load_operator_aliases(
            alias_settings.operator_aliases_path
        )

    # 鍒濆鍖栨父鎴忥紝杩斿洖涓存椂鏂囦欢璺緞
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

    async def initialize(self):
        await self.db.init_db()
        logger.debug(f"[Mrfzccl] 鍒濆鍖栨暟鎹簱{self.db.db_url}")

    # 鎻掍欢鍗歌浇鏃剁殑娓呯悊閽╁瓙
    async def terminate(self):
        self._shutting_down = True
        # 鍙栨秷姣旇禌鐩稿叧浠诲姟锛堥槻姝㈠嵏杞藉悗浠嶅湪鍚庡彴鍙戦€佹秷鎭級
        self.match_runtime.cancel_all_match_tasks()

        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("[Mrfzccl] HTTP session closed")

    # 鑾峰彇鎴栧垱寤?HTTP 浼氳瘽
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            connector = aiohttp.TCPConnector(
                limit=10, limit_per_host=5
            )  # 闄愬埗杩炴帴姹犲ぇ灏?
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )
            logger.debug("[Mrfzccl] 鍒涘缓鏂扮殑HTTP浼氳瘽")
        return self._session
