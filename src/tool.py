import asyncio
import json
import os
import random
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from pypinyin import Style, lazy_pinyin

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent


# 计算去重后字符集合的覆盖率。
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


# 计算保留重复字符次数的覆盖率。
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


# 生成正确次数排行榜的文本内容。
def generate_correct_leaderboard_text(
    users: Iterable[Any], summary: Mapping[str, Any] | None = None
) -> str:
    """生成正确量排行榜文本"""
    users = list(users or [])
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

        total_answers = getattr(user, "correct_count", 0) + getattr(
            user, "wrong_count", 0
        )
        accuracy = (
            (getattr(user, "correct_count", 0) / total_answers * 100)
            if total_answers > 0
            else 0
        )

        message += f"{medal} {getattr(user, 'user_name', '-')}\n"
        message += f"   ✅ 正确: {getattr(user, 'correct_count', 0)} | ❌ 错误: {getattr(user, 'wrong_count', 0)} | 💡 提示: {getattr(user, 'tip_count', 0)}\n"
        updated_at = getattr(user, "updated_at", None)
        updated_str = (
            updated_at.strftime("%Y-%m-%d") if hasattr(updated_at, "strftime") else "-"
        )
        message += f"   📈 准确率: {accuracy:.1f}% | 📅 最后更新: {updated_str}\n\n"

    if summary:
        message += "📊 **统计信息**\n"
        message += f"总用户数: {summary.get('total_users', '-')} | 总答题数: {summary.get('total_questions', '-')}\n"
        message += f"总正确数: {summary.get('total_correct', '-')} | 总错误数: {summary.get('total_wrong', '-')}\n"
        message += f"平均正确数: {summary.get('avg_correct', 0):.1f}"

    return message


# 生成错误次数排行榜的文本内容。
def generate_wrong_leaderboard_text(users: Iterable[Any]) -> str:
    """生成错误个数排行榜文本"""
    users = list(users or [])
    if not users:
        return "📊 当前还没有用户的答题记录哦~"

    message = "💥 **错误个数排行榜** 💥\n\n"

    for i, user in enumerate(users, 1):
        if i == 1:
            medal = "💣"
        elif i == 2:
            medal = "🧨"
        elif i == 3:
            medal = "🎆"
        else:
            medal = f"{i}."

        total_answers = getattr(user, "correct_count", 0) + getattr(
            user, "wrong_count", 0
        )
        error_rate = (
            (getattr(user, "wrong_count", 0) / total_answers * 100)
            if total_answers > 0
            else 0
        )

        message += f"{medal} {getattr(user, 'user_name', '-')}\n"
        message += f"   ❌ 错误: {getattr(user, 'wrong_count', 0)} | ✅ 正确: {getattr(user, 'correct_count', 0)} | 💡 提示: {getattr(user, 'tip_count', 0)}\n"
        updated_at = getattr(user, "updated_at", None)
        updated_str = (
            updated_at.strftime("%Y-%m-%d") if hasattr(updated_at, "strftime") else "-"
        )
        message += f"   📉 错误率: {error_rate:.1f}% | 📅 最后更新: {updated_str}\n\n"

    return message


# 生成提示使用次数排行榜的文本内容。
def generate_hints_leaderboard_text(users: Iterable[Any]) -> str:
    """生成提示次数排行榜文本"""
    users = list(users or [])
    if not users:
        return "📊 当前还没有用户的答题记录哦~"

    message = "💡 **提示次数排行榜** 💡\n\n"

    for i, user in enumerate(users, 1):
        if i == 1:
            medal = "🎯"
        elif i == 2:
            medal = "🔍"
        elif i == 3:
            medal = "🧩"
        else:
            medal = f"{i}."

        total_answers = getattr(user, "correct_count", 0) + getattr(
            user, "wrong_count", 0
        )
        tips_per_question = (
            (getattr(user, "tip_count", 0) / total_answers) if total_answers > 0 else 0
        )

        message += f"{medal} {getattr(user, 'user_name', '-')}\n"
        message += f"   💡 提示: {getattr(user, 'tip_count', 0)} | ✅ 正确: {getattr(user, 'correct_count', 0)} | ❌ 错误: {getattr(user, 'wrong_count', 0)}\n"
        updated_at = getattr(user, "updated_at", None)
        updated_str = (
            updated_at.strftime("%Y-%m-%d") if hasattr(updated_at, "strftime") else "-"
        )
        message += f"   📊 提示频率: {tips_per_question:.2f}/题 | 📅 最后更新: {updated_str}\n\n"

    return message


