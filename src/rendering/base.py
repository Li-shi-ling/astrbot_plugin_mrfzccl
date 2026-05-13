import asyncio
import base64
import html
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from html2image import Html2Image

    HTML2IMAGE_AVAILABLE = True
except ImportError:
    HTML2IMAGE_AVAILABLE = False

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

from ..db.tables import MatchHonor, MatchParticipant, UserQnAStats


class BaseRenderer(ABC):
    """问答统计图片渲染器抽象基类。子类只需实现 _theme_css() 即可定义主题样式。"""

    CARD_WIDTH = 900

    BASE_HEIGHT = 240
    TABLE_HEADER_HEIGHT = 54
    TABLE_ROW_HEIGHT = 46
    SAFE_PADDING = 120

    USER_PROFILE_HEIGHT = 580
    USER_PROFILE_HONOR_MAX = 5
    USER_PROFILE_HONOR_ROW_HEIGHT = 44
    USER_PROFILE_HONOR_BASE_HEIGHT = 170

    def __init__(
        self,
        output_dir: str = "data/quiz_images",
        t2i_enabled: bool = False,
        t2i_max_concurrent: int = 1,
        html_render_func: Callable[[str, dict, bool, dict | None], Awaitable[Any]]
        | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # T2I 配置
        self.t2i_enabled = bool(t2i_enabled)
        self._t2i_semaphore = asyncio.Semaphore(max(1, int(t2i_max_concurrent or 1)))
        self._html_render_func = html_render_func

        if not HTML2IMAGE_AVAILABLE and not self.t2i_enabled:
            raise ImportError(
                "Html2Image包未安装，且未启用 T2I 服务。请安装：pip install html2image 或启用 T2I 配置"
            )

        self._avatar_concurrency = 8
        self._avatar_timeout_seconds = 4

    # ======================= 子类必须实现 =======================
    @abstractmethod
    def _theme_css(self) -> str:
        """返回主题 CSS（:root 变量定义）。"""
        ...

    # ======================= 子类可选覆盖的钩子 =======================
    def _extra_height(self) -> int:
        """图片额外高度（像素风主题需要额外边框空间）。"""
        return 0

    def _body_class(self) -> str:
        """<body> 的额外 class。"""
        return ""

    def _top_bar_html(self) -> str:
        """卡片顶部的额外 HTML（像素风主题的状态栏）。"""
        return ""

    def _body_wrap_prefix(self) -> str:
        """卡片内容区域的开始包裹标签。"""
        return ""

    def _body_wrap_suffix(self) -> str:
        """卡片内容区域的结束包裹标签。"""
        return ""

    # ======================= 辅助函数 =======================
    @staticmethod
    def _esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _fmt_int(value: Any) -> str:
        try:
            return f"{int(value):,}"
        except Exception:
            return str(value)

    @staticmethod
    def _fmt_dt(value: Any) -> str:
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d %H:%M")
        return "-"

    def _rank_badge(self, rank: int) -> str:
        label = f"{rank:02d}" if rank < 100 else str(rank)
        classes = ["rank"]
        if rank == 1:
            classes.append("rank-1")
        elif rank == 2:
            classes.append("rank-2")
        elif rank == 3:
            classes.append("rank-3")
        return f'<span class="{" ".join(classes)}">{self._esc(label)}</span>'

    @staticmethod
    def _avatar_url(user_id: Any) -> str:
        return f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"

    @staticmethod
    def _pick_avatar_char(user_name: Any) -> str:
        text = str(user_name or "")
        return text[:1] if text else "U"

    async def _fetch_avatar_data_url(
        self, session: "aiohttp.ClientSession", user_id: str
    ) -> str | None:
        try:
            url = self._avatar_url(user_id)
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                content_type = (
                    (resp.headers.get("Content-Type") or "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                if not content_type.startswith("image/"):
                    content_type = "image/png"
                data = await resp.read()
                if not data:
                    return None
            b64 = base64.b64encode(data).decode("ascii")
            return f"data:{content_type};base64,{b64}"
        except Exception:
            return None

    async def _download_avatar_map(self, user_ids: list[Any]) -> dict[str, str]:
        """
        并行下载头像并返回 data-url 映射。
        - 下载失败：不返回该 key（调用方自行降级为首字头像）
        """
        unique_ids: list[str] = []
        seen: set[str] = set()
        for raw_id in user_ids:
            uid = str(raw_id or "").strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            unique_ids.append(uid)

        if not unique_ids or not AIOHTTP_AVAILABLE:
            return {}

        timeout = aiohttp.ClientTimeout(total=self._avatar_timeout_seconds)
        connector = aiohttp.TCPConnector(
            limit=self._avatar_concurrency * 2, limit_per_host=self._avatar_concurrency
        )
        headers = {"User-Agent": "Mozilla/5.0"}

        sem = asyncio.Semaphore(self._avatar_concurrency)

        async with aiohttp.ClientSession(
            timeout=timeout, connector=connector, headers=headers
        ) as session:

            async def worker(uid: str) -> tuple[str, str] | None:
                async with sem:
                    data_url = await self._fetch_avatar_data_url(session, uid)
                    if not data_url:
                        return None
                    return uid, data_url

            results = await asyncio.gather(
                *(worker(uid) for uid in unique_ids), return_exceptions=False
            )

        avatar_map: dict[str, str] = {}
        for item in results:
            if not item:
                continue
            uid, data_url = item
            avatar_map[uid] = data_url
        return avatar_map

    # ======================= 布局样式 =======================
    def _layout_css(self) -> str:
        return """
        <style>
        *{ box-sizing:border-box; }
        html, body {
            width: 100%;
            height: 100%;
            margin: 0;
            padding: 0;
        }
        body{
            font-family: "Bahnschrift", "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
            -webkit-font-smoothing: antialiased;
            color: var(--text);
            overflow: hidden;
        }

        .content-container{
            width: 100%;
            min-height: 100%;
            padding: 18px;
            position: relative;
            background:
              radial-gradient(1100px 520px at 10% 0%, var(--glow1), transparent 60%),
              radial-gradient(900px 520px at 90% 10%, var(--glow2), transparent 55%),
              linear-gradient(180deg, var(--bg0), var(--bg1));
        }
        .content-container::before{
            content:"";
            position:absolute;
            inset:0;
            z-index:0;
            background-image:
              linear-gradient(to right, var(--grid) 1px, transparent 1px),
              linear-gradient(to bottom, var(--grid) 1px, transparent 1px);
            background-size: 48px 48px;
            opacity: 0.55;
            pointer-events:none;
        }
        .page{
            position: relative;
            z-index:1;
            width: 100%;
            min-height: 100%;
            padding: 0;
        }

        .card{
            position: relative;
            z-index:0;
            width: 100%;
            min-height: 100%;
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 16px 16px 12px 16px;
            background:
              linear-gradient(180deg, var(--panel), var(--panel2));
            box-shadow:
              inset 0 0 0 1px rgba(255,255,255,0.04),
              0 18px 50px rgba(0,0,0,0.35);
            overflow: hidden;
        }
        .card::before{
            content:"";
            position:absolute;
            inset:-2px;
            z-index:0;
            background:
              repeating-linear-gradient(135deg,
                var(--stripe) 0 10px,
                rgba(0,0,0,0) 10px 26px);
            opacity: 0.08;
            pointer-events:none;
        }
        .card > *{
            position: relative;
            z-index: 1;
        }

        .header{
            position: relative;
            display:flex;
            align-items:flex-end;
            justify-content:space-between;
            gap: 16px;
            padding: 4px 2px 10px 2px;
        }
        .kicker{
            font-size: 12px;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--muted);
        }
        .title{
            margin-top: 6px;
            font-size: 26px;
            font-weight: 800;
            line-height: 1.15;
            letter-spacing: 0.02em;
        }
        .meta-group{
            display:flex;
            gap: 10px;
            align-items: stretch;
        }
        .meta{
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 8px 10px 7px 10px;
            background: rgba(255,255,255,0.03);
            min-width: 92px;
            text-align:right;
        }
        .meta-label{
            font-size: 11px;
            letter-spacing: 0.10em;
            text-transform: uppercase;
            color: var(--muted);
        }
        .meta-value{
            margin-top: 4px;
            font-size: 14px;
            font-weight: 700;
            color: var(--text);
        }
        .divider{
            height: 1px;
            background: linear-gradient(90deg, transparent, var(--line), transparent);
            margin: 8px 0 12px 0;
        }

        table.leaderboard{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            overflow: hidden;
        }
        table.leaderboard thead th{
            height: 44px;
            padding: 10px 10px;
            font-size: 12px;
            letter-spacing: 0.10em;
            text-transform: uppercase;
            color: var(--muted);
            border-bottom: 1px solid var(--line);
            background: rgba(255,255,255,0.02);
        }
        table.leaderboard tbody td{
            height: 44px;
            padding: 10px 10px;
            border-bottom: 1px solid rgba(148,163,184,0.10);
            font-size: 14px;
            vertical-align: middle;
        }
        table.leaderboard tbody tr{
            position: relative;
        }
        table.leaderboard tbody tr:nth-child(even){
            background: rgba(255,255,255,0.02);
        }
        table.leaderboard tbody tr::after{
            content:"";
            position:absolute;
            inset:0;
            background: linear-gradient(90deg, rgba(34,211,238,0.10) calc(var(--acc, 0) * 100%), transparent 0);
            opacity: 0.55;
            pointer-events:none;
        }
        table.leaderboard tbody tr.top1::after{
            background: linear-gradient(90deg, rgba(251,191,36,0.18) calc(var(--acc, 0) * 100%), transparent 0);
        }
        table.leaderboard tbody tr td, table.leaderboard tbody tr th{
            position: relative;
            z-index: 1;
        }
        .col-rank{ width: 78px; }
        .col-user{ width: 280px; }
        .user{
            display:flex;
            align-items:center;
            gap: 10px;
            min-width: 0;
        }
        .avatar-sm{
            width: 30px;
            height: 30px;
            border-radius: 10px;
            border: 1px solid var(--line);
            background:
              linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
            display:flex;
            align-items:center;
            justify-content:center;
            font-weight: 900;
            font-size: 14px;
            color: var(--accent);
            flex: 0 0 auto;
            overflow: hidden;
        }
        .avatar-sm img{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .name{
            display:block;
            overflow:hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 100%;
        }

        .rank{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-width: 52px;
            padding: 6px 10px;
            border-radius: 10px;
            border: 1px solid var(--line);
            background: rgba(255,255,255,0.03);
            font-weight: 800;
            letter-spacing: 0.08em;
        }
        .rank-1{ border-color: rgba(251,191,36,0.55); color: var(--accent); }
        .rank-2{ border-color: rgba(148,163,184,0.45); color: #e2e8f0; }
        .rank-3{ border-color: rgba(251,146,60,0.45); color: #fdba74; }

        .mono{
            font-family: "Cascadia Mono", "JetBrains Mono", Consolas, monospace;
            font-variant-numeric: tabular-nums;
        }
        .num-accent{ color: var(--accent2); font-weight: 800; }
        .num-good{ color: var(--good); font-weight: 800; }
        .num-bad{ color: var(--bad); font-weight: 800; }
        .num-warn{ color: var(--warn); font-weight: 800; }
        .chip{
            display:inline-flex;
            align-items:center;
            padding: 5px 9px;
            border-radius: 999px;
            border: 1px solid rgba(148,163,184,0.18);
            background: rgba(255,255,255,0.02);
            font-size: 12px;
            color: var(--muted);
            white-space: nowrap;
        }

        table.honors{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            overflow: hidden;
        }
        table.honors thead th{
            height: 38px;
            padding: 8px 10px;
            font-size: 11px;
            letter-spacing: 0.10em;
            text-transform: uppercase;
            color: var(--muted);
            border-bottom: 1px solid var(--line);
            background: rgba(255,255,255,0.02);
        }
        table.honors tbody td{
            height: 44px;
            padding: 10px 10px;
            border-bottom: 1px solid rgba(148,163,184,0.10);
            font-size: 14px;
            vertical-align: middle;
        }
        table.honors tbody tr:nth-child(even){
            background: rgba(255,255,255,0.02);
        }
        .col-medal{ width: 72px; }
        .col-rank2{ width: 90px; text-align:right; }
        .col-score{ width: 220px; text-align:right; }
        .honor-medal{ font-size: 18px; }

        .acc{
            display:flex;
            flex-direction: column;
            gap: 6px;
        }
        .acc-top{
            display:flex;
            align-items:baseline;
            justify-content: space-between;
            gap: 10px;
        }
        .pct{
            font-weight: 800;
            color: var(--text);
        }
        .mini-bar{
            height: 6px;
            border-radius: 999px;
            background: rgba(148,163,184,0.14);
            overflow: hidden;
        }
        .mini-fill{
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--accent2), rgba(34,211,238,0.25));
            width: 0%;
        }

        .profile-head{
            display:flex;
            align-items:center;
            justify-content: space-between;
            gap: 12px;
            padding: 6px 2px 10px 2px;
        }
        .avatar{
            width: 54px;
            height: 54px;
            border-radius: 14px;
            border: 1px solid var(--line);
            background:
              linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
            display:flex;
            align-items:center;
            justify-content:center;
            font-weight: 900;
            font-size: 22px;
            color: var(--accent);
            flex: 0 0 auto;
            overflow: hidden;
        }
        .avatar.avatar--img{
            padding: 0;
        }
        .avatar-img-lg{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .profile-main{
            flex: 1 1 auto;
            min-width: 0;
        }
        .profile-title{
            font-size: 24px;
            font-weight: 900;
            margin-top: 6px;
            overflow:hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .profile-sub{
            margin-top: 6px;
            color: var(--muted);
            font-size: 12px;
            letter-spacing: 0.04em;
        }

        .grid2{
            display:grid;
            grid-template-columns: 1.35fr 0.65fr;
            gap: 12px;
        }
        .panel{
            border: 1px solid rgba(148,163,184,0.14);
            border-radius: 12px;
            background: rgba(255,255,255,0.02);
            padding: 12px;
        }
        .panel-title{
            font-size: 12px;
            color: var(--muted);
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 10px;
        }
        .stats{
            display:grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
        }
        .stat{
            border: 1px solid rgba(148,163,184,0.14);
            border-radius: 12px;
            padding: 10px 10px 9px 10px;
            background: rgba(0,0,0,0.06);
        }
        .stat-label{
            font-size: 11px;
            color: var(--muted);
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .stat-value{
            margin-top: 8px;
            font-size: 20px;
            font-weight: 900;
            color: var(--text);
        }
        .stat.good .stat-value{ color: var(--good); }
        .stat.bad .stat-value{ color: var(--bad); }
        .stat.warn .stat-value{ color: var(--warn); }

        .progress{
            margin-top: 12px;
        }
        .progress-track{
            height: 10px;
            border-radius: 999px;
            background: rgba(148,163,184,0.14);
            overflow:hidden;
        }
        .progress-fill{
            height: 100%;
            width: 0%;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--good), rgba(52,211,153,0.25));
        }
        .progress-meta{
            margin-top: 8px;
            display:flex;
            justify-content: space-between;
            gap: 10px;
            color: var(--muted);
            font-size: 12px;
        }

        .ranks{
            display:grid;
            grid-template-columns: 1fr;
            gap: 10px;
        }
        .rank-card{
            border: 1px solid rgba(148,163,184,0.14);
            border-radius: 12px;
            padding: 10px;
            background: rgba(0,0,0,0.06);
            display:flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 10px;
        }
        .rank-label{
            font-size: 11px;
            color: var(--muted);
            letter-spacing: 0.10em;
            text-transform: uppercase;
        }
        .rank-value{
            font-size: 18px;
            font-weight: 900;
            color: var(--accent2);
        }

        .footer{
            position: relative;
            margin-top: 12px;
            padding-top: 10px;
            border-top: 1px solid rgba(148,163,184,0.14);
            display:flex;
            align-items:center;
            justify-content: space-between;
            gap: 12px;
            color: var(--muted);
            font-size: 12px;
        }
        .footer .tag{
            display:inline-flex;
            align-items:center;
            gap: 8px;
            padding: 6px 10px;
            border-radius: 999px;
            border: 1px solid rgba(148,163,184,0.14);
            background: rgba(255,255,255,0.02);
        }

        /* ======================= retro win theme overrides ======================= */
        body.theme-retro{
            font-family: "DotGothic16", "MS Gothic", "SimSun", "Microsoft YaHei", Arial, sans-serif;
            -webkit-font-smoothing: none;
        }
        body.theme-retro .content-container{
            padding: 18px;
            background-color: var(--bg0);
            background-image: radial-gradient(rgba(0,0,0,0.12) 0.5px, transparent 0.5px);
            background-size: 4px 4px;
        }
        body.theme-retro .content-container::before{ display:none; }

        body.theme-retro .card{
            border: 4px solid var(--line);
            border-radius: 0;
            padding: 0;
            background: var(--panel);
            box-shadow: 12px 12px 0 rgba(0,0,0,0.15);
        }
        body.theme-retro .card::before{ display:none; }

        body.theme-retro .retro-top-header{
            background: var(--line);
            color: #eee;
            padding: 4px 12px;
            font-family: "VT323", "Cascadia Mono", "JetBrains Mono", Consolas, monospace;
            font-size: 16px;
            letter-spacing: 1px;
            display:flex;
            justify-content: space-between;
            align-items:center;
        }
        body.theme-retro .retro-inner{
            padding: 18px 18px 12px 18px;
        }

        body.theme-retro .kicker{
            font-family: "VT323", "Cascadia Mono", Consolas, monospace;
            color: var(--text);
            letter-spacing: 0.14em;
        }
        body.theme-retro .title{
            color: var(--text);
            -webkit-text-stroke: 1px var(--line);
            text-shadow: 3px 3px 0px #fff;
            letter-spacing: -0.02em;
        }
        body.theme-retro .divider{
            height: 10px;
            border: 2px solid var(--line);
            background:
              linear-gradient(90deg,
                #a8dadc 0%,
                #a8dadc 16.6%,
                #457b9d 16.6%,
                #457b9d 33.2%,
                #f1faee 33.2%,
                #f1faee 49.8%,
                #ffb703 49.8%,
                #ffb703 66.4%,
                #fb8500 66.4%,
                #fb8500 83.0%,
                #8ecae6 83.0%,
                #8ecae6 100%);
            margin: 12px 0 14px 0;
        }

        body.theme-retro .meta{
            border: 2px solid var(--line);
            border-radius: 0;
            background: #fff;
        }
        body.theme-retro .meta-label{ color: var(--muted); }
        body.theme-retro .meta-value{ color: var(--text); }

        body.theme-retro table.leaderboard thead th{
            border-bottom: 2px solid var(--line);
            background: #fff;
            color: var(--text);
        }
        body.theme-retro table.leaderboard tbody td{
            border-bottom: 1px solid rgba(0,0,0,0.20);
        }
        body.theme-retro table.leaderboard tbody tr:nth-child(even){
            background: rgba(0,0,0,0.03);
        }
        body.theme-retro table.leaderboard tbody tr::after{
            content: none;
        }

        body.theme-retro .rank,
        body.theme-retro .avatar-sm,
        body.theme-retro .avatar{
            border: 2px solid var(--line);
            border-radius: 0;
            background: #fff;
            color: var(--accent2);
        }

        body.theme-retro .chip{
            border: 2px solid var(--line);
            border-radius: 0;
            background: #fff;
            color: var(--muted);
        }

        body.theme-retro .panel,
        body.theme-retro .rank-card,
        body.theme-retro .stat{
            border: 3px solid var(--line);
            border-radius: 0;
            background: #fff;
        }
        body.theme-retro .rank-card{
            border-width: 2px;
        }
        body.theme-retro .progress-track{
            border: 2px solid var(--line);
            border-radius: 0;
            background: #fff;
        }
        body.theme-retro .progress-fill{
            border-radius: 0;
            background: linear-gradient(90deg, var(--accent), rgba(243,152,0,0.25));
        }

        body.theme-retro table.honors thead th{
            border-bottom: 2px solid var(--line);
            background: #fff;
            color: var(--text);
        }
        body.theme-retro table.honors tbody td{
            border-bottom: 1px solid rgba(0,0,0,0.20);
        }
        body.theme-retro table.honors tbody tr:nth-child(even){
            background: rgba(0,0,0,0.03);
        }

        body.theme-retro .footer{
            border-top: 3px solid var(--line);
            color: var(--muted);
        }
        body.theme-retro .footer .tag{
            border: 2px solid var(--line);
            border-radius: 0;
            background: #fff;
        }
        </style>
        """

    # ======================= 尺寸计算 =======================
    def _calc_table_height(self, row_count: int) -> int:
        return (
            self.BASE_HEIGHT
            + self.TABLE_HEADER_HEIGHT
            + row_count * self.TABLE_ROW_HEIGHT
            + self.SAFE_PADDING
        )

    # ======================= 渲染核心 =======================
    def _build_html(self, body_html: str, title: str) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body_class = self._body_class()
        top_bar = self._top_bar_html()
        inner_open = self._body_wrap_prefix()
        inner_close = self._body_wrap_suffix()
        return f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
          <meta charset="utf-8">
          <title>{self._esc(title)}</title>
          {self._theme_css()}
          {self._layout_css()}
        </head>
        <body class="{body_class}">
          <div class="content-container">
            <div class="page">
              <div class="card">
                {top_bar}
                {inner_open}
                  {body_html}
                  <div class="footer">
                    <span class="tag">Mrfzccl · QnA Stats</span>
                    <span class="mono">{self._esc(ts)}</span>
                  </div>
                {inner_close}
              </div>
            </div>
          </div>
        </body>
        </html>
        """

    def _html_to_image(
        self, html_str: str, filename: str, width: int, height: int
    ) -> str:
        try:
            return self._html_to_image_local(html_str, filename, width, height)
        except Exception:
            import traceback as _tb

            from astrbot.api import logger as _logger

            _logger.error(f"[渲染] HTML 转图片失败: filename={filename}")
            _logger.error(_tb.format_exc())
            raise

    async def _render_html_to_image(
        self, html_str: str, filename: str, width: int, height: int
    ) -> str:
        from astrbot.api import logger as _logger

        if self.t2i_enabled and self._html_render_func is not None:
            try:
                _logger.info(
                    "[渲染] 图片生成尝试 T2I: filename=%s size=%sx%s",
                    filename,
                    width,
                    height,
                )
                return await self._html_to_image_t2i(html_str, filename, width, height)
            except Exception:
                if not HTML2IMAGE_AVAILABLE:
                    raise

                _logger.warning(
                    "[渲染] T2I 渲染失败，回退到本地 Html2Image: filename=%s",
                    filename,
                    exc_info=True,
                )
        else:
            _logger.info(
                "[渲染] 图片生成使用本地 Html2Image: filename=%s reason=%s",
                filename,
                "t2i_disabled" if not self.t2i_enabled else "html_render_missing",
            )

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self._html_to_image_local(html_str, filename, width, height)
        )

    def _html_to_image_t2i_document(
        self, html_str: str, width: int, height: int
    ) -> str:
        fixed_size_css = f"""
        <style id="mrfzccl-t2i-fixed-size">
        html, body {{
            width: {int(width)}px !important;
            min-width: {int(width)}px !important;
            max-width: {int(width)}px !important;
            height: auto !important;
            min-height: 0 !important;
            max-height: none !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: visible !important;
        }}
        .content-container {{
            width: {int(width)}px !important;
            min-width: {int(width)}px !important;
            max-width: {int(width)}px !important;
            height: auto !important;
            min-height: 0 !important;
            max-height: none !important;
            overflow: visible !important;
        }}
        .page {{
            width: 100% !important;
            height: auto !important;
            min-height: 0 !important;
            max-height: none !important;
            overflow: visible !important;
        }}
        .card {{
            width: 100% !important;
            height: auto !important;
            min-height: 0 !important;
            max-height: none !important;
        }}
        </style>
        """
        if "</head>" in html_str:
            return html_str.replace("</head>", f"{fixed_size_css}</head>", 1)
        return fixed_size_css + html_str

    def _html_to_image_local(
        self, html_str: str, filename: str, width: int, height: int
    ) -> str:
        hti = Html2Image(output_path=str(self.output_dir))
        out = f"{filename}.png"
        hti.screenshot(html_str=html_str, save_as=out, size=(width, height))
        out_path = self.output_dir / out

        from astrbot.api import logger as _logger

        _logger.info(
            "[渲染] 本地 Html2Image 完成: filename=%s path=%s", filename, out_path
        )
        return str(out_path)

    async def _html_to_image_t2i(
        self, html_str: str, filename: str, width: int, height: int
    ) -> str:
        """Render HTML through AstrBot's native html_render T2I chain."""
        if self._html_render_func is None:
            raise RuntimeError("T2I rendering requires AstrBot html_render")

        from astrbot.api import logger as _logger

        t2i_html = self._html_to_image_t2i_document(html_str, width, height)
        last_error: Exception | None = None
        async with self._t2i_semaphore:
            for index, image_options in enumerate(self._t2i_render_strategies(), 1):
                options = dict(image_options)
                if options.get("type") == "png":
                    options["quality"] = None
                try:
                    result = await self._html_render_func(t2i_html, {}, False, options)
                    path = self._write_t2i_result(result, filename)
                    _logger.info(
                        "[渲染] T2I 渲染完成: filename=%s strategy=%s type=%s result=%s path=%s",
                        filename,
                        index,
                        options.get("type"),
                        type(result).__name__,
                        path,
                    )
                    return path
                except Exception as exc:
                    last_error = exc
                    _logger.warning(
                        "[渲染] T2I 策略失败: filename=%s strategy=%s options=%s",
                        filename,
                        index,
                        options,
                        exc_info=True,
                    )

        raise RuntimeError(
            f"All T2I render strategies failed: {last_error}"
        ) from last_error

    @staticmethod
    def _t2i_render_strategies() -> list[dict[str, Any]]:
        return [
            {
                "full_page": True,
                "type": "png",
                "scale": "device",
                "device_scale_factor_level": "ultra",
            },
            {
                "full_page": True,
                "type": "jpeg",
                "quality": 100,
                "scale": "device",
                "device_scale_factor_level": "ultra",
            },
            {
                "full_page": True,
                "type": "jpeg",
                "quality": 95,
                "scale": "device",
                "device_scale_factor_level": "high",
            },
            {
                "full_page": True,
                "type": "jpeg",
                "quality": 80,
                "scale": "device",
            },
        ]

    def _write_t2i_result(self, result: Any, filename: str) -> str:
        if isinstance(result, (bytes, bytearray)):
            data = bytes(result)
            if not self._is_image_bytes(data):
                raise RuntimeError(f"T2I 返回了非图片数据（头部: {data[:10].hex()}）")
            out_path = self.output_dir / f"{filename}.png"
            with open(out_path, "wb") as f:
                f.write(data)
            return self._trim_t2i_screenshot_border(out_path, filename)

        if isinstance(result, str):
            path = Path(result)
            if path.exists():
                return self._trim_t2i_screenshot_border(path, filename)
            raise RuntimeError(f"T2I 返回了不可用的字符串结果: {result[:120]}")

        raise RuntimeError(f"T2I 返回了不支持的数据类型: {type(result).__name__}")

    @staticmethod
    def _is_image_bytes(data: bytes) -> bool:
        return data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8")

    def _trim_t2i_screenshot_border(self, image_path: Path, filename: str) -> str:
        """Crop remote T2I viewport borders while keeping local Html2Image untouched."""
        from PIL import Image, UnidentifiedImageError

        from astrbot.api import logger as _logger

        try:
            with Image.open(image_path) as image:
                source = image.convert("RGBA")
                bbox = self._t2i_content_bbox(source)
                if bbox is None:
                    _logger.info(
                        "[渲染] T2I 结果无需裁剪: filename=%s path=%s size=%sx%s reason=no_border",
                        filename,
                        image_path,
                        source.width,
                        source.height,
                    )
                    return str(image_path)

                full_bbox = (0, 0, source.width, source.height)
                if bbox == full_bbox:
                    _logger.info(
                        "[渲染] T2I 结果无需裁剪: filename=%s path=%s size=%sx%s reason=full_content",
                        filename,
                        image_path,
                        source.width,
                        source.height,
                    )
                    return str(image_path)

                cropped = self._trim_t2i_trailing_light_edges(source.crop(bbox))
                out_path = self.output_dir / f"{filename}.png"
                cropped.save(out_path)
                _logger.info(
                    "[渲染] T2I 结果裁剪白边: filename=%s source=%s original=%sx%s cropped=%sx%s path=%s",
                    filename,
                    image_path,
                    source.width,
                    source.height,
                    cropped.width,
                    cropped.height,
                    out_path,
                )
                return str(out_path)
        except (OSError, UnidentifiedImageError):
            _logger.warning(
                "[渲染] T2I 结果白边裁剪跳过: filename=%s path=%s reason=image_open_failed",
                filename,
                image_path,
                exc_info=True,
            )
            return str(image_path)

    @staticmethod
    def _t2i_content_bbox(image: Any) -> tuple[int, int, int, int] | None:
        from PIL import Image, ImageChops

        corners = [
            image.getpixel((0, 0)),
            image.getpixel((image.width - 1, 0)),
            image.getpixel((0, image.height - 1)),
            image.getpixel((image.width - 1, image.height - 1)),
        ]

        def close(
            left: tuple[int, ...], right: tuple[int, ...], tolerance: int
        ) -> bool:
            return all(
                abs(int(left_value) - int(right_value)) <= tolerance
                for left_value, right_value in zip(left, right)
            )

        background = None
        for candidate in corners:
            matches = sum(close(candidate, corner, 8) for corner in corners)
            if matches >= 2:
                background = candidate
                break
        if background is None:
            return None

        background_image = Image.new("RGBA", image.size, background)
        diff = ImageChops.difference(image, background_image).convert("L")
        mask = diff.point(lambda value: 255 if value > 12 else 0)
        return mask.getbbox()

    @staticmethod
    def _trim_t2i_trailing_light_edges(image: Any) -> Any:
        width, height = image.size
        rgb = image.convert("RGB")

        def has_dark_pixel_in_column(x: int) -> bool:
            step = max(1, height // 100)
            return any(min(rgb.getpixel((x, y))) < 210 for y in range(0, height, step))

        def has_dark_pixel_in_row(y: int) -> bool:
            step = max(1, width // 100)
            return any(min(rgb.getpixel((x, y))) < 210 for x in range(0, width, step))

        right = width
        for x in range(width - 1, -1, -1):
            if has_dark_pixel_in_column(x):
                right = x + 1
                break

        bottom = height
        for y in range(height - 1, -1, -1):
            if has_dark_pixel_in_row(y):
                bottom = y + 1
                break

        if right <= 0 or bottom <= 0 or (right == width and bottom == height):
            return image
        return image.crop((0, 0, right, bottom))

    def render_to_image(
        self, body_html: str, filename: str, title: str, height: int
    ) -> str:
        height = int(height) + self._extra_height()
        html_str = self._build_html(body_html, title)
        return self._html_to_image(html_str, filename, self.CARD_WIDTH, height)

    async def render_to_image_async(
        self, body_html: str, filename: str, title: str, height: int
    ) -> str:
        height = int(height) + self._extra_height()
        html_str = self._build_html(body_html, title)
        return await self._render_html_to_image(
            html_str, filename, self.CARD_WIDTH, height
        )

    # ======================= 内容构建（HTML）=======================
    def _build_leaderboard_body(
        self,
        users: list[UserQnAStats],
        title: str,
        sort_key: str,
        mode: str,
        avatar_map: Mapping[str, str],
    ) -> str:
        sorted_users = sorted(
            users,
            key=lambda u: self._safe_int(getattr(u, sort_key, 0), 0),
            reverse=True,
        )

        if mode == "correct":
            headers = ["排名", "用户", "正确", "错误", "提示", "准确率"]
        elif mode == "wrong":
            headers = ["排名", "用户", "错误", "正确", "提示", "准确率"]
        else:  # hints
            headers = ["排名", "用户", "提示", "正确", "错误", "频率"]

        head_html = f"""
        <div class="header">
          <div>
            <div class="kicker">Q&amp;A STATS</div>
            <div class="title">{self._esc(title)}</div>
          </div>
          <div class="meta-group">
            <div class="meta">
              <div class="meta-label">TOP</div>
              <div class="meta-value mono">{len(sorted_users)}</div>
            </div>
            <div class="meta">
              <div class="meta-label">MODE</div>
              <div class="meta-value">{self._esc(mode.upper())}</div>
            </div>
          </div>
        </div>
        <div class="divider"></div>
        """

        th_html = "".join(f"<th>{self._esc(h)}</th>" for h in headers)

        row_html_parts: list[str] = []
        for idx, u in enumerate(sorted_users, 1):
            correct = self._safe_int(getattr(u, "correct_count", 0))
            wrong = self._safe_int(getattr(u, "wrong_count", 0))
            tip = self._safe_int(getattr(u, "tip_count", 0))
            total = correct + wrong
            acc = (correct / total) if total else 0.0
            acc_pct = acc * 100.0

            user_name_raw = getattr(u, "user_name", "-")
            user_id_raw = str(getattr(u, "user_id", "") or "").strip()
            avatar_data_url = avatar_map.get(user_id_raw)
            if avatar_data_url:
                avatar_html = f'<div class="avatar-sm"><img src="{self._esc(avatar_data_url)}" /></div>'
            else:
                avatar_html = f'<div class="avatar-sm">{self._esc(self._pick_avatar_char(user_name_raw))}</div>'

            row_class = []
            if idx == 1:
                row_class.append("top1")
            row_class_str = f' class="{" ".join(row_class)}"' if row_class else ""

            rank_cell = f'<td class="col-rank">{self._rank_badge(idx)}</td>'
            user_cell = f"""
              <td class="col-user">
                <div class="user">{avatar_html}<span class="name">{self._esc(user_name_raw)}</span></div>
              </td>
            """

            if mode == "correct":
                cells = [
                    f'<td class="mono num-good">{self._fmt_int(correct)}</td>',
                    f'<td class="mono num-bad">{self._fmt_int(wrong)}</td>',
                    f'<td class="mono num-warn">{self._fmt_int(tip)}</td>',
                    self._acc_cell_html(acc_pct),
                ]
            elif mode == "wrong":
                cells = [
                    f'<td class="mono num-bad">{self._fmt_int(wrong)}</td>',
                    f'<td class="mono num-good">{self._fmt_int(correct)}</td>',
                    f'<td class="mono num-warn">{self._fmt_int(tip)}</td>',
                    self._acc_cell_html(acc_pct),
                ]
            else:
                freq = (tip / total) if total else 0.0
                cells = [
                    f'<td class="mono num-warn">{self._fmt_int(tip)}</td>',
                    f'<td class="mono num-good">{self._fmt_int(correct)}</td>',
                    f'<td class="mono num-bad">{self._fmt_int(wrong)}</td>',
                    f'<td><span class="chip mono">{freq:.2f}/题</span></td>',
                ]

            row_html = (
                f'<tr{row_class_str} style="--acc:{acc:.4f};">'
                f"{rank_cell}{user_cell}{''.join(cells)}"
                "</tr>"
            )
            row_html_parts.append(row_html)

        table_html = f"""
        <table class="leaderboard">
          <thead><tr>{th_html}</tr></thead>
          <tbody>
            {"".join(row_html_parts)}
          </tbody>
        </table>
        """

        return head_html + table_html

    def _build_match_leaderboard_body(
        self,
        participants: list[MatchParticipant],
        title: str,
        avatar_map: Mapping[str, str],
    ) -> str:
        sorted_participants = sorted(
            participants,
            key=lambda p: float(getattr(p, "score", 0.0) or 0.0),
            reverse=True,
        )

        headers = ["排名", "用户", "得分", "正确", "错误", "准确率"]

        head_html = f"""
        <div class="header">
          <div>
            <div class="kicker">MATCH</div>
            <div class="title">{self._esc(title)}</div>
          </div>
          <div class="meta-group">
            <div class="meta">
              <div class="meta-label">TOP</div>
              <div class="meta-value mono">{len(sorted_participants)}</div>
            </div>
            <div class="meta">
              <div class="meta-label">MODE</div>
              <div class="meta-value">SCORE</div>
            </div>
          </div>
        </div>
        <div class="divider"></div>
        """

        th_html = "".join(f"<th>{self._esc(h)}</th>" for h in headers)

        row_html_parts: list[str] = []
        for idx, p in enumerate(sorted_participants, 1):
            correct = self._safe_int(getattr(p, "correct_count", 0))
            wrong = self._safe_int(getattr(p, "wrong_count", 0))
            total = correct + wrong
            acc = (correct / total) if total else 0.0
            acc_pct = acc * 100.0

            try:
                score_value = float(getattr(p, "score", 0.0) or 0.0)
                score_str = f"{score_value:.2f}"
            except Exception:
                score_str = "-"

            user_name_raw = getattr(p, "user_name", "-")
            user_id_raw = str(getattr(p, "user_id", "") or "").strip()
            avatar_data_url = avatar_map.get(user_id_raw)
            if avatar_data_url:
                avatar_html = f'<div class="avatar-sm"><img src="{self._esc(avatar_data_url)}" /></div>'
            else:
                avatar_html = f'<div class="avatar-sm">{self._esc(self._pick_avatar_char(user_name_raw))}</div>'

            row_class = []
            if idx == 1:
                row_class.append("top1")
            row_class_str = f' class="{" ".join(row_class)}"' if row_class else ""

            rank_cell = f'<td class="col-rank">{self._rank_badge(idx)}</td>'
            user_cell = f"""
              <td class="col-user">
                <div class="user">{avatar_html}<span class="name">{self._esc(user_name_raw)}</span></div>
              </td>
            """

            cells = [
                f'<td class="mono num-accent">{self._esc(score_str)}</td>',
                f'<td class="mono num-good">{self._fmt_int(correct)}</td>',
                f'<td class="mono num-bad">{self._fmt_int(wrong)}</td>',
                self._acc_cell_html(acc_pct),
            ]

            row_html = (
                f'<tr{row_class_str} style="--acc:{acc:.4f};">'
                f"{rank_cell}{user_cell}{''.join(cells)}"
                "</tr>"
            )
            row_html_parts.append(row_html)

        table_html = f"""
        <table class="leaderboard">
          <thead><tr>{th_html}</tr></thead>
          <tbody>
            {"".join(row_html_parts)}
          </tbody>
        </table>
        """

        return head_html + table_html

    def _acc_cell_html(self, acc_pct: float) -> str:
        safe_pct = max(0.0, min(100.0, float(acc_pct)))
        return f"""
        <td>
          <div class="acc">
            <div class="acc-top">
              <span class="pct mono">{safe_pct:.1f}%</span>
              <span class="chip mono">{safe_pct / 100.0:.2f}</span>
            </div>
            <div class="mini-bar"><div class="mini-fill" style="width:{safe_pct:.1f}%"></div></div>
          </div>
        </td>
        """

    def _build_user_profile_body(self, u: UserQnAStats, rank: Mapping[str, Any]) -> str:
        return self._build_user_profile_body_with_avatar(u, rank, avatar_data_url=None)

    # ======================= 公开接口 =======================
    async def generate_correct_leaderboard_image(
        self, users: list[UserQnAStats]
    ) -> str:
        avatar_map = await self._download_avatar_map(
            [getattr(u, "user_id", "") for u in users]
        )
        body = self._build_leaderboard_body(
            users,
            title="正确次数排行榜",
            sort_key="correct_count",
            mode="correct",
            avatar_map=avatar_map,
        )
        height = self._calc_table_height(len(users))
        name = f"correct_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"
        return await self.render_to_image_async(body, name, "正确次数排行榜", height)

    async def generate_wrong_leaderboard_image(self, users: list[UserQnAStats]) -> str:
        avatar_map = await self._download_avatar_map(
            [getattr(u, "user_id", "") for u in users]
        )
        body = self._build_leaderboard_body(
            users,
            title="错误次数排行榜",
            sort_key="wrong_count",
            mode="wrong",
            avatar_map=avatar_map,
        )
        height = self._calc_table_height(len(users))
        name = f"wrong_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"
        return await self.render_to_image_async(body, name, "错误次数排行榜", height)

    async def generate_hints_leaderboard_image(self, users: list[UserQnAStats]) -> str:
        avatar_map = await self._download_avatar_map(
            [getattr(u, "user_id", "") for u in users]
        )
        body = self._build_leaderboard_body(
            users,
            title="提示次数排行榜",
            sort_key="tip_count",
            mode="hints",
            avatar_map=avatar_map,
        )
        height = self._calc_table_height(len(users))
        name = f"hints_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"
        return await self.render_to_image_async(body, name, "提示次数排行榜", height)

    async def generate_match_leaderboard_image(
        self,
        match_name: str,
        participants: list[MatchParticipant],
        title: str | None = None,
    ) -> str:
        participants = list(participants or [])
        title_text = title or f"比赛「{match_name}」排行榜"
        avatar_map = await self._download_avatar_map(
            [getattr(p, "user_id", "") for p in participants]
        )
        body = self._build_match_leaderboard_body(participants, title_text, avatar_map)
        height = self._calc_table_height(len(participants))
        name = f"match_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"
        return await self.render_to_image_async(body, name, title_text, height)

    async def generate_user_profile_image(
        self,
        user_stats: UserQnAStats,
        rank_info: Mapping[str, Any],
        honors: list[MatchHonor] | None = None,
    ) -> str:
        avatar_map = await self._download_avatar_map(
            [getattr(user_stats, "user_id", "")]
        )
        avatar_data_url = avatar_map.get(
            str(getattr(user_stats, "user_id", "") or "").strip()
        )
        honor_list = list(honors or [])[: self.USER_PROFILE_HONOR_MAX]
        body = self._build_user_profile_body_with_avatar(
            user_stats, rank_info, avatar_data_url, honor_list
        )
        name = f"user_profile_{getattr(user_stats, 'user_id', 'unknown')}_{datetime.now():%Y%m%d_%H%M%S}"
        height = self.USER_PROFILE_HEIGHT
        if honor_list:
            height += (
                self.USER_PROFILE_HONOR_BASE_HEIGHT
                + len(honor_list) * self.USER_PROFILE_HONOR_ROW_HEIGHT
            )
        return await self.render_to_image_async(body, name, "用户信息", height)

    def _build_user_honor_section(self, honors: list[MatchHonor]) -> str:
        if not honors:
            return ""

        row_html_parts: list[str] = []
        for h in honors[: self.USER_PROFILE_HONOR_MAX]:
            medal = getattr(h, "medal", "")
            match_name = getattr(h, "match_name", "-")
            rank = getattr(h, "rank", "-")

            correct = self._safe_int(getattr(h, "correct_count", 0))
            wrong = self._safe_int(getattr(h, "wrong_count", 0))
            score = getattr(h, "score", 0.0)
            try:
                score_str = f"{float(score):.1f}"
            except Exception:
                score_str = "-"

            row_html_parts.append(
                f"""
                <tr>
                  <td class="col-medal"><span class="honor-medal">{self._esc(medal)}</span></td>
                  <td><span class="name">{self._esc(match_name)}</span></td>
                  <td class="mono col-rank2">#{self._esc(rank)}</td>
                  <td class="mono col-score"><span class="num-good">{self._fmt_int(correct)}</span>/<span class="num-bad">{self._fmt_int(wrong)}</span> <span class="chip">S {self._esc(score_str)}</span></td>
                </tr>
                """
            )

        rows_html = "".join(row_html_parts)
        return f"""
        <div class="divider"></div>
        <div class="panel honor-panel">
          <div class="panel-title">比赛荣誉</div>
          <table class="honors">
            <thead>
              <tr>
                <th class="col-medal">奖牌</th>
                <th>比赛</th>
                <th class="col-rank2">名次</th>
                <th class="col-score">战绩</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
          </table>
        </div>
        """

    def _build_user_profile_body_with_avatar(
        self,
        u: UserQnAStats,
        rank: Mapping[str, Any],
        avatar_data_url: str | None,
        honors: list[MatchHonor] | None = None,
    ) -> str:
        user_name_raw = getattr(u, "user_name", "-")
        user_id_raw = getattr(u, "user_id", "-")

        correct = self._safe_int(getattr(u, "correct_count", 0))
        wrong = self._safe_int(getattr(u, "wrong_count", 0))
        tip = self._safe_int(getattr(u, "tip_count", 0))
        total = correct + wrong
        acc_pct = (correct / total * 100.0) if total else 0.0
        freq = (tip / total) if total else 0.0

        created_at = self._fmt_dt(getattr(u, "created_at", None))
        updated_at = self._fmt_dt(getattr(u, "updated_at", None))

        avatar_char = self._pick_avatar_char(user_name_raw)

        correct_rank = rank.get("correct_rank", "-")
        wrong_rank = rank.get("wrong_rank", "-")
        tip_rank = rank.get("tip_rank", "-")

        avatar_block = (
            f'<div class="avatar avatar--img"><img class="avatar-img-lg" src="{self._esc(avatar_data_url)}" /></div>'
            if avatar_data_url
            else f'<div class="avatar">{self._esc(avatar_char)}</div>'
        )

        honor_section = self._build_user_honor_section(list(honors or []))

        return f"""
        <div class="profile-head">
          {avatar_block}
          <div class="profile-main">
            <div class="kicker">USER PROFILE</div>
            <div class="profile-title">{self._esc(user_name_raw)}</div>
            <div class="profile-sub">ID · <span class="mono">{self._esc(user_id_raw)}</span> · 频率 <span class="mono">{freq:.2f}/题</span></div>
          </div>
          <div class="meta-group">
            <div class="meta">
              <div class="meta-label">ACCURACY</div>
              <div class="meta-value mono">{max(0.0, min(100.0, acc_pct)):.1f}%</div>
            </div>
          </div>
        </div>
        <div class="divider"></div>

        <div class="grid2">
          <div class="panel">
            <div class="panel-title">统计</div>
            <div class="stats">
              <div class="stat good"><div class="stat-label">正确</div><div class="stat-value mono">{self._fmt_int(correct)}</div></div>
              <div class="stat bad"><div class="stat-label">错误</div><div class="stat-value mono">{self._fmt_int(wrong)}</div></div>
              <div class="stat warn"><div class="stat-label">提示</div><div class="stat-value mono">{self._fmt_int(tip)}</div></div>
            </div>
            <div class="progress">
              <div class="progress-track"><div class="progress-fill" style="width:{max(0.0, min(100.0, acc_pct)):.1f}%"></div></div>
              <div class="progress-meta">
                <span>总题数 <span class="mono">{self._fmt_int(total)}</span></span>
                <span>准确率 <span class="mono">{max(0.0, min(100.0, acc_pct)):.1f}%</span></span>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-title">排名</div>
            <div class="ranks">
              <div class="rank-card"><span class="rank-label">正确</span><span class="rank-value mono">#{self._esc(correct_rank)}</span></div>
              <div class="rank-card"><span class="rank-label">错误</span><span class="rank-value mono">#{self._esc(wrong_rank)}</span></div>
              <div class="rank-card"><span class="rank-label">提示</span><span class="rank-value mono">#{self._esc(tip_rank)}</span></div>
            </div>
            <div style="margin-top:10px; color:var(--muted); font-size:12px;">
              创建 <span class="mono">{self._esc(created_at)}</span><br/>
              更新 <span class="mono">{self._esc(updated_at)}</span>
            </div>
          </div>
        </div>
        {honor_section}
        """
