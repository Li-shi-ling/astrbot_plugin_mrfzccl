"""指令重命名 / 别名相关回归测试。

覆盖场景（对应 PR #27 的修复与评审意见）：
1. 重命名与多别名下的带空格写法；
2. 紧凑写法（``猜史尔特尔``）；
3. 部分平台残留的 ``/``、``\\`` 唤醒前缀（紧凑 + 带空格）；
4. 重命名后原始指令名作为「兼容别名」的行为一致性；
5. 同一条消息不重复判题、统计只加一次；
6. 普通消息不抢锁、不误判，紧凑写法要求唤醒与进行中的游戏；
7. 「纯文本精确匹配」开关关闭后指令写法仍可用；
8. 其它插件持有同名 handler 时不干扰本插件；
9. 纯函数（清洗 / 归一化 / 参数提取）行为。
"""

from __future__ import annotations

import pytest

ANSWER = "能天使"
OTHER = "史尔特尔"

# (指令名, 别名集合)
CONFIGS = [
    ("fcc", ()),
    ("猜", ()),
    ("fcc猜", ()),
    ("竞猜", ()),
    ("fcc", ("猜",)),
    ("fcc", ("caicai", "猜")),
    ("fcc", ("猜", "猜猜")),
]


def live_names(command_name, aliases):
    return [command_name, *aliases]


# --------------------------------------------------------------------------
# 1/2/3. 各种写法都必须判题
# --------------------------------------------------------------------------
@pytest.mark.parametrize(("command_name", "aliases"), CONFIGS)
@pytest.mark.parametrize("sep", [" ", ""], ids=["space", "compact"])
@pytest.mark.parametrize("prefix", ["", "/", "\\"], ids=["noprefix", "slash", "backslash"])
def test_command_forms_are_judged(harness, command_name, aliases, sep, prefix):
    """唤醒 + 游戏进行中时，带空格与紧凑写法都必须判题，且只判一次。

    说明：残留前缀 + 带空格写法（``/猜 能天使``）在 AstrBot 指令过滤器里无法命中，
    由插件兜底处理；``normalize`` 仍保留长度/标点守卫，只对紧凑写法生效。
    """
    harness.set_command(command_name, aliases)
    for name in live_names(command_name, aliases):
        text = f"{prefix}{name}{sep}{ANSWER}"
        case = harness.run(text)
        assert case.correct == 1, f"{text!r} 应判为正确: {case.texts}"
        assert case.wrong == 0, f"{text!r} 不应判错: {case.texts}"
        assert (case.correct_delta, case.wrong_delta) == (1, 0), f"{text!r} 计数应 +1"
        assert case.lock_calls == 1, f"{text!r} 应恰好取锁一次"
        assert "请输入要猜测的干员名称" not in case.joined, f"{text!r} 不应提示空参数"


@pytest.mark.parametrize(("command_name", "aliases"), CONFIGS)
def test_wrong_answer_is_counted_once(harness, command_name, aliases):
    """错误答案应判错并只计一次错误。"""
    harness.set_command(command_name, aliases)
    for name in live_names(command_name, aliases):
        for text in (f"{name} {OTHER}", f"{name}{OTHER}"):
            case = harness.run(text)
            assert case.wrong == 1, f"{text!r} 应判错: {case.texts}"
            assert case.correct == 0
            assert (case.correct_delta, case.wrong_delta) == (0, 1), f"{text!r} 应只计一次错误"


# --------------------------------------------------------------------------
# 4. 重命名后原始指令名 = 兼容别名（两种写法行为一致）
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["fcc 能天使", "fcc能天使"])
def test_renamed_away_name_is_not_a_hidden_alias(harness, text):
    """指令被重命名后，旧指令名不再是 AstrBot 无法感知的「隐藏别名」。

    `resolve_command_names(fallback=...)` 只在运行时名称解析失败时使用 fallback；
    否则会出现：管理员把 `fcc` 重命名后 AstrBot 认为该名称已释放（可被其它插件
    注册），本插件却仍会处理 `fcc ...`，造成重复响应且绕过冲突/权限管理。
    """
    harness.set_command("猜", ())
    case = harness.run(text)
    assert case.texts == [], f"{text!r} 重命名后不应再响应: {case.texts}"
    assert (case.correct_delta, case.wrong_delta) == (0, 0)


def test_renamed_command_still_supports_aliases(harness):
    """重命名 + 多别名同时存在时，各项名称均可用。"""
    harness.set_command("竞猜", ("猜", "caicai"))
    for name in ("竞猜", "猜", "caicai"):
        case = harness.run(f"{name} {ANSWER}")
        assert case.correct == 1, f"{name!r} 应可用: {case.texts}"


# --------------------------------------------------------------------------
# 5/6. 不重复判题、普通消息不抢锁
# --------------------------------------------------------------------------
def test_no_duplicate_judging(harness):
    """同一条指令消息不得既被指令处理、又被纯文本监听重复判题。"""
    harness.set_command("猜", ())
    for text in ("猜 能天使", "猜能天使", "/猜 能天使", "/猜能天使"):
        case = harness.run(text)
        assert case.correct + case.wrong == 1, f"{text!r} 只应判题一次: {case.texts}"
        assert case.correct_delta + case.wrong_delta == 1


