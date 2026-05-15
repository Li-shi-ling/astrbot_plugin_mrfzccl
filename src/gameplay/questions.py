from __future__ import annotations

import ipaddress
import traceback
from typing import Any, Optional
from urllib.parse import urlparse

import numpy as np

from astrbot.api import logger


def is_public_http_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url or len(url) > 2048:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    if str(hostname).strip().lower() == "localhost":
        return False
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return bool(ip.is_global)


class QuestionPicker:
    def __init__(
        self,
        data: dict[str, Any],
        *,
        low_weight_keywords: list[str] | tuple[str, ...],
        low_weight_ratio: float,
        max_recent_count: int = 20,
        rng: np.random.Generator | None = None,
    ) -> None:
        self.data = data
        self.low_weight_keywords = tuple(low_weight_keywords or ())
        self.low_weight_ratio = low_weight_ratio
        self.max_recent_count = max_recent_count
        self.recent_characters: list[str] = []
        self.rng = rng or np.random.default_rng()
        self._cache_data_id: int | None = None
        self._cache_kw_sig: tuple[str, ...] | None = None
        self._candidate_names: np.ndarray | None = None
        self._candidate_urls: list[list[str]] = []
        self._low_idx: np.ndarray = np.array([], dtype=int)
        self._normal_idx: np.ndarray = np.array([], dtype=int)

    def refresh_data(self, data: dict[str, Any]) -> None:
        if data is self.data:
            return
        self.data = data
        self._cache_data_id = None

    def _ensure_cache(self) -> bool:
        data_id = id(self.data)
        kw_sig = tuple(
            kw for kw in self.low_weight_keywords if isinstance(kw, str) and kw
        )
        if (
            self._cache_data_id == data_id
            and self._cache_kw_sig == kw_sig
            and self._candidate_names is not None
        ):
            return True

        candidate_names: list[str] = []
        candidate_urls: list[list[str]] = []
        is_low_weight: list[bool] = []
        low_keywords = [kw.strip() for kw in kw_sig if kw.strip()]

        for name, character_data in (self.data or {}).items():
            if not isinstance(name, str) or not name:
                continue
            if not isinstance(character_data, dict):
                continue
            urls = character_data.get("original_url", None)
            if not isinstance(urls, list) or not urls:
                continue
            valid_urls = [u.strip() for u in urls if is_public_http_url(u)]
            if not valid_urls:
                continue
            candidate_names.append(name)
            candidate_urls.append(valid_urls)
            is_low_weight.append(any(kw in name for kw in low_keywords))

        if not candidate_names:
            logger.error("[Mrfzccl][extract_questions] 无可用题库（请检查 original_url 配置）")
            return False

        self._candidate_names = np.array(candidate_names, dtype=object)
        self._candidate_urls = candidate_urls
        low_mask = np.array(is_low_weight, dtype=bool)
        self._low_idx = np.flatnonzero(low_mask)
        self._normal_idx = np.flatnonzero(~low_mask)
        self._cache_data_id = data_id
        self._cache_kw_sig = kw_sig
        return True

    def pick(self) -> Optional[dict[str, Any]]:
        try:
            if not self.data:
                logger.error("[Mrfzccl][extract_questions] 数据未加载")
                return None
            if not self._ensure_cache() or self._candidate_names is None:
                return None

            names_arr = self._candidate_names
            recent_set = set(self.recent_characters or [])

            try:
                low_ratio = float(self.low_weight_ratio)
            except Exception:
                low_ratio = 0.0
            low_ratio = max(0.0, float(low_ratio))

            weights = np.ones(len(names_arr), dtype=float)
            if self._low_idx.size > 0 and low_ratio != 1.0:
                weights[self._low_idx] = low_ratio

            if recent_set:
                recent_mask = np.array(
                    [str(name) in recent_set for name in names_arr], dtype=bool
                )
                weights[recent_mask] = 0.0

            total_weight = float(weights.sum())
            if total_weight <= 0:
                self.recent_characters = []
                weights = np.ones(len(names_arr), dtype=float)
                if self._low_idx.size > 0 and low_ratio != 1.0:
                    weights[self._low_idx] = low_ratio
                total_weight = float(weights.sum())
                if total_weight <= 0:
                    weights = np.ones(len(names_arr), dtype=float)
                    total_weight = float(weights.sum())

            probs = weights / total_weight
            picked = int(self.rng.choice(len(names_arr), p=probs))

            random_name = str(names_arr[picked])
            url_list = self._candidate_urls[picked]
            random_url = url_list[int(self.rng.integers(len(url_list)))]

            self.recent_characters.append(random_name)
            if len(self.recent_characters) > self.max_recent_count:
                self.recent_characters.pop(0)

            return {"name": random_name, "url": random_url, "fctn": 0}
        except (KeyError, IndexError, TypeError) as exc:
            logger.error(f"[Mrfzccl][extract_questions] 提取题目失败: {exc}")
            return None
        except Exception as exc:
            logger.error(f"[Mrfzccl][extract_questions] 提取题目时发生未知错误: {exc}")
            logger.debug(f"[Mrfzccl][extract_questions] {traceback.format_exc()}")
            return None
