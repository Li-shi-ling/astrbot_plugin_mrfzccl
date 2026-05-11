from __future__ import annotations

import time

import numpy as np
from PIL import Image

from data.plugins.astrbot_plugin_mrfzccl.src.core.config import (
    DEFAULT_LLM_JUDGE_PROMPT,
    LLM_JUDGE_MAX_RETRIES_HARD_LIMIT,
    load_settings,
)
from data.plugins.astrbot_plugin_mrfzccl.src.gameplay.judging import (
    MatchSettings,
    is_recent_previous_match_answer,
    should_skip_plain_answer_message,
)
from data.plugins.astrbot_plugin_mrfzccl.src.images.service import (
    pil_image_to_bytes,
    resize_to_target,
    validate_public_image_url,
)
from data.plugins.astrbot_plugin_mrfzccl.src.gameplay.questions import (
    QuestionPicker,
    is_public_http_url,
)
from data.plugins.astrbot_plugin_mrfzccl.src.core.runtime import GameRuntime, MatchRuntime


def test_load_settings_normalizes_nested_retry_config(tmp_path):
    settings = load_settings(
        {
            "llm_judge": "invalid",
            "image_download_retry": {"max_retries": 3, "retry_interval_seconds": 0.25},
        },
        tmp_path,
    )

    assert settings.llm_judge.prompt == DEFAULT_LLM_JUDGE_PROMPT
    assert settings.llm_judge.max_retries == 0
    assert settings.image_download.max_retries == 3
    assert settings.image_download.retry_interval_seconds == 0.25

    capped = load_settings(
        {"llm_judge": {"max_retries": LLM_JUDGE_MAX_RETRIES_HARD_LIMIT + 10}},
        tmp_path,
    )
    assert capped.llm_judge.max_retries == LLM_JUDGE_MAX_RETRIES_HARD_LIMIT


def test_match_runtime_keeps_active_room_lock_and_cleans_idle_lock():
    game = GameRuntime()
    runtime = MatchRuntime(game)

    active_lock = runtime.get_room_lock("active-room")
    idle_lock = runtime.get_room_lock("idle-room")
    game.player["active-room"] = {"status": "active"}
    runtime.lock_last_used["idle-room"] = time.time() - 48 * 3600

    removed = runtime.cleanup_stale_room_locks(max_idle_hours=24)

    assert removed == 1
    assert runtime.locks["active-room"] is active_lock
    assert "idle-room" not in runtime.locks
    assert idle_lock is not active_lock


def test_plain_answer_skip_and_previous_match_answer_grace_period():
    settings = MatchSettings(
        similarity_threshold=0.95,
        calculate_threshold=0.95,
        enable_similarity_match=False,
        enable_character_coverage_match=False,
        enable_homophone=False,
        enable_operator_alias_match=True,
        match_answer_grace_period=3.0,
    )
    player_state = {
        "previous_answer": "Amiya",
        "previous_answer_switched_at": time.time(),
    }

    assert should_skip_plain_answer_message("/fcc Amiya", is_wake_command=False)
    assert should_skip_plain_answer_message("hello", is_wake_command=True)
    assert not should_skip_plain_answer_message("Amiya", is_wake_command=False)
    assert is_recent_previous_match_answer(
        player_state,
        "Bunny",
        alias_map={"Bunny": "Amiya"},
        aliases_by_name={},
        settings=settings,
    )


def test_question_picker_filters_private_urls_and_returns_public_question():
    picker = QuestionPicker(
        {
            "Private": {"original_url": ["http://127.0.0.1/a.png"]},
            "Public": {"original_url": ["https://example.com/a.png"]},
        },
        low_weight_keywords=(),
        low_weight_ratio=0.0,
        rng=np.random.default_rng(1),
    )

    assert not is_public_http_url("http://localhost/a.png")
    assert picker.pick() == {"name": "Public", "url": "https://example.com/a.png", "fctn": 0}


def test_media_helpers_reject_private_urls_and_roundtrip_png():
    validate_public_image_url("https://example.com/a.png")
    try:
        validate_public_image_url("http://127.0.0.1/a.png")
    except ValueError:
        pass
    else:
        raise AssertionError("private image URL should be rejected")

    image = Image.new("RGB", (20, 10), "red")
    resized = resize_to_target(image, 128)
    assert resized.size == (128, 100)
    assert pil_image_to_bytes(resized).startswith(b"\x89PNG")
