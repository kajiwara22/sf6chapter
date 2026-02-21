"""
検出パラメータの設定管理モジュール
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils.logger import get_logger

logger = get_logger()


@dataclass
class ResultDetectionParams:
    """RESULT画面検出パラメータ"""

    enabled: bool
    result_template_paths: list[str]  # 複数のテンプレートに対応
    win_template_paths: list[str]  # 複数のテンプレートに対応
    result_threshold: float
    win_threshold: float
    result_screen_search_region: tuple[int, int, int, int] | None
    win_text_search_region: tuple[int, int, int, int] | None


@dataclass
class DetectionParams:
    """検出パラメータを保持するデータクラス"""

    template_path: str
    reject_templates: list[str]
    threshold: float
    reject_threshold: float
    min_interval_sec: float
    post_check_frames: int
    post_check_reject_limit: int
    search_region: tuple[int, int, int, int]
    crop_region: tuple[int, int, int, int]  # キャラクター名表示領域 (x1, y1, x2, y2)
    frame_interval: int
    recognize_frame_offset: int  # 認識用フレームのデフォルトオフセット（フレーム数）
    recognize_frame_offset_alt: int  # 認識用フレームの代替オフセット（フレーム数）
    recognize_frame_offset_threshold: float  # 動的オフセット選択の閾値（標準偏差の差分）
    result_detection: ResultDetectionParams  # RESULT画面検出パラメータ
    profile: str  # 使用したプロファイル名

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換"""
        return {
            "profile": self.profile,
            "template_path": self.template_path,
            "reject_templates": self.reject_templates,
            "threshold": self.threshold,
            "reject_threshold": self.reject_threshold,
            "min_interval_sec": self.min_interval_sec,
            "post_check_frames": self.post_check_frames,
            "post_check_reject_limit": self.post_check_reject_limit,
            "search_region": list(self.search_region),
            "crop_region": list(self.crop_region),
            "frame_interval": self.frame_interval,
            "recognize_frame_offset": self.recognize_frame_offset,
            "recognize_frame_offset_alt": self.recognize_frame_offset_alt,
            "recognize_frame_offset_threshold": self.recognize_frame_offset_threshold,
        }

    def log_params(self) -> None:
        """パラメータをログに出力"""
        logger.info("=" * 60)
        logger.info("Detection Parameters (Profile: %s)", self.profile)
        logger.info("=" * 60)
        logger.info("  [Match Detection]")
        logger.info("    template_path:            %s", self.template_path)
        logger.info("    reject_templates:         %s", self.reject_templates)
        logger.info("    threshold:                %.2f", self.threshold)
        logger.info("    reject_threshold:         %.2f", self.reject_threshold)
        logger.info("    min_interval_sec:         %.1f", self.min_interval_sec)
        logger.info("    post_check_frames:        %d", self.post_check_frames)
        logger.info("    post_check_reject_limit:  %d", self.post_check_reject_limit)
        logger.info("    search_region:            %s", self.search_region)
        logger.info("    crop_region:              %s", self.crop_region)
        logger.info("    frame_interval:           %d", self.frame_interval)
        logger.info("    recognize_frame_offset:   %d", self.recognize_frame_offset)
        logger.info("    recognize_frame_offset_alt: %d", self.recognize_frame_offset_alt)
        logger.info("    recognize_frame_offset_threshold: %.1f", self.recognize_frame_offset_threshold)
        logger.info("  [Result Detection]")
        logger.info("    enabled:                  %s", self.result_detection.enabled)
        if self.result_detection.enabled:
            logger.info("    result_template_paths:    %s", self.result_detection.result_template_paths)
            logger.info("    win_template_paths:       %s", self.result_detection.win_template_paths)
            logger.info("    result_threshold:         %.2f", self.result_detection.result_threshold)
            logger.info("    win_threshold:            %.2f", self.result_detection.win_threshold)
            logger.info("    result_screen_search_region: %s", self.result_detection.result_screen_search_region)
            logger.info("    win_text_search_region:   %s", self.result_detection.win_text_search_region)
        logger.info("=" * 60)