# 生成比赛排行榜的文本内容。
def generate_match_leaderboard_text(
    match_name: str, participants: Iterable[Any], ended: bool = False
) -> str:
    """生成比赛排行榜文本（图片生成失败时的回退）"""
    participants = list(participants or [])
    if not participants:
        status = "已结束" if ended else "排行榜"
        return f"比赛「{match_name}」{status}\n\n暂无参赛记录"

    try:
        participants.sort(
            key=lambda p: float(getattr(p, "score", 0.0) or 0.0), reverse=True
        )
    except Exception:
        pass

    title = (
        f"比赛「{match_name}」已结束\n排行榜"
        if ended
        else f"比赛「{match_name}」排行榜"
    )
    message = f"{title}\n----------------\n"
    for i, p in enumerate(participants[:10], 1):
        user_name = getattr(p, "user_name", "-")
        correct = getattr(p, "correct_count", 0)
        wrong = getattr(p, "wrong_count", 0)
        try:
            score_str = f"{float(getattr(p, 'score', 0.0) or 0.0):.2f}"
        except Exception:
            score_str = "-"
        message += f"{i}. {user_name}: {correct}对 {wrong}错 {score_str}分\n"
    return message


# 生成人物名片或个人统计文本。
def generate_user_profile_text(
    user_stats: Any,
    rank_info: Mapping[str, Any],
    honors=None,
    user_id: str | None = None,
) -> str:
    """生成用户个人信息文本"""
    honors = list(honors or [])

    title = getattr(user_stats, "user_name", None) if user_stats else None
    title = title or (user_id or "未知用户")
    message = f"👤 **用户信息 - {title}**\n\n"

    if not user_stats:
        message += "📊 **基础统计**\n"
        message += "暂无答题记录\n"
    else:
        total_answers = getattr(user_stats, "correct_count", 0) + getattr(
            user_stats, "wrong_count", 0
        )
        accuracy = (
            (getattr(user_stats, "correct_count", 0) / total_answers * 100)
            if total_answers > 0
            else 0
        )

        message += "📊 **基础统计**\n"
        message += f"✅ 正确: {getattr(user_stats, 'correct_count', 0)}\n"
        message += f"❌ 错误: {getattr(user_stats, 'wrong_count', 0)}\n"
        message += f"💡 提示: {getattr(user_stats, 'tip_count', 0)}\n"
        message += f"🎯 准确率: {accuracy:.1f}%\n"
        message += f"📝 总答题数: {total_answers}\n\n"

        if rank_info:
            message += f"🏆 **排名信息** (共{rank_info.get('total_users', '?')}人)\n"
            message += f"✅ 正确排名: 第{rank_info.get('correct_rank', '?')}名\n"
            message += f"❌ 错误排名: 第{rank_info.get('wrong_rank', '?')}名\n"
            message += f"💡 提示排名: 第{rank_info.get('tip_rank', '?')}名\n\n"

        created_at = getattr(user_stats, "created_at", None)
        updated_at = getattr(user_stats, "updated_at", None)
        created_str = (
            created_at.strftime("%Y-%m-%d %H:%M")
            if hasattr(created_at, "strftime")
            else "-"
        )
        updated_str = (
            updated_at.strftime("%Y-%m-%d %H:%M")
            if hasattr(updated_at, "strftime")
            else "-"
        )

        message += "📅 **时间信息**\n"
        message += f"⏰ 注册时间: {created_str}\n"
        message += f"🔄 最后更新: {updated_str}\n"

    if honors:
        message += "\n🏅 **比赛荣誉**\n"
        for h in honors[:5]:
            try:
                score_str = f"{float(getattr(h, 'score', 0.0)):.1f}"
            except Exception:
                score_str = "-"
            message += (
                f"{getattr(h, 'medal', '')} {getattr(h, 'match_name', '-')}: "
                f"第{getattr(h, 'rank', '?')}名（✅{getattr(h, 'correct_count', 0)}/"
                f"❌{getattr(h, 'wrong_count', 0)}，S{score_str}）\n"
            )
    else:
        message += "\n暂无荣誉记录\n"

    return message


