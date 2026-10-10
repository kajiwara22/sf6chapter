"""対戦シーン検出モジュール"""

from .config import DetectionParams, get_available_profiles, load_detection_params
from .gauge import (
    DRIVE_MAX,
    GaugeAnalysisParams,
    GaugeAnalyzer,
    GaugeSample,
    GaugeThresholds,
    SideGaugeState,
)
from .matcher import MatchDetection, TemplateMatcher
from .result_detector import ResultDetection, ResultScreenDetector
from .round_splitter import RoundWindow, split_rounds

__all__ = [
    "TemplateMatcher",
    "MatchDetection",
    "ResultScreenDetector",
    "ResultDetection",
    "DetectionParams",
    "load_detection_params",
    "get_available_profiles",
    "GaugeAnalyzer",
    "GaugeAnalysisParams",
    "GaugeThresholds",
    "GaugeSample",
    "SideGaugeState",
    "DRIVE_MAX",
    "RoundWindow",
    "split_rounds",
]
