from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LLM_JUDGE_MAX_RETRIES_HARD_LIMIT = 5
DEFAULT_LLM_JUDGE_PROMPT = (
    "判断以下别名是否属于《明日方舟》中人物“{answer}”的，并使用True或False作答，不输出额外内容：{guess}"
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class LlmJudgeSettings:
    enabled: bool
    provider_id: str
    prompt: str
    debug: bool
    enable_retry: bool
    max_retries: int
    retry_interval_seconds: float


@dataclass(frozen=True)
class ImageDownloadSettings:
    max_retries: int
    retry_interval_seconds: float


@dataclass(frozen=True)
class MatchSettings:
    question_limit: int
    time_limit: int
    hint_delay: int
    answer_grace_period: float


@dataclass(frozen=True)
class QuestionSettings:
    low_weight_keywords: tuple[str, ...]
    low_weight_ratio: float
    max_recent_count: int
    target_size: int
    easy_probability: float
    medium_probability: float
    hard_probability: float


@dataclass(frozen=True)
class AliasSettings:
    character_aliases: str
    character_aliases_json: str
    operator_aliases_path: Path


@dataclass(frozen=True)
class T2ISettings:
    enabled: bool
    max_concurrent: int


@dataclass(frozen=True)
class PluginSettings:
    require_admin: bool
    admin_ids: tuple[str, ...]
    daily_limit: int
    renderer_theme: str
    data_path: Path
    similarity_threshold: float
    enable_similarity_match: bool
    calculate_threshold: float
    enable_character_coverage_match: bool
    enable_homophone: bool
    enable_operator_alias_match: bool
    enable_other_message_exact_match: bool
    llm_judge: LlmJudgeSettings
    image_download: ImageDownloadSettings
    match: MatchSettings
    question: QuestionSettings
    aliases: AliasSettings
    t2i: T2ISettings


def resolve_data_path(raw_path: Any, plugin_dir: Path) -> Path:
    path_text = str(raw_path or "arknights_skins_dict.json")
    path = Path(path_text)
    if path.is_absolute():
        return path
    return plugin_dir / "arknights_skins_dict.json"


def resolve_alias_path(raw_path: Any, plugin_dir: Path) -> Path:
    path = Path(str(raw_path or "arknights_operator_aliases.json"))
    if path.is_absolute():
        return path
    return plugin_dir / path


def load_settings(
    config: Mapping[str, Any],
    plugin_dir: Path,
    system_config: Any = None,
) -> PluginSettings:
    llm_config = _as_dict(config.get("llm_judge", {}))
    retry_config = _as_dict(config.get("image_download_retry", {}))
    t2i_config = _as_dict(config.get("t2i", {}))
    t2i_enabled = bool(t2i_config.get("enabled", True))

    configured_retries = int(llm_config.get("max_retries", 0) or 0)
    llm_max_retries = max(0, min(configured_retries, LLM_JUDGE_MAX_RETRIES_HARD_LIMIT))

    low_weight_raw = str(
        config.get("low_weight_characters", "预备干员,机师,W,SideStory")
    )
    low_weight_keywords = tuple(
        item.strip() for item in low_weight_raw.split(",") if item.strip()
    )

    return PluginSettings(
        require_admin=bool(config.get("require_admin", True)),
        admin_ids=tuple(str(item) for item in config.get("admin_ids", []) or []),
        daily_limit=int(config.get("daily_game_limit", 10) or 0),
        renderer_theme=str(config.get("renderer_theme", "light") or "light"),
        data_path=resolve_data_path(config.get("mrfz_data_path"), plugin_dir),
        similarity_threshold=float(config.get("similarity_threshold", 0.5) or 0.5),
        enable_similarity_match=bool(config.get("enable_similarity_match", True)),
        calculate_threshold=float(config.get("calculate_threshold", 0.5) or 0.5),
        enable_character_coverage_match=bool(
            config.get("enable_character_coverage_match", True)
        ),
        enable_homophone=bool(config.get("enable_homophone", False)),
        enable_operator_alias_match=bool(
            config.get("enable_operator_alias_match", True)
        ),
        enable_other_message_exact_match=bool(
            config.get("enable_other_message_exact_match", True)
        ),
        llm_judge=LlmJudgeSettings(
            enabled=bool(llm_config.get("enabled", False)),
            provider_id=str(
                llm_config.get("provider_id", llm_config.get("model", "")) or ""
            ).strip(),
            prompt=str(llm_config.get("prompt", DEFAULT_LLM_JUDGE_PROMPT) or ""),
            debug=bool(llm_config.get("debug", False)),
            enable_retry=bool(llm_config.get("enable_retry", False)),
            max_retries=llm_max_retries,
            retry_interval_seconds=max(
                0.0, float(llm_config.get("retry_interval_seconds", 0.0) or 0.0)
            ),
        ),
        image_download=ImageDownloadSettings(
            max_retries=max(
                0,
                int(
                    retry_config.get(
                        "max_retries", config.get("image_download_max_retries", 2)
                    )
                    or 0
                ),
            ),
            retry_interval_seconds=max(
                0.0, float(retry_config.get("retry_interval_seconds", 0.5) or 0.0)
            ),
        ),
        match=MatchSettings(
            question_limit=int(config.get("match_question_limit", 0) or 0),
            time_limit=int(config.get("match_time_limit", 0) or 0),
            hint_delay=int(config.get("match_hint_delay", 0) or 0),
            answer_grace_period=float(
                config.get("match_answer_grace_period", 3.0) or 0
            ),
        ),
        question=QuestionSettings(
            low_weight_keywords=low_weight_keywords,
            low_weight_ratio=float(config.get("low_weight_ratio", 0.2) or 0.0),
            max_recent_count=20,
            target_size=int(config.get("target_size", 128) or 128),
            easy_probability=float(config.get("easy_probability", 0.6) or 0.0),
            medium_probability=float(config.get("medium_probability", 0.3) or 0.0),
            hard_probability=float(config.get("hard_probability", 0.1) or 0.0),
        ),
        aliases=AliasSettings(
            character_aliases=str(
                config.get(
                    "character_aliases",
                    "铃兰:小狐狸,阿米娅:兔兔,小羊:艾雅法拉",
                )
                or ""
            ),
            character_aliases_json=str(
                config.get("character_aliases_json", "{}") or "{}"
            ),
            operator_aliases_path=resolve_alias_path(
                config.get("operator_aliases_path", "arknights_operator_aliases.json"),
                plugin_dir,
            ),
        ),
        t2i=T2ISettings(
            enabled=t2i_enabled,
            max_concurrent=int(t2i_config.get("max_concurrent", 1) or 1),
        ),
    )
