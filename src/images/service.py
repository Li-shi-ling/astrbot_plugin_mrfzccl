from __future__ import annotations

import asyncio
import ipaddress
from io import BytesIO
from urllib.parse import urlparse

import aiohttp
import numpy as np
from PIL import Image


def validate_public_image_url(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"无效的URL协议: {url}")

    parsed_url = urlparse(url)
    hostname = parsed_url.hostname
    if not hostname:
        raise ValueError(f"无效的URL地址: {url}")

    hostname_norm = str(hostname).strip().lower()
    if hostname_norm == "localhost":
        raise ValueError(f"禁止访问内网地址: {hostname}")
    try:
        ip = ipaddress.ip_address(hostname_norm)
    except ValueError:
        return
    if not ip.is_global:
        raise ValueError(f"禁止访问内网地址: {hostname}")


def load_image_from_bytes(content: bytes) -> Image.Image:
    image = Image.open(BytesIO(content))
    if image.format not in ["JPEG", "PNG", "GIF", "WEBP", "BMP"]:
        raise Exception(f"不支持的图片格式: {image.format}")
    image.load()

    width, height = image.size
    if width > 5000 or height > 5000:
        raise Exception(f"图片尺寸过大: {width}x{height}")
    return image


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
    import random

    original_rgba = image.convert("RGBA") if image.mode != "RGBA" else image.copy()
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

            if any(
                not (
                    x2 + min_gap < bx1
                    or x1 > bx2 + min_gap
                    or y2 + min_gap < by1
                    or y1 > by2 + min_gap
                )
                for bx1, by1, bx2, by2 in blocks
            ):
                continue

            blocks.append((x1, y1, x2, y2))
            mask_layer[y1:y2, x1:x2, 3] = 0
            break

    alpha = mask_layer[..., 3:4] / 255.0
    result_arr = (arr * (1 - alpha) + mask_layer * alpha).astype(np.uint8)
    return Image.fromarray(result_arr, "RGBA"), blocks


def resize_to_target(image: Image.Image, target_size: int) -> Image.Image:
    if target_size <= 0:
        target_size = 800
    width, height = image.size
    if width >= height:
        new_width = target_size
        new_height = int(target_size * height / width)
    else:
        new_height = target_size
        new_width = int(target_size * width / height)
    return image.resize(
        (max(new_width, 100), max(new_height, 100)), Image.Resampling.LANCZOS
    )


def pil_image_to_bytes(image: Image.Image, format: str = "PNG") -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=format, optimize=True)
    return buffer.getvalue()


class ImageDownloader:
    def __init__(
        self,
        session_provider,
        *,
        max_retries: int = 2,
        retry_interval_seconds: float = 0.0,
    ) -> None:
        self.session_provider = session_provider
        self.max_retries = max(0, int(max_retries or 0))
        self.retry_interval_seconds = max(0.0, float(retry_interval_seconds or 0.0))

    async def get_image_from_url(self, url: str) -> Image.Image:
        validate_public_image_url(url)

        max_attempts = max(1, self.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                session = await self.session_provider()
                async with session.get(url, ssl=False) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}: {response.reason}")
                    content = await response.read()
                    if not content:
                        raise Exception("下载的图片数据为空")
                    if len(content) > 10 * 1024 * 1024:
                        raise Exception("图片文件过大")
                    loop = asyncio.get_running_loop()
                    return await loop.run_in_executor(None, load_image_from_bytes, content)
            except ValueError:
                raise
            except (aiohttp.ClientError, Exception) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                if self.retry_interval_seconds > 0:
                    await asyncio.sleep(self.retry_interval_seconds)

        if last_error is not None:
            raise last_error
        raise RuntimeError("获取图片失败，未捕获到具体错误")
