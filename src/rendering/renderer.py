"""浅色主题渲染器。"""
from .base import BaseRenderer


class LightRenderer(BaseRenderer):
    """浅色主题渲染器。"""

    def _theme_css(self) -> str:
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
          --glow1: rgba(14,165,233,0.10);
          --glow2: rgba(245,158,11,0.08);
          --grid: rgba(2,6,23,0.045);
          --stripe: rgba(2,6,23,0.06);
        }
        </style>
        """


# 向后兼容别名
QnAStatsRenderer = LightRenderer