def test_plain_message_does_not_take_lock(harness):
    """游戏进行中的无关发言不得抢占房间锁，也不得判题。"""
    harness.set_command("猜", ())
    case = harness.run("今天天气真不错")
    assert case.texts == [], f"无关发言不应有回复: {case.texts}"
    assert case.lock_calls == 0, "无关发言不应取锁"
    assert (case.correct_delta, case.wrong_delta) == (0, 0)


@pytest.mark.parametrize("text", ["猜不到", "猜猜我是谁呀"])
def test_non_wake_message_is_not_treated_as_guess(harness, text):
    """未唤醒时，以别名开头的普通发言不得被当作答案判错。"""
    harness.set_command("猜", ())
    case = harness.run(text, wake=False, group="g-plain")
    assert case.wrong == 0, f"{text!r} 不应被判错: {case.texts}"
    assert (case.correct_delta, case.wrong_delta) == (0, 0)
    assert case.lock_calls == 0


def test_compact_requires_active_game(harness):
    """没有进行中的游戏时，别名紧凑写法不应产生回复。"""
    harness.set_command("猜", ())
    case = harness.run("猜能天使", active_game=False)
    assert case.texts == [], f"无游戏时不应回复: {case.texts}"


def test_plain_text_answer_still_supported(harness):
    """未重命名时，纯文本精确命中答案的既有行为保持不变。"""
    harness.set_command("fcc", ())
    case = harness.run(ANSWER)
    assert case.correct == 1, f"纯文本答案应判对: {case.texts}"


# --------------------------------------------------------------------------
# 7. 纯文本匹配开关不影响指令写法
# --------------------------------------------------------------------------
def test_plain_match_setting_does_not_disable_commands(harness, plugin):
    """关闭 ``enable_other_message_exact_match`` 后指令写法仍可用。"""
    harness.set_command("猜", ())
    plugin.enable_other_message_exact_match = False
    try:
        for text in ("猜 能天使", "猜能天使", "/猜 能天使"):
            case = harness.run(text)
            assert case.correct == 1, f"{text!r} 仍应可用: {case.texts}"
        # 纯文本精确匹配被关闭，普通消息不应被判题
        case = harness.run(ANSWER)
        assert case.texts == [], f"关闭开关后不应判纯文本: {case.texts}"
    finally:
        plugin.enable_other_message_exact_match = True


# --------------------------------------------------------------------------
# 8. 其它插件同名 handler 不干扰
# --------------------------------------------------------------------------
def test_foreign_same_named_handler_is_ignored(plugin, tool_module, event_cls, make_handler):
    """activated_handlers 中出现其它插件的同名 handler 时不得算作本插件命中。"""
    own_module = plugin.__class__.__module__

    def activated(handlers) -> bool:
        event = event_cls("x")
        event.set_extra("activated_handlers", handlers)
        return tool_module.is_plugin_handler_activated(event, plugin, ("fcc",))

    assert activated([make_handler("fcc", own_module, plugin)]) is True
    # 其它插件：已绑定实例 / 未绑定实例 都不应算命中
    assert activated([make_handler("fcc", "other.plugin.main", None)]) is False
    assert activated([make_handler("fcc", "other.plugin.main", object())]) is False
    assert activated([]) is False


# --------------------------------------------------------------------------
# 9. 纯函数行为
# --------------------------------------------------------------------------
def test_pure_helpers(tool_module):
    tool = tool_module

    # 清洗：去标点、限长到 50
    assert tool.sanitize_guess_text("能天使！") == "能天使"
    assert len(tool.sanitize_guess_text("般" * 100)) == 50

    # 残留唤醒前缀
    assert tool.strip_wake_prefix("/猜能天使") == "猜能天使"
    assert tool.strip_wake_prefix("//猜能天使") == "猜能天使"
    assert tool.strip_wake_prefix("\\猜能天使") == "猜能天使"
    assert tool.strip_wake_prefix("猜能天使") == "猜能天使"

    # 参数提取：紧凑 / 带空格 / 残留前缀 / 长名优先
    names = ["fcc", "fcc猜", "猜"]
    assert tool.extract_argument_after_command("猜能天使", names) == "能天使"
    assert tool.extract_argument_after_command("猜 能天使", names) == "能天使"
    assert tool.extract_argument_after_command("/猜 能天使", names) == "能天使"
    assert tool.extract_argument_after_command("fcc猜能天使", names) == "能天使"
    assert tool.extract_argument_after_command("无关消息", names) is None

    # 紧凑归一化：含长度与标点守卫
    assert tool.normalize_compact_fc_command("fcc能天使", names) == "fcc 能天使"
    assert tool.normalize_compact_fc_command("/猜能天使", names) == "猜 能天使"
    assert tool.normalize_compact_fc_command("猜 能天使", names) is None  # 带空格不属紧凑
    assert tool.normalize_compact_fc_command("fcc" + "啊" * 20, names) is None  # 超长
    assert tool.normalize_compact_fc_command("fcc能天使，", names) is None  # 含标点

