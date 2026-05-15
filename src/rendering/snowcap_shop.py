import base64
from functools import lru_cache
from pathlib import Path

from .base import BaseRenderer


@lru_cache(maxsize=16)
def _asset_data_url(filename: str) -> str:
    asset_path = (
        Path(__file__).resolve().parents[2] / "assets" / "snowcap_shop" / filename
    )
    try:
        data = asset_path.read_bytes()
    except OSError:
        return ""
    suffix = asset_path.suffix.lower().lstrip(".") or "png"
    return f"data:image/{suffix};base64,{base64.b64encode(data).decode('ascii')}"


class SnowcapShopRenderer(BaseRenderer):
    """Snowcap's shop inspired theme."""

    def _body_class(self) -> str:
        return "theme-snowcap-shop"

    def _theme_css(self) -> str:
        sign = _asset_data_url("sign.png")
        bottle = _asset_data_url("bottle.png")
        bag = _asset_data_url("bag.png")
        tray = _asset_data_url("tray.png")
        mascot = _asset_data_url("mascot.png")
        return f"""
        <style>
        :root{{
          --bg0:#9aae7c;
          --bg1:#7f965f;
          --panel:#efdfc7;
          --panel2:#fff7e9;
          --line:#5d7028;
          --text:#1f241a;
          --muted:#6f7653;
          --accent:#c53926;
          --accent2:#5d7028;
          --good:#5d7028;
          --bad:#c53926;
          --warn:#b7832f;
          --glow1: rgba(239,223,199,0.16);
          --glow2: rgba(197,57,38,0.12);
          --grid: rgba(255,255,255,0.34);
          --stripe: rgba(93,112,40,0.08);
          --shop-sign:url("{sign}");
          --shop-bottle:url("{bottle}");
          --shop-bag:url("{bag}");
          --shop-tray:url("{tray}");
          --shop-mascot:url("{mascot}");
        }}
        body.theme-snowcap-shop{{
          font-family: "Bahnschrift", "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
        }}
        body.theme-snowcap-shop .content-container{{
          background:
            linear-gradient(to right, rgba(255,255,255,0.28) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(255,255,255,0.28) 1px, transparent 1px),
            radial-gradient(740px 420px at 15% 0%, rgba(239,223,199,0.22), transparent 64%),
            linear-gradient(180deg, var(--bg0), var(--bg1));
          background-size: 48px 48px, 48px 48px, auto, auto;
          padding: 24px;
        }}
        body.theme-snowcap-shop .content-container::before{{
          background-image:
            repeating-linear-gradient(90deg, transparent 0 42px, rgba(255,255,255,0.28) 42px 43px),
            repeating-linear-gradient(0deg, transparent 0 42px, rgba(255,255,255,0.22) 42px 43px);
          opacity: 1;
        }}
        body.theme-snowcap-shop .card{{
          border: 5px solid #5d7028;
          border-radius: 18px;
          background:
            linear-gradient(180deg, rgba(255,247,233,0.92), rgba(239,223,199,0.96));
          box-shadow: 14px 14px 0 rgba(31,36,26,0.16);
          padding: 22px 22px 16px;
        }}
        body.theme-snowcap-shop .card::before{{
          inset: 12px;
          border: 2px dashed rgba(93,112,40,0.42);
          border-radius: 11px;
          background:
            var(--shop-bottle) no-repeat left 10px bottom 12px / 82px auto,
            var(--shop-bag) no-repeat right 16px top 76px / 84px auto,
            var(--shop-tray) no-repeat right 18px bottom 14px / 76px auto;
          opacity: 0.34;
        }}
        body.theme-snowcap-shop .card::after{{
          content:"";
          position:absolute;
          right: 14px;
          top: 10px;
          width: 96px;
          height: 96px;
          background: var(--shop-mascot) no-repeat center / contain;
          opacity: 0.22;
          pointer-events:none;
        }}
        body.theme-snowcap-shop .header,
        body.theme-snowcap-shop .profile-head{{
          padding-right: 104px;
        }}
        body.theme-snowcap-shop .kicker{{
          color:#5d7028;
          font-weight: 800;
          letter-spacing: 0.16em;
        }}
        body.theme-snowcap-shop .title,
        body.theme-snowcap-shop .profile-title{{
          color:#c53926;
          text-shadow: 2px 2px 0 rgba(255,247,233,0.9);
        }}
        body.theme-snowcap-shop .divider{{
          height: 12px;
          margin: 8px 0 14px;
          border: 2px solid #5d7028;
          border-left: 0;
          border-right: 0;
          background:
            repeating-linear-gradient(90deg, #5d7028 0 22px, #efdfc7 22px 34px, #c53926 34px 46px, #efdfc7 46px 58px);
        }}
        body.theme-snowcap-shop .meta,
        body.theme-snowcap-shop .panel,
        body.theme-snowcap-shop .rank-card,
        body.theme-snowcap-shop .stat{{
          border: 3px solid #5d7028;
          border-radius: 8px;
          background:#fff7e9;
          box-shadow: 4px 4px 0 rgba(93,112,40,0.16);
        }}
        body.theme-snowcap-shop .meta-label,
        body.theme-snowcap-shop .panel-title,
        body.theme-snowcap-shop .stat-label,
        body.theme-snowcap-shop .rank-label{{
          color:#5d7028;
          font-weight: 800;
        }}
        body.theme-snowcap-shop table.leaderboard{{
          border: 3px solid #5d7028;
          border-radius: 10px;
          background:#fff7e9;
        }}
        body.theme-snowcap-shop table.leaderboard thead th{{
          background:#c53926;
          color:#efdfc7;
          border-bottom: 3px solid #5d7028;
        }}
        body.theme-snowcap-shop table.leaderboard tbody td{{
          border-bottom: 2px dotted rgba(93,112,40,0.28);
        }}
        body.theme-snowcap-shop table.leaderboard tbody tr:nth-child(even){{
          background: rgba(154,174,124,0.18);
        }}
        body.theme-snowcap-shop table.leaderboard tbody tr::after{{
          background: linear-gradient(90deg, rgba(154,174,124,0.26) calc(var(--acc, 0) * 100%), transparent 0);
        }}
        body.theme-snowcap-shop table.leaderboard tbody tr.top1::after{{
          background: linear-gradient(90deg, rgba(197,57,38,0.18) calc(var(--acc, 0) * 100%), transparent 0);
        }}
        body.theme-snowcap-shop .rank,
        body.theme-snowcap-shop .avatar-sm,
        body.theme-snowcap-shop .avatar{{
          border: 3px solid #5d7028;
          border-radius: 50%;
          background:#efdfc7;
          color:#c53926;
        }}
        body.theme-snowcap-shop .chip,
        body.theme-snowcap-shop .footer .tag{{
          border: 2px solid #5d7028;
          border-radius: 7px;
          background:#efdfc7;
          color:#5d7028;
        }}
        body.theme-snowcap-shop .progress-track,
        body.theme-snowcap-shop .mini-bar{{
          border: 2px solid #5d7028;
          background:#efdfc7;
        }}
        body.theme-snowcap-shop .progress-fill,
        body.theme-snowcap-shop .mini-fill{{
          background: linear-gradient(90deg, #5d7028, #9aae7c);
        }}
        body.theme-snowcap-shop .footer{{
          border-top: 2px dashed rgba(93,112,40,0.46);
          color:#6f7653;
        }}
        </style>
        """


QnAStatsRendererSnowcapShop = SnowcapShopRenderer
