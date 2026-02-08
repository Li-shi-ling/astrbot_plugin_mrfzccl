import os
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from html2image import Html2Image
from markdown_it import MarkdownIt

from .db.tables import UserQnAStats


class QnAStatsRenderer:
    """
    问答统计渲染器（生产级）
    - 宽高完全人工计算
    - 不依赖 html2image 的自动高度
    """

    # ======================= 尺寸参数（核心） =======================

    CARD_WIDTH = 900

    # 高度相关（px）
    BASE_HEIGHT = 220        # padding + title + timestamp
    TABLE_HEADER_HEIGHT = 52
    TABLE_ROW_HEIGHT = 44
    SAFE_PADDING = 80        # 防止被截断

    USER_PROFILE_HEIGHT = 900

    # ======================= init =======================

    def __init__(self, output_dir: str = "data/quiz_images"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

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

        self.css = """
        <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont,
                         "Segoe UI", "PingFang SC",
                         "Microsoft YaHei", Arial;
            padding: 0;
            background: linear-gradient(135deg,#f5f7fa,#c3cfe2);
            margin: 0;
        }

        .card {
            background: #fff;
            border-radius: 16px;
            padding: 28px;
            max-width: 860px;
            margin: auto;
            box-shadow: 0 12px 30px rgba(0,0,0,.12);
            width: 100%;
            max-width: none;
            margin: 0;
        }

        h1 {
            text-align:center;
            border-bottom:3px solid #3498db;
            padding-bottom:12px;
        }

        table {
            width:100%;
            border-collapse:collapse;
            margin:20px 0;
        }

        th {
            background: linear-gradient(135deg,#3498db,#2980b9);
            color:white;
            padding:14px;
        }

        td {
            padding:12px 14px;
            border-bottom:1px solid #eee;
        }

        tr:nth-child(even) {
            background:#f8f9fa;
        }

        .badge {
            display:inline-block;
            padding:4px 10px;
            border-radius:14px;
            font-size:12px;
            font-weight:bold;
            color:white;
        }

        .badge-correct { background:#27ae60; }
        .badge-wrong   { background:#e74c3c; }
        .badge-tip     { background:#f39c12; }

        .stats-grid {
            display:grid;
            grid-template-columns:repeat(3,1fr);
            gap:16px;
            margin-top:20px;
        }

        .stat-box {
            background:#f8f9fa;
            border-radius:12px;
            padding:18px;
            text-align:center;
        }

        .stat-value {
            font-size:26px;
            font-weight:bold;
            color:#3498db;
        }

        .accuracy-bar {
            height:10px;
            background:#ecf0f1;
            border-radius:5px;
            overflow:hidden;
            margin:8px 0 20px;
        }

        .accuracy-fill {
            height:100%;
            background:linear-gradient(90deg,#2ecc71,#27ae60);
        }

        .timestamp {
            margin-top:24px;
            text-align:center;
            font-size:12px;
            color:#999;
            border-top:1px solid #eee;
            padding-top:12px;
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
            {self.css}
        </head>
        <body>
            <div class="card">
                {body}
                <div class="timestamp">
                    生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
            </div>
        </body>
        </html>
        """

    def _html_to_image(self, html: str, filename: str, width: int, height: int) -> str:
        hti = Html2Image(
            output_path=str(self.output_dir),
            size=(width, height),
            custom_flags=[
                "--disable-smart-width",
                "--hide-scrollbars",
            ],
        )

        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html)
            temp_path = f.name

        try:
            out = f"{filename}.png"
            hti.screenshot(html_file=temp_path, save_as=out)
            return str(self.output_dir / out)
        finally:
            os.unlink(temp_path)

    def render_to_image(self, markdown: str, filename: str, title: str, height: int) -> str:
        html_body = self._render_markdown(markdown)
        html = self._build_html(html_body, title)
        return self._html_to_image(html, filename, self.CARD_WIDTH, height)

    # ======================= Markdown builders =======================

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
<tr><td><span class="badge badge-correct">正确</span></td><td>{u.correct_count}</td><td>{acc:.1f}%</td></tr>
<tr><td><span class="badge badge-wrong">错误</span></td><td>{u.wrong_count}</td><td>{100-acc:.1f}%</td></tr>
<tr><td><span class="badge badge-tip">提示</span></td><td>{u.tip_count}</td><td>-</td></tr>
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

    # ======================= Public APIs（不变） =======================

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
