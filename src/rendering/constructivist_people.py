import base64
from functools import lru_cache
from pathlib import Path

from .base import BaseRenderer


@lru_cache(maxsize=32)
def _asset_data_url(filename: str) -> str:
    asset_path = (
        Path(__file__).resolve().parents[2]
        / "assets"
        / "constructivist_people"
        / filename
    )

    try:
        data = asset_path.read_bytes()
    except OSError:
        return ""

    suffix = asset_path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix

    return f"data:image/{mime};base64,{base64.b64encode(data).decode('ascii')}"


class ConstructivistPeopleRenderer(BaseRenderer):
    FRAME_EXTRA_HEIGHT = 44

    def _extra_height(self) -> int:
        return self.FRAME_EXTRA_HEIGHT

    def _body_class(self) -> str:
        return "theme-people-we"

    def _top_bar_html(self) -> str:
        return """
        <div class="peoplewe-topbar">
          <span class="peoplewe-brand">Arknights Design // PEOPLE, WE</span>
          <span class="peoplewe-status">QNA RECORD BOARD_</span>
        </div>
        """

    def _body_wrap_prefix(self) -> str:
        return '<div class="peoplewe-inner">'

    def _body_wrap_suffix(self) -> str:
        return "</div>"

    def _theme_css(self) -> str:
        home_bg = _asset_data_url("people_we_home_bg.jpg")
        detail_bg = _asset_data_url("people_we_detail_bg.jpg")

        name_label = _asset_data_url("name_label.png")

        red_mark = _asset_data_url("red_brush_mark.png")
        barrage = _asset_data_url("barrage_strip.png")

        frame_wide = _asset_data_url("photo_frame_wide.png")
        frame_large = _asset_data_url("photo_frame_large.png")

        return f"""
        <style>

        :root{{
          --bg0:#e8e5dc;
          --bg1:#cfcfc9;

          --line:#262522;
          --text:#24231f;
          --muted:#6f6c61;

          --accent:#9f302a;

          --good:#455746;
          --bad:#9f302a;
          --warn:#8f5b3f;

          --people-home:url("{home_bg}");
          --people-detail:url("{detail_bg}");

          --people-name:url("{name_label}");

          --people-red-mark:url("{red_mark}");
          --people-barrage:url("{barrage}");

          --people-frame-wide:url("{frame_wide}");
          --people-frame-large:url("{frame_large}");
        }}

        body.theme-people-we {{
          font-family:
            "Bahnschrift",
            "Microsoft YaHei",
            "PingFang SC",
            sans-serif;

          letter-spacing:0.01em;
        }}

        body.theme-people-we .content-container {{
          padding:22px;

          background:
            linear-gradient(
              180deg,
              rgba(232,229,220,0.20),
              rgba(10,10,10,0.26)
            ),
            var(--people-home) no-repeat center / cover,
            linear-gradient(180deg, var(--bg0), var(--bg1));
        }}

        body.theme-people-we .card {{
          border:0;
          border-radius:0;
          padding:0;

          background:
            linear-gradient(
              180deg,
              rgba(239,238,226,0.90),
              rgba(215,216,204,0.88)
            ),
            var(--people-detail) no-repeat center / cover;

          box-shadow:
            0 0 0 2px rgba(38,37,34,0.12),
            18px 18px 0 rgba(38,37,34,0.20);

          position:relative;
          overflow:hidden;
        }}

        body.theme-people-we .card::before {{
          content:"";
          position:absolute;
          inset:0;

          background:
            var(--people-frame-large)
            no-repeat center / 96% 96%;

          opacity:0.95;
          z-index:0;
        }}

        body.theme-people-we .card::after {{
          content:"";
          position:absolute;

          right:22px;
          top:58px;

          width:220px;
          height:54px;

          background:
            var(--people-barrage)
            no-repeat center / contain;

          opacity:0.54;

          pointer-events:none;
          z-index:1;
        }}

        /* 顶栏 */

        body.theme-people-we .peoplewe-topbar {{
          height:38px;

          display:flex;
          align-items:center;
          justify-content:space-between;

          padding:0 22px;

          background:rgba(38,37,34,0.94);

          color:#efeee2;

          border-bottom:7px solid #9f302a;

          font-family:
            "Cascadia Mono",
            monospace;

          font-size:12px;
          letter-spacing:0.12em;
          text-transform:uppercase;
        }}

        /* 主容器 */

        body.theme-people-we .peoplewe-inner {{
          position:relative;
          padding:22px 22px 16px 22px;
        }}

        /* 左上背景 */

        body.theme-people-we .peoplewe-inner::before {{
          content:"";
          position:absolute;

          left:18px;
          top:26px;

          width:185px;
          height:82px;

          background:
            var(--people-name)
            no-repeat left top / contain;

          opacity:0.22;

          pointer-events:none;
          z-index:0;
        }}

        /* 所有内容提高层级 */

        body.theme-people-we .peoplewe-inner > * {{
          position:relative;
          z-index:2;
        }}

        /* Header */

        body.theme-people-we .header,
        body.theme-people-we .profile-head {{
          padding:10px 230px 12px 18px;

          min-height:88px;

          border-left:5px solid #9f302a;

          background:
            linear-gradient(
              90deg,
              rgba(239,238,226,0.74),
              rgba(239,238,226,0.28),
              transparent
            );

          position:relative;
          z-index:3;
        }}

        body.theme-people-we .kicker {{
          display:inline-flex;

          background:#262522;
          color:#efeee2;

          padding:5px 10px;

          font-weight:900;
          letter-spacing:0.18em;

          transform:rotate(-2deg) skewX(-7deg);

          box-shadow:8px 6px 0 rgba(159,48,42,0.32);
        }}

        body.theme-people-we .title,
        body.theme-people-we .profile-title {{
          margin-top:8px;

          color:#262522;

          font-size:32px;
          font-weight:900;

          letter-spacing:-0.04em;
          text-transform:uppercase;
        }}

        body.theme-people-we .profile-sub {{
          color:#5f5a4f;
          font-weight:800;
        }}

        /* 分割线 */

        body.theme-people-we .divider {{
          position:relative;

          height:18px;
          margin:4px 0 14px;

          border:0;

          background:
            linear-gradient(
              90deg,
              transparent 0 4%,
              #9f302a 4% 46%,
              transparent 46% 100%
            );
        }}

        body.theme-people-we .divider::before {{
          content:"";
          position:absolute;

          left:0;
          top:-10px;

          width:210px;
          height:40px;

          background:
            var(--people-red-mark)
            no-repeat left center / contain;

          opacity:0.72;
        }}

        /* 表格 */

        body.theme-people-we table.leaderboard,
        body.theme-people-we table.honors {{
          border:2px solid #262522;
          border-radius:0;

          background:rgba(239,238,226,0.86);

          box-shadow:
            9px 9px 0 rgba(38,37,34,0.16);

          position:relative;
          z-index:2;
        }}

        body.theme-people-we table.leaderboard thead th,
        body.theme-people-we table.honors thead th {{
          height:42px;

          background:#262522;
          color:#efeee2;

          border-bottom:5px solid #9f302a;

          font-weight:900;
          letter-spacing:0.16em;
        }}

        body.theme-people-we table.leaderboard tbody td,
        body.theme-people-we table.honors tbody td {{
          border-bottom:1px solid rgba(38,37,34,0.18);
          font-weight:800;
        }}

        /* Rank */

        body.theme-people-we .rank {{
          min-width:58px;

          border:2px solid #262522;

          background:#262522;
          color:#efeee2;

          box-shadow:4px 4px 0 rgba(159,48,42,0.42);

          font-size:16px;
          font-weight:900;
        }}

        body.theme-people-we .rank-1 {{
          background:#9f302a;
          color:#fff8ec;
        }}

        /* Avatar */

        body.theme-people-we .avatar-sm,
        body.theme-people-we .avatar {{
          position:relative;
          z-index:5;

          border:2px solid #262522;

          background:#d8d6c7;
          color:#9f302a;

          box-shadow:4px 4px 0 rgba(38,37,34,0.18);
        }}

        body.theme-people-we .avatar {{
          width:64px;
          height:64px;
          font-size:28px;
        }}

        body.theme-people-we .name {{
          font-weight:900;
        }}

        /* 数值颜色 */

        body.theme-people-we .num-good {{
          color:#455746;
        }}

        body.theme-people-we .num-bad {{
          color:#9f302a;
        }}

        body.theme-people-we .num-warn {{
          color:#8f5b3f;
        }}

        /* Progress */

        body.theme-people-we .mini-bar,
        body.theme-people-we .progress-track {{
          height:9px;

          border:2px solid #262522;

          background:#d8d6c7;
        }}

        body.theme-people-we .mini-fill,
        body.theme-people-we .progress-fill {{
          background:
            linear-gradient(
              90deg,
              #9f302a,
              #262522
            );
        }}

        /* Panel */

        body.theme-people-we .panel,
        body.theme-people-we .stat,
        body.theme-people-we .rank-card {{
          border:2px solid #262522;

          background:rgba(239,238,226,0.82);

          box-shadow:7px 7px 0 rgba(38,37,34,0.14);
        }}

        body.theme-people-we .panel {{
          background:
            linear-gradient(
              180deg,
              rgba(239,238,226,0.82),
              rgba(216,214,199,0.72)
            ),
            var(--people-frame-wide)
            no-repeat center / 100% 100%;
        }}

        body.theme-people-we .panel-title,
        body.theme-people-we .stat-label,
        body.theme-people-we .rank-label {{
          display:inline-flex;

          padding:3px 8px;

          background:#262522;
          color:#efeee2;

          font-weight:900;
          letter-spacing:0.16em;
        }}

        body.theme-people-we .stat-value,
        body.theme-people-we .rank-value {{
          color:#9f302a;
          font-size:22px;
          font-weight:900;
        }}

        body.theme-people-we .grid2 {{
          grid-template-columns:1.25fr 0.75fr;
        }}

        /* Footer */

        body.theme-people-we .footer {{
          position:relative;
          z-index:3;

          border-top:2px solid rgba(38,37,34,0.52);

          color:#5f5a4f;
          font-weight:800;

          display:flex;
          justify-content:space-between;
          align-items:center;
        }}

        body.theme-people-we .footer .tag {{
          border:2px solid #262522;

          background:#262522;
          color:#efeee2;

          font-weight:900;
        }}

        </style>
        """


ConstructivistRenderer = ConstructivistPeopleRenderer
QnAStatsRendererConstructivist = ConstructivistPeopleRenderer