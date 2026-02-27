from collections import Counter
from io import BytesIO
import random
import re
from typing import List, Tuple

import numpy as np
from PIL import Image

def calculate_char_coverage_set(correct_name: str, guess_text: str) -> float:
    """
    计算guess_text包含correct_name中字符的比例（去重版本）

    Args:
        correct_name: 正确答案
        guess_text: 用户猜测的答案

    Returns:
        float: 字符覆盖率 (0-1之间)
    """
    if not correct_name:
        return 0.0

    # 转换为集合去重
    correct_chars = set(correct_name)
    guess_chars = set(guess_text)

    # 计算匹配的字符数比例
    matched_chars = correct_chars & guess_chars
    coverage = len(matched_chars) / len(correct_chars)

    return coverage

def calculate_char_coverage_counter(correct_name: str, guess_text: str) -> float:
    """
    计算guess_text包含correct_name中字符的比例（不去重版本）

    Args:
        correct_name: 正确答案
        guess_text: 用户猜测的答案

    Returns:
        float: 字符覆盖率 (0-1之间)
    """
    if not correct_name:
        return 0.0

    # 使用Counter统计字符出现次数
    correct_counter = Counter(correct_name)
    guess_counter = Counter(guess_text)

    # 计算总字符数和匹配的字符数
    total_chars = sum(correct_counter.values())
    matched_chars = 0

    for char, count in correct_counter.items():
        matched_chars += min(count, guess_counter.get(char, 0))

    coverage = matched_chars / total_chars if total_chars > 0 else 0.0

    return coverage

def _load_image_from_bytes(content: bytes) -> Image.Image:
    """同步加载图片（可用于在线程池中执行）"""
    image = Image.open(BytesIO(content))
    if image.format not in ["JPEG", "PNG", "GIF", "WEBP", "BMP"]:
        raise Exception(f"不支持的图片格式: {image.format}")
    image.load()

    width, height = image.size
    if width > 5000 or height > 5000:
        raise Exception(f"图片尺寸过大: {width}x{height}")
    return image

def extract_and_sanitize_input(text: str, keyword: str) -> str:
    """提取并清理用户输入"""
    if not text or not keyword:
        return ""
    pattern = rf"{re.escape(keyword)}\\s*(.*)"
    match = re.search(pattern, text)
    if not match:
        return ""
    user_input = match.group(1).strip()
    cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\\s]", "", user_input)
    if len(cleaned) > 50:
        cleaned = cleaned[:50]
    return cleaned

def resize_to_target(image: Image.Image, target_size: int) -> Image.Image:
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
    new_w = max(new_w, 100)
    new_h = max(new_h, 100)
    return image.resize((new_w, new_h), Image.Resampling.LANCZOS)

def pil_image_to_bytes(image: Image.Image, format: str = "PNG") -> bytes:
    """PIL 图片转 bytes"""
    buf = BytesIO()
    image.save(buf, format=format, optimize=True)
    return buf.getvalue()

def mask_image_with_random_blocks(
    image: Image.Image,
    block_count: int = 5,
    mask_color: Tuple[int, int, int] = (0, 0, 0),
    min_width_percent: int = 10,
    max_width_percent: int = 20,
    min_height_percent: int = 10,
    max_height_percent: int = 20,
    min_gap_percent: int = 2,
    avoid_edges: bool = True,
) -> Tuple[Image.Image, List[Tuple[int, int, int, int]]]:
    """
    高性能遮罩图片，只露出几个小方块，保持原始游戏逻辑

    参数:
        image: 原始图片
        block_count: 遮罩方块数量
        mask_color: 遮罩颜色(RGB)
        min/max_width/height_percent: 方块尺寸范围（图片尺寸的百分比）
        min_gap_percent: 方块间最小间距（图片尺寸的百分比）
        avoid_edges: 是否尽量避开边缘
    """
    if image.mode != "RGBA":
        original_rgba = image.convert("RGBA")
    else:
        original_rgba = image.copy()

    width, height = original_rgba.size
    arr = np.array(original_rgba)

    mask_layer = np.zeros_like(arr)
    mask_layer[..., 0] = mask_color[0]
    mask_layer[..., 1] = mask_color[1]
    mask_layer[..., 2] = mask_color[2]
    mask_layer[..., 3] = 255

    min_width = max(5, int(width * min_width_percent / 100))
    max_width = max(min_width, int(width * max_width_percent / 100))
    min_height = max(5, int(height * min_height_percent / 100))
    max_height = max(min_height, int(height * max_height_percent / 100))
    min_gap = int(min(width, height) * min_gap_percent / 100)
    edge_margin = min_gap if avoid_edges else 0

    blocks: List[Tuple[int, int, int, int]] = []

    for _ in range(block_count):
        for _attempt in range(100):
            w = random.randint(min_width, max_width)
            h = random.randint(min_height, max_height)
            max_x = width - w - edge_margin
            max_y = height - h - edge_margin
            if max_x <= edge_margin or max_y <= edge_margin:
                break

            x1 = random.randint(edge_margin, max_x)
            y1 = random.randint(edge_margin, max_y)
            x2, y2 = x1 + w, y1 + h

            conflict = False
            for bx1, by1, bx2, by2 in blocks:
                if not (
                    x2 + min_gap < bx1
                    or x1 > bx2 + min_gap
                    or y2 + min_gap < by1
                    or y1 > by2 + min_gap
                ):
                    conflict = True
                    break

            if not conflict:
                blocks.append((x1, y1, x2, y2))
                mask_layer[y1:y2, x1:x2, 3] = 0
                break

    alpha = mask_layer[..., 3:4] / 255.0
    result_arr = arr * (1 - alpha) + mask_layer * alpha
    result_arr = result_arr.astype(np.uint8)
    result = Image.fromarray(result_arr, "RGBA")
    return result, blocks
