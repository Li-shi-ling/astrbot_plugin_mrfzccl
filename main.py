from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register
from typing import Optional, Dict, Any, Tuple, List
import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from difflib import SequenceMatcher
from urllib.parse import urlparse
from io import BytesIO
from PIL import Image
import traceback
import tempfile
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
        self.temp_files: Dict[str, str] = {}  # user_id -> temp_file_path (遮罩图)
        self.original_images: Dict[str, Image.Image] = {}  # 新增：保存原始图片对象
        self.is_load = False
        self._shutting_down = False  # 添加关闭标志

        # 存放临时文件的数据文件夹
        self.data_dir = str(StarTools.get_data_dir())
        # 临时文件目录
        self.temp_path = os.path.join(self.data_dir, "temp")

        # 确保临时目录存在
        try:
            os.makedirs(self.temp_path, exist_ok=True)
            logger.info(f"[Mrfzccl] 临时文件目录: {self.temp_path}")
        except OSError as e:
            logger.error(f"[Mrfzccl] 创建临时目录失败: {e}")
            self.temp_path = tempfile.gettempdir()  # 回退到系统临时目录

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

    async def on_unload(self):
        """插件卸载时的清理钩子"""
        self._shutting_down = True
        await self.cleanup_all_temp_files()

    @filter.command("fc")
    async def fc(self, event: AstrMessageEvent):
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
                # 使用 fromFileSystem 方法发送图片
                yield event.chain_result([
                    Comp.Plain("干员立绘,请使用/fcc [干员名称] 进行猜测"),
                    Comp.Image.fromFileSystem(result)
                ])
        except Exception as e:
            logger.error(f"[fc] 命令执行失败: {e}")
            logger.error(traceback.format_exc())
            yield event.plain_result("游戏初始化失败，请稍后重试")

    @filter.command("fcc")
    async def fcc(self, event: AstrMessageEvent):
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
            # 发送原始图片
            yield event.chain_result(chain)
            yield await self.send_original_image(user_id, event)
        else:
            chain = [
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain("回答错误!")
            ]
            yield event.chain_result(chain)

    @filter.command("fce")
    async def fce(self, event: AstrMessageEvent):
        """强制结束游戏"""
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
        # 发送原始图片
        yield await self.send_original_image(user_id, event)

    async def send_original_image(self, user_id: str, event: AstrMessageEvent):
        """发送原始图片"""
        if user_id in self.original_images:
            try:
                # 调整原始图片大小
                original_image = self.original_images[user_id]
                resized_original = self.resize_to_target(original_image, self.target_size)

                # 保存原始图片到临时文件
                original_temp_path = await self.save_original_image_to_temp(resized_original, user_id)

                # 发送原始图片
                return event.chain_result([
                    Comp.Plain("正确答案的完整立绘:"),
                    Comp.Image.fromFileSystem(original_temp_path)
                ])
            except Exception as e:
                logger.error(f"[send_original_image] 发送原始图片失败: {e}")
                return event.plain_result("发送正确答案图片失败")
            # 无论是否发送成功，都要结束游戏
            finally:
                self.end_game(user_id)
        else:
            logger.warning(f"[send_original_image] 用户 {user_id} 没有原始图片")
            return event.plain_result("无法获取正确答案图片")

    @filter.command("fch")
    async def fch(self, event: AstrMessageEvent):
        """显示帮助"""
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
            """
        yield event.plain_result(help_text)

    # 游戏管理方法
    def end_game(self, user_id: str) -> None:
        """结束游戏并清理资源"""
        # 异步清理临时文件
        asyncio.create_task(self.cleanup_user_temp_files(user_id))
        # 清理原始图片
        asyncio.create_task(self.cleanup_original_image(user_id))
        # 定期清理旧文件
        asyncio.create_task(self.periodic_cleanup_old_files())
        # 移除游戏状态
        self.player.pop(user_id, None)

    def has_active_game(self, user_id: str) -> bool:
        """检查用户是否有活跃游戏"""
        return user_id in self.player and self.player[user_id].get("status") != "loading"

    # 初始化题目
    async def fc_init(self, user_id: str) -> Optional[str]:
        """初始化游戏，返回临时文件路径"""
        if self.has_active_game(user_id):
            return "already_exists"

        # 设置加载状态，防止竞态条件
        self.player[user_id] = {"status": "loading"}

        try:
            # 提取题目
            question = await self.extract_questions()
            if not question:
                logger.error(f"[fc_init] 提取题目失败")
                self.player.pop(user_id, None)
                return None

            # 获取图片
            image = await self.get_image_from_url(question["url"])
            if not image:
                logger.error(f"[fc_init] 获取图片失败")
                self.player.pop(user_id, None)
                return None

            # 保存原始图片到内存中
            self.original_images[user_id] = image.copy()

            # 更新游戏状态（此时已完成图片下载）
            question["status"] = "active"
            self.player[user_id] = question

            # 处理图片（创建遮罩图）
            result, _ = self.mask_image_with_random_blocks(
                image,
                block_count=5
            )
            # 调整大小
            resized = self.resize_to_target(result, self.target_size)
            # 保存遮罩图到临时文件
            temp_path = await self.save_image_to_temp(resized, user_id)

            # 定期清理旧文件
            await self.periodic_cleanup_old_files()

            return temp_path
        except Exception as e:
            logger.error(f"[fc_init] 初始化失败: {e}")
            logger.error(traceback.format_exc())
            await self.cleanup_user_temp_files(user_id)
            await self.cleanup_original_image(user_id)
            if user_id in self.player:
                self.player.pop(user_id, None)
            return None

    # 获取明日方舟猜猜乐题目
    async def extract_questions(self) -> Optional[Dict[str, Any]]:
        """随机选择题目"""
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
                "url": random_url
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

    # 异步获取图片
    async def get_image_from_url(self, url: str, timeout: int = 10) -> Optional[Image.Image]:
        """从URL异步获取图片"""
        try:
            # 验证URL
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"无效的URL协议: {url}")

            # 检查URL是否指向内网地址（SSRF防护）
            parsed_url = urlparse(url)
            hostname = parsed_url.hostname
            if hostname:
                # 检查是否是私有IP地址
                if hostname.startswith(('10.', '172.16.', '192.168.', '127.', '169.254.', '::1', 'localhost')):
                    raise ValueError(f"禁止访问内网地址: {hostname}")

            async with aiohttp.ClientSession() as session:
                timeout_obj = aiohttp.ClientTimeout(total=timeout)
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                async with session.get(
                        url,
                        timeout=timeout_obj,
                        headers=headers,
                        ssl=False  # 注意：生产环境可能需要调整
                ) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}: {response.reason}")
                    content = await response.read()
                    if len(content) == 0:
                        raise Exception("下载的图片数据为空")
                    if len(content) > 10 * 1024 * 1024:  # 10MB限制
                        raise Exception("图片文件过大")
                    # 加载图片
                    image = Image.open(BytesIO(content))
                    # 验证图片格式
                    if image.format not in ['JPEG', 'PNG', 'GIF', 'WEBP', 'BMP']:
                        raise Exception(f"不支持的图片格式: {image.format}")
                    # 确保图片加载完成
                    image.load()
                    # 检查图片尺寸
                    width, height = image.size
                    if width > 5000 or height > 5000:
                        raise Exception(f"图片尺寸过大: {width}x{height}")
                    return image
        except (aiohttp.ClientError, ValueError) as e:
            logger.error(f"[get_image_from_url] 请求失败: {e}")
            raise
        except Exception as e:
            logger.error(f"[get_image_from_url] 处理图片时出错: {e}")
            raise

    # 输入处理
    def extract_and_sanitize_input(self, text: str, keyword: str) -> str:
        """提取并清理用户输入"""
        if not text or not keyword:
            return ""
        pattern = rf'{re.escape(keyword)}\s*(.*)'
        match = re.search(pattern, text)
        if not match:
            return ""
        user_input = match.group(1).strip()
        # 清理输入：移除特殊字符，只保留中文、英文、数字和空格
        cleaned = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', '', user_input)
        # 限制长度
        if len(cleaned) > 50:
            cleaned = cleaned[:50]
        return cleaned

    # 图片处理方法
    def mask_image_with_random_blocks(
            self,
            image: Image.Image,
            mask_color: Tuple[int, int, int] = (0, 0, 0),
            block_count: int = 5,
            min_width_percent: int = 10,
            max_width_percent: int = 20,
            min_height_percent: int = 10,
            max_height_percent: int = 20,
            min_gap_percent: int = 2,
            avoid_edges: bool = True
    ) -> Tuple[Image.Image, List[Tuple[int, int, int, int]]]:
        """
        在图片上生成随机透明小方块
        """
        # 参数验证
        if block_count < 1 or block_count > 20:
            block_count = 5
        if min_width_percent < 1 or min_width_percent > 50:
            min_width_percent = 10
        if max_width_percent < min_width_percent or max_width_percent > 50:
            max_width_percent = 20
        if min_height_percent < 1 or min_height_percent > 50:
            min_height_percent = 10
        if max_height_percent < min_height_percent or max_height_percent > 50:
            max_height_percent = 20
        width, height = image.size
        # 计算实际像素值
        min_width = max(5, int(width * min_width_percent / 100))
        max_width = max(min_width, int(width * max_width_percent / 100))
        min_height = max(5, int(height * min_height_percent / 100))
        max_height = max(min_height, int(height * max_height_percent / 100))
        min_gap = int(min(width, height) * min_gap_percent / 100)
        # 转换图片模式
        if image.mode != 'RGBA':
            original_rgba = image.convert('RGBA')
        else:
            original_rgba = image.copy()
        mask_layer = Image.new('RGBA', (width, height), mask_color + (255,))
        blocks = []
        edge_margin = min_gap if avoid_edges else 0
        for i in range(block_count):
            for attempt in range(100):  # 最多尝试100次
                block_width = random.randint(min_width, max_width)
                block_height = random.randint(min_height, max_height)
                max_x = width - block_width - edge_margin
                max_y = height - block_height - edge_margin
                if max_x <= edge_margin or max_y <= edge_margin:
                    logger.warning(f"图片太小，无法生成方块 {i + 1}")
                    break
                x = random.randint(edge_margin, max_x)
                y = random.randint(edge_margin, max_y)
                x1, y1 = x, y
                x2, y2 = x + block_width, y + block_height
                # 检查是否与现有方块冲突
                conflict = False
                for (bx1, by1, bx2, by2) in blocks:
                    if not (x2 + min_gap < bx1 or x1 > bx2 + min_gap or
                            y2 + min_gap < by1 or y1 > by2 + min_gap):
                        conflict = True
                        break
                if not conflict:
                    blocks.append((x1, y1, x2, y2))
                    # 创建透明区域
                    for block_y in range(y1, min(y2, height)):
                        for block_x in range(x1, min(x2, width)):
                            mask_layer.putpixel((block_x, block_y), (*mask_color, 0))
                    break
            else:
                logger.warning(f"无法生成方块 {i + 1}，可能空间不足")
        result = Image.alpha_composite(original_rgba, mask_layer)
        return result, blocks

    # 图片缩放方法
    def resize_to_target(self, image: Image.Image, target_size: int) -> Image.Image:
        """按比例缩放图像，保持宽高比"""
        if target_size <= 0:
            target_size = 800
        w, h = image.size
        if w >= h:
            new_w = target_size
            new_h = int(target_size * h / w)
        else:
            new_h = target_size
            new_w = int(target_size * w / h)
        # 确保最小尺寸
        new_w = max(new_w, 100)
        new_h = max(new_h, 100)
        return image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 临时文件管理 - 遮罩图
    async def save_image_to_temp(self, image: Image.Image, user_id: str) -> str:
        """将 PIL Image（遮罩图）保存到临时文件"""
        try:
            # 确保临时目录存在
            os.makedirs(self.temp_path, exist_ok=True)

            # 生成临时文件名
            timestamp = int(time.time() * 1000)
            import hashlib
            filename_hash = hashlib.md5(f"{user_id}_{timestamp}_masked".encode()).hexdigest()[:8]
            temp_filename = f"fc_masked_{user_id}_{filename_hash}.png"
            temp_path = os.path.join(self.temp_path, temp_filename)

            # 保存图片
            image.save(temp_path, 'PNG', optimize=True)

            # 记录临时文件
            self.temp_files[user_id] = temp_path

            logger.debug(f"[save_image_to_temp] 遮罩临时文件已保存: {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"[save_image_to_temp] 保存临时文件失败: {e}")
            raise

    # 新增：原始图片保存方法
    async def save_original_image_to_temp(self, image: Image.Image, user_id: str) -> str:
        """将原始图片保存到临时文件"""
        try:
            # 确保临时目录存在
            os.makedirs(self.temp_path, exist_ok=True)

            # 生成临时文件名
            timestamp = int(time.time() * 1000)
            import hashlib
            filename_hash = hashlib.md5(f"{user_id}_{timestamp}_original".encode()).hexdigest()[:8]
            temp_filename = f"fc_original_{user_id}_{filename_hash}.png"
            temp_path = os.path.join(self.temp_path, temp_filename)

            # 保存图片
            image.save(temp_path, 'PNG', optimize=True)

            logger.debug(f"[save_original_image_to_temp] 原始图片临时文件已保存: {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"[save_original_image_to_temp] 保存原始图片临时文件失败: {e}")
            raise

    async def cleanup_user_temp_files(self, user_id: str):
        """清理用户的临时文件（遮罩图）"""
        if user_id in self.temp_files:
            temp_path = self.temp_files.pop(user_id)
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    logger.debug(f"[cleanup_user_temp_files] 清理遮罩临时文件: {temp_path}")
            except OSError as e:
                logger.warning(f"[cleanup_user_temp_files] 清理遮罩文件失败 {temp_path}: {e}")

    async def cleanup_original_image(self, user_id: str):
        """清理内存中的原始图片"""
        if user_id in self.original_images:
            # 从字典中移除，让Python的垃圾回收处理
            del self.original_images[user_id]
            logger.debug(f"[cleanup_original_image] 清理内存中的原始图片: {user_id}")

    async def cleanup_all_temp_files(self):
        """清理所有临时文件"""
        if self._shutting_down:
            return

        try:
            # 清理记录的遮罩文件
            for user_id in list(self.temp_files.keys()):
                await self.cleanup_user_temp_files(user_id)

            # 清理内存中的原始图片
            for user_id in list(self.original_images.keys()):
                await self.cleanup_original_image(user_id)

            # 清理整个临时目录中的旧文件
            await self.cleanup_old_temp_files(max_age_hours=24)
        except Exception as e:
            logger.error(f"[cleanup_all_temp_files] 清理失败: {e}")

    async def cleanup_old_temp_files(self, max_age_hours: int = 24):
        """清理过期的临时文件"""
        try:
            current_time = time.time()
            for filename in os.listdir(self.temp_path):
                if filename.startswith("fc_"):
                    file_path = os.path.join(self.temp_path, filename)
                    try:
                        file_age = current_time - os.path.getmtime(file_path)
                        if file_age > max_age_hours * 3600:
                            os.unlink(file_path)
                            logger.debug(f"[cleanup_old_temp_files] 清理过期文件: {filename}")
                    except (OSError, FileNotFoundError) as e:
                        logger.warning(f"[cleanup_old_temp_files] 无法处理文件 {filename}: {e}")
        except (OSError, FileNotFoundError) as e:
            logger.error(f"[cleanup_old_temp_files] 访问临时目录失败: {e}")

    async def periodic_cleanup_old_files(self):
        """定期清理旧文件，概率性触发以减少开销"""
        if random.random() < 0.1:  # 10%的概率触发清理
            await self.cleanup_old_temp_files(max_age_hours=24)
