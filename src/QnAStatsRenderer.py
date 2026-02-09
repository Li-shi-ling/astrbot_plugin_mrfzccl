import os
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List

from html2image import Html2Image
from markdown_it import MarkdownIt

from .db.tables import UserQnAStats


class QnAStatsRenderer:
    """
    问答统计渲染器（Layout + Theme 解耦版）
    - Layout：尺寸 / 结构 / 排版
    - Theme：颜色 / 背景 / 风格
    """

    # ======================= 尺寸参数（Layout） =======================

    CARD_WIDTH = 900

    BASE_HEIGHT = 220
    TABLE_HEADER_HEIGHT = 52
    TABLE_ROW_HEIGHT = 49
    SAFE_PADDING = 80

    USER_PROFILE_HEIGHT = 750

    # ======================= init =======================

    def __init__(self, output_dir: str = "data/quiz_images", theme: str = "light"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.theme = theme

        self.md = (
            MarkdownIt(
                "commonmark",
                {
                    "html": True,
                    "linkify": True,
                    "typographer": True,
                }
            )
            .enable("table")
            .enable("strikethrough")
        )

    # ======================= CSS（核心拆分） =======================

    def _layout_css(self) -> str:
        """只管布局，不管颜色"""
        return """
        <style>
        html, body {
            width: 100%;
            height: 100%;
            margin: 0;
            padding: 0;
            background: transparent;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont,
                         "Segoe UI", "PingFang SC",
                         "Microsoft YaHei", Arial;
            overflow: hidden;
            background: transparent;
        }

        .content-container {
            width: 100%;
            min-height: 100%;
            background: #f5f5f5;
            box-sizing: border-box;
            padding: 10px;
        }

        .page {
            width: 100%;
            min-height: 100%;
            box-sizing: border-box;
            padding: 15px;
            background: transparent;
        }

        h1 {
            text-align: center;
            padding-bottom: 12px;
            margin-bottom: 15px;
            margin-top: 5px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }

        th, td {
            padding: 14px;
            text-align: left;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin-top: 20px;
        }

        .stat-box {
            border-radius: 12px;
            padding: 18px;
            text-align: center;
        }

        .stat-value {
            font-size: 26px;
            font-weight: bold;
        }

        .accuracy-bar {
            height: 10px;
            border-radius: 5px;
            overflow: hidden;
            margin: 8px 0 20px;
        }

        .accuracy-fill {
            height: 100%;
        }

        .timestamp {
            margin-top: 20px;
            margin-bottom: 15px;
            text-align: center;
            font-size: 12px;
            padding-top: 12px;
        }
        </style>
        """

    def _theme_css(self) -> str:
        """只管配色 / 风格"""
        if self.theme == "dark":
            return """
            <style>
            body {
                background: transparent;
            }

            .page {
                background: transparent;
                color: #e5e7eb;
            }

            h1 {
                border-bottom: 3px solid #38bdf8;
            }

            table th {
                background: linear-gradient(135deg, #38bdf8, #0284c7);
                color: #020617;
            }

            table td {
                border-bottom: 1px solid #334155;
            }

            tr:nth-child(even) {
                background: transparent;
            }

            .stat-box {
                background: transparent;
            }

            .stat-value {
                color: #38bdf8;
            }

            .accuracy-bar {
                background: transparent;
            }

            .accuracy-fill {
                background: linear-gradient(90deg,#22c55e,#16a34a);
            }

            .timestamp {
                color: #94a3b8;
                border-top: 1px solid #334155;
            }
            </style>
            """

        # 默认 light theme
        return """
        <style>
        body {
            background: transparent;
        }

        .page {
            background: transparent;
            color: #111;
        }

        h1 {
            border-bottom: 3px solid #3498db;
        }

        table th {
            background: linear-gradient(135deg,#3498db,#2980b9);
            color: white;
        }

        table td {
            border-bottom: 1px solid #eee;
        }

        tr:nth-child(even) {
            background:transparent;
        }

        .stat-box {
            background:transparent;
        }

        .stat-value {
            color:#3498db;
        }

        .accuracy-bar {
            background:transparent;
        }

        .accuracy-fill {
            background:linear-gradient(90deg,#2ecc71,#27ae60);
        }

        .timestamp {
            color:#999;
            border-top:1px solid #eee;
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

    # ======================= render core =======================

    def _render_markdown(self, markdown: str) -> str:
        return self.md.render(markdown)

    def _build_html(self, body: str, title: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="utf-8">
            <title>{title}</title>
            {self._layout_css()}
            {self._theme_css()}
        </head>
        <body>
            <div class="content-container">
                <div class="page">
                    {body}
                    <div class="timestamp">
                        生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    def _html_to_image(self, html: str, filename: str, width: int, height: int) -> str:
        hti = Html2Image(output_path=str(self.output_dir))

        try:
            out = f"{filename}.png"
            hti.screenshot(html_str=html, save_as=out, size=(width, height))
            return str(self.output_dir / out)
        finally:
            pass

    def render_to_image(self, markdown: str, filename: str, title: str, height: int) -> str:
        html_body = self._render_markdown(markdown)
        html = self._build_html(html_body, title)
        return self._html_to_image(html, filename, self.CARD_WIDTH, height)

    # ======================= Markdown builders（原样保留） =======================

    def format_hints_leaderboard(self, users: List[UserQnAStats]) -> str:
        md = "# 💡 提示次数排行榜\n\n"
        md += "| 排名 | 用户 | 提示 | 正确 | 错误 | 频率 |\n"
        md += "|------|------|------|------|------|------|\n"

        for i, u in enumerate(users, 1):
            total = u.correct_count + u.wrong_count
            freq = (u.tip_count / total) if total else 0
            md += f"| {i} | **{u.user_name}** | {u.tip_count} | {u.correct_count} | {u.wrong_count} | {freq:.2f}/题 |\n"

        return md

    def format_user_profile(self, u: UserQnAStats, rank: dict) -> str:
        total = u.correct_count + u.wrong_count
        acc = (u.correct_count / total * 100) if total else 0

        return f"""
# 👤 用户信息 - {u.user_name}

**用户ID**：`{u.user_id}`

## 📊 答题统计

<table>
<tr><th>类型</th><th>数量</th><th>占比</th></tr>
<tr><td>正确</td><td>{u.correct_count}</td><td>{acc:.1f}%</td></tr>
<tr><td>错误</td><td>{u.wrong_count}</td><td>{100-acc:.1f}%</td></tr>
<tr><td>提示</td><td>{u.tip_count}</td><td>-</td></tr>
</table>

<div class="accuracy-bar">
  <div class="accuracy-fill" style="width:{min(acc,100)}%"></div>
</div>

<div class="stats-grid">
  <div class="stat-box"><div>正确排名</div><div class="stat-value">#{rank.get("correct_rank","-")}</div></div>
  <div class="stat-box"><div>错误排名</div><div class="stat-value">#{rank.get("wrong_rank","-")}</div></div>
  <div class="stat-box"><div>提示排名</div><div class="stat-value">#{rank.get("tip_rank","-")}</div></div>
</div>
"""

    # ======================= Public APIs =======================

    async def generate_hints_leaderboard_image(self, users) -> str:
        md = self.format_hints_leaderboard(users)
        height = self._calc_table_height(len(users))

        name = f"hints_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.render_to_image(md, name, "提示次数排行榜", height)
        )

    async def generate_user_profile_image(self, user_stats, rank_info) -> str:
        md = self.format_user_profile(user_stats, rank_info)
        height = self.USER_PROFILE_HEIGHT

        name = f"user_profile_{user_stats.user_id}_{datetime.now():%Y%m%d_%H%M%S}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.render_to_image(md, name, f"用户信息 - {user_stats.user_name}", height)
        )

    def format_leaderboard(
        self,
        users: List[UserQnAStats],
        title: str,
        key: str,
    ) -> str:
        md = f"# {title}\n\n"
        md += "| 排名 | 用户 | 数量 | 正确 | 错误 | 提示 |\n"
        md += "|------|------|------|------|------|------|\n"

        sorted_users = sorted(
            users,
            key=lambda u: getattr(u, key),
            reverse=True
        )

        for i, u in enumerate(sorted_users, 1):
            md += (
                f"| {i} | **{u.user_name}** | "
                f"{getattr(u, key)} | "
                f"{u.correct_count} | "
                f"{u.wrong_count} | "
                f"{u.tip_count} |\n"
            )

        return md

    async def generate_correct_leaderboard_image(self, users) -> str:
        md = self.format_leaderboard(
            users,
            title="✅ 正确次数排行榜",
            key="correct_count",
        )

        height = self._calc_table_height(len(users))
        name = f"correct_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.render_to_image(md, name, "正确次数排行榜", height)
        )

    async def generate_wrong_leaderboard_image(self, users) -> str:
        md = self.format_leaderboard(
            users,
            title="❌ 错误次数排行榜",
            key="wrong_count",
        )

        height = self._calc_table_height(len(users))
        name = f"wrong_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.render_to_image(md, name, "错误次数排行榜", height)
        )