# 优先发送图片结果，失败时回退到文本结果。
async def generate_image_or_fallback(
    event: AstrMessageEvent,
    generate_image_func: Callable[..., Any],
    generate_text_func: Callable[..., str],
    *args,
    **kwargs,
):
    """统一的图片生成和回退处理"""
    try:
        image_path = await generate_image_func(*args, **kwargs)

        if image_path and os.path.exists(image_path):
            yield event.chain_result([Comp.Image.fromFileSystem(image_path)])
            return

        text_message = generate_text_func(*args, **kwargs)
        yield event.plain_result(f"图片生成失败，使用文本模式显示\n\n{text_message}")

    except Exception as render_error:
        text_message = generate_text_func(*args, **kwargs)
        yield event.plain_result(
            f"图片生成失败，使用文本模式显示\n错误: {str(render_error)}\n\n{text_message}"
        )


# 解析旧版字符串格式的别名映射配置。
def parse_aliases(alias_str: str) -> dict[str, str]:
    """解析别名配置字符串为映射表：别名:正名,别名:正名"""
    alias_map: dict[str, str] = {}
    if not alias_str:
        return alias_map
    for pair in str(alias_str).split(","):
        if ":" not in pair:
            continue
        alias, name = pair.split(":", 1)
        alias = alias.strip()
        name = name.strip()
        if not alias or not name:
            continue
        alias_map[alias] = name
    return alias_map


# 解析 JSON 文本格式的别名映射配置。
def parse_aliases_json_text(alias_text: str) -> dict[str, str]:
    """解析 JSON 格式的干员别名配置，返回别名到正式名称的映射。"""
    if not alias_text:
        return {}

    try:
        raw_data = json.loads(str(alias_text))
    except json.JSONDecodeError as exc:
        logger.warning(f"[Mrfzccl] 解析干员别名 JSON 配置失败: {exc}")
        return {}

    if not isinstance(raw_data, dict):
        return {}

    alias_map: dict[str, str] = {}
    for alias, name in raw_data.items():
        if not isinstance(alias, str) or not isinstance(name, str):
            continue
        normalized_alias = alias.strip()
        normalized_name = name.strip()
        if not normalized_alias or not normalized_name:
            continue
        alias_map[normalized_alias] = normalized_name
    return alias_map


# 合并多份别名映射并让后者覆盖前者。
def merge_alias_maps(*alias_maps: Mapping[str, str]) -> dict[str, str]:
    """合并多份别名映射并让后者覆盖前者。"""
    merged: dict[str, str] = {}
    for alias_map in alias_maps:
        for alias, name in (alias_map or {}).items():
            if not alias or not name:
                continue
            merged[alias] = name
    return merged


# 将输入名称解析为正式干员名。
def resolve_alias(name: str, alias_map: Mapping[str, str]) -> str:
    """将别名解析为正名（若不存在则返回原值）"""
    return (alias_map or {}).get(name, name)


# 从 JSON 文件加载按真名索引的干员别名表。
def load_operator_aliases(path: str | Path) -> dict[str, list[str]]:
    """加载算子别名表，按规范算子名建立索引。"""
    alias_path = Path(path)
    if not alias_path.exists():
        return {}

    try:
        with alias_path.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[Mrfzccl] 加载干员别名文件失败 {alias_path}: {exc}")
        return {}

    if not isinstance(raw_data, dict):
        return {}

    alias_data: dict[str, list[str]] = {}
    for name, aliases in raw_data.items():
        if not isinstance(name, str) or not isinstance(aliases, list):
            continue

        normalized_aliases: list[str] = []
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            normalized_alias = alias.strip()
            if normalized_alias and normalized_alias not in normalized_aliases:
                normalized_aliases.append(normalized_alias)

        normalized_name = name.strip()
        if normalized_name and normalized_aliases:
            alias_data[normalized_name] = normalized_aliases

    return alias_data


# 判断输入是否精确命中某个干员的别名。
def is_exact_operator_alias_match(
    name: str, guess: str, aliases_by_name: Mapping[str, list[str]]
) -> bool:
    """判断 guess 是否正好等于该算子的某一个别名。"""
    if not name or not guess:
        return False
    normalized_name = name.strip()
    normalized_guess = guess.strip()
    if not normalized_name or not normalized_guess:
        return False
    return normalized_guess in (aliases_by_name or {}).get(normalized_name, [])


