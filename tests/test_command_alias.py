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
def test_original_name_kept_as_compat_alias_after_rename(harness, text):
    """重命名后 ``fcc`` 仍作为兼容别名可用，且带空格/紧凑行为一致。

    这是 `resolve_command_names(fallback=...)` 的**有意**设计：上游 `fcregex`
    本就按字面 ``fcc`` 匹配，保留它可以避免同一旧指令名出现「有空格失效、
    无空格有效」的不一致。若不希望保留，去掉调用处的 fallback 即可。
    """
    harness.set_command("猜", ())
    case = harness.run(text)
    assert case.correct == 1, f"{text!r} 兼容别名应可用: {case.texts}"


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
    for text in ("猜 能天使", "猜能天使", "fcc 能天使", "fcc能天使"):
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
