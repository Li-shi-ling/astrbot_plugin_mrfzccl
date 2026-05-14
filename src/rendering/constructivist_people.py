import base64
from functools import lru_cache
from pathlib import Path

from .base import BaseRenderer


@lru_cache(maxsize=32)
def _asset_data_url(filename: str) -> str:
    """Load People/We constructivist assets as data URLs.

    Expected project layout:
      your_package/
        renderers/constructivist.py
        assets/constructivist_people/*

    This follows the same deployment idea as SnowcapShopRenderer: all theme
    assets are local files and are embedded as data URLs during rendering.
    """
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
    """People/We inspired constructivist theme for ranking and profile cards."""

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
        transition_bg = _asset_data_url("people_we_transition_bg.jpg")
        name_label = _asset_data_url("name_label.png")
        speaker_label = _asset_data_url("speaker_label.png")
        red_mark = _asset_data_url("red_brush_mark.png")
        barrage = _asset_data_url("barrage_strip.png")
        frame_wide = _asset_data_url("photo_frame_wide.png")
        frame_large = _asset_data_url("photo_frame_large.png")
        return f"""
        <style>
        :root{{
          --bg0:#e8e5dc;
          --bg1:#cfcfc9;
          --panel:rgba(239,238,226,0.92);
          --panel2:rgba(214,215,205,0.90);
          --line:#262522;
          --text:#24231f;
          --muted:#6f6c61;
          --accent:#9f302a;
          --accent2:#2b2a26;
          --good:#455746;
          --bad:#9f302a;
          --warn:#8f5b3f;
          --glow1: rgba(159,48,42,0.13);
          --glow2: rgba(34,34,30,0.08);
          --grid: rgba(100,91,82,0.10);
          --stripe: rgba(159,48,42,0.22);
          --people-home:url("{home_bg}");
          --people-detail:url("{detail_bg}");
          --people-transition:url("{transition_bg}");
          --people-name:url("{name_label}");
          --people-speaker:url("{speaker_label}");
          --people-red-mark:url("{red_mark}");
          --people-barrage:url("{barrage}");
          --people-frame-wide:url("{frame_wide}");
          --people-frame-large:url("{frame_large}");
        }}

        body.theme-people-we{{
          font-family:"Bahnschrift", "Arial Narrow", "DIN Condensed", "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
          letter-spacing:0.01em;
        }}
        body.theme-people-we .content-container{{
          padding:22px;
          background:
            linear-gradient(180deg, rgba(232,229,220,0.20), rgba(10,10,10,0.26)),
            var(--people-home) no-repeat center / cover,
            linear-gradient(180deg, var(--bg0), var(--bg1));
        }}
        body.theme-people-we .content-container::before{{
          background:
            linear-gradient(to right, rgba(159,48,42,0.13) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(38,37,34,0.06) 1px, transparent 1px),
            repeating-linear-gradient(115deg, transparent 0 18px, rgba(42,42,37,0.045) 18px 20px);
          background-size:72px 72px, 72px 72px, auto;
          opacity:1;
        }}

        body.theme-people-we .card{{
          border:0;
          border-radius:0;
          padding:0;
          background:
            linear-gradient(180deg, rgba(239,238,226,0.86), rgba(215,216,204,0.84)),
            var(--people-detail) no-repeat center / cover;
          box-shadow: 0 0 0 2px rgba(38,37,34,0.12), 18px 18px 0 rgba(38,37,34,0.20);
        }}
        body.theme-people-we .card::before{{
          inset:0;
          background:
            var(--people-frame-large) no-repeat center / 96% 96%,
            linear-gradient(90deg, rgba(159,48,42,0.25) 0 1px, transparent 1px),
            linear-gradient(180deg, rgba(38,37,34,0.10), transparent 28%, rgba(38,37,34,0.16));
          opacity:0.95;
        }}
        body.theme-people-we .card::after{{
          content:"";
          position:absolute;
          right:22px;
          top:58px;
          width:220px;
          height:54px;
          background:var(--people-barrage) no-repeat center / contain;
          opacity:0.54;
          pointer-events:none;
          z-index:1;
        }}

        body.theme-people-we .peoplewe-topbar{{
          height:38px;
          display:flex;
          align-items:center;
          justify-content:space-between;
          padding:0 22px;
          background:rgba(38,37,34,0.94);
          color:#efeee2;
          border-bottom:7px solid #9f302a;
          font-family:"Cascadia Mono", "JetBrains Mono", Consolas, monospace;
          font-size:12px;
          letter-spacing:0.12em;
          text-transform:uppercase;
        }}
        body.theme-people-we .peoplewe-brand{{ color:#efeee2; }}
        body.theme-people-we .peoplewe-status{{ color:#d8d6c7; }}
        body.theme-people-we .peoplewe-inner{{
          position:relative;
          padding:22px 22px 16px 22px;
        }}
        body.theme-people-we .peoplewe-inner::before{{
          content:"";
          position:absolute;
          left:10px;
          top:16px;
          width:185px;
          height:82px;
          background:var(--people-name) no-repeat left top / contain;
          opacity:0.40;
          pointer-events:none;
        }}
        body.theme-people-we .peoplewe-inner::after{{
          content:"";
          position:absolute;
          right:36px;
          bottom:12px;
          width:180px;
          height:62px;
          background:var(--people-speaker) no-repeat right bottom / contain;
          opacity:0.28;
          pointer-events:none;
        }}

        body.theme-people-we .header,
        body.theme-people-we .profile-head{{
          padding:10px 230px 12px 18px;
          min-height:88px;
          align-items:flex-end;
          border-left:5px solid #9f302a;
          background:linear-gradient(90deg, rgba(239,238,226,0.74), rgba(239,238,226,0.28), transparent);
        }}
        body.theme-people-we .kicker{{
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
        body.theme-people-we .profile-title{{
          margin-top:8px;
          color:#262522;
          font-size:32px;
          font-weight:900;
          letter-spacing:-0.04em;
          text-transform:uppercase;
          text-shadow: 2px 2px 0 rgba(239,238,226,0.7), 4px 4px 0 rgba(159,48,42,0.18);
        }}
        body.theme-people-we .profile-sub{{
          color:#5f5a4f;
          font-weight:800;
        }}

        body.theme-people-we .meta{{
          border:2px solid #262522;
          border-radius:0;
          background:rgba(239,238,226,0.88);
          box-shadow:5px 5px 0 rgba(38,37,34,0.18);
          min-width:96px;
        }}
        body.theme-people-we .meta-label{{
          color:#9f302a;
          font-weight:900;
          letter-spacing:0.14em;
        }}
        body.theme-people-we .meta-value{{
          color:#262522;
          font-weight:900;
        }}

        body.theme-people-we .divider{{
          position:relative;
          height:18px;
          margin:4px 0 14px;
          border:0;
          background:
            linear-gradient(90deg, transparent 0 4%, #9f302a 4% 46%, transparent 46% 100%);
        }}
        body.theme-people-we .divider::before{{
          content:"";
          position:absolute;
          left:0;
          top:-10px;
          width:210px;
          height:40px;
          background:var(--people-red-mark) no-repeat left center / contain;
          opacity:0.72;
        }}

        body.theme-people-we table.leaderboard,
        body.theme-people-we table.honors{{
          border:2px solid #262522;
          border-radius:0;
          background:rgba(239,238,226,0.86);
          box-shadow: 9px 9px 0 rgba(38,37,34,0.16);
        }}
        body.theme-people-we table.leaderboard thead th,
        body.theme-people-we table.honors thead th{{
          height:42px;
          background:#262522;
          color:#efeee2;
          border-bottom:5px solid #9f302a;
          font-weight:900;
          letter-spacing:0.16em;
        }}
        body.theme-people-we table.leaderboard tbody td,
        body.theme-people-we table.honors tbody td{{
          border-bottom:1px solid rgba(38,37,34,0.18);
          font-weight:800;
        }}
        body.theme-people-we table.leaderboard tbody tr:nth-child(even),
        body.theme-people-we table.honors tbody tr:nth-child(even){{
          background:rgba(159,48,42,0.055);
        }}
        body.theme-people-we table.leaderboard tbody tr::after{{
          background:linear-gradient(90deg, rgba(159,48,42,0.20) calc(var(--acc, 0) * 100%), transparent 0);
          opacity:1;
        }}
        body.theme-people-we table.leaderboard tbody tr.top1::after{{
          background:linear-gradient(90deg, rgba(159,48,42,0.30) calc(var(--acc, 0) * 100%), transparent 0);
        }}

        body.theme-people-we .rank{{
          min-width:58px;
          border:2px solid #262522;
          border-radius:0;
          background:#262522;
          color:#efeee2;
          box-shadow:4px 4px 0 rgba(159,48,42,0.42);
          font-size:16px;
          font-weight:900;
        }}
        body.theme-people-we .rank-1{{
          background:#9f302a;
          color:#fff8ec;
        }}
        body.theme-people-we .rank-3{{ color:#f0c17b; }}

        body.theme-people-we .avatar-sm,
        body.theme-people-we .avatar{{
          border:2px solid #262522;
          border-radius:0;
          background:#d8d6c7;
          color:#9f302a;
          box-shadow:4px 4px 0 rgba(38,37,34,0.18);
        }}
        body.theme-people-we .avatar{{ width:64px; height:64px; font-size:28px; }}
        body.theme-people-we .name{{ font-weight:900; letter-spacing:0.02em; }}
        body.theme-people-we .chip{{
          border:2px solid #262522;
          border-radius:0;
          background:#efeee2;
          color:#262522;
          font-weight:900;
        }}
        body.theme-people-we .num-accent,
        body.theme-people-we .num-warn{{ color:#9f302a; }}
        body.theme-people-we .num-good{{ color:#455746; }}
        body.theme-people-we .num-bad{{ color:#9f302a; }}

        body.theme-people-we .mini-bar,
        body.theme-people-we .progress-track{{
          height:9px;
          border:2px solid #262522;
          border-radius:0;
          background:#d8d6c7;
        }}
        body.theme-people-we .mini-fill,
        body.theme-people-we .progress-fill{{
          border-radius:0;
          background:linear-gradient(90deg, #9f302a, #262522);
        }}

        body.theme-people-we .panel,
        body.theme-people-we .stat,
        body.theme-people-we .rank-card{{
          border:2px solid #262522;
          border-radius:0;
          background:rgba(239,238,226,0.82);
          box-shadow:7px 7px 0 rgba(38,37,34,0.14);
        }}
        body.theme-people-we .panel{{
          background:
            linear-gradient(180deg, rgba(239,238,226,0.82), rgba(216,214,199,0.72)),
            var(--people-frame-wide) no-repeat center / 100% 100%;
        }}
        body.theme-people-we .panel-title,
        body.theme-people-we .stat-label,
        body.theme-people-we .rank-label{{
          display:inline-flex;
          padding:3px 8px;
          background:#262522;
          color:#efeee2;
          font-weight:900;
          letter-spacing:0.16em;
          transform:skewX(-6deg);
        }}
        body.theme-people-we .stat-value,
        body.theme-people-we .rank-value{{
          color:#9f302a;
          font-size:22px;
          font-weight:900;
        }}
        body.theme-people-we .stat.good .stat-value{{ color:#455746; }}
        body.theme-people-we .stat.bad .stat-value{{ color:#9f302a; }}
        body.theme-people-we .stat.warn .stat-value{{ color:#8f5b3f; }}
        body.theme-people-we .grid2{{ grid-template-columns:1.25fr 0.75fr; }}

        body.theme-people-we .footer{{
          border-top:2px solid rgba(38,37,34,0.52);
          color:#5f5a4f;
          font-weight:800;
        }}
        body.theme-people-we .footer .tag{{
          border:2px solid #262522;
          border-radius:0;
          background:#262522;
          color:#efeee2;
          font-weight:900;
        }}
        </style>
        """


# Backward-compatible aliases for older theme registrations.
ConstructivistRenderer = ConstructivistPeopleRenderer
QnAStatsRendererConstructivist = ConstructivistPeopleRenderer
