"""対戦シーン検出モジュール"""

from .config import DetectionParams, get_available_profiles, load_detection_params
from .matcher import MatchDetection, TemplateMatcher
from .result_detector import ResultDetection, ResultScreenDetector

__all__ = [
    "TemplateMatcher",
    "MatchDetection",
    "ResultScreenDetector",
    "ResultDetection",
    "DetectionParams",
    "load_detection_params",
    "get_available_profiles",
]
