"""LiangHua 投资研究框架集合"""
from app.framework.serenity_alpha import SerenityAlphaAnalyzer
from app.framework.tam_adj_peg import TAMAdjPEGAanalyzer
from app.framework.gf_dma_health import GFDMAHealthAnalyzer
from app.framework.bayesian_intrinsic_growth import BayesianIntrinsicGrowthValuation

__all__ = [
    "SerenityAlphaAnalyzer",
    "TAMAdjPEGAanalyzer",
    "GFDMAHealthAnalyzer",
    "BayesianIntrinsicGrowthValuation",
]
