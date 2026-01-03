from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import StarTools
import PIL
import json
from PIL import Image
import requests
from io import BytesIO
import random
import os
import re
from difflib import SequenceMatcher
import aiohttp

@register("mrfzccl", "Lishining", "你知道的,我一直是明日方舟高手", "1.0.0")
class Mrfzccl(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.Config = config
        self.player = {}
        self.is_load = False
        try:
            with open(self._get_absolute_path(self.Config.get("mrfz_data_path", "")),"r") as f:
                self.data = json.loads(f.read())
            self.is_load = True
        except Exception as e:
            logger.error(f"[Mrfzccl] __init__ 加载数据文件错误,e:{e}", exc_info=True)
            self.is_load = False
        self.target_size = self.Config.get("target_size", 512)
        self.data_dir = str(StarTools.get_data_dir())
        self.temp_path = os.path.join(self.data_dir, "temp")

    @filter.command("fc")
    async def fc(self, event: AstrMessageEvent):
        if not self.is_load:
            yield event.plain_result("数据加载失败,请检查数据加载路径和后台日志")
            return
        user_id = event.get_group_id()
        if user_id is None:
            user_id = event.get_sender_id()
        code = await self.fc_init(user_id)
        if code == 0:
            yield event.plain_result("图片获取失败,请重试")
            return
        elif code == 2:
            yield event.plain_result("已经初始化,请不要重复操作")
            return
        yield event.chain_result([Comp.Plain("干员立绘,请使用/fcc [干员名称] 进行猜测"), Comp.Image.fromBytes(code.tobytes())])

    @filter.command("fcc")
    async def fcc(self, event: AstrMessageEvent):
        user_id = event.get_group_id()
        if not self.has_active_game(user_id):
            yield event.plain_result("没有初始化房间,请使用/fc")
            return
        if SequenceMatcher(None, self.player[user_id]["name"], self.extract_after_keyword(event.message_str, "fcc")).ratio() > 0.5:
            chain = [
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain(f"回答正确!答案为:{self.player[user_id]['name']}")
            ]
            yield event.chain_result(chain)
            self.destroy(user_id)
        else:
            chain = [
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain("回答错误!")
            ]
            yield event.chain_result(chain)

    @filter.command("fce")
    async def fce(self, event: AstrMessageEvent):
        user_id = event.get_group_id()
        if user_id is None:
            user_id = event.get_sender_id()
        if not self.has_active_game(user_id):
            yield event.plain_result("没有初始化房间,请使用/fc")
            return
        yield event.plain_result(f"游戏已结束,答案为:{self.player[user_id]['name']}")
        self.destroy(user_id)

    @filter.command("fch")
    async def fch(self, event: AstrMessageEvent):
        help_text = """fc 插件使用说明
        1. 开始游戏
        命令：/fc
        说明：生成遮挡图片并发出
        2. 猜角色
        命令：/fcc [角色名称]
        说明：进行角色猜测
        3. 强制结束游戏
        命令：/fce
        说明：结束当前进行的游戏
        """
        yield event.plain_result(help_text)

    # 注销游戏
    def destroy(self, user_id):
        self.player.pop(user_id, None)

    # 检测玩家是否存在
    def has_active_game(self, user_id):
        return user_id in self.player

    # 初始化题目
    async def fc_init(self, player_id):
        if self.player.get(player_id, None):
            self.player[player_id] = await self.extract_questions()
            try:
                image = await self.get_image_from_url(self.player[player_id]["url"])
            except Exception as e:
                logger.error(f"[fc_init] 获取图片失败,e:{e}", exc_info=True)
                self.player.pop(player_id, None)
                return 0
        else:
            return 2
        result, revealed_lines = self.mask_image_with_random_blocks(image, block_count=5)
        return self.resize_by_scale_(result, self.target_size)

    # 获取明日方舟猜猜乐题目
    async def extract_questions(self):
        names = list(self.data.keys())
        random_name = random.choice(names)
        urls = self.data[random_name]["original_url"]
        random_url = random.choice(urls)
        return {"name":random_name,"url":random_url}

    # 将路径转换为绝对路径
    def _get_absolute_path(self, path):
        if not path:
            return ""
        return os.path.abspath(path)

    # 从url获取image
    async def get_image_from_url(self, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}: {response.reason}")
                    content = await response.read()
                    if not content:
                        raise Exception("下载的图片数据为空")
                    image = Image.open(BytesIO(content))
                    image.load()
                    return image
        except aiohttp.ClientError as e:
            raise Exception(f"网络请求失败: {str(e)}")
        except Exception as e:
            raise Exception(f"处理图片时出错: {str(e)}")

    # 对图片进行随机的行显示
    def mask_image_with_dynamic_thickness(
            self,
            image,
            mask_color=(0, 0, 0),
            line_count=4,
            line_thickness_percent=3,
            min_gap_percent=5
    ):
        """
        Args:
            image: PIL Image对象
            mask_color: 遮挡颜色
            line_count: 要透明的行数
            line_thickness_percent: 行厚度占图片高度的百分比
            min_gap_percent: 最小间隔占图片高度的百分比

        Returns:
            PIL.Image.Image: 处理后的图片
        """
        width, height = image.size
        line_thickness = max(10, int(height * line_thickness_percent / 100))
        min_gap = max(20, int(height * min_gap_percent / 100))
        if image.mode != 'RGBA':
            original_rgba = image.convert('RGBA')
        else:
            original_rgba = image.copy()
        mask_opacity = 255
        mask_layer = Image.new('RGBA', (width, height), mask_color + (mask_opacity,))
        revealed_lines = []
        min_center = line_thickness
        max_center = height - line_thickness
        if max_center <= min_center:
            min_center = 0
            max_center = height
        possible_centers = list(range(min_center, max_center + 1))
        for attempt in range(100):
            if len(revealed_lines) >= line_count or not possible_centers:
                break
            center = random.choice(possible_centers)
            top = max(0, center - line_thickness // 2)
            bottom = min(height, center + line_thickness // 2)
            conflict = False
            for existing_center, _, _ in revealed_lines:
                if abs(center - existing_center) < min_gap:
                    conflict = True
                    break
            if not conflict:
                revealed_lines.append((center, top, bottom))
                possible_centers = [
                    pos for pos in possible_centers
                    if abs(pos - center) >= min_gap
                ]
        if not revealed_lines:
            logger.error("警告：无法创建透明行，图片可能太小")
        mask_pixels = mask_layer.load()
        for center, top, bottom in revealed_lines:
            for y in range(top, bottom):
                for x in range(width):
                    r, g, b, a = mask_pixels[x, y]
                    mask_pixels[x, y] = (r, g, b, 0)
        result = Image.alpha_composite(original_rgba, mask_layer)
        return result, revealed_lines

    # 对图片进行随机的方块显示
    def mask_image_with_random_blocks(
            self,
            image,
            mask_color=(0, 0, 0),
            block_count=5,
            min_width_percent=10, max_width_percent=20,
            min_height_percent=10, max_height_percent=20,
            min_gap_percent=2,
            avoid_edges=True
    ):
        """
        在图片上生成随机透明小方块

        Args:
            image: PIL Image对象
            mask_color: 遮挡颜色
            block_count: 要生成的透明方块数量
            min_width_percent: 最小方块宽度占图片宽度的百分比
            max_width_percent: 最大方块宽度占图片宽度的百分比
            min_height_percent: 最小方块高度占图片高度的百分比
            max_height_percent: 最大方块高度占图片高度的百分比
            min_gap_percent: 最小间隔占图片尺寸的百分比
            avoid_edges: 是否避免方块紧贴图片边缘

        Returns:
            PIL.Image.Image: 处理后的图片
            list: 生成的方块位置信息 [(x1, y1, x2, y2), ...]
        """
        width, height = image.size
        min_width = max(5, int(width * min_width_percent / 100))
        max_width = max(min_width, int(width * max_width_percent / 100))
        min_height = max(5, int(height * min_height_percent / 100))
        max_height = max(min_height, int(height * max_height_percent / 100))
        min_gap = int(min(width, height) * min_gap_percent / 100)
        if image.mode != 'RGBA':
            original_rgba = image.convert('RGBA')
        else:
            original_rgba = image.copy()
        mask_opacity = 255
        mask_layer = Image.new('RGBA', (width, height), mask_color + (mask_opacity,))
        blocks = []
        mask_pixels = mask_layer.load()
        edge_margin = min_gap if avoid_edges else 0
        for i in range(block_count):
            for attempt in range(100):
                block_width = random.randint(min_width, max_width)
                block_height = random.randint(min_height, max_height)
                max_x = width - block_width - edge_margin
                max_y = height - block_height - edge_margin
                if max_x <= edge_margin or max_y <= edge_margin:
                    logger.error(f"警告：图片太小，无法生成方块 {i + 1}")
                    break
                x = random.randint(edge_margin, max_x)
                y = random.randint(edge_margin, max_y)
                x1, y1 = x, y
                x2, y2 = x + block_width, y + block_height
                conflict = False
                for (bx1, by1, bx2, by2) in blocks:
                    if not (x2 + min_gap < bx1 or x1 > bx2 + min_gap or
                            y2 + min_gap < by1 or y1 > by2 + min_gap):
                        conflict = True
                        break

                if not conflict:
                    blocks.append((x1, y1, x2, y2))
                    for block_y in range(y1, min(y2, height)):
                        for block_x in range(x1, min(x2, width)):
                            r, g, b, a = mask_pixels[block_x, block_y]
                            mask_pixels[block_x, block_y] = (r, g, b, 0)
                    break
            else:
                logger.error(f"警告：无法生成方块 {i + 1}，可能空间不足")
        logger.info(f"成功创建 {len(blocks)} 个透明方块")
        if not blocks:
            logger.error("警告：无法创建任何透明方块")
        result = Image.alpha_composite(original_rgba, mask_layer)
        return result, blocks

    # 按比例缩放图像
    def resize_by_scale(self, image, scale_factor):
        w, h = image.size
        return image.resize((int(w * scale_factor), int(h * scale_factor)), Image.Resampling.LANCZOS)

    # 保留长宽比，将较大边缩放到目标大小
    def resize_by_scale_(self, image, target_size):
        w, h = image.size
        ratio = w / h
        if w >= h:
            new_w = target_size
            new_h = int(target_size / ratio)
        else:
            new_h = target_size
            new_w = int(target_size * ratio)
        return image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 提取指令参数
    def extract_after_keyword(self, text, keyword):
        pattern = rf'{re.escape(keyword)}\s*(.*)'
        match = re.search(pattern, text)
        if match:
            return match.group(1)
        return None