# 获取文本对应的无声调拼音串。
def get_pinyin(text: str) -> str:
    """获取汉字的拼音（不带声调）"""
    return "".join(lazy_pinyin(text, style=Style.NORMAL))


# 判断两个文本是否满足同音匹配。
def check_homophone(correct: str, guess: str, enable_homophone: bool = False) -> bool:
    """检查两个字符串是否同音（基于拼音）"""
    if not enable_homophone:
        return False
    return get_pinyin(correct) == get_pinyin(guess)


# 检查用户是否超过每日游戏次数限制。
def check_daily_limit(user_id: str, daily_counter: dict, daily_limit: int) -> bool:
    """检查并更新每日计数器，返回是否允许继续游戏"""
    if daily_limit < 0:
        return True
    today = datetime.now().date()
    key = f"{user_id}_{today}"
    count = daily_counter.get(key, 0)
    if count >= daily_limit:
        return False
    daily_counter[key] = count + 1
    return True


# 判断指定用户是否存在激活中的游戏状态。
def has_active_game(player: Mapping[str, Any], user_id: str) -> bool:
    """检查用户是否有活跃游戏"""
    data = (player or {}).get(user_id)
    return bool(data and data.get("status") == "active")


# 安全取消异步任务。
def safe_cancel_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    try:
        if not task.done():
            task.cancel()
    except Exception:
        pass


# 解析 LLM 判题输出为布尔结果。
def parse_llm_judge_result(completion_text: str) -> bool | None:
    text = str(completion_text or "").strip()
    if not text:
        return None

    tokens = re.findall(
        r"(?<![A-Za-z])(?:true|false)(?![A-Za-z])",
        text,
        flags=re.IGNORECASE,
    )
    if not tokens:
        return None
    if any(token.lower() == "false" for token in tokens):
        return False
    return any(token.lower() == "true" for token in tokens)


# 转换为绝对路径。
def get_absolute_path(path: str) -> str:
    if not path:
        raise ValueError("路径不能为空")
    return os.path.abspath(path)


# 从字节内容加载并校验图片。
def load_image_from_bytes(content: bytes) -> Image.Image:
    image = Image.open(BytesIO(content))
    if image.format not in ["JPEG", "PNG", "GIF", "WEBP", "BMP"]:
        raise Exception(f"不支持的图片格式: {image.format}")
    image.load()

    width, height = image.size
    if width > 5000 or height > 5000:
        raise Exception(f"图片尺寸过大: {width}x{height}")
    return image


# 提取并清理用户输入。
def extract_and_sanitize_input(text: str, keyword: str) -> str:
    if not text or not keyword:
        return ""
    pattern = rf"{re.escape(keyword)}\s*(.*)"
    match = re.search(pattern, text)
    if not match:
        return ""
    user_input = match.group(1).strip()
    cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s]", "", user_input)
    if len(cleaned) > 50:
        cleaned = cleaned[:50]
    return cleaned


# 生成随机方块遮罩图片。
def mask_image_with_random_blocks(
    image: Image.Image,
    block_count: int = 5,
    mask_color: tuple[int, int, int] = (0, 0, 0),
    min_width_percent: int = 10,
    max_width_percent: int = 20,
    min_height_percent: int = 10,
    max_height_percent: int = 20,
    min_gap_percent: int = 2,
    avoid_edges: bool = True,
) -> tuple[Image.Image, list[tuple[int, int, int, int]]]:
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

    blocks: list[tuple[int, int, int, int]] = []

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


# 按比例缩放图片并保持宽高比。
def resize_to_target(image: Image.Image, target_size: int) -> Image.Image:
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


# 将 PIL 图片转换为字节。
def pil_image_to_bytes(image: Image.Image, format: str = "PNG") -> bytes:
    buf = BytesIO()
    image.save(buf, format=format, optimize=True)
    return buf.getvalue()


# 清洗ffc消息,转变为指令
def normalize_compact_fc_command(message_str: str) -> str | None:
    message = re.sub(r"\s+", " ", (message_str or "").strip())
    if not message:
        return None

    match = re.fullmatch(r"(fcc)(\S+)", message)
    if not match:
        return None

    command, argument = match.groups()
    if len(argument) > 16:
        return None

    if re.search(r"[，。！？、,.!?/\\\\]", argument):
        return None

    return f"{command} {argument}"
