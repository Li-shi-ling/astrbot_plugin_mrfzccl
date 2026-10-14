"""pytest 夹具：实例化插件并模拟 AstrBot 的 handler 绑定与事件派发。

设计要点：
* 仅依赖 ``astrbot`` / ``PIL`` / ``pypinyin`` / ``numpy``；缺少时整体 skip，
  便于在未安装 AstrBot 的环境里优雅跳过而不是报错。
* 用一个 session 级事件循环，避免 aiosqlite 连接跨事件循环导致的报错。
* 用真实 filter 判定 handler 激活、按注册顺序真实派发，可自动发现
  「漏判」与「重复判题」两类问题。
"""

from __future__ import annotations

import asyncio
import functools
import importlib
import importlib.util
import inspect
import os
import pathlib
import sys
import types
from dataclasses import dataclass, field

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = f"{REPO_ROOT.name}.main"


@pytest.fixture(scope="session")
def loop():
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    yield _loop
    _loop.close()


@pytest.fixture(scope="session")
def plugin(tmp_path_factory, loop):
    # 依赖缺失时默认**显式失败**而不是静默跳过：否则 CI 里一旦 AstrBot 装不上，
    # 测试会全部 skip 而工作流仍然变绿，失去回归保护的意义。
    missing = [
        name
        for name in ("astrbot", "PIL", "pypinyin", "numpy")
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        if os.environ.get("MRFZCCL_SKIP_WITHOUT_ASTRBOT") == "1":
            pytest.skip(f"缺少依赖 {missing}，已按 MRFZCCL_SKIP_WITHOUT_ASTRBOT=1 跳过")
        pytest.fail(
            "回归测试需要 AstrBot 运行时，缺少依赖: "
            f"{', '.join(missing)}\n"
            "请先安装：\n"
            "    pip install -r requirements.txt astrbot pytest\n"
            "若确实想跳过，可设置环境变量 MRFZCCL_SKIP_WITHOUT_ASTRBOT=1。",
            pytrace=False,
        )

    if str(REPO_ROOT.parent) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT.parent))

    import astrbot.core.star.star_handler as sh
    import astrbot.core.star.star_tools as star_tools

    # 把插件数据目录指向临时目录（sqlite 数据库、原始图缓存都落在这里）
    data_dir = tmp_path_factory.mktemp("mrfzccl_data")
    star_tools.StarTools.get_data_dir = classmethod(lambda cls, name=None: data_dir)

    main = importlib.import_module(MODULE_PATH)
    instance = main.Mrfzccl(
        context=types.SimpleNamespace(),
        config={"require_admin": False},
    )
    loop.run_until_complete(instance.initialize())

    # 模拟 star_manager 的 handler 绑定：handler = functools.partial(raw, star)
    for md in sh.star_handlers_registry.get_handlers_by_module_name(MODULE_PATH):
        raw = md.handler.func if isinstance(md.handler, functools.partial) else md.handler
        md.handler = functools.partial(raw, instance)

    return instance


class FakeEvent:
    """尽量贴近 AstrMessageEvent 对外契约（get_extra 为真实签名）。"""

    def __init__(self, text, sender="10001", group=None, wake=True, role="member"):
        self.message_str = text
        self._sender = str(sender)
        self._group = group
        self.role = role
        self.is_at_or_wake_command = wake
        self.unified_msg_origin = (
            f"aiocqhttp:group:{group}" if group else f"aiocqhttp:private:{sender}"
        )
        self._extras: dict = {}

    def get_group_id(self):
        return self._group

    def get_sender_id(self):
        return self._sender

    def get_sender_name(self):
        return f"user{self._sender}"

    def get_message_str(self):
        return self.message_str

    def is_admin(self):
        return self.role == "admin"

    def get_message_type(self):
        from astrbot.core.platform.message_type import MessageType

        return MessageType.GROUP_MESSAGE if self._group else MessageType.FRIEND_MESSAGE

    def get_extra(self, key: str | None = None, default=None):
        return self._extras if key is None else self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value

    def chain_result(self, comps):
        return ("chain", [getattr(c, "text", str(c)) for c in comps])

    def plain_result(self, text):
        return ("plain", text)


@dataclass
class Case:
    """一次派发的结果快照。"""

    texts: list[str] = field(default_factory=list)
    correct_delta: int = 0
    wrong_delta: int = 0
    lock_calls: int = 0
    judged: int = 0

    @property
    def correct(self) -> int:
        return sum(1 for t in self.texts if "回答正确" in t)

    @property
    def wrong(self) -> int:
        return sum(1 for t in self.texts if "回答错误" in t)

    @property
    def joined(self) -> str:
        return "\n".join(self.texts)


