import asyncio
import html
from datetime import datetime
from pathlib import Path
from typing import Any, List, Mapping

try:
    from html2image import Html2Image

    HTML2IMAGE_AVAILABLE = True
except ImportError:
    HTML2IMAGE_AVAILABLE = False

from .db.tables import UserQnAStats


class QnAStatsRenderer:
    """
    工业风问答统计图片渲染器（HTML -> Image）。

    设计目标：
    - 工业风格 UI（深色面板 / 网格纹理 / 高对比强调色）
    - 删除 markdown-it-py 依赖：避免 Markdown 渲染与潜在的 HTML 注入
    - 对外接口保持兼容：generate_*_image
    """

    CARD_WIDTH = 900

    BASE_HEIGHT = 240
    TABLE_HEADER_HEIGHT = 54
    TABLE_ROW_HEIGHT = 46
    SAFE_PADDING = 120

    USER_PROFILE_HEIGHT = 820

    def __init__(self, output_dir: str = "data/quiz_images", theme: str = "industrial"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.theme = (theme or "industrial").strip().lower()

        if not HTML2IMAGE_AVAILABLE:
            raise ImportError("Html2Image包未安装，无法生成图片。请安装：pip install html2image")

    # ======================= helpers =======================

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

    # ======================= CSS =======================

    def _theme_css(self) -> str:
        if self.theme in {"light", "white"}:
            return """
            <style>
            :root{
              --bg0:#f6f7fb;
              --bg1:#eef2f7;
              --panel:rgba(255,255,255,0.92);
              --panel2:rgba(248,250,252,0.92);
              --line:rgba(2,6,23,0.12);
              --text:#0f172a;
              --muted:#475569;
              --accent:#b45309;
              --accent2:#0ea5e9;
              --good:#16a34a;
              --bad:#e11d48;
              --warn:#b45309;
            }
            </style>
            """

        # industrial (default)
        return """
        <style>
        :root{
          --bg0:#070a0f;
          --bg1:#0b1220;
          --panel:rgba(17,24,39,0.92);
          --panel2:rgba(2,6,23,0.92);
          --line:rgba(148,163,184,0.18);
          --text:#e5e7eb;
          --muted:#94a3b8;
          --accent:#fbbf24;
          --accent2:#22d3ee;
          --good:#34d399;
          --bad:#fb7185;
          --warn:#fbbf24;
        }
        </style>
        """

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
              radial-gradient(1100px 520px at 10% 0%, rgba(34,211,238,0.14), transparent 60%),
              radial-gradient(900px 520px at 90% 10%, rgba(251,191,36,0.10), transparent 55%),
              linear-gradient(180deg, var(--bg0), var(--bg1));
        }
        .content-container::before{
            content:"";
            position:absolute;
            inset:0;
            z-index:0;
            background-image:
              linear-gradient(to right, rgba(148,163,184,0.06) 1px, transparent 1px),
              linear-gradient(to bottom, rgba(148,163,184,0.06) 1px, transparent 1px);
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
                rgba(251,191,36,0.08) 0 10px,
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
        </style>
        """

    # ======================= size =======================

    def _calc_table_height(self, row_count: int) -> int:
        return (
            self.BASE_HEIGHT
            + self.TABLE_HEADER_HEIGHT
            + row_count * self.TABLE_ROW_HEIGHT
            + self.SAFE_PADDING
        )

    # ======================= render core =======================

    def _build_html(self, body_html: str, title: str) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
          <meta charset="utf-8">
          <title>{self._esc(title)}</title>
          {self._theme_css()}
          {self._layout_css()}
        </head>
        <body>
          <div class="content-container">
            <div class="page">
              <div class="card">
                {body_html}
                <div class="footer">
                  <span class="tag">Mrfzccl · QnA Stats</span>
                  <span class="mono">{self._esc(ts)}</span>
                </div>
              </div>
            </div>
          </div>
        </body>
        </html>
        """

    def _html_to_image(self, html_str: str, filename: str, width: int, height: int) -> str:
        hti = Html2Image(output_path=str(self.output_dir))
        out = f"{filename}.png"
        hti.screenshot(html_str=html_str, save_as=out, size=(width, height))
        return str(self.output_dir / out)

    def render_to_image(self, body_html: str, filename: str, title: str, height: int) -> str:
        html_str = self._build_html(body_html, title)
        return self._html_to_image(html_str, filename, self.CARD_WIDTH, height)

    # ======================= body builders (HTML) =======================

    def _build_leaderboard_body(
        self,
        users: List[UserQnAStats],
        title: str,
        sort_key: str,
        mode: str,
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

        row_html_parts: List[str] = []
        for idx, u in enumerate(sorted_users, 1):
            correct = self._safe_int(getattr(u, "correct_count", 0))
            wrong = self._safe_int(getattr(u, "wrong_count", 0))
            tip = self._safe_int(getattr(u, "tip_count", 0))
            total = correct + wrong
            acc = (correct / total) if total else 0.0
            acc_pct = acc * 100.0

            row_class = []
            if idx == 1:
                row_class.append("top1")
            row_class_str = f' class="{" ".join(row_class)}"' if row_class else ""

            rank_cell = f'<td class="col-rank">{self._rank_badge(idx)}</td>'
            user_cell = f"""
              <td class="col-user">
                <div class="user"><span class="name">{self._esc(getattr(u, "user_name", "-"))}</span></div>
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
            {''.join(row_html_parts)}
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
              <span class="chip mono">{safe_pct/100.0:.2f}</span>
            </div>
            <div class="mini-bar"><div class="mini-fill" style="width:{safe_pct:.1f}%"></div></div>
          </div>
        </td>
        """

    def _build_user_profile_body(self, u: UserQnAStats, rank: Mapping[str, Any]) -> str:
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

        avatar_char = str(user_name_raw)[:1] if str(user_name_raw) else "U"

        correct_rank = rank.get("correct_rank", "-")
        wrong_rank = rank.get("wrong_rank", "-")
        tip_rank = rank.get("tip_rank", "-")

        return f"""
        <div class="profile-head">
          <div class="avatar">{self._esc(avatar_char)}</div>
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
        """

    # ======================= Public APIs =======================

    async def generate_correct_leaderboard_image(self, users: List[UserQnAStats]) -> str:
        body = self._build_leaderboard_body(users, title="正确次数排行榜", sort_key="correct_count", mode="correct")
        height = self._calc_table_height(len(users))
        name = f"correct_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.render_to_image(body, name, "正确次数排行榜", height),
        )

    async def generate_wrong_leaderboard_image(self, users: List[UserQnAStats]) -> str:
        body = self._build_leaderboard_body(users, title="错误次数排行榜", sort_key="wrong_count", mode="wrong")
        height = self._calc_table_height(len(users))
        name = f"wrong_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.render_to_image(body, name, "错误次数排行榜", height),
        )

    async def generate_hints_leaderboard_image(self, users: List[UserQnAStats]) -> str:
        body = self._build_leaderboard_body(users, title="提示次数排行榜", sort_key="tip_count", mode="hints")
        height = self._calc_table_height(len(users))
        name = f"hints_leaderboard_{datetime.now():%Y%m%d_%H%M%S}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.render_to_image(body, name, "提示次数排行榜", height),
        )

    async def generate_user_profile_image(self, user_stats: UserQnAStats, rank_info: Mapping[str, Any]) -> str:
        body = self._build_user_profile_body(user_stats, rank_info)
        name = f"user_profile_{getattr(user_stats, 'user_id', 'unknown')}_{datetime.now():%Y%m%d_%H%M%S}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.render_to_image(body, name, "用户信息", self.USER_PROFILE_HEIGHT),
        )
