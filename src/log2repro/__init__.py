"""log2repro: Error log → runnable reproduction code generator."""

__version__ = "0.3.0"

from log2repro.cli import analyze
from log2repro.models import AnalysisResult, FixRecommendation

__all__ = [
    "__version__",
    "analyze",
    "AnalysisResult",
    "FixRecommendation",
]
