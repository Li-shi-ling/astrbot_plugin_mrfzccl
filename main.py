from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from typing import Optional, Dict, Any, Tuple, List
from .src.QnAStatsRenderer import QnAStatsRenderer
import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import StarTools
from .src.db.database import DBManager
from .src.db.repo import UserQnARepo
from difflib import SequenceMatcher
from urllib.parse import urlparse
from io import BytesIO
from PIL import Image
import numpy as np
import traceback
import asyncio
import aiohttp
import random
import json
import time
import os
import re

@register("mrfzccl", "Lishining", "你知道的,我一直是明日方舟高手", "1.0.0")
class Mrfzccl(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.Config = config
        self.player: Dict[str, Dict[str, Any]] = {}
        self.original_images: Dict[str, Image.Image] = {}  # 保存原始图片对象
        self.is_load = False
        self._shutting_down = False  # 添加关闭标志
        self.fct_key = {
            0 : "职业分支",
            1 : "阵营",
            2 : "性别",
        }

        # 添加 HTTP 会话管理
        self._session: Optional[aiohttp.ClientSession] = None
        self._executor = None  # 线程池执行器

        self.db_path = self.Config.get("db_path", None)
        if self.db_path is None:
            self.db_path = str(StarTools.get_data_dir())
        self.db = DBManager(db_path = self.db_path)
        self.user_qna_repo = UserQnARepo(self.db)

        self.img_tmp_path = StarTools.get_data_dir() / "tmp"
        self.renderer = QnAStatsRenderer(
            output_dir = str(self.img_tmp_path)
        )

        # 设置默认配置
        self.target_size = self.Config.get("target_size", 128)
        data_path = self.Config.get("mrfz_data_path", "")
        if not data_path:
            logger.error("[Mrfzccl] 未配置数据文件路径")
            return
        try:
            abs_data_path = self._get_absolute_path(data_path)
            logger.info(f"[Mrfzccl] 尝试加载数据文件: {abs_data_path}")
            if not os.path.exists(abs_data_path):
                logger.error(f"[Mrfzccl] 数据文件不存在: {abs_data_path}")
                return
            with open(abs_data_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            if not isinstance(self.data, dict):
                logger.error("[Mrfzccl] 数据文件格式错误: 应为字典类型")
                return
            self.is_load = True
            logger.info(f"[Mrfzccl] 数据加载成功，共加载 {len(self.data)} 个角色")
        except json.JSONDecodeError as e:
            logger.error(f"[Mrfzccl] JSON解析错误: {e}")
        except FileNotFoundError as e:
            logger.error(f"[Mrfzccl] 文件未找到: {e}")
        except PermissionError as e:
            logger.error(f"[Mrfzccl] 权限错误: {e}")
        except Exception as e:
            logger.error(f"[Mrfzccl] 加载数据文件时发生未知错误: {e}")
            logger.error(traceback.format_exc())

        self.cleanup_task: asyncio.Task | None = None
        self.cleanup_running = True

    # 初始化游戏
    @filter.command("fc")
    async def fc(self, event: AstrMessageEvent):
        """开始游戏 /fc"""
        if not self.is_load:
            yield event.chain_result([
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain("插件未加载成功，请联系管理员配置数据文件")
            ])
            return
        user_id = str(event.get_group_id() or event.get_sender_id())
        try:
            result = await self.fc_init(user_id)
            if result == "already_exists":
                yield event.plain_result("已经初始化,请不要重复操作")
            elif result is None:
                yield event.plain_result("图片获取失败,请重试")
            else:
                yield event.chain_result([
                    Comp.Plain("干员立绘,请使用/fcc [干员名称] 进行猜测"),
                    Comp.Image.fromBytes(result)
                ])
        except Exception as e:
            logger.error(f"[fc] 命令执行失败: {e}")
            logger.error(traceback.format_exc())
            yield event.plain_result("游戏初始化失败，请稍后重试")

    # 进行猜测
    @filter.command("fcc")
    async def fcc(self, event: AstrMessageEvent):
        """进行猜题 /fcc [干员名称]"""
        user_id = str(event.get_group_id() or event.get_sender_id())
        if not self.has_active_game(user_id):
            yield event.plain_result("没有初始化房间,请使用/fc")
            return
        guess_text = self.extract_and_sanitize_input(event.message_str, "fcc")
        if not guess_text:
            yield event.chain_result([
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain("请输入要猜测的干员名称")
            ])
            return
        correct_name = self.player[user_id]["name"]
        similarity = SequenceMatcher(None, correct_name, guess_text).ratio()
        threshold = 0.5
        if similarity > threshold:
            chain = [
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain(f"回答正确! 答案为: {correct_name}")
            ]
            yield event.chain_result(chain)
            yield await self.send_original_image(user_id, event)
            await self.user_qna_repo.increment_correct_count(
                user_id = event.get_sender_id(),
                user_name = event.get_sender_name()
            )
        else:
            chain = [
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain("回答错误!")
            ]
            yield event.chain_result(chain)
            await self.user_qna_repo.increment_wrong_count(
                user_id = event.get_sender_id(),
                user_name = event.get_sender_name()
            )

    # 强制结束游戏
    @filter.command("fce")
    async def fce(self, event: AstrMessageEvent):
        """强置结束游戏 /fce"""
        user_id = str(event.get_group_id() or event.get_sender_id())
        if not self.has_active_game(user_id):
            yield event.plain_result("没有初始化房间,请使用/fc")
            return
        answer = self.player[user_id]["name"]
        chain = [
            Comp.At(qq=event.get_sender_id()),
            Comp.Plain(f"游戏已结束,答案为: {answer}")
        ]
        yield event.chain_result(chain)
        yield await self.send_original_image(user_id, event)

    # 获取提示
    @filter.command("fct")
    async def fct(self, event: AstrMessageEvent):
        """获取提示 /fct"""
        user_id = str(event.get_group_id() or event.get_sender_id())
        if not self.has_active_game(user_id):
            yield event.plain_result("没有初始化房间,请使用/fc")
            return
        if self.player[user_id]["fctn"] <= 2:
            yield event.plain_result(
                f"这个干员的{self.fct_key[self.player[user_id]['fctn']]}为:{self.data.get(self.player[user_id]['name'],{}).get(self.fct_key[self.player[user_id]['fctn']],'该干员没有该属性')}"
            )
        else:
            name_len = self.player[user_id]["fctn"] - 2
            yield event.plain_result(f"这个干员的前{name_len}个字为:{self.player[user_id]['name'][:name_len]}")
        self.player[user_id]["fctn"] += 1
        await self.user_qna_repo.increment_tip_count(
            user_id=event.get_sender_id(),
            user_name=event.get_sender_name()
        )

    # 获取正确个数的排行榜
    @filter.command("cal")
    async def correct_answers_leaderboard(self, event: AstrMessageEvent):
        """获取正确个数的排行榜 /fc cal"""
        try:
            # 获取排行榜数据（前10名）
            users = await self.user_qna_repo.get_correct_answers_leaderboard(limit=10)

            if not users:
                yield event.plain_result("📊 当前还没有用户的答题记录哦~")
                return

            # 获取统计信息
            summary = await self.user_qna_repo.get_leaderboard_summary()

            # 使用统一的图片/文本生成函数
            async for result in self._generate_image_or_fallback(
                    event=event,
                    generate_image_func=lambda: self.renderer.generate_correct_leaderboard_image(users),
                    generate_text_func=lambda: self._generate_correct_leaderboard_text(users, summary),
            ):
                yield result

        except Exception as e:
            yield event.plain_result(f"获取排行榜时出现错误: {str(e)}")

    # 获取错误个数的排行榜
    @filter.command("wal")
    async def wrong_answers_leaderboard(self, event: AstrMessageEvent):
        """获取错误个数的排行榜 /fc wal"""
        try:
            # 获取排行榜数据（前10名）
            users = await self.user_qna_repo.get_wrong_answers_leaderboard(limit=10)

            if not users:
                yield event.plain_result("📊 当前还没有用户的答题记录哦~")
                return

            # 使用统一的图片/文本生成函数
            async for result in self._generate_image_or_fallback(
                    event=event,
                    generate_image_func=lambda: self.renderer.generate_wrong_leaderboard_image(users),
                    generate_text_func=lambda: self._generate_wrong_leaderboard_text(users),
            ):
                yield result

        except Exception as e:
            yield event.plain_result(f"获取排行榜时出现错误: {str(e)}")

    # 获取使用提示次数的排行榜
    @filter.command("hul")
    async def hints_usage_leaderboard(self, event: AstrMessageEvent):
        """获取使用提示次数的排行榜 /fc hul"""
        try:
            # 获取排行榜数据（前10名）
            users = await self.user_qna_repo.get_hints_usage_leaderboard(limit=10)

            if not users:
                yield event.plain_result("📊 当前还没有用户的答题记录哦~")
                return

            # 使用统一的图片/文本生成函数
            async for result in self._generate_image_or_fallback(
                    event=event,
                    generate_image_func=lambda: self.renderer.generate_hints_leaderboard_image(users),
                    generate_text_func=lambda: self._generate_hints_leaderboard_text(users),
            ):
                yield result

        except Exception as e:
            yield event.plain_result(f"获取排行榜时出现错误: {str(e)}")

    # 获取个人信息获取
    @filter.command("upr")
    async def user_profile_retrieval(self, event: AstrMessageEvent, user_id: str | None = None):
        """获取个人信息获取 /fc upr [user_id] (如果user_id为空默认为发送人)"""
        try:
            # 确定用户ID
            target_user_id = user_id or event.get_sender_id()

            # 获取用户信息及排名
            user_stats, rank_info = await self.user_qna_repo.get_user_profile_with_rank(target_user_id)

            if not user_stats:
                yield event.plain_result("❌ 未找到该用户的答题记录")
                return

            # 使用统一的图片/文本生成函数
            async for result in self._generate_image_or_fallback(
                    event=event,
                    generate_image_func=lambda: self.renderer.generate_user_profile_image(user_stats, rank_info),
                    generate_text_func=lambda: self._generate_user_profile_text(user_stats, rank_info),
            ):
                yield result

        except Exception as e:
            yield event.plain_result(f"获取用户信息时出现错误: {str(e)}")

    # ========== 排行榜相关函数 ==========
    # 生成正确量排行榜文本
    def _generate_correct_leaderboard_text(self, users, summary=None):
        """生成正确量排行榜文本"""
        if not users:
            return "📊 当前还没有用户的答题记录哦~"

        message = "🏆 **正确量排行榜** 🏆\n\n"

        for i, user in enumerate(users, 1):
            if i == 1:
                medal = "🥇"
            elif i == 2:
                medal = "🥈"
            elif i == 3:
                medal = "🥉"
            else:
                medal = f"{i}."

            # 计算准确率
            total_answers = user.correct_count + user.wrong_count
            accuracy = (user.correct_count / total_answers * 100) if total_answers > 0 else 0

            message += f"{medal} {user.user_name}\n"
            message += f"   ✅ 正确: {user.correct_count} | ❌ 错误: {user.wrong_count} | 💡 提示: {user.tip_count}\n"
            message += f"   📈 准确率: {accuracy:.1f}% | 📅 最后更新: {user.updated_at.strftime('%Y-%m-%d')}\n\n"

        # 添加统计信息（如果提供了summary）
        if summary:
            message += f"📊 **统计信息**\n"
            message += f"总用户数: {summary['total_users']} | 总答题数: {summary['total_questions']}\n"
            message += f"总正确数: {summary['total_correct']} | 总错误数: {summary['total_wrong']}\n"
            message += f"平均正确数: {summary['avg_correct']:.1f}"

        return message

    # 生成错误个数排行榜文本
    def _generate_wrong_leaderboard_text(self, users):
        """生成错误个数排行榜文本"""
        if not users:
            return "📊 当前还没有用户的答题记录哦~"

        message = "💥 **错误个数排行榜** 💥\n\n"

        for i, user in enumerate(users, 1):
            medal = ""
            if i == 1:
                medal = "💣"  # 炸弹表示错误最多
            elif i == 2:
                medal = "🧨"
            elif i == 3:
                medal = "🎆"
            else:
                medal = f"{i}."

            # 计算错误率
            total_answers = user.correct_count + user.wrong_count
            error_rate = (user.wrong_count / total_answers * 100) if total_answers > 0 else 0

            message += f"{medal} {user.user_name}\n"
            message += f"   ❌ 错误: {user.wrong_count} | ✅ 正确: {user.correct_count} | 💡 提示: {user.tip_count}\n"
            message += f"   📉 错误率: {error_rate:.1f}% | 📅 最后更新: {user.updated_at.strftime('%Y-%m-%d')}\n\n"

        return message

    # 生成提示次数排行榜文本
    def _generate_hints_leaderboard_text(self, users):
        """生成提示次数排行榜文本"""
        if not users:
            return "📊 当前还没有用户的答题记录哦~"

        message = "💡 **提示次数排行榜** 💡\n\n"

        for i, user in enumerate(users, 1):
            medal = ""
            if i == 1:
                medal = "🎯"  # 靶心表示最依赖提示
            elif i == 2:
                medal = "🔍"
            elif i == 3:
                medal = "🧩"
            else:
                medal = f"{i}."

            # 计算提示频率（每道题平均提示次数）
            total_answers = user.correct_count + user.wrong_count
            tips_per_question = (user.tip_count / total_answers) if total_answers > 0 else 0

            message += f"{medal} {user.user_name}\n"
            message += f"   💡 提示: {user.tip_count} | ✅ 正确: {user.correct_count} | ❌ 错误: {user.wrong_count}\n"
            message += f"   📊 提示频率: {tips_per_question:.2f}/题 | 📅 最后更新: {user.updated_at.strftime('%Y-%m-%d')}\n\n"

        return message

    # 生成用户个人信息文本
    def _generate_user_profile_text(self, user_stats, rank_info):
        """生成用户个人信息文本"""
        if not user_stats:
            return "❌ 未找到该用户的答题记录"

        # 构建个人信息消息
        message = f"👤 **用户信息 - {user_stats.user_name}**\n\n"

        # 基础统计
        total_answers = user_stats.correct_count + user_stats.wrong_count
        accuracy = (user_stats.correct_count / total_answers * 100) if total_answers > 0 else 0

        message += f"📊 **基础统计**\n"
        message += f"✅ 正确: {user_stats.correct_count}\n"
        message += f"❌ 错误: {user_stats.wrong_count}\n"
        message += f"💡 提示: {user_stats.tip_count}\n"
        message += f"🎯 准确率: {accuracy:.1f}%\n"
        message += f"📝 总答题数: {total_answers}\n\n"

        # 排名信息
        if rank_info:
            message += f"🏆 **排名信息** (共{rank_info.get('total_users', '?')}人)\n"
            message += f"✅ 正确排名: 第{rank_info.get('correct_rank', '?')}名\n"
            message += f"❌ 错误排名: 第{rank_info.get('wrong_rank', '?')}名\n"
            message += f"💡 提示排名: 第{rank_info.get('tip_rank', '?')}名\n\n"

        # 时间信息
        message += f"📅 **时间信息**\n"
        message += f"⏰ 注册时间: {user_stats.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        message += f"🔄 最后更新: {user_stats.updated_at.strftime('%Y-%m-%d %H:%M')}\n"

        return message

    # 统一的图片生成和回退处理
    async def _generate_image_or_fallback(self, event, generate_image_func, generate_text_func, *args, **kwargs):
        """统一的图片生成和回退处理"""
        try:
            # 尝试生成图片
            image_path = await generate_image_func(*args, **kwargs)

            # 检查图片是否存在
            if os.path.exists(image_path):
                yield event.chain_result([Comp.Image.fromFileSystem(image_path)])
                return

            # 图片不存在，使用文本模式
            text_message = generate_text_func(*args, **kwargs)
            yield event.plain_result(f"图片生成失败，使用文本模式显示\n\n{text_message}")

        except Exception as render_error:
            # 生成图片出错，使用文本模式
            text_message = generate_text_func(*args, **kwargs)
            yield event.plain_result(f"图片生成失败，使用文本模式显示\n错误: {str(render_error)}\n\n{text_message}")

    # 发送原始图片
    async def send_original_image(self, user_id: str, event: AstrMessageEvent):
        if user_id in self.original_images:
            try:
                original_image = self.original_images[user_id]
                loop = asyncio.get_running_loop()
                resized_original = await loop.run_in_executor(
                    None,
                    self.resize_to_target,
                    original_image,
                    self.target_size
                )
                img_bytes = self.pil_image_to_bytes(resized_original)
                output_data = event.chain_result([
                    Comp.Plain("正确答案的完整立绘:"),
                    Comp.Image.fromBytes(img_bytes)
                ])
                self.end_game(user_id)
                return output_data
            except Exception as e:
                logger.error(f"[send_original_image] 发送原始图片失败: {e}")
                self.end_game(user_id)
                return event.plain_result("发送正确答案图片失败")
        else:
            logger.warning(f"[send_original_image] 用户 {user_id} 没有原始图片")
            return event.plain_result("无法获取正确答案图片")

    # 结束游戏并清理资源
    def end_game(self, user_id: str) -> None:
        self.player.pop(user_id, None)
        self.original_images.pop(user_id, None)

    # 检查用户是否有活跃游戏
    def has_active_game(self, user_id: str) -> bool:
        data = self.player.get(user_id)
        return bool(data and data.get("status") == "active")

    # 初始化游戏，返回临时文件路径
    async def fc_init(self, user_id: str) -> bytes | str | None:
        if self.has_active_game(user_id):
            return "already_exists"
        self.player[user_id] = {"status": "loading"}
        try:
            question = await self.extract_questions()
            if not question:
                logger.error(f"[fc_init] 提取题目失败")
                self.player.pop(user_id, None)
                return None
            try:
                image = await self.get_image_from_url(question["url"])
                if not image:
                    logger.error(f"[fc_init] 获取图片失败")
                    self.player.pop(user_id, None)
                    return None
            except Exception as e:
                logger.error(f"[fc_init] 获取图片失败,e:{e}")
                self.player.pop(user_id, None)
                return None

            self.original_images[user_id] = image.copy()
            question["status"] = "active"
            self.player[user_id] = question
            loop = asyncio.get_running_loop()
            result, _ = await loop.run_in_executor(
                None,
                self.mask_image_with_random_blocks,
                image,
                5
            )
            resized = await loop.run_in_executor(
                None,
                self.resize_to_target,
                result,
                self.target_size
            )
            img_bytes = self.pil_image_to_bytes(resized)
            return img_bytes
        except Exception as e:
            logger.error(f"[fc_init] 初始化失败: {e}")
            logger.error(traceback.format_exc())
            if user_id in self.player:
                self.player.pop(user_id, None)
            return None

    # 获取明日方舟猜猜乐题目
    async def extract_questions(self) -> Optional[Dict[str, Any]]:
        try:
            if not self.data:
                logger.error("[extract_questions] 数据未加载")
                return None
            names = list(self.data.keys())
            if not names:
                logger.error("[extract_questions] 数据为空")
                return None
            random_name = random.choice(names)
            character_data = self.data[random_name]
            if not isinstance(character_data, dict):
                logger.error(f"[extract_questions] 角色数据格式错误: {random_name}")
                return None
            urls = character_data.get("original_url", [])
            if not urls or not isinstance(urls, list):
                logger.error(f"[extract_questions] 角色URL数据错误: {random_name}")
                return None
            random_url = random.choice(urls)
            if not isinstance(random_url, str) or not random_url.startswith(("http://", "https://")):
                logger.error(f"[extract_questions] 无效的URL: {random_url}")
                return None
            return {
                "name": random_name,
                "url": random_url,
                "fctn": 0
            }
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"[extract_questions] 提取题目失败: {e}")
            return None
        except Exception as e:
            logger.error(f"[extract_questions] 提取题目时发生未知错误: {e}")
            logger.error(traceback.format_exc())
            return None

    # 路径处理
    def _get_absolute_path(self, path: str) -> str:
        if not path:
            raise ValueError("路径不能为空")
        return os.path.abspath(path)

    # 从URL异步获取图片
    async def get_image_from_url(self, url: str, timeout: int = 10) -> Optional[Image.Image]:
        try:
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"无效的URL协议: {url}")
            parsed_url = urlparse(url)
            hostname = parsed_url.hostname
            if hostname:
                if hostname.startswith(('10.', '172.16.', '192.168.', '127.', '169.254.', '::1', 'localhost')):
                    raise ValueError(f"禁止访问内网地址: {hostname}")
            session = await self._get_session()
            async with session.get(
                    url,
                    ssl=False
            ) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}: {response.reason}")
                content = await response.read()
                if len(content) == 0:
                    raise Exception("下载的图片数据为空")
                if len(content) > 10 * 1024 * 1024:
                    raise Exception("图片文件过大")
                loop = asyncio.get_running_loop()
                image = await loop.run_in_executor(
                    None,
                    self._load_image_from_bytes,
                    content
                )
                return image
        except (aiohttp.ClientError, ValueError) as e:
            logger.error(f"[get_image_from_url] 请求失败: {e}")
            raise
        except Exception as e:
            logger.error(f"[get_image_from_url] 处理图片时出错: {e}")
            raise

    # 同步加载图片（在线程池中执行）
    def _load_image_from_bytes(self, content: bytes) -> Image.Image:
        image = Image.open(BytesIO(content))
        if image.format not in ['JPEG', 'PNG', 'GIF', 'WEBP', 'BMP']:
            raise Exception(f"不支持的图片格式: {image.format}")
        image.load()
        width, height = image.size
        if width > 5000 or height > 5000:
            raise Exception(f"图片尺寸过大: {width}x{height}")
        return image

    # 提取并清理用户输入
    def extract_and_sanitize_input(self, text: str, keyword: str) -> str:
        if not text or not keyword:
            return ""
        pattern = rf'{re.escape(keyword)}\s*(.*)'
        match = re.search(pattern, text)
        if not match:
            return ""
        user_input = match.group(1).strip()
        cleaned = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', '', user_input)
        if len(cleaned) > 50:
            cleaned = cleaned[:50]
        return cleaned

    # 遮挡图生成
    def mask_image_with_random_blocks(
            self,
            image: Image.Image,
            block_count: int = 5,
            mask_color: Tuple[int, int, int] = (0, 0, 0),
            min_width_percent: int = 10,
            max_width_percent: int = 20,
            min_height_percent: int = 10,
            max_height_percent: int = 20,
            min_gap_percent: int = 2,
            avoid_edges: bool = True
    ) -> Tuple[Image.Image, List[Tuple[int, int, int, int]]]:
        """
        高性能遮罩图片，只露出几个小方块，保持原始游戏逻辑
        """
        if image.mode != 'RGBA':
            original_rgba = image.convert('RGBA')
        else:
            original_rgba = image.copy()

        width, height = original_rgba.size
        arr = np.array(original_rgba)

        # 创建遮罩层，填充 mask_color 并全覆盖
        mask_layer = np.zeros_like(arr)
        mask_layer[..., 0] = mask_color[0]
        mask_layer[..., 1] = mask_color[1]
        mask_layer[..., 2] = mask_color[2]
        mask_layer[..., 3] = 255  # 全不透明

        min_width = max(5, int(width * min_width_percent / 100))
        max_width = max(min_width, int(width * max_width_percent / 100))
        min_height = max(5, int(height * min_height_percent / 100))
        max_height = max(min_height, int(height * max_height_percent / 100))
        min_gap = int(min(width, height) * min_gap_percent / 100)
        edge_margin = min_gap if avoid_edges else 0

        blocks = []

        for _ in range(block_count):
            for attempt in range(100):
                w = random.randint(min_width, max_width)
                h = random.randint(min_height, max_height)
                max_x = width - w - edge_margin
                max_y = height - h - edge_margin
                if max_x <= edge_margin or max_y <= edge_margin:
                    break
                x1 = random.randint(edge_margin, max_x)
                y1 = random.randint(edge_margin, max_y)
                x2, y2 = x1 + w, y1 + h

                # 检查是否冲突
                conflict = False
                for bx1, by1, bx2, by2 in blocks:
                    if not (x2 + min_gap < bx1 or x1 > bx2 + min_gap or
                            y2 + min_gap < by1 or y1 > by2 + min_gap):
                        conflict = True
                        break

                if not conflict:
                    blocks.append((x1, y1, x2, y2))
                    mask_layer[y1:y2, x1:x2, 3] = 0  # 方块区域透明
                    break

        # alpha 合成：遮罩层覆盖原图
        alpha = mask_layer[..., 3:4] / 255.0
        result_arr = arr * (1 - alpha) + mask_layer * alpha
        result_arr = result_arr.astype(np.uint8)
        result = Image.fromarray(result_arr, 'RGBA')
        return result, blocks

    # 按比例缩放图像，保持宽高比
    def resize_to_target(self, image: Image.Image, target_size: int) -> Image.Image:
        if target_size <= 0:
            target_size = 800
        w, h = image.size
        if w >= h:
            new_w = target_size
            new_h = int(target_size * h / w)
        else:
            new_h = target_size
            new_w = int(target_size * w / h)
        new_w = max(new_w, 100)
        new_h = max(new_h, 100)
        return image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # pil图片转变为bytes
    def pil_image_to_bytes(self, image: Image.Image, format: str = "PNG") -> bytes:
        buf = BytesIO()
        image.save(buf, format=format, optimize=True)
        return buf.getvalue()

    # 插件初始化时
    async def initialize(self):
        await self.start_cleanup_task()

    # 插件卸载时的清理钩子
    async def terminate(self):
        self._shutting_down = True
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("[Mrfzccl] HTTP会话已关闭")
        await self.stop_cleanup_task()

    # 开启定时清理任务
    async def start_cleanup_task(self, interval_hours=1):
        """启动定时清理任务"""
        self.cleanup_running = True
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup(interval_hours))
        return self.cleanup_task

    # 关闭定时清理任务
    async def stop_cleanup_task(self):
        """停止定时清理任务（带超时保护）"""
        self.cleanup_running = False

        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                # 最多等 2 秒让任务自己退出
                await asyncio.wait_for(self.cleanup_task, timeout=2)
            except asyncio.TimeoutError:
                logger.warning("[Mrfzccl] 清理任务取消超时，强制退出")
            except asyncio.CancelledError:
                # 正常情况
                pass
            finally:
                self.cleanup_task = None

    # 定时清理任务
    async def _periodic_cleanup(self, interval_hours=1):
        """可控制的定期清理"""
        while self.cleanup_running:
            try:
                # 等待指定时间
                await asyncio.sleep(interval_hours * 3600)

                # 检查是否还在运行
                if not self.cleanup_running:
                    break

                # 执行清理
                await self._cleanup_old_images()

            except asyncio.CancelledError:
                # 任务被取消
                break
            except Exception as e:
                # 记录错误但不停止任务
                logger.error(f"[Mrfzccl] 清理任务出错: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟再重试

    # 清理超过指定时间的图片
    async def _cleanup_old_images(self, max_age_hours=1):
        """清理超过指定时间的图片"""
        cutoff_time = time.time() - max_age_hours * 3600

        try:
            for file_path in self.img_tmp_path.glob("*.png"):
                if os.path.getmtime(file_path) < cutoff_time:
                    try:
                        os.remove(file_path)
                        logger.info(f"🧹 清理旧图片: {file_path}")
                    except:
                        pass
        except Exception as e:
            logger.error(f"清理图片时出错: {e}")

    # 获取或创建 HTTP 会话
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)  # 限制连接池大小
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            logger.debug("[Mrfzccl] 创建新的HTTP会话")
        return self._session
