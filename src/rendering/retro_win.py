from .base import BaseRenderer


class RetroWinRenderer(BaseRenderer):
    """复古 Win / 像素风主题渲染器。"""

    RETRO_FRAME_EXTRA_HEIGHT = 52

    def _extra_height(self) -> int:
        return self.RETRO_FRAME_EXTRA_HEIGHT

    def _body_class(self) -> str:
        return "theme-retro"

    def _top_bar_html(self) -> str:
        return """
        <div class="retro-top-header">
          <span>MRFZCCL // QNA STATS</span>
          <span>SYSTEM READY_</span>
        </div>
        """

    def _body_wrap_prefix(self) -> str:
        return '<div class="retro-inner">'

    def _body_wrap_suffix(self) -> str:
        return "</div>"

    def _theme_css(self) -> str:
        return """
        <style>
        :root{
          --bg0:#c5ced1;
          --bg1:#c5ced1;
          --panel:#f4f0e6;
          --panel2:#ffffff;
          --line:#1a1a1a;
          --text:#1a1a1a;
          --muted:#3b3b3b;
          --accent:#f39800;
          --accent2:#2c3e50;
          --good:#1b873f;
          --bad:#b91c1c;
          --warn:#f39800;
          --glow1: rgba(0,0,0,0);
          --glow2: rgba(0,0,0,0);
          --grid: rgba(0,0,0,0.10);
          --stripe: rgba(0,0,0,0.00);
        }
        </style>
        """


# 向后兼容别名
QnAStatsRendererRetroWin = RetroWinRenderer