# --------------------------------------------------------------------------
# 10. 权限 / 禁用状态不得被兜底路径绕过
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["fcc能天使", "猜 能天使", "猜能天使", "/猜 能天使"])
def test_disabled_command_is_not_judged(harness, text):
    """面板中禁用 /fcc 后，任何写法都不得再判题（含 fcregex 与别名兜底）。"""
    harness.set_command("猜", ("猜",))
    md = harness.command_handler("fcc")
    md.enabled = False
    try:
        case = harness.run(text)
        assert case.texts == [], f"禁用后不应判题: {text!r} -> {case.texts}"
        assert (case.correct_delta, case.wrong_delta) == (0, 0)
    finally:
        md.enabled = True


def test_admin_only_command_blocks_member(harness):
    """把 /fcc 设为管理员指令后，普通成员不得通过别名/紧凑写法绕过。"""
    from astrbot.core.star.filter.permission import PermissionType, PermissionTypeFilter

    harness.set_command("猜", ())
    md = harness.command_handler("fcc")
    md.event_filters.append(PermissionTypeFilter(PermissionType.ADMIN))
    try:
        for text in ("猜 能天使", "猜能天使", "fcc能天使"):
            case = harness.run(text, role="member")
            assert case.texts == [], f"普通成员不应判题: {text!r} -> {case.texts}"
            assert (case.correct_delta, case.wrong_delta) == (0, 0)
        # 管理员仍可用
        case = harness.run("猜 能天使", role="admin")
        assert case.correct == 1, f"管理员应可判题: {case.texts}"
    finally:
        md.event_filters = [
            f for f in md.event_filters if not isinstance(f, PermissionTypeFilter)
        ]


# --------------------------------------------------------------------------
# 11. 原图缺失必须结束当前游戏（否则可重复刷正确次数）
# --------------------------------------------------------------------------
def test_missing_original_image_ends_game(harness):
    """有游戏但原图缓存丢失时，答对后仍必须结束房间，不能重复计分。"""
    harness.set_command("fcc", ())
    room = "no-image-room"
    first = harness.run("fcc 能天使", sender=room, image=False)
    assert first.correct == 1
    assert first.correct_delta == 1
    assert first.joined.count("无法获取正确答案图片") == 1
    # 房间必须已被清理，否则可以用同一答案继续刷分、/fc 也无法重开
    assert not harness.plugin.player.get(room), "答对后房间应已结束"
    assert not harness.plugin.original_images.get(room)
    # 再次提交同一答案（不重新注入状态）：房间已结束，不应再计分
    second = harness.run("fcc 能天使", sender=room, image=False, seed=False)
    assert second.correct_delta == 0, "房间未结束会导致重复计分"
    assert "没有初始化房间" in second.joined


# --------------------------------------------------------------------------
# 12. 并发切题：基于旧答案放行的消息必须被丢弃
# --------------------------------------------------------------------------
def test_stale_snapshot_message_is_dropped(harness):
    """锁内复查答案快照：等待锁期间题目切换后，旧事件不得被判为下一题答案。"""
    harness.set_command("fcc", ())
    plugin = harness.plugin
    uid = "stale-1"
    plugin.player[uid] = {"name": ANSWER, "status": "active"}
    from PIL import Image

    plugin.original_images[uid] = Image.new("RGB", (16, 16))

    real_lock = plugin._get_match_lock
    room_lock = real_lock(uid)

    class RacingLock:
        """进入临界区前把题目推进到下一题，模拟排队期间被切题。"""

        async def __aenter__(self):
            await room_lock.__aenter__()
            plugin.player[uid]["name"] = OTHER
            return self

        async def __aexit__(self, *exc):
            return await room_lock.__aexit__(*exc)

    plugin._get_match_lock = lambda room_id: RacingLock()
    try:
        # 消息同时包含旧答案与下一题答案
        case = harness.run(f"{ANSWER}{OTHER}", sender=uid)
        assert case.correct == 0, f"旧事件不应被判为下一题答案: {case.texts}"
        assert (case.correct_delta, case.wrong_delta) == (0, 0)
    finally:
        plugin._get_match_lock = real_lock


# --------------------------------------------------------------------------
# 13. 残留前缀下「带空格写法」与标准指令行为一致
# --------------------------------------------------------------------------
def test_retained_prefix_spaced_uses_standard_semantics(harness):
    """无进行中的游戏时，`/猜 能天使` 应像标准指令那样提示未初始化房间。"""
    harness.set_command("猜", ())
    case = harness.run("/猜 能天使", active_game=False)
    assert "没有初始化房间" in case.joined, f"应提示未初始化房间: {case.texts}"


@pytest.mark.parametrize("sep", ["\t", "\u3000"])
def test_whitespace_separated_forms_are_judged(harness, sep):
    """用制表符/全角空格分隔时也应识别为指令写法。"""
    harness.set_command("猜", ())
    case = harness.run(f"猜{sep}{ANSWER}")
    assert case.correct == 1, f"空白分隔应判题: {case.texts}"
