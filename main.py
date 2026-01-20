from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from typing import Optional, Dict, Any, Tuple, List
import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
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

    # 插件卸载时的清理钩子
    async def terminate(self):
        self._shutting_down = True
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("[Mrfzccl] HTTP会话已关闭")

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
        else:
            chain = [
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain("回答错误!")
            ]
            yield event.chain_result(chain)

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
                yield event.chain_result([
                    Comp.Plain("正确答案的完整立绘:"),
                    Comp.Image.fromBytes(img_bytes)
                ])
            except Exception as e:
                logger.error(f"[send_original_image] 发送原始图片失败: {e}")
                yield event.plain_result("发送正确答案图片失败")
            finally:
                self.end_game(user_id)
        else:
            logger.warning(f"[send_original_image] 用户 {user_id} 没有原始图片")
            yield event.plain_result("无法获取正确答案图片")

    # 显示帮助
    @filter.command("fch")
    async def fch(self, event: AstrMessageEvent):
        """获取帮助文档 /fch"""
        help_text = """fc 插件使用说明
            1. 开始游戏
            命令：/fc
            说明：生成遮挡图片并发出
            2. 猜角色
            命令：/fcc [角色名称]
            说明：进行角色猜测
            3. 强制结束游戏
            命令：/fce
            说明：结束当前进行的游戏并显示原图
            3. 提示功能
            命令：/fct
            说明：获取提示
            """
        yield event.plain_result(help_text)

    # 结束游戏并清理资源
    def end_game(self, user_id: str) -> None:
        self.player.pop(user_id, None)

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
            image = await self.get_image_from_url(question["url"])
            if not image:
                logger.error(f"[fc_init] 获取图片失败")
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

    def pil_image_to_bytes(self, image: Image.Image, format: str = "PNG") -> bytes:
        buf = BytesIO()
        image.save(buf, format=format, optimize=True)
        return buf.getvalue()