class Harness:
    """把「改指令名 → 造事件 → 真实派发 → 采集结果」封装成一步操作。"""

    def __init__(self, plugin, loop):
        self.plugin = plugin
        self.loop = loop
        self._n = 0

    # ---------- 指令名配置 ----------
    def set_command(self, command_name: str, aliases=()):
        """模拟面板重命名 / 配置别名。"""
        from astrbot.core.star.filter.command import CommandFilter

        md = self._handler("fcc")
        flt = next(f for f in md.event_filters if isinstance(f, CommandFilter))
        flt.command_name = command_name
        flt.alias = set(aliases or ())
        flt._cmpl_cmd_names = None

    def command_handler(self, name: str = "fcc"):
        """取到已绑定的指令 handler 元数据，便于测试里模拟禁用/加权限过滤器。"""
        for md in self._activated_pool():
            if md.handler_name == name:
                return md
        raise AssertionError(f"未找到 handler: {name}")

    # ---------- 事件派发 ----------
    def _handler(self, name: str):
        for md in self._activated_pool():
            if md.handler_name == name:
                return md
        raise AssertionError(f"未找到 handler: {name}")

    def _activated_pool(self):
        import astrbot.core.star.star_handler as sh

        # 与生产一致：面板中禁用的 handler 不会进入事件派发
        return [
            md
            for md in sh.star_handlers_registry.get_handlers_by_module_name(MODULE_PATH)
            if md.enabled
        ]

    def activate(self, event) -> list:
        """用真实 filter 复现 waking_check 的激活判定。"""
        from astrbot.core.star.filter.command_group import CommandGroupFilter

        activated = []
        for md in self._activated_pool():
            if not md.event_filters:
                continue
            if any(isinstance(f, CommandGroupFilter) for f in md.event_filters):
                continue
            if all(f.filter(event, {}) for f in md.event_filters):
                activated.append(md)
        event.set_extra("activated_handlers", activated)
        event.set_extra("handlers_parsed_params", {})
        return activated

    async def _dispatch(self, event) -> list[str]:
        out: list[str] = []
        for md in event.get_extra("activated_handlers") or []:
            gen = md.handler(event)
            if inspect.isasyncgen(gen):
                async for r in gen:
                    out.append(r)
            else:
                r = await gen
                if r is not None:
                    out.append(r)
        return out

    # ---------- 对外用例入口 ----------
    def run(
        self,
        text,
        *,
        sender=None,
        group=None,
        wake=True,
        answer="能天使",
        active_game=True,
        image=True,
        role="member",
        seed=True,
    ) -> Case:
        """派发一条消息并返回结果。

        seed=False 表示**不重新注入**游戏状态，用于验证「答对后房间是否真的结束」
        这类需要连续两次派发同一房间的场景。
        """
        self._n += 1
        uid = sender or f"u{self._n}"
        room = group if group is not None else uid
        if seed:
            if active_game:
                self.plugin.player[room] = {"name": answer, "status": "active"}
            else:
                self.plugin.player.pop(room, None)
            if image:
                from PIL import Image

                self.plugin.original_images[room] = Image.new("RGB", (32, 32))
            else:
                self.plugin.original_images.pop(room, None)
        async def _scenario():
            before = await self.plugin.user_qna_repo.get_user_stats(uid)
            calls = {"n": 0}
            original_lock = self.plugin._get_match_lock

            def spy(room_id):
                calls["n"] += 1
                return original_lock(room_id)

            self.plugin._get_match_lock = spy
            try:
                event = FakeEvent(
                    text, sender=uid, group=group, wake=wake, role=role
                )
                self.activate(event)
                results = await self._dispatch(event)
            finally:
                self.plugin._get_match_lock = original_lock
            after = await self.plugin.user_qna_repo.get_user_stats(uid)
            payload = []
            for r in results:
                if isinstance(r, tuple) and r[0] == "plain":
                    payload.append(str(r[1]))
                elif isinstance(r, tuple) and r[0] == "chain":
                    payload.extend(str(x) for x in r[1])
                else:
                    payload.append(str(r))
            return Case(
                texts=payload,
                correct_delta=(after.correct_count if after else 0)
                - (before.correct_count if before else 0),
                wrong_delta=(after.wrong_count if after else 0)
                - (before.wrong_count if before else 0),
                lock_calls=calls["n"],
            )

        return self.loop.run_until_complete(_scenario())


@pytest.fixture(scope="session")
def harness(plugin, loop) -> Harness:
    return Harness(plugin, loop)


@pytest.fixture(scope="session")
def tool_module(plugin):
    """插件自身的 src.tool 模块。"""
    return importlib.import_module(f"{plugin.__class__.__module__.rsplit('.', 1)[0]}.src.tool")


@pytest.fixture(scope="session")
def event_cls():
    """构造事件用的 FakeEvent 类。"""
    return FakeEvent


@pytest.fixture(scope="session")
def make_handler():
    """构造 StarHandlerMetadata，用于验证同名 handler 的归属判定。"""
    from astrbot.core.star.star_handler import EventType, StarHandlerMetadata

    def _make(name: str, module_path: str, owner=None):
        def raw(self, event, **kwargs):
            ...

        raw.__name__ = name
        raw.__module__ = module_path
        handler = functools.partial(raw, owner) if owner is not None else raw
        return StarHandlerMetadata(
            event_type=EventType.AdapterMessageEvent,
            handler_full_name=f"{module_path}_{name}",
            handler_name=name,
            handler_module_path=module_path,
            handler=handler,
            event_filters=[],
        )

    return _make
