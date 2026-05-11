from .base import BaseRenderer


class IndustrialRenderer(BaseRenderer):
    """工业（深色）主题渲染器。"""

    def _theme_css(self) -> str:
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
          --glow1: rgba(34,211,238,0.14);
          --glow2: rgba(251,191,36,0.10);
          --grid: rgba(148,163,184,0.06);
          --stripe: rgba(251,191,36,0.08);
        }
        </style>
        """


# 向后兼容别名
QnAStatsRendererIndustrial = IndustrialRenderer
