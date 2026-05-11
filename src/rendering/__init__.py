from .base import BaseRenderer
from .industrial import IndustrialRenderer, QnAStatsRendererIndustrial
from .renderer import LightRenderer, QnAStatsRenderer
from .retro_win import QnAStatsRendererRetroWin, RetroWinRenderer

__all__ = [
    # 新类名
    "BaseRenderer",
    "LightRenderer",
    "IndustrialRenderer",
    "RetroWinRenderer",
    # 向后兼容别名
    "QnAStatsRenderer",
    "QnAStatsRendererIndustrial",
    "QnAStatsRendererRetroWin",
]