def load_detection_params(profile: str = "production", config_path: str | None = None) -> DetectionParams:
    """
    検出パラメータを設定ファイルから読み込む

    Args:
        profile: 使用するプロファイル名 (production/test/legacy)
        config_path: 設定ファイルのパス（省略時はデフォルト）

    Returns:
        DetectionParams: 読み込まれたパラメータ

    Raises:
        FileNotFoundError: 設定ファイルが見つからない
        KeyError: 指定されたプロファイルが存在しない
        ValueError: パラメータの値が不正
    """
    # 環境変数でプロファイルを上書き可能
    profile = os.environ.get("DETECTION_PROFILE", profile)

    # 設定ファイルのパス解決
    if config_path is None:
        # main.pyの親ディレクトリから相対パス
        app_root = Path(__file__).parent.parent.parent
        config_path = str(app_root / "config" / "detection_params.json")

    if not Path(config_path).exists():
        raise FileNotFoundError(f"Detection config file not found: {config_path}")

    # JSONファイルを読み込み
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    # プロファイルを取得
    if profile not in config["profiles"]:
        available = ", ".join(config["profiles"].keys())
        raise KeyError(f"Profile '{profile}' not found. Available profiles: {available}")

    params_dict = config["profiles"][profile]

    # RESULT検出パラメータを読み込み
    result_detection_dict = params_dict.get("result_detection", {})
    result_screen_search_region = result_detection_dict.get("result_screen_search_region")
    if result_screen_search_region is not None:
        result_screen_search_region = tuple(result_screen_search_region)
    win_text_search_region = result_detection_dict.get("win_text_search_region")
    if win_text_search_region is not None:
        win_text_search_region = tuple(win_text_search_region)

    # result_template_path / win_template_path は文字列または配列に対応
    result_template_paths = result_detection_dict.get("result_template_paths", [])
    if isinstance(result_template_paths, str):
        result_template_paths = [result_template_paths]
    elif not isinstance(result_template_paths, list):
        # 互換性: 古い形式の result_template_path から変換
        result_template_path = result_detection_dict.get("result_template_path")
        result_template_paths = [result_template_path] if result_template_path else []
    result_template_paths = [str(p) for p in result_template_paths]

    win_template_paths = result_detection_dict.get("win_template_paths", [])
    if isinstance(win_template_paths, str):
        win_template_paths = [win_template_paths]
    elif not isinstance(win_template_paths, list):
        # 互換性: 古い形式の win_template_path から変換
        win_template_path = result_detection_dict.get("win_template_path")
        win_template_paths = [win_template_path] if win_template_path else []
    win_template_paths = [str(p) for p in win_template_paths]

    result_detection = ResultDetectionParams(
        enabled=bool(result_detection_dict.get("enabled", False)),
        result_template_paths=result_template_paths,
        win_template_paths=win_template_paths,
        result_threshold=float(result_detection_dict.get("result_threshold", 0.3)),
        win_threshold=float(result_detection_dict.get("win_threshold", 0.3)),
        result_screen_search_region=result_screen_search_region,
        win_text_search_region=win_text_search_region,
    )

    # DetectionParamsに変換
    params = DetectionParams(
        template_path=str(params_dict["template_path"]),
        reject_templates=[str(p) for p in params_dict["reject_templates"]],
        threshold=float(params_dict["threshold"]),
        reject_threshold=float(params_dict["reject_threshold"]),
        min_interval_sec=float(params_dict["min_interval_sec"]),
        post_check_frames=int(params_dict["post_check_frames"]),
        post_check_reject_limit=int(params_dict["post_check_reject_limit"]),
        search_region=tuple(params_dict["search_region"]),
        crop_region=tuple(params_dict["crop_region"]),
        frame_interval=int(params_dict["frame_interval"]),
        recognize_frame_offset=int(params_dict.get("recognize_frame_offset", 6)),
        recognize_frame_offset_alt=int(params_dict.get("recognize_frame_offset_alt", 4)),
        recognize_frame_offset_threshold=float(params_dict.get("recognize_frame_offset_threshold", 5.0)),
        result_detection=result_detection,
        profile=profile,
    )

    # パラメータの妥当性チェック
    _validate_params(params)

    logger.info("Loaded detection parameters from profile: %s", profile)
    return params


def get_available_profiles(config_path: str | None = None) -> list[str]:
    """
    利用可能なプロファイル名の一覧を取得

    Args:
        config_path: 設定ファイルのパス（省略時はデフォルト）

    Returns:
        list[str]: プロファイル名のリスト
    """
    # 設定ファイルのパス解決
    if config_path is None:
        app_root = Path(__file__).parent.parent.parent
        config_path = str(app_root / "config" / "detection_params.json")

    if not Path(config_path).exists():
        # ファイルが見つからない場合はデフォルトを返す
        return ["production", "test", "legacy"]

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    return list(config.get("profiles", {}).keys())


def _validate_params(params: DetectionParams) -> None:
    """パラメータの妥当性をチェック"""
    if not 0.0 <= params.threshold <= 1.0:
        raise ValueError(f"threshold must be between 0.0 and 1.0, got {params.threshold}")

    if not 0.0 <= params.reject_threshold <= 1.0:
        raise ValueError(f"reject_threshold must be between 0.0 and 1.0, got {params.reject_threshold}")

    if params.min_interval_sec < 0:
        raise ValueError(f"min_interval_sec must be positive, got {params.min_interval_sec}")

    if params.post_check_frames < 0:
        raise ValueError(f"post_check_frames must be non-negative, got {params.post_check_frames}")

    if params.post_check_reject_limit < 0:
        raise ValueError(f"post_check_reject_limit must be non-negative, got {params.post_check_reject_limit}")

    if len(params.search_region) != 4:
        raise ValueError(f"search_region must have 4 elements, got {len(params.search_region)}")

    if len(params.crop_region) != 4:
        raise ValueError(f"crop_region must have 4 elements, got {len(params.crop_region)}")

    if params.frame_interval < 1:
        raise ValueError(f"frame_interval must be at least 1, got {params.frame_interval}")

    if params.recognize_frame_offset < 0:
        raise ValueError(f"recognize_frame_offset must be non-negative, got {params.recognize_frame_offset}")

    if params.recognize_frame_offset_alt < 0:
        raise ValueError(f"recognize_frame_offset_alt must be non-negative, got {params.recognize_frame_offset_alt}")

    if params.recognize_frame_offset_threshold < 0:
        raise ValueError(f"recognize_frame_offset_threshold must be non-negative, got {params.recognize_frame_offset_threshold}")
