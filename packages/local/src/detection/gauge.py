"""ドライブゲージ・SAゲージの時系列計測（ADR-048）

対戦動画から 1P/2P それぞれの
- ドライブゲージ（0〜6本、バーンアウト期間つき）
- SAゲージ（0〜3ストック、CA表示期間つき）
の変化点を抽出する。

計測は ROI の画素解析（HSV）とテンプレートマッチングのみで行い、
学習モデルや VLM は使わない。既存の TemplateMatcher のデコードループから
feed() を呼び出すため、動画の再デコードは発生しない。

状態判定の考え方:

- SA の数字（0〜3, CA）が読めていることを「HUD が表示されている」の判定に使う
- HUD 表示中に、ゲージ中央側から白/銀の回復バーが現れている状態をバーンアウトとみなす（ADR-065）。
  黄緑の有無だけでは低ドライブ警告（金色バー）をバーンアウトと誤判定するため判定条件に使わない
- 単発の誤検出を抑えるため、メディアンによる平滑化と最小継続時間フィルタをかける

ラウンド開始バナーは「ROUND 1 / ROUND 2」と「FINAL ROUND」でレイアウトが異なるため、
文字列ごとのテンプレートを照合する（ADR-052）。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..utils.logger import get_logger
from .preprocessing import preprocess_for_matching
from .round_splitter import RoundWindow, split_rounds

logger = get_logger()

SIDES: tuple[str, str] = ("player1", "player2")

# ドライブゲージの満タン時の本数
DRIVE_MAX = 6.0

# ADR-062: 毒（体力バーが紫に変わる）を与えるキャラクター
POISON_CHARACTERS = frozenset({"AKI"})


def _is_poison_character(name: str | None) -> bool:
    """毒（紫の体力バー）を与えるキャラクターかどうか（ADR-062）

    キャラクター名の表記揺れ（`A.K.I.` / `AKI` / `aki` 等）を吸収する。
    """
    if not name:
        return False
    normalized = str(name).upper().replace(".", "").replace(" ", "").replace("-", "")
    return normalized in POISON_CHARACTERS


@dataclass
class GaugeThresholds:
    """ゲージ計測の閾値"""

    drive_filled_v: int = 135
    drive_filled_s: int = 150
    drive_filled_h_min: int = 20
    drive_filled_h_max: int = 65
    # ADR-065: ドライブが 2 本以下になると残りのバーは金色/オレンジ（低ドライブ警告）で描画される。
    # これも残っているドライブなので充填として数える（黄緑と明度で分離し、二重計上しない）
    drive_low_filled_v: int = 40
    drive_low_filled_h_min: int = 12
    drive_low_filled_h_max: int = 38
    drive_column_fill_ratio: float = 0.5
    drive_detect_min_fraction: float = 0.03
    drive_smoothing_window: int = 7
    drive_max_gap_sec: float = 1.0
    drive_event_epsilon: float = 0.25
    hud_flicker_tolerance_sec: float = 0.5
    burnout_min_duration_sec: float = 1.0
    burnout_merge_gap_sec: float = 1.0
    # ADR-065: バーンアウト中の白/銀回復バー。ゲージ上下の枠線（常に明るい）を避けるため
    # 内側の行だけを見て、画面中央側から連続する「低彩度・高明度」の列を数える
    drive_recover_inset_px: int = 6
    drive_recover_v_min: int = 110
    # 明度上限は設けない（255）。回復バーは V>210 のハイライトを約2割含むため、
    # 明度で切ると本物のバーを取りこぼす。全画面の白フラッシュは下の flash 条件で除外する
    drive_recover_v_max: int = 255
    # 白飛び（V > この値）の割合が drive_recover_max_flash_fraction 以上なら、
    # 全画面の白フラッシュ（ヒット演出やラウンド移行）とみなして回復バーとしない。
    # 実測: 回復バーは 0.02〜0.20、バーンアウト開始フラッシュ 0.34〜0.40、全画面フラッシュ 0.88〜1.00
    drive_recover_flash_v_min: int = 210
    drive_recover_max_flash_fraction: float = 0.6
    drive_recover_s_max: int = 90
    drive_recover_column_fill_ratio: float = 0.6
    drive_recover_min_fraction: float = 0.02
    # バーンアウト確定に必要な白/銀回復バーの連続観測秒数（単発の白を除外）
    burnout_min_bar_sec: float = 0.5
    # バーンアウトの候補とするドライブ残量の上限（本）。低ドライブ警告の金色バーだけの状態も含む
    burnout_candidate_max_drive: float = 0.5
    # ラウンド開始バナーの前後ではゲージがまだ描画されず HUD 可視判定も残るため、
    # 明るい背景を回復バーと誤認する。バナーのこの秒数前後は候補から外す（ADR-065）
    burnout_round_banner_before_sec: float = 1.5
    burnout_round_banner_after_sec: float = 3.0
    # ADR-057: ラウンド終了（K.O.）後の試合間画面での HUD 誤検出を visible_to から除外する途切れ秒数
    round_end_gap_sec: float = 5.0
    # ADR-067: ラウンド開始直後は ROUND バナー／FIGHT 演出の白文字を K.O. と誤検出しやすく、
    # 実効終了が開始直後に切り詰められる。開始からこの秒数未満の K.O. 検出は無視する。
    # 誤検出は実測でバナー開始 +2.5 秒、SF6 でこの範囲の真の K.O. は実質存在しない
    ko_start_guard_sec: float = 5.0
    sa_digit_min_score: float = 0.45
    sa_bar_filled_v: int = 140
    sa_bar_filled_s: int = 100
    sa_max_gap_sec: float = 1.0
    sa_revert_window_sec: float = 1.0
    sa_progress_event_epsilon: float = 0.15
    ca_merge_gap_sec: float = 1.0
    # ADR-050: 体力ゲージ（現在体力のみ）
    health_filled_v: int = 110
    health_filled_s: int = 110
    health_column_fill_ratio: float = 0.5
    health_detect_min_fraction: float = 0.01
    health_smoothing_window: int = 7
    health_max_gap_sec: float = 1.0
    health_event_epsilon: float = 1.0
    health_warmup_sec: float = 1.5
    health_start_min_percent: float = 90.0
    health_max_increase_per_sec: float = 5.0
    # ADR-054: 回復可能ダメージ（白ゲージ）の観測
    health_recoverable_v_min: int = 130
    health_recoverable_s_min: int = 60
    health_despike_revert_sec: float = 1.2
    # ADR-061: 低体力（概ね25%以下）では現在体力バーが明るい黄色に変わる。
    # コンボダメージ／回復可能表示の「暗い黄色」とは明度で分離する
    health_low_v_min: int = 190

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    def log(self) -> None:
        logger.info("  [Gauge Thresholds]")
        for key, value in self.__dict__.items():
            logger.info("    %-32s %s", f"{key}:", value)


@dataclass
class RoundBannerTemplate:
    """ラウンド開始バナーのテンプレート定義（ADR-052）

    SF6 のラウンド開始バナーは「ROUND 1 / ROUND 2」と「FINAL ROUND」で文字列・
    レイアウトが異なる。文字列ごとにテンプレート・探索領域・閾値を持たせ、
    いずれかに一致したフレームをラウンド開始とみなす。
    """

    name: str
    template: str
    search_region: tuple[int, int, int, int]
    threshold: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoundBannerTemplate:
        return cls(
            name=str(data.get("name", "")),
            template=str(data.get("template", "")),
            search_region=tuple(data["search_region"]),
            threshold=float(data["threshold"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "template": self.template,
            "search_region": list(self.search_region),
            "threshold": self.threshold,
        }

    def _validate(self) -> None:
        if not self.template:
            raise ValueError(f"round_banners[{self.name}] template must not be empty")
        if len(self.search_region) != 4:
            raise ValueError(f"round_banners[{self.name}] search_region must have 4 elements, got {self.search_region}")
        x1, y1, x2, y2 = self.search_region
        if x2 <= x1 or y2 <= y1:
            raise ValueError(
                f"round_banners[{self.name}] search_region must be (x1, y1, x2, y2), got {self.search_region}"
            )
        if not 0 < self.threshold <= 1.0:
            raise ValueError(f"round_banners[{self.name}] threshold must be in (0, 1.0], got {self.threshold}")


@dataclass
class KoColorMaskParams:
    """K.O.文字の白/銀マスク照合パラメータ（ADR-063）

    K.O. 文字は背景が透ける半透明の白/銀文字で、輪郭はどのステージでも共通する。
    エッジ（輝度勾配）は背景のエッジに埋もれてしまうため、明るく低彩度な
    「文字の形」を二値マスクにして IoU で照合する。これにより背景ごとの
    テンプレート追加が不要になる。
    """

    enabled: bool = False
    search_region: tuple[int, int, int, int] = (640, 360, 1280, 720)
    s_max: int = 70
    v_min: int = 150
    threshold: float = 0.6
    min_consecutive: int = 2

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KoColorMaskParams:
        region = data.get("search_region")
        return cls(
            enabled=bool(data.get("enabled", True)),
            search_region=tuple(int(v) for v in region) if region else cls.search_region,
            s_max=int(data.get("s_max", 70)),
            v_min=int(data.get("v_min", 150)),
            threshold=float(data.get("threshold", 0.6)),
            min_consecutive=int(data.get("min_consecutive", 2)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "search_region": list(self.search_region),
            "s_max": self.s_max,
            "v_min": self.v_min,
            "threshold": self.threshold,
            "min_consecutive": self.min_consecutive,
        }

    def _validate(self) -> None:
        if len(self.search_region) != 4:
            raise ValueError(f"ko_color_mask search_region must have 4 elements, got {self.search_region}")
        x1, y1, x2, y2 = self.search_region
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"ko_color_mask search_region must be (x1, y1, x2, y2), got {self.search_region}")
        if not 0 <= self.s_max <= 255:
            raise ValueError(f"ko_color_mask s_max must be in [0, 255], got {self.s_max}")
        if not 0 <= self.v_min <= 255:
            raise ValueError(f"ko_color_mask v_min must be in [0, 255], got {self.v_min}")
        if not 0 < self.threshold <= 1.0:
            raise ValueError(f"ko_color_mask threshold must be in (0, 1.0], got {self.threshold}")
        if self.min_consecutive < 1:
            raise ValueError(f"ko_color_mask min_consecutive must be >= 1, got {self.min_consecutive}")


@dataclass
class BurnoutBannerParams:
    """バーンアウト開始時の EMPTY 文字（金色）マスク照合パラメータ（ADR-066）

    SF6 はバーンアウトした瞬間、ドライブゲージの上に金色の「EMPTY」を表示する。
    金色の文字マスク（テンプレート）と探索領域の金色マスクを照合し、
    「テンプレートのどれだけが一致したか（coverage）」と
    「探索領域の金色のうちどれだけがテンプレートと一致したか（precision）」の
    両方で判定する。低ドライブ警告の金色バー（矩形）は precision が下がるため除かれる。
    """

    enabled: bool = False
    search_region: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)
    templates: dict[str, str] = field(default_factory=dict)
    h_min: int = 8
    h_max: int = 35
    s_min: int = 110
    v_min: int = 215
    coverage: float = 0.4
    precision: float = 0.6
    scales: tuple[float, ...] = (0.85, 1.0, 1.18)
    min_consecutive: int = 2
    consecutive_window_sec: float = 0.3
    onset_tolerance_sec: float = 1.0
    same_time_tolerance_sec: float = 0.3

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BurnoutBannerParams:
        regions = data.get("search_region") or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            search_region={side: tuple(int(v) for v in regions[side]) for side in SIDES if side in regions},
            templates={side: str(path) for side, path in (data.get("templates") or {}).items()},
            h_min=int(data.get("h_min", 8)),
            h_max=int(data.get("h_max", 35)),
            s_min=int(data.get("s_min", 110)),
            v_min=int(data.get("v_min", 215)),
            coverage=float(data.get("coverage", 0.4)),
            precision=float(data.get("precision", 0.6)),
            scales=tuple(float(v) for v in (data.get("scales") or (0.85, 1.0, 1.18))),
            min_consecutive=int(data.get("min_consecutive", 2)),
            consecutive_window_sec=float(data.get("consecutive_window_sec", 0.3)),
            onset_tolerance_sec=float(data.get("onset_tolerance_sec", 1.0)),
            same_time_tolerance_sec=float(data.get("same_time_tolerance_sec", 0.3)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "search_region": {side: list(region) for side, region in self.search_region.items()},
            "templates": dict(self.templates),
            "h_min": self.h_min,
            "h_max": self.h_max,
            "s_min": self.s_min,
            "v_min": self.v_min,
            "coverage": self.coverage,
            "precision": self.precision,
            "scales": list(self.scales),
            "min_consecutive": self.min_consecutive,
            "consecutive_window_sec": self.consecutive_window_sec,
            "onset_tolerance_sec": self.onset_tolerance_sec,
            "same_time_tolerance_sec": self.same_time_tolerance_sec,
        }

    def _validate(self) -> None:
        for side, region in self.search_region.items():
            if len(region) != 4:
                raise ValueError(f"burnout_banner search_region[{side}] must have 4 elements, got {region}")
            x1, y1, x2, y2 = region
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f"burnout_banner search_region[{side}] must be (x1, y1, x2, y2), got {region}")
        for side, path in self.templates.items():
            if not path:
                raise ValueError(f"burnout_banner templates[{side}] must not be empty")
        for name in ("h_min", "h_max", "s_min", "v_min"):
            value = getattr(self, name)
            if not 0 <= value <= 255:
                raise ValueError(f"burnout_banner {name} must be in [0, 255], got {value}")
        if self.h_max <= self.h_min:
            raise ValueError(f"burnout_banner h_max must be > h_min, got {self.h_max}")
        if not 0 < self.coverage <= 1.0:
            raise ValueError(f"burnout_banner coverage must be in (0, 1.0], got {self.coverage}")
        if not 0 < self.precision <= 1.0:
            raise ValueError(f"burnout_banner precision must be in (0, 1.0], got {self.precision}")
        if not self.scales or any(scale <= 0 for scale in self.scales):
            raise ValueError(f"burnout_banner scales must be positive, got {self.scales}")
        if self.min_consecutive < 1:
            raise ValueError(f"burnout_banner min_consecutive must be >= 1, got {self.min_consecutive}")
        if self.consecutive_window_sec <= 0:
            raise ValueError(
                f"burnout_banner consecutive_window_sec must be positive, got {self.consecutive_window_sec}"
            )


@dataclass
class GaugeAnalysisParams:
    """ゲージ計測パラメータ（座標は base_width x base_height 基準）"""

    enabled: bool
    base_width: int
    base_height: int
    sample_interval_sec: float
    banner_scale: float
    banner_sample_interval_sec: float
    drive_roi: dict[str, tuple[int, int, int, int]]
    sa_digit_roi: dict[str, tuple[int, int, int, int]]
    sa_bar_roi: dict[str, tuple[int, int, int, int]]
    health_roi: dict[str, tuple[int, int, int, int]]
    health_hue_ranges: dict[str, list[tuple[int, int]]]
    health_low_hue_ranges: dict[str, list[tuple[int, int]]]
    health_poison_hue_ranges: dict[str, list[tuple[int, int]]]
    health_recoverable_hue_ranges: dict[str, list[tuple[int, int]]]
    thresholds: GaugeThresholds
    sa_digit_templates: dict[str, str]
    round_banners: list[RoundBannerTemplate]
    ko_banners: list[RoundBannerTemplate] = field(default_factory=list)
    ko_color_mask: KoColorMaskParams = field(default_factory=KoColorMaskParams)
    burnout_banner: BurnoutBannerParams = field(default_factory=BurnoutBannerParams)
    drive_fill_scale: dict[str, float] = field(default_factory=dict)
    health_fill_scale: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GaugeAnalysisParams:
        """設定ファイルの gauge_analysis セクションから生成"""
        thresholds = GaugeThresholds(**data.get("thresholds", {}))
        calibration = data.get("calibration", {}) or {}
        drive_fill_scale = {side: float(calibration.get("drive_fill_scale", {}).get(side, 1.0)) for side in SIDES}
        health_fill_scale = {side: float(calibration.get("health_fill_scale", {}).get(side, 1.0)) for side in SIDES}
        templates = data.get("templates", {}) or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            base_width=int(data.get("base_width", 1920)),
            base_height=int(data.get("base_height", 1080)),
            sample_interval_sec=float(data.get("sample_interval_sec", 0.1)),
            banner_scale=float(data.get("banner_scale", 0.5)),
            banner_sample_interval_sec=float(data.get("banner_sample_interval_sec", 0.25)),
            drive_roi={side: tuple(data["drive_roi"][side]) for side in SIDES},
            sa_digit_roi={side: tuple(data["sa_digit_roi"][side]) for side in SIDES},
            sa_bar_roi={side: tuple(data["sa_bar_roi"][side]) for side in SIDES},
            health_roi={side: tuple(data["health_roi"][side]) for side in SIDES},
            health_hue_ranges={
                side: [tuple(int(v) for v in pair) for pair in data["health_hue_ranges"][side]] for side in SIDES
            },
            health_low_hue_ranges={
                side: [tuple(int(v) for v in pair) for pair in (data.get("health_low_hue_ranges") or {}).get(side, [])]
                for side in SIDES
            },
            health_poison_hue_ranges={
                side: [
                    tuple(int(v) for v in pair) for pair in (data.get("health_poison_hue_ranges") or {}).get(side, [])
                ]
                for side in SIDES
            },
            health_recoverable_hue_ranges={
                side: [
                    tuple(int(v) for v in pair)
                    for pair in (data.get("health_recoverable_hue_ranges") or {}).get(side, [])
                ]
                for side in SIDES
            },
            thresholds=thresholds,
            sa_digit_templates=dict(templates.get("sa_digits") or {}),
            round_banners=[RoundBannerTemplate.from_dict(item) for item in data.get("round_banners", [])],
            ko_banners=[RoundBannerTemplate.from_dict(item) for item in data.get("ko_banners", [])],
            ko_color_mask=KoColorMaskParams.from_dict(data.get("ko_color_mask") or {}),
            burnout_banner=BurnoutBannerParams.from_dict(data.get("burnout_banner") or {}),
            drive_fill_scale=drive_fill_scale,
            health_fill_scale=health_fill_scale,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_width": self.base_width,
            "base_height": self.base_height,
            "sample_interval_sec": self.sample_interval_sec,
            "banner_scale": self.banner_scale,
            "banner_sample_interval_sec": self.banner_sample_interval_sec,
            "drive_roi": {k: list(v) for k, v in self.drive_roi.items()},
            "sa_digit_roi": {k: list(v) for k, v in self.sa_digit_roi.items()},
            "sa_bar_roi": {k: list(v) for k, v in self.sa_bar_roi.items()},
            "health_roi": {k: list(v) for k, v in self.health_roi.items()},
            "health_hue_ranges": {k: [list(pair) for pair in v] for k, v in self.health_hue_ranges.items()},
            "health_low_hue_ranges": {k: [list(pair) for pair in v] for k, v in self.health_low_hue_ranges.items()},
            "health_poison_hue_ranges": {
                k: [list(pair) for pair in v] for k, v in self.health_poison_hue_ranges.items()
            },
            "health_recoverable_hue_ranges": {
                k: [list(pair) for pair in v] for k, v in self.health_recoverable_hue_ranges.items()
            },
            "thresholds": self.thresholds.to_dict(),
            "templates": {
                "sa_digits": dict(self.sa_digit_templates),
            },
            "round_banners": [banner.to_dict() for banner in self.round_banners],
            "ko_banners": [banner.to_dict() for banner in self.ko_banners],
            "ko_color_mask": self.ko_color_mask.to_dict(),
            "burnout_banner": self.burnout_banner.to_dict(),
            "calibration": {
                "drive_fill_scale": dict(self.drive_fill_scale),
                "health_fill_scale": dict(self.health_fill_scale),
            },
        }

    def _validate(self) -> None:
        if self.sample_interval_sec <= 0:
            raise ValueError(f"sample_interval_sec must be positive, got {self.sample_interval_sec}")
        if not 0 < self.banner_scale <= 1.0:
            raise ValueError(f"banner_scale must be in (0, 1.0], got {self.banner_scale}")
        for name, roi in {
            "drive_roi": self.drive_roi,
            "sa_digit_roi": self.sa_digit_roi,
            "sa_bar_roi": self.sa_bar_roi,
            "health_roi": self.health_roi,
        }.items():
            for side, values in roi.items():
                if len(values) != 4:
                    raise ValueError(f"{name}[{side}] must have 4 elements, got {values}")
                if values[2] <= values[0] or values[3] <= values[1]:
                    raise ValueError(f"{name}[{side}] must be (x1, y1, x2, y2) with x2>x1, y2>y1, got {values}")
        if not self.round_banners:
            logger.warning("round_banners is empty; round start banner detection is disabled")
        for banner in self.round_banners:
            banner._validate()
        for banner in self.ko_banners:
            banner._validate()
        self.ko_color_mask._validate()
        self.burnout_banner._validate()

    def log_params(self) -> None:
        logger.info("  [Gauge Analysis]")
        logger.info("    enabled:                  %s", self.enabled)
        logger.info("    base size:                %dx%d", self.base_width, self.base_height)
        logger.info("    sample_interval_sec:      %.2f", self.sample_interval_sec)
        logger.info("    banner_scale:             %.2f", self.banner_scale)
        logger.info("    banner_sample_interval:   %.2f", self.banner_sample_interval_sec)
        for side in SIDES:
            logger.info("    drive_roi[%s]:       %s", side, self.drive_roi[side])
            logger.info("    sa_digit_roi[%s]:    %s", side, self.sa_digit_roi[side])
            logger.info("    sa_bar_roi[%s]:      %s", side, self.sa_bar_roi[side])
            logger.info("    health_roi[%s]:      %s", side, self.health_roi[side])
        for side in SIDES:
            logger.info("    health_hue_ranges[%s]: %s", side, self.health_hue_ranges[side])
        for side in SIDES:
            logger.info("    health_low_hue_ranges[%s]: %s", side, self.health_low_hue_ranges[side])
        for side in SIDES:
            logger.info("    health_poison_hue_ranges[%s]: %s", side, self.health_poison_hue_ranges[side])
        for side in SIDES:
            logger.info("    health_recoverable_hue_ranges[%s]: %s", side, self.health_recoverable_hue_ranges[side])
        for banner in self.round_banners:
            logger.info(
                "    round_banner[%s]: region=%s threshold=%.2f template=%s",
                banner.name,
                banner.search_region,
                banner.threshold,
                banner.template,
            )
        for banner in self.ko_banners:
            logger.info(
                "    ko_banner[%s]: region=%s threshold=%.2f template=%s",
                banner.name,
                banner.search_region,
                banner.threshold,
                banner.template,
            )
        km = self.ko_color_mask
        logger.info(
            "    ko_color_mask: enabled=%s region=%s s_max=%d v_min=%d threshold=%.2f min_consecutive=%d",
            km.enabled,
            km.search_region,
            km.s_max,
            km.v_min,
            km.threshold,
            km.min_consecutive,
        )
        self.thresholds.log()


@dataclass
class SideGaugeState:
    """1サンプル時点の片側のゲージ状態

    feed() 直後は raw 値のみが入っており、build() 内の派生処理で
    drive / drive_burnout（平滑化・バーンアウト判定後）が埋まる。
    """

    hud_visible: bool = False
    drive_raw: float | None = None  # 黄緑（通常）と金色（低ドライブ警告）の充填から換算した本数。None=どちらも検出なし
    drive_recover_raw: float | None = None  # ADR-065: 中央側から連続する白/銀回復バーの充填率（0〜1）。None=検出なし
    burnout_candidate: bool = False  # HUD表示中に白/銀の回復バーが検出された状態（ADR-065）
    drive: float | None = None  # 平滑化・バーンアウト判定後の本数
    drive_burnout: bool = False
    sa_stock: int | None = None
    sa_label: str | None = None
    sa_score: float = 0.0
    sa_critical_art: bool = False
    sa_progress: float | None = None
    # ADR-050: 現在体力（％）。None=未計測
    health_raw: float | None = None
    health: float | None = None
    # ADR-062: 毒の紫を含めた現在体力（％）。A.K.I. の試合でのみ採用する
    health_poison_raw: float | None = None
    health_poison: float | None = None
    # ADR-054: 回復可能ダメージ（％）。None=未計測
    health_recoverable_raw: float | None = None
    health_recoverable: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hudVisible": self.hud_visible,
            "drive": self.drive,
            "driveRaw": self.drive_raw,
            "driveRecoverRaw": self.drive_recover_raw,
            "driveBurnout": self.drive_burnout,
            "saStock": self.sa_stock,
            "saLabel": self.sa_label,
            "saScore": round(self.sa_score, 3),
            "saCriticalArt": self.sa_critical_art,
            "saProgress": self.sa_progress,
            "health": self.health,
            "healthRaw": self.health_raw,
            "healthPoison": self.health_poison,
            "healthPoisonRaw": self.health_poison_raw,
            "healthRecoverable": self.health_recoverable,
            "healthRecoverableRaw": self.health_recoverable_raw,
        }


@dataclass
class GaugeSample:
    """1サンプル時点の両サイドの状態"""

    timestamp: float
    states: dict[str, SideGaugeState]


def _median_filter(values: list[float | None], window: int) -> list[float | None]:
    """None を無視するメディアンフィルタ（中心対称）"""
    if window <= 1:
        return list(values)
    half = window // 2
    result: list[float | None] = []
    for index in range(len(values)):
        nearby = [
            values[i] for i in range(max(0, index - half), min(len(values), index + half + 1)) if values[i] is not None
        ]
        result.append(float(np.median(nearby)) if nearby else None)
    return result


def _fill_short_gaps(values: list[float | None], timestamps: list[float], max_gap_sec: float) -> list[float | None]:
    """短い欠損を直前の値で埋める（max_gap_sec を超える欠損は None のまま）"""
    result = list(values)
    index = 0
    while index < len(result):
        if result[index] is not None:
            index += 1
            continue
        start = index
        while index < len(result) and result[index] is None:
            index += 1
        end = index  # exclusive
        if start == 0 or end >= len(result):
            continue
        gap = timestamps[end] - timestamps[start - 1]
        if gap <= max_gap_sec:
            previous = result[start - 1]
            for i in range(start, end):
                result[i] = previous
    return result


def _suppress_transient_reverts(
    values: list[float | None], timestamps: list[float], max_revert_sec: float
) -> list[float | None]:
    """SA ストック／体力の「一時的な下振れ→即復帰」を計測ノイズとして除去する

    SA ゲージが実際に減少するのはスーパーアーツ／クリティカルアートの発動時だけで、
    消費したストックはバーが溜まるまで戻らない。体力も通常の被弾は永続的で、増加するのは
    回復可能ダメージの自然回復かエレナの SA2 のみ。したがって直前値より下がったあと
    ``max_revert_sec`` 以内に直前値以上へ戻る下振れは誤検出（ヒット演出・遮蔽など）と
    みなし、直前値で塗り直す。

    下振れが復帰しない場合（＝本当に被弾／スーパーアーツを使った場合）や、復帰が
    ``max_revert_sec`` より遅い場合はそのまま残す。
    """
    result = list(values)
    index = 1
    while index < len(result):
        previous = result[index - 1]
        current = result[index]
        if previous is None or current is None or current >= previous:
            index += 1
            continue

        # 直前値以上へ戻るサンプルを max_revert_sec 以内で探す
        end = index
        while end < len(result):
            if timestamps[end] - timestamps[index - 1] > max_revert_sec:
                break
            if result[end] is not None and result[end] >= previous:
                break
            end += 1

        if (
            end < len(result)
            and result[end] is not None
            and result[end] >= previous
            and timestamps[end] - timestamps[index - 1] <= max_revert_sec
        ):
            for i in range(index, end):
                result[i] = previous
            index = end
            continue

        index += 1

    return result


def _find_runs(flags: list[bool], timestamps: list[float]) -> list[tuple[int, int]]:
    """True が連続する区間を [start, end) の添字で返す"""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def _runs_to_periods(runs: list[tuple[int, int]], timestamps: list[float]) -> list[list[float]]:
    """添字の連続区間を時刻の期間リストに変換する"""
    return [[round(timestamps[start], 2), round(timestamps[end - 1], 2)] for start, end in runs]


def _merge_periods(periods: list[list[float]], gap_sec: float) -> list[list[float]]:
    """近接する期間を結合する（gap_sec 以内の間隔は同一期間とみなす）"""
    if not periods:
        return []
    ordered = sorted(periods, key=lambda period: period[0])
    merged: list[list[float]] = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start - merged[-1][1] <= gap_sec:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


class GaugeAnalyzer:
    """デコードループから呼び出されるゲージ計測器

    使い方::

        analyzer = GaugeAnalyzer(params, app_root)
        matcher.set_gauge_analyzer(analyzer)   # detect_matches() のループ内で feed() が呼ばれる
        detections = matcher.detect_matches(...)
        gauge_data = analyzer.build(matches, video_end=...)
    """

    # デバッグ用スナップショットの保存上限
    MAX_SNAPSHOTS = 80

    def __init__(self, params: GaugeAnalysisParams, app_root: Path):
        params._validate()
        self.params = params
        self.app_root = Path(app_root)

        self.samples: list[GaugeSample] = []
        self.round_banner_times: list[float] = []
        self.ko_times: list[float] = []
        self.burnout_banner_times: dict[str, list[float]] = {side: [] for side in SIDES}  # noqa: C420
        self._burnout_banner_hits: dict[str, list[float]] = {side: [] for side in SIDES}  # noqa: C420
        self._ko_color_streak = 0
        self._ko_color_first: float | None = None
        self.snapshots: list[dict[str, Any]] = []
        self.burnout_periods: dict[str, list[list[float]]] = {side: [] for side in SIDES}  # noqa: C420 (共有リスト回避のため内包表記)

        self._last_sample_time: float | None = None
        self._last_banner_time: float | None = None
        self._prev_states: dict[str, SideGaugeState | None] = dict.fromkeys(SIDES)
        self._derived = False

        # テンプレートを読み込む
        self._sa_edge_templates: dict[str, np.ndarray] = {}
        for label, path in params.sa_digit_templates.items():
            template = cv2.imread(str(self._resolve(path)), cv2.IMREAD_COLOR)
            if template is None:
                logger.warning("⚠️ SA digit template not found: %s", path)
                continue
            self._sa_edge_templates[label] = preprocess_for_matching(template)

        self._round_banner_templates: list[tuple[RoundBannerTemplate, np.ndarray]] = []
        for banner in params.round_banners:
            image = cv2.imread(str(self._resolve(banner.template)), cv2.IMREAD_COLOR)
            if image is None:
                logger.warning("⚠️ Round banner template not found: %s", banner.template)
                continue
            self._round_banner_templates.append((banner, image))

        # バーンアウト開始の EMPTY 文字マスク（ADR-066）
        self._burnout_banner_templates: dict[str, list[np.ndarray]] = {side: [] for side in SIDES}  # noqa: C420
        if params.burnout_banner.enabled:
            for side in SIDES:
                path = params.burnout_banner.templates.get(side)
                if not path:
                    continue
                mask = cv2.imread(str(self._resolve(path)), cv2.IMREAD_GRAYSCALE)
                if mask is None:
                    logger.warning("⚠️ Burnout banner template not found: %s", path)
                    continue
                self._burnout_banner_templates[side].append(mask)

        # K.O. バナー（勝利演出の検出、ADR-059）
        self._ko_banner_templates: list[tuple[RoundBannerTemplate, np.ndarray]] = []
        for banner in params.ko_banners:
            image = cv2.imread(str(self._resolve(banner.template)), cv2.IMREAD_COLOR)
            if image is None:
                logger.warning("⚠️ KO banner template not found: %s", banner.template)
                continue
            self._ko_banner_templates.append((banner, image))

        # 実フレームサイズに応じたスケール済み ROI（最初の feed で確定）
        self._frame_size: tuple[int, int] | None = None
        self._roi: dict[str, dict[str, tuple[int, int, int, int]]] = {}
        self._round_banner_prepared: list[dict[str, Any]] = []
        self._ko_banner_prepared: list[dict[str, Any]] = []
        self._ko_color_masks: list[np.ndarray] = []
        self._ko_color_search: tuple[int, int, int, int] | None = None

    # ------------------------------------------------------------------
    # 計測本体
    # ------------------------------------------------------------------
    @property
    def banner_times(self) -> list[float]:
        """検出した ROUND バナーの時刻（秒、昇順）"""
        return list(self.round_banner_times)

    def feed(self, frame: np.ndarray, timestamp: float) -> None:
        """デコードループから毎フレーム呼び出す（間隔判定は内部で行う）"""
        if not self.params.enabled or self._derived:
            return
        if not self._prepare_geometry(frame):
            return

        interval = self.params.banner_sample_interval_sec
        if self._last_banner_time is None or timestamp - self._last_banner_time >= interval:
            self._last_banner_time = timestamp
            if self._detect_round_banner(frame, timestamp):
                self.round_banner_times.append(timestamp)
                self._add_snapshot(frame, timestamp, "round_banner")
                logger.info("[Gauge] ROUND banner detected at %.2fs", timestamp)
            ko_time = self._detect_ko(frame, timestamp)
            if ko_time is not None:
                self.ko_times.append(ko_time)
                logger.info("[Gauge] K.O. banner detected at %.2fs", ko_time)

        interval = self.params.sample_interval_sec
        if self._last_sample_time is not None and timestamp - self._last_sample_time < interval:
            return
        self._last_sample_time = timestamp

        states: dict[str, SideGaugeState] = {}
        for side in SIDES:
            raw_drive = self._measure_drive(frame, side)
            drive_recover = self._measure_drive_recover(frame, side)
            self._detect_burnout_banner(frame, side, timestamp)
            sa_stock, sa_label, sa_score, sa_progress, sa_ca = self._measure_sa(frame, side)
            health_raw = self._measure_health(frame, side, include_poison=False)
            health_poison_raw = self._measure_health(frame, side, include_poison=True)
            health_recoverable_raw = self._measure_health_recoverable(frame, side)
            hud_visible = sa_score >= self.params.thresholds.sa_digit_min_score
            states[side] = SideGaugeState(
                hud_visible=hud_visible,
                drive_raw=raw_drive,
                drive_recover_raw=drive_recover,
                burnout_candidate=hud_visible and drive_recover is not None,
                health_raw=health_raw,
                health_poison_raw=health_poison_raw,
                health_recoverable_raw=health_recoverable_raw,
                sa_stock=sa_stock,
                sa_label=sa_label,
                sa_score=sa_score,
                sa_critical_art=sa_ca,
                sa_progress=sa_progress,
            )

            previous = self._prev_states[side]
            if previous is not None:
                if states[side].burnout_candidate and not previous.burnout_candidate:
                    self._add_snapshot(frame, timestamp, "burnout_candidate")
                if states[side].sa_critical_art and not previous.sa_critical_art:
                    self._add_snapshot(frame, timestamp, "critical_art_start")
                if states[side].sa_stock != previous.sa_stock and states[side].sa_stock is not None:
                    self._add_snapshot(frame, timestamp, "sa_change")
            self._prev_states[side] = states[side]

        self.samples.append(GaugeSample(timestamp=timestamp, states=states))

    def build(
        self,
        matches: list[tuple[str, float]],
        video_end: float | None = None,
        characters: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """検出済みマッチ情報からラウンド単位のゲージデータを構築する

        Args:
            matches: (match_id, 開始時刻[秒]) のリスト（時系列順）
            video_end: 動画長（秒）。最後の試合の終端に使う
            characters: match_id -> {"player1": キャラ名, "player2": キャラ名}。
                エレナの SA2 による回復を例外扱いするために使う（ADR-054）。

        Returns:
            {"videoId": ..., "matches": {match_id: {"matchId":..., "rounds": [...]}}, ...}
        """
        self._derive_states()

        if not matches:
            return {"matches": {}, "roundBannerTimes": list(self.round_banner_times)}

        if video_end is None:
            video_end = self.samples[-1].timestamp if self.samples else 0.0

        out_matches: dict[str, Any] = {}
        for index, (match_id, start_time) in enumerate(matches):
            end_time = matches[index + 1][1] if index + 1 < len(matches) else video_end
            rounds = self._build_match_rounds(match_id, start_time, end_time, (characters or {}).get(match_id) or {})
            out_matches[match_id] = {"matchId": match_id, "rounds": rounds}

        return {
            "matches": out_matches,
            "roundBannerTimes": list(self.round_banner_times),
            "koTimes": list(self.ko_times),
            "burnoutBannerTimes": {side: list(times) for side, times in self.burnout_banner_times.items()},
            "burnoutPeriods": dict(self.burnout_periods),
        }

    # ------------------------------------------------------------------
    # 内部処理: 幾何・判定
    # ------------------------------------------------------------------
    def _resolve(self, path: str) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else self.app_root / candidate

    def _prepare_geometry(self, frame: np.ndarray) -> bool:
        """実フレームサイズに合わせて ROI をスケールする（初回のみ）"""
        height, width = frame.shape[:2]
        if self._frame_size == (width, height):
            return True

        scale_x = width / self.params.base_width
        scale_y = height / self.params.base_height

        def scale_roi(roi: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            x1, y1, x2, y2 = roi
            return (
                int(round(x1 * scale_x)),
                int(round(y1 * scale_y)),
                int(round(x2 * scale_x)),
                int(round(y2 * scale_y)),
            )

        self._roi = {
            "drive": {side: scale_roi(self.params.drive_roi[side]) for side in SIDES},
            "sa_digit": {side: scale_roi(self.params.sa_digit_roi[side]) for side in SIDES},
            "sa_bar": {side: scale_roi(self.params.sa_bar_roi[side]) for side in SIDES},
            "health": {side: scale_roi(self.params.health_roi[side]) for side in SIDES},
        }
        self._frame_size = (width, height)

        # バーンアウト開始の EMPTY 文字マスク（ADR-066）: 実フレームサイズに合わせて拡大縮小する
        self._burnout_banner_search: dict[str, tuple[int, int, int, int]] = {}
        self._burnout_banner_masks: dict[str, list[np.ndarray]] = {side: [] for side in SIDES}  # noqa: C420
        banner = self.params.burnout_banner
        if banner.enabled and any(self._burnout_banner_templates.values()):
            for side in SIDES:
                region = banner.search_region.get(side)
                if region is None or not self._burnout_banner_templates[side]:
                    continue
                self._burnout_banner_search[side] = scale_roi(region)
                for base in self._burnout_banner_templates[side]:
                    for scale in banner.scales:
                        mask_w = max(4, int(round(base.shape[1] * scale_x * scale)))
                        mask_h = max(4, int(round(base.shape[0] * scale_y * scale)))
                        resized = cv2.resize(base, (mask_w, mask_h), interpolation=cv2.INTER_AREA)
                        self._burnout_banner_masks[side].append((resized > 127).astype(np.uint8))

        banner_scale = self.params.banner_scale
        self._round_banner_prepared = []
        for banner, image in self._round_banner_templates:
            resized = cv2.resize(image, None, fx=banner_scale, fy=banner_scale, interpolation=cv2.INTER_AREA)
            self._round_banner_prepared.append(
                {
                    "name": banner.name,
                    "search": scale_roi(banner.search_region),
                    "template": preprocess_for_matching(resized),
                    "threshold": banner.threshold,
                }
            )

        self._ko_banner_prepared = []
        for banner, image in self._ko_banner_templates:
            resized = cv2.resize(image, None, fx=banner_scale, fy=banner_scale, interpolation=cv2.INTER_AREA)
            self._ko_banner_prepared.append(
                {
                    "name": banner.name,
                    "search": scale_roi(banner.search_region),
                    "template": preprocess_for_matching(resized),
                    "threshold": banner.threshold,
                }
            )

        # K.O. 文字の白/銀マスクテンプレート（ADR-063）。既存の K.O. テンプレート画像から
        # 明るく低彩度な画素だけを抜き出し、背景に依存しない形状として使う
        self._ko_color_masks = []
        ko_color = self.params.ko_color_mask
        if ko_color.enabled and self._ko_banner_templates:
            color_search = scale_roi(ko_color.search_region)
            mask_w = max(1, color_search[2] - color_search[0])
            mask_h = max(1, color_search[3] - color_search[1])
            for _banner, image in self._ko_banner_templates:
                resized = cv2.resize(image, (mask_w, mask_h), interpolation=cv2.INTER_AREA)
                self._ko_color_masks.append(self._white_mask(resized, ko_color))
            self._ko_color_search = color_search
            logger.info("[Gauge] K.O. color mask prepared with %d templates", len(self._ko_color_masks))

        logger.info("[Gauge] Geometry prepared for %dx%d (scale x%.3f, y%.3f)", width, height, scale_x, scale_y)
        return True

    def _crop(self, frame: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = roi
        height, width = frame.shape[:2]
        x1 = max(0, min(x1, width - 1))
        x2 = max(x1 + 1, min(x2, width))
        y1 = max(0, min(y1, height - 1))
        y2 = max(y1 + 1, min(y2, height))
        return frame[y1:y2, x1:x2]

    def _detect_round_banner(self, frame: np.ndarray, timestamp: float) -> bool:
        """ラウンド開始バナーを検出する（ADR-048 / ADR-052）

        「ROUND」（ROUND 1 / ROUND 2）と「FINAL ROUND」でテンプレートが異なるため、
        定義済みの全テンプレートを照合し、いずれかが閾値を超えれば検出とする。
        """
        if not self._round_banner_prepared:
            return False

        scale = self.params.banner_scale
        for banner in self._round_banner_prepared:
            region = self._crop(frame, banner["search"])
            if region.size == 0:
                continue
            scaled = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            edges = preprocess_for_matching(scaled)

            template = banner["template"]
            if template.shape[0] > edges.shape[0] or template.shape[1] > edges.shape[1]:
                continue

            score = float(cv2.matchTemplate(edges, template, cv2.TM_CCOEFF_NORMED).max())
            if score < banner["threshold"]:
                continue

            # 近接フレームの多重検出を抑制（バナーは約1.5秒表示される）
            if self.round_banner_times and timestamp - self.round_banner_times[-1] < 3.0:
                return False
            logger.debug("[Gauge] Round banner '%s' matched at %.2fs (score %.3f)", banner["name"], timestamp, score)
            return True

        return False

    def _detect_ko(self, frame: np.ndarray, timestamp: float) -> float | None:
        """K.O. バナー（勝利演出の開始）を検出し、確定時刻を返す（ADR-059 / ADR-063）

        エッジテンプレート（背景依存）と白/銀マスク（背景非依存）を併用する。
        マスク照合は min_consecutive 回連続で閾値を超えた時点で確定し、
        最初に閾値を超えた時刻を返す（単発の白フラッシュを除外するため）。
        検出時刻は ko_times に記録され、勝利演出中の health 誤読の除去に使う。
        """
        if self._detect_ko_edge(frame):
            self._ko_color_streak = 0
            self._ko_color_first = None
            return self._register_ko_time(timestamp)

        if self._ko_color_masks and self._ko_color_search is not None:
            score = self._ko_color_score(frame)
            if score >= self.params.ko_color_mask.threshold:
                if self._ko_color_streak == 0:
                    self._ko_color_first = timestamp
                self._ko_color_streak += 1
                if self._ko_color_streak >= self.params.ko_color_mask.min_consecutive:
                    first = self._ko_color_first if self._ko_color_first is not None else timestamp
                    self._ko_color_streak = 0
                    self._ko_color_first = None
                    logger.debug("[Gauge] K.O. color mask matched at %.2fs (IoU %.3f)", first, score)
                    return self._register_ko_time(first)
            else:
                self._ko_color_streak = 0
                self._ko_color_first = None

        return None

    def _detect_ko_edge(self, frame: np.ndarray) -> bool:
        """エッジテンプレートによる K.O. 検出（ADR-059）"""
        if not self._ko_banner_prepared:
            return False

        scale = self.params.banner_scale
        for prepared in self._ko_banner_prepared:
            region = self._crop(frame, prepared["search"])
            if region.size == 0:
                continue
            scaled = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            edges = preprocess_for_matching(scaled)

            template = prepared["template"]
            if template.shape[0] > edges.shape[0] or template.shape[1] > edges.shape[1]:
                continue

            score = float(cv2.matchTemplate(edges, template, cv2.TM_CCOEFF_NORMED).max())
            if score < prepared["threshold"]:
                continue

            logger.debug("[Gauge] K.O. banner '%s' matched (score %.3f)", prepared["name"], score)
            return True

        return False

    def _register_ko_time(self, timestamp: float) -> float | None:
        """近接する多重検出を抑制して K.O. 時刻を確定する

        K.O. 文字は約2秒表示されるため、直近3秒以内の再検出は無視する。
        """
        if self.ko_times and timestamp - self.ko_times[-1] < 3.0:
            return None
        return timestamp

    @staticmethod
    def _white_mask(image: np.ndarray, params: KoColorMaskParams) -> np.ndarray:
        """明るく低彩度な画素（白/銀の K.O. 文字）を二値マスク化する（ADR-063）"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1].astype(np.int16)
        value = hsv[:, :, 2].astype(np.int16)
        return ((saturation < params.s_max) & (value > params.v_min)).astype(np.uint8)

    @staticmethod
    def _gold_mask(image: np.ndarray, params: BurnoutBannerParams) -> np.ndarray:
        """バーンアウトの EMPTY 文字（高輝度の金色）を二値マスク化する（ADR-066）"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0].astype(np.int16)
        saturation = hsv[:, :, 1].astype(np.int16)
        value = hsv[:, :, 2].astype(np.int16)
        return (
            (hue >= params.h_min) & (hue <= params.h_max) & (saturation >= params.s_min) & (value >= params.v_min)
        ).astype(np.uint8)

    def _detect_burnout_banner(self, frame: np.ndarray, side: str, timestamp: float) -> None:
        """バーンアウト開始時の EMPTY 文字を検出する（ADR-066）

        金色文字のマスクと、探索領域の金色マスクの
        coverage（テンプレートの何割が一致したか）と
        precision（領域の金色のうち何割をテンプレートで説明できるか）
        の両方が閾値を超えたフレームを検出とみなす。大きな金色の塊（低ドライブ警告の金色バーや
        全画面の演出）は precision が低いため検出されない。単発の金色演出を除外するため、
        consecutive_window_sec 以内に min_consecutive 回検出した時点で最初の時刻を記録する
        （EMPTY 文字は約0.5秒しか出ないため、連続フレームでは拾えないことがある）。
        """
        params = self.params.burnout_banner
        search = self._burnout_banner_search.get(side)
        masks = self._burnout_banner_masks.get(side) or []
        if search is None or not masks:
            return
        region = self._crop(frame, search)
        if region.size == 0:
            return

        detected = False
        mask = self._gold_mask(region, params).astype(np.float32)
        region_gold = float(mask.sum())
        if region_gold > 0:
            for template in masks:
                if template.shape[0] > mask.shape[0] or template.shape[1] > mask.shape[1]:
                    continue
                template_f = template.astype(np.float32)
                # 一致量は相関の最大値。coverage はテンプレートの一致割合、precision は
                # 探索領域の金色のうちテンプレートで説明できる割合（大きな金色の塊を除く）
                intersection = float(cv2.matchTemplate(mask, template_f, cv2.TM_CCORR).max())
                coverage = intersection / float(template_f.sum())
                precision = intersection / region_gold
                if coverage >= params.coverage and precision >= params.precision:
                    detected = True
                    break

        hits = self._burnout_banner_hits[side]
        if detected:
            hits.append(timestamp)
        while hits and timestamp - hits[0] > params.consecutive_window_sec:
            hits.pop(0)
        if not detected or len(hits) < params.min_consecutive:
            return
        first = hits[0]
        hits.clear()
        times = self.burnout_banner_times[side]
        if times and first - times[-1] < 3.0:
            return
        times.append(first)
        self._add_snapshot(frame, timestamp, "burnout_banner")
        logger.debug("[Gauge] EMPTY banner detected at %.2fs (%s)", first, side)

    def _effective_burnout_banner_times(self, side: str) -> list[float]:
        """EMPTY 文字の検出時刻から、全画面演出による誤検出を除いたものを返す（ADR-066）

        両サイドでほぼ同時に検出されたものは全画面の金色演出なので、
        どちらのプレイヤーのバーンアウトでもない。
        """
        tolerance = self.params.burnout_banner.same_time_tolerance_sec
        other = SIDES[1] if side == SIDES[0] else SIDES[0]
        others = self.burnout_banner_times.get(other, [])
        results: list[float] = []
        for timestamp in self.burnout_banner_times.get(side, []):
            if any(abs(timestamp - value) <= tolerance for value in others):
                continue
            results.append(timestamp)
        return results

    def _ko_color_score(self, frame: np.ndarray) -> float:
        """K.O. 文字の白/銀マスクと検索領域のマスクの最大 IoU を返す（ADR-063）"""
        if self._ko_color_search is None:
            return 0.0
        region = self._crop(frame, self._ko_color_search)
        if region.size == 0:
            return 0.0
        mask = self._white_mask(region, self.params.ko_color_mask)
        total = int(mask.sum())
        if total == 0:
            return 0.0
        best = 0.0
        for template in self._ko_color_masks:
            inter = int(np.logical_and(mask, template).sum())
            union = total + int(template.sum()) - inter
            if union > 0:
                best = max(best, inter / union)
        return best

    def _measure_drive(self, frame: np.ndarray, side: str) -> float | None:
        """ドライブゲージの残量を本数で返す（ADR-065）

        黄緑（通常ゲージ）と金色/オレンジ（2 本以下で出る低ドライブ警告）の両方を充填として数える。

        Returns:
            0〜6（小数あり）。どちらも検出できない場合は None
            （バーンアウト中や HUD 非表示時は None になる）
        """
        thresholds = self.params.thresholds
        roi = self._crop(frame, self._roi["drive"][side])
        if roi.size == 0:
            return None

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0].astype(np.int16)
        sat = hsv[:, :, 1].astype(np.int16)
        val = hsv[:, :, 2].astype(np.int16)

        normal = (
            (val > thresholds.drive_filled_v)
            & (sat > thresholds.drive_filled_s)
            & (hue >= thresholds.drive_filled_h_min)
            & (hue <= thresholds.drive_filled_h_max)
        )
        low = (
            (val > thresholds.drive_low_filled_v)
            & (val <= thresholds.drive_filled_v)
            & (sat > thresholds.drive_filled_s)
            & (hue >= thresholds.drive_low_filled_h_min)
            & (hue <= thresholds.drive_low_filled_h_max)
        )
        filled = normal | low

        width = float(hsv.shape[1])
        filled_fraction = float((filled.mean(axis=0) >= thresholds.drive_column_fill_ratio).sum()) / width
        if filled_fraction < thresholds.drive_detect_min_fraction:
            return None

        raw = min(DRIVE_MAX, filled_fraction * DRIVE_MAX)
        return round(min(DRIVE_MAX, raw * self.params.drive_fill_scale.get(side, 1.0)), 2)

    def _measure_drive_recover(self, frame: np.ndarray, side: str) -> float | None:
        """バーンアウト中の白/銀回復バーの充填率（0〜1）を返す（ADR-065）

        回復バーは画面中央側（1P=右端 / 2P=左端）から溜まるため、
        中央側から連続する「低彩度・高明度」の列だけを数える。ゲージ上下の枠線は
        常に明るいので内側の行だけを見る。通常ゲージ（黄緑）、低ドライブ警告（金色）、
        空きトラック（暗い青）、背景の映り込みはいずれも白と判定されない。

        Returns:
            0〜1。回復バーが検出できない場合は None
        """
        thresholds = self.params.thresholds
        roi = self._crop(frame, self._roi["drive"][side])
        inset = thresholds.drive_recover_inset_px
        if roi.shape[0] <= inset * 2 + 1:
            return None
        inner = roi[inset : roi.shape[0] - inset]
        if inner.size == 0:
            return None

        hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1].astype(np.int16)
        val = hsv[:, :, 2].astype(np.int16)
        # 全画面の白フラッシュ（ヒット演出やラウンド移行）は ROI 全体が白飛びする。
        # 白飛びの割合が高ければ回復バーではない
        blown = float(((sat <= thresholds.drive_recover_s_max) & (val > thresholds.drive_recover_flash_v_min)).mean())
        if blown >= thresholds.drive_recover_max_flash_fraction:
            return None
        white = (
            (val >= thresholds.drive_recover_v_min)
            & (val <= thresholds.drive_recover_v_max)
            & (sat <= thresholds.drive_recover_s_max)
        )
        filled_columns = white.mean(axis=0) >= thresholds.drive_recover_column_fill_ratio

        # 画面中央側（1P=右端 / 2P=左端）から連続する列だけを数える
        x1, _, x2, _ = self._roi["drive"][side]
        anchor_right = ((x1 + x2) / 2) < (frame.shape[1] / 2)
        width = len(filled_columns)
        order = range(width - 1, -1, -1) if anchor_right else range(width)
        count = 0
        for column in order:
            if not filled_columns[column]:
                break
            count += 1
        fraction = count / float(width)
        if fraction < thresholds.drive_recover_min_fraction:
            return None
        return round(fraction, 3)

    def _measure_sa(self, frame: np.ndarray, side: str) -> tuple[int | None, str | None, float, float | None, bool]:
        """SAゲージ（ストック数とバー進捗）を計測する

        Returns:
            (ストック数 0〜3, グリフ名, スコア, バー進捗 0〜1, CA表示か)
        """
        thresholds = self.params.thresholds

        digit_roi = self._crop(frame, self._roi["sa_digit"][side])
        best_label: str | None = None
        best_score = 0.0
        if digit_roi.size > 0 and self._sa_edge_templates:
            edges = preprocess_for_matching(digit_roi)
            for label, template in self._sa_edge_templates.items():
                if template.shape[0] > edges.shape[0] or template.shape[1] > edges.shape[1]:
                    continue
                score = float(cv2.matchTemplate(edges, template, cv2.TM_CCOEFF_NORMED).max())
                if score > best_score:
                    best_label, best_score = label, score

        stock: int | None = None
        critical_art = False
        if best_label is not None and best_score >= thresholds.sa_digit_min_score:
            if best_label == "ca":
                stock = 3
                critical_art = True
            else:
                stock = int(best_label)

        bar_roi = self._crop(frame, self._roi["sa_bar"][side])
        progress: float | None = None
        if bar_roi.size > 0:
            hsv = cv2.cvtColor(bar_roi, cv2.COLOR_BGR2HSV)
            filled = (hsv[:, :, 2] > thresholds.sa_bar_filled_v) & (hsv[:, :, 1] > thresholds.sa_bar_filled_s)
            progress = round(float(filled.mean()), 3)

        return stock, best_label, best_score, progress, critical_art

    def _current_health_mask(
        self, hue: np.ndarray, sat: np.ndarray, val: np.ndarray, side: str, include_poison: bool = True
    ) -> np.ndarray:
        """現在体力とみなす画素マスク（プレイヤー色 + 低体力の明るい黄色 + 毒の紫, ADR-061/062）

        - 通常時: 1P マゼンタ〜赤 / 2P 青
        - 低体力時（概ね 25% 以下）: 現在体力バーが明るい黄色に変わるため、
          `health_low_hue_ranges` かつ明度 `health_low_v_min` 以上を現在体力に含める。
          コンボダメージ／回復可能表示の「暗い黄色」は明度が低く、ここでは含めない。
        - A.K.I. の毒状態: 現在体力バーが紫（H≈139）に変わるため、
          `health_poison_hue_ranges` を現在体力に含める（ADR-062）。毒は画面演出の紫とも
          色相が重なるため、採用は A.K.I. を含む試合に限定する（include_poison）。
        """
        thresholds = self.params.thresholds
        mask = (val > thresholds.health_filled_v) & (sat > thresholds.health_filled_s)
        hue_mask = np.zeros(hue.shape, dtype=bool)
        for h_min, h_max in self.params.health_hue_ranges.get(side, []):
            hue_mask |= (hue >= h_min) & (hue <= h_max)
        mask &= hue_mask

        low_mask = np.zeros(hue.shape, dtype=bool)
        for h_min, h_max in self.params.health_low_hue_ranges.get(side, []):
            low_mask |= (hue >= h_min) & (hue <= h_max)
        low = low_mask & (val >= thresholds.health_low_v_min) & (sat > thresholds.health_filled_s)

        if not include_poison:
            return mask | low

        poison_mask = np.zeros(hue.shape, dtype=bool)
        for h_min, h_max in self.params.health_poison_hue_ranges.get(side, []):
            poison_mask |= (hue >= h_min) & (hue <= h_max)
        poison = poison_mask & (val > thresholds.health_filled_v) & (sat > thresholds.health_filled_s)

        return mask | low | poison

    def _measure_health(self, frame: np.ndarray, side: str, include_poison: bool = True) -> float | None:
        """体力ゲージ（現在体力のみ）を％で計測する（ADR-050 / ADR-061 / ADR-062）

        各列を「現在体力の色（1P: マゼンタ〜赤 / 2P: 青 / 低体力時: 明るい黄色 / 毒時: 紫）」で判定し、
        その列数 ÷ バー幅 を体力％とする。暗い黄（コンボダメージ／回復可能）と
        空きトラックは数えない。

        Args:
            include_poison: 毒の紫を現在体力に含めるか（A.K.I. を含む試合でのみ True）

        Returns:
            0〜100（小数1桁）。計測できない場合は None
        """
        thresholds = self.params.thresholds
        roi = self._crop(frame, self._roi["health"][side])
        if roi.size == 0:
            return None

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0].astype(np.int16)
        sat = hsv[:, :, 1].astype(np.int16)
        val = hsv[:, :, 2].astype(np.int16)

        current = self._current_health_mask(hue, sat, val, side, include_poison=include_poison)

        width = float(hsv.shape[1])
        filled_fraction = float((current.mean(axis=0) >= thresholds.health_column_fill_ratio).sum()) / width
        if filled_fraction < thresholds.health_detect_min_fraction:
            return None
        value = filled_fraction * 100.0 * self.params.health_fill_scale.get(side, 1.0)
        return round(min(100.0, value), 1)

    def _measure_health_recoverable(self, frame: np.ndarray, side: str) -> float | None:
        """体力バーの回復可能ダメージ（白／黄ゲージ）を％で計測する（ADR-054）

        SF6 で体力が増えるのは「回復可能ダメージの自然回復」か「エレナの SA2」のみ。
        その回復可能分を別系列として観測し、現在体力の増加が本当に回復可能分の
        減少で説明できるかを検証できるようにする（後段のゲートで使用）。

        バーは画面中央側を基準に減るため、**現在体力に隣接する外側の帯**だけを
        回復可能分として数える。空きトラックは半透明でステージが透けて見えるため、
        ROI 内の回復可能色を単純に数えると背景を誤検出する。

        注: この色域は低体力時に現在体力が変わる明るい黄色も含む（ADR-061 参照）。
        現行の WALK は連続性を前提にしており、明るい黄を除外するとコンボゲージを
        取り落とすため、ADR-061 では本系列の判定は変更しない。

        Returns:
            0〜100（小数1桁）。計測できない場合は None
        """
        ranges = self.params.health_recoverable_hue_ranges.get(side, [])
        if not ranges:
            return None

        thresholds = self.params.thresholds
        roi = self._crop(frame, self._roi["health"][side])
        if roi.size == 0:
            return None

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0].astype(np.int16)
        sat = hsv[:, :, 1].astype(np.int16)
        val = hsv[:, :, 2].astype(np.int16)

        recoverable = val > thresholds.health_recoverable_v_min
        recoverable &= sat > thresholds.health_recoverable_s_min
        hue_mask = np.zeros(hue.shape, dtype=bool)
        for h_min, h_max in ranges:
            hue_mask |= (hue >= h_min) & (hue <= h_max)
        recoverable &= hue_mask

        current = val > thresholds.health_filled_v
        current &= sat > thresholds.health_filled_s
        current_hue = np.zeros(hue.shape, dtype=bool)
        for h_min, h_max in self.params.health_hue_ranges.get(side, []):
            current_hue |= (hue >= h_min) & (hue <= h_max)
        current &= current_hue

        ratio = thresholds.health_column_fill_ratio
        recoverable_col = recoverable.mean(axis=0) >= ratio
        current_col = current.mean(axis=0) >= ratio

        # 画面中央側（アンカー側）から、現在体力 → 回復可能 の順に連続する帯だけを数える
        x1, _, x2, _ = self._roi["health"][side]
        frame_width = frame.shape[1]
        anchor_right = ((x1 + x2) / 2) < (frame_width / 2)
        width = len(recoverable_col)
        order = range(width - 1, -1, -1) if anchor_right else range(width)
        columns = list(order)

        index = 0
        while index < width and current_col[columns[index]]:
            index += 1
        count = 0
        while index < width and recoverable_col[columns[index]]:
            count += 1
            index += 1

        if count == 0:
            return None
        filled_fraction = count / float(width)
        if filled_fraction < thresholds.health_detect_min_fraction:
            return None
        return round(min(100.0, filled_fraction * 100.0), 1)

    # ------------------------------------------------------------------
    # 内部処理: 派生（平滑化・バーンアウト判定）
    # ------------------------------------------------------------------
    def _derive_states(self) -> None:
        """生サンプルから drive / drive_burnout / sa の欠損補完を行う（1回だけ）"""
        if self._derived:
            return
        thresholds = self.params.thresholds
        timestamps = [sample.timestamp for sample in self.samples]

        for side in SIDES:
            states = [sample.states[side] for sample in self.samples]
            # SA 数字のスコアが閾値付近で揺れると HUD 可視判定が 0.1 秒単位で振れるため、
            # 短い非表示区間を表示中に丸める（ラウンド移行の 1.5 秒以上は非表示のまま）
            hud = self._extend_flags(
                [state.hud_visible for state in states], timestamps, thresholds.hud_flicker_tolerance_sec
            )

            # ドライブ: メディアン平滑化 → 短い欠損補完
            raw_values = [states[i].drive_raw if hud[i] else None for i in range(len(states))]
            smoothed = _median_filter(raw_values, thresholds.drive_smoothing_window)
            filled = _fill_short_gaps(smoothed, timestamps, thresholds.drive_max_gap_sec)
            hud_extended = self._extend_flags(hud, timestamps, thresholds.drive_max_gap_sec)

            # バーンアウト（ADR-065）: HUD 表示中にゲージが空（黄緑も低ドライブ警告の金色も無い）区間のうち、
            # 白/銀の回復バーが観測されたものをバーンアウトとする（ADR-056 の「黄緑なし＋低彩度画素」を置換）。
            # 黄緑の有無だけでは、1〜2 本の低ドライブ警告（金色バー）をバーンアウトと誤判定する。
            recover_values = [state.drive_recover_raw for state in states]
            banner_times = self._effective_burnout_banner_times(side)
            banner_tolerance = self.params.burnout_banner.onset_tolerance_sec
            bar_min = thresholds.drive_recover_min_fraction
            round_intro = [
                (
                    banner - thresholds.burnout_round_banner_before_sec,
                    banner + thresholds.burnout_round_banner_after_sec,
                )
                for banner in self.round_banner_times
            ]
            candidates = [
                hud[i]
                and (raw_values[i] is None or raw_values[i] < thresholds.burnout_candidate_max_drive)
                and not any(start <= timestamps[i] <= end for start, end in round_intro)
                for i in range(len(states))
            ]
            candidate_periods = _merge_periods(
                _runs_to_periods(_find_runs(candidates, timestamps), timestamps),
                thresholds.burnout_merge_gap_sec,
            )
            burnout_periods: list[list[float]] = []
            for start, end in candidate_periods:
                if end - start < thresholds.burnout_min_duration_sec:
                    continue
                indices = [i for i in range(len(states)) if start - 1e-6 <= timestamps[i] <= end + 1e-6]
                # 白/銀の証拠を探す: 連続して観測される回復バー（ヒット演出の単発の白は除外される）か、
                # バーンアウト開始時にゲージ全体が白く光るフラッシュ。最初の証拠時刻を開始点にする。
                onset: float | None = None
                streak_start: float | None = None
                longest_bar = 0.0
                for i in indices:
                    value = recover_values[i]
                    if value is None or value < bar_min:
                        streak_start = None
                        continue
                    if onset is None:
                        onset = timestamps[i]
                    if streak_start is None:
                        streak_start = timestamps[i]
                    longest_bar = max(longest_bar, timestamps[i] - streak_start)
                # EMPTY 文字（ADR-066）が出ていれば、回復バーが細くて連続検出できない場合でも確定する。
                # また開始時刻は EMPTY 文字の時刻を採用する（回復バーは細く、数秒遅れて検出されることがある）
                banner_onset = next(
                    (t for t in banner_times if start - banner_tolerance <= t <= end + banner_tolerance), None
                )
                if banner_onset is not None and (onset is None or banner_onset < onset):
                    onset = banner_onset
                if onset is None:
                    continue
                if longest_bar < thresholds.burnout_min_bar_sec and banner_onset is None:
                    continue
                if end - onset < thresholds.burnout_min_duration_sec:
                    continue
                burnout_periods.append([onset, end])
            self.burnout_periods[side] = _merge_periods(burnout_periods, thresholds.burnout_merge_gap_sec)
            for start, end in self.burnout_periods[side]:
                for state, timestamp in zip(states, timestamps, strict=True):
                    # round() 済みの境界値と浮動小数を比較するため微小な許容幅を持たせる
                    if start - 1e-6 <= timestamp <= end + 1e-6:
                        state.drive_burnout = True

            # SA: 短い欠損補完 → 単発スパイク除去（3点メディアン）
            sa_values: list[float | None] = [
                float(state.sa_stock) if state.sa_stock is not None else None for state in states
            ]
            sa_filled = _median_filter(_fill_short_gaps(sa_values, timestamps, thresholds.sa_max_gap_sec), 3)
            # 数字グリフの瞬間的な読み違えによる「下振れ→即復帰」を除去する（SA 使用回数の過大カウント防止）
            sa_filled = _suppress_transient_reverts(sa_filled, timestamps, thresholds.sa_revert_window_sec)
            progress_values = [state.sa_progress for state in states]
            progress_filled = _fill_short_gaps(progress_values, timestamps, thresholds.sa_max_gap_sec)

            # 体力（ADR-050）: メディアン平滑化 → 短い欠損補完 → 一時的な低値（遮蔽・演出）の除去
            health_values = [states[i].health_raw if hud[i] else None for i in range(len(states))]
            health_smoothed = _median_filter(health_values, thresholds.health_smoothing_window)
            health_filled = _fill_short_gaps(health_smoothed, timestamps, thresholds.health_max_gap_sec)
            # ヒット演出・遮蔽で数サンプルだけ低く出て即復帰する下振れは、後段で
            # 「回復可能分では説明できない増加」に化けるため、ここで除去する（ADR-054）
            health_filled = _suppress_transient_reverts(health_filled, timestamps, thresholds.health_despike_revert_sec)

            # 毒込みの体力（ADR-062）: A.K.I. を含む試合でのみ採用する。同じ平滑化をかける
            health_poison_values = [states[i].health_poison_raw if hud[i] else None for i in range(len(states))]
            health_poison_smoothed = _median_filter(health_poison_values, thresholds.health_smoothing_window)
            health_poison_filled = _fill_short_gaps(health_poison_smoothed, timestamps, thresholds.health_max_gap_sec)
            health_poison_filled = _suppress_transient_reverts(
                health_poison_filled, timestamps, thresholds.health_despike_revert_sec
            )

            # 回復可能ダメージ（ADR-054）: メディアン平滑化 → 短い欠損補完
            recoverable_values = [states[i].health_recoverable_raw if hud[i] else None for i in range(len(states))]
            recoverable_smoothed = _median_filter(recoverable_values, thresholds.health_smoothing_window)
            recoverable_filled = _fill_short_gaps(recoverable_smoothed, timestamps, thresholds.health_max_gap_sec)

            for index, state in enumerate(states):
                state.hud_visible = hud[index]
                if state.drive_burnout:
                    state.drive = 0.0
                elif hud_extended[index]:
                    state.drive = filled[index]
                else:
                    state.drive = None
                if sa_filled[index] is not None:
                    state.sa_stock = int(round(sa_filled[index]))
                state.sa_progress = progress_filled[index]
                state.health = health_filled[index] if hud_extended[index] else None
                state.health_poison = health_poison_filled[index] if hud_extended[index] else None
                state.health_recoverable = recoverable_filled[index] if hud_extended[index] else None

        self._derived = True
        logger.info(
            "[Gauge] Derived states for %d samples (burnout periods: p1=%d, p2=%d)",
            len(self.samples),
            len(self.burnout_periods[SIDES[0]]),
            len(self.burnout_periods[SIDES[1]]),
        )

    # ------------------------------------------------------------------
    # 内部処理: ラウンド構築
    # ------------------------------------------------------------------
    def _build_match_rounds(
        self,
        match_id: str,
        start_time: float,
        end_time: float,
        characters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """1試合ぶんのラウンド構造を構築する"""
        windows: list[RoundWindow] = split_rounds(
            match_start=start_time,
            match_end=end_time,
            round_banner_times=self.round_banner_times,
        )

        characters = characters or {}
        # ADR-062: A.K.I. を含む試合でのみ毒の紫を現在体力として採用する
        poison = any(_is_poison_character(name) for name in characters.values())
        rounds: list[dict[str, Any]] = []
        for window in windows:
            player1 = self._side_round_payload(window, "player1", characters.get("player1"), poison)
            player2 = self._side_round_payload(window, "player2", characters.get("player2"), poison)
            # ADR-063: ラウンドの実効終了は HUD が見えている最後の時刻（K.O. で打ち切り）とする。
            # 従来は次ラウンド開始バナーまでを roundEndTime としていたため、勝利演出・待ち受けが
            # ゲージ詳細の表示区間に含まれていた。境界そのものは boundaryEndTime に残す
            visible_ends = [
                float(payload["visibleTo"]) for payload in (player1, player2) if payload.get("visibleTo") is not None
            ]
            if visible_ends:
                effective_end = min(window.end_time, window.start_time + max(visible_ends))
            else:
                effective_end = window.end_time
            rounds.append(
                {
                    "round": window.index,
                    "roundStartTime": round(window.start_time, 2),
                    "roundEndTime": round(effective_end, 2),
                    "boundaryEndTime": round(window.end_time, 2),
                    "endReason": window.end_reason,
                    "bannerDetected": window.banner_detected,
                    "player1": player1,
                    "player2": player2,
                }
            )

        logger.info(
            "[Gauge] matchId=%s start=%.2f end=%.2f rounds=%d",
            match_id,
            start_time,
            end_time,
            len(rounds),
        )
        return rounds

    @staticmethod
    def _extend_flags(flags: list[bool], timestamps: list[float], max_gap_sec: float) -> list[bool]:
        """True の前後 max_gap_sec 以内を True に広げる（短い HUD 検出失敗を吸収）

        timestamps は昇順である前提で、前方向・後方向の 1 パスずつで処理する。
        """
        count = len(flags)
        result = list(flags)

        previous_true = -1
        for index in range(count):
            if flags[index]:
                previous_true = index
            if previous_true >= 0 and timestamps[index] - timestamps[previous_true] <= max_gap_sec:
                result[index] = True

        next_true = -1
        for index in range(count - 1, -1, -1):
            if flags[index]:
                next_true = index
            if next_true >= 0 and timestamps[next_true] - timestamps[index] <= max_gap_sec:
                result[index] = True

        return result

    def _round_samples(self, window: RoundWindow) -> list[GaugeSample]:
        """ラウンド境界内のサンプルを返す"""
        result = []
        for sample in self.samples:
            if sample.timestamp < window.start_time - 0.5:
                continue
            if window.boundary_time is not None and sample.timestamp > window.boundary_time:
                continue
            result.append(sample)
        return result

    def _round_ko_time(self, window: RoundWindow) -> float | None:
        """ラウンド内の K.O. バナー検出時刻（絶対秒）を返す（ADR-059 / ADR-067）

        K.O. バナーは勝利演出の開始を示し、それ以降は HUD が消える。

        ラウンド開始直後は ROUND バナーや FIGHT 演出の白文字を K.O. と誤検出しやすく、
        その場合は実効終了が開始直後に切り詰められて durationSec が数秒になる。
        開始から ko_start_guard_sec 未満の検出は誤検出として無視する（ADR-067）。
        真に HUD が消えた場合は _visible_range の途切れ判定が終端を決める。
        """
        upper = window.boundary_time
        guard = window.start_time + self.params.thresholds.ko_start_guard_sec
        for ko in self.ko_times:
            if ko < guard:
                continue
            if window.start_time - 1.0 <= ko and (upper is None or ko <= upper):
                return ko
        return None

    @staticmethod
    def _visible_range(
        samples: list[GaugeSample],
        side: str,
        base: float,
        max_gap_sec: float,
        ko_time: float | None = None,
    ) -> tuple[float | None, float | None]:
        """ラウンド内の HUD 可視範囲（相対秒）を、長い途切れを考慮して求める（ADR-057）

        HUD はラウンド終了（K.O.）後に消えるが、試合間画面（勝利ポーズ・次試合待ち）で
        誤検出されることがある。HUD が max_gap_sec を超えて途切れた後の可視は
        visible_to に含めない。また、K.O. バナー検出時刻（ko_time）以降の可視も
        無視する（ADR-059）。
        """
        visible_from: float | None = None
        last_visible_abs: float | None = None
        gap_start_abs: float | None = None
        for sample in samples:
            if ko_time is not None and sample.timestamp > ko_time:
                break
            state = sample.states[side]
            visible = state.drive is not None or state.sa_stock is not None
            if visible:
                if visible_from is None:
                    visible_from = round(sample.timestamp - base, 2)
                last_visible_abs = sample.timestamp
                gap_start_abs = None
            elif last_visible_abs is not None:
                if gap_start_abs is None:
                    gap_start_abs = sample.timestamp
                elif sample.timestamp - gap_start_abs > max_gap_sec:
                    break
        visible_to = round(last_visible_abs - base, 2) if last_visible_abs is not None else None
        return visible_from, visible_to

    @staticmethod
    def _elena_heal_allowed(samples: list[GaugeSample], side: str, character: str | None) -> bool:
        """エレナの SA2 による直接回復を許可するか（ADR-054）

        エレナの SA2 だけは回復可能ダメージに依存せず体力を直接回復する。
        ラウンド中に SA ストックを消費（＝スーパーアーツ発動）していれば、
        その回復を計測ノイズとして消さないようゲートを無効化する。
        """
        if (character or "").strip().upper() != "ELENA":
            return False
        stock = [sample.states[side].sa_stock for sample in samples if sample.states[side].sa_stock is not None]
        return any(current < previous for previous, current in zip(stock, stock[1:], strict=False))

    def _side_round_payload(
        self, window: RoundWindow, side: str, character: str | None = None, poison: bool = False
    ) -> dict[str, Any]:
        """ラウンド内の片側の変化点列を作る（時刻はラウンド開始からの相対秒）

        Args:
            poison: A.K.I. を含む試合なら True。毒の紫を含めた体力系列（ADR-062）を使う
        """
        base = window.start_time
        samples = self._round_samples(window)
        valid_samples = sum(1 for sample in samples if sample.states[side].drive is not None)
        coverage = round(valid_samples / len(samples), 3) if samples else 0.0
        health_attr = "health_poison" if poison else "health"

        drive_events: list[list[float]] = []
        sa_events: list[list[float]] = []
        progress_events: list[list[float]] = []
        health_events: list[list[float]] = []
        recoverable_events: list[list[float]] = []
        previous_drive: float | None = None
        previous_stock: int | None = None
        previous_progress: float | None = None
        previous_health: float | None = None
        previous_health_rel = 0.0
        previous_recoverable: float | None = None
        health_started = False
        health_valid_samples = 0

        thresholds = self.params.thresholds
        # エレナの SA2 は回復可能ゲートの例外（ADR-054）
        heal_allowed = self._elena_heal_allowed(samples, side, character)

        # ラウンド内の K.O. 時刻（勝利演出の開始、ADR-059）
        ko_time = self._round_ko_time(window)

        # visible_from / visible_to は「HUD が長く途切れる前の最後の可視時刻」とする（ADR-057）。
        # ラウンド終了（K.O.）後の試合間画面での HUD 誤検出が visible_to を伸ばすのを防ぐ。
        visible_from, visible_to = self._visible_range(
            samples, side, base, thresholds.round_end_gap_sec, ko_time=ko_time
        )

        for sample in samples:
            state = sample.states[side]
            rel = round(sample.timestamp - base, 2)

            # visibleTo を超えるサンプルは HUD 途切れ後の誤検出として除外する（ADR-057）
            if visible_to is not None and rel > visible_to:
                break

            # 変化点はチャンネルごとに独立して記録する
            if state.drive is not None and (
                previous_drive is None or abs(state.drive - previous_drive) > thresholds.drive_event_epsilon
            ):
                drive_events.append([rel, state.drive])
                previous_drive = state.drive
            if state.sa_stock is not None and state.sa_stock != previous_stock:
                sa_events.append([rel, state.sa_stock])
                previous_stock = state.sa_stock
            if state.sa_progress is not None and (
                previous_progress is None
                or abs(state.sa_progress - previous_progress) > thresholds.sa_progress_event_epsilon
            ):
                progress_events.append([rel, state.sa_progress])
                previous_progress = state.sa_progress
            # 体力（ADR-050）は変化点の閾値を 1.0% とする。
            # ラウンド開始直後のバー伸長演出を除外し、増加は「回復可能分の減少」で
            # 説明できる分だけ許可する（ADR-054）。説明できない増加は計測ノイズとして前値を保持する
            recoverable = state.health_recoverable
            health_value = getattr(state, health_attr)
            if health_value is not None:
                health_valid_samples += 1
                if not health_started:
                    if rel >= thresholds.health_warmup_sec or health_value >= thresholds.health_start_min_percent:
                        health_started = True
                    else:
                        previous_recoverable = recoverable
                        continue
                value = health_value
                if previous_health is not None and not heal_allowed:
                    elapsed = max(1e-6, rel - previous_health_rel)
                    # 上限1: 現行のレート上限（5%/s）
                    rate_delta = thresholds.health_max_increase_per_sec * elapsed
                    # 上限2: 直前サンプルから減った回復可能分（白ゲージ）の範囲だけ回復できる
                    available_delta = max(0.0, (previous_recoverable or 0.0) - (recoverable or 0.0))
                    max_allowed = previous_health + min(rate_delta, available_delta)
                    if value > max_allowed:
                        value = max(previous_health, max_allowed)
                if previous_health is None or abs(value - previous_health) > thresholds.health_event_epsilon:
                    health_events.append([rel, value])
                    previous_health = value
                    previous_health_rel = rel
                if recoverable is not None and (
                    previous_recoverable is None
                    or abs(recoverable - previous_recoverable) > thresholds.health_event_epsilon
                ):
                    recoverable_events.append([rel, recoverable])
                previous_recoverable = recoverable
            elif recoverable is not None and health_started:
                if (
                    previous_recoverable is None
                    or abs(recoverable - previous_recoverable) > thresholds.health_event_epsilon
                ):
                    recoverable_events.append([rel, recoverable])
                previous_recoverable = recoverable

        # ラウンド内のバーンアウト期間・CA期間を相対時刻で切り出す
        burnout_periods = self._clip_periods(self.burnout_periods[side], window, base)
        ca_periods = self._collect_ca_periods(samples, side, base, thresholds.ca_merge_gap_sec)
        health_coverage = round(health_valid_samples / len(samples), 3) if samples else 0.0

        return {
            "visibleFrom": visible_from,
            "visibleTo": visible_to,
            "coverage": coverage,
            "healthCoverage": health_coverage,
            "health": health_events,
            "healthRecoverable": recoverable_events,
            "drive": drive_events,
            "driveBurnout": burnout_periods,
            "sa": sa_events,
            "saProgress": progress_events,
            "saCriticalArt": ca_periods,
        }

    @staticmethod
    def _clip_periods(periods: list[list[float]], window: RoundWindow, base: float) -> list[list[float]]:
        """絶対時刻の期間リストをラウンド内の相対時刻に切り出す"""
        clipped: list[list[float]] = []
        upper = window.boundary_time
        for start, end in periods:
            if end < window.start_time or (upper is not None and start > upper):
                continue
            clipped_start = max(start, window.start_time)
            clipped_end = min(end, upper) if upper is not None else end
            if clipped_end <= clipped_start:
                continue
            clipped.append([round(clipped_start - base, 2), round(clipped_end - base, 2)])
        return clipped

    @staticmethod
    def _collect_ca_periods(
        samples: list[GaugeSample], side: str, base: float, merge_gap_sec: float = 1.0
    ) -> list[list[float]]:
        """CA 表示期間をラウンド内の相対時刻で集める"""
        raw_periods: list[list[float]] = []
        start: float | None = None
        last: float | None = None
        for sample in samples:
            state = sample.states[side]
            rel = round(sample.timestamp - base, 2)
            if state.sa_critical_art:
                if start is None:
                    start = rel
                last = rel
            elif start is not None and last is not None:
                raw_periods.append([start, last])
                start = None
                last = None
        if start is not None and last is not None:
            raw_periods.append([start, last])
        return _merge_periods(raw_periods, merge_gap_sec)

    # ------------------------------------------------------------------
    # 検証用の中間ファイル出力（ADR-048 決定7）
    # ------------------------------------------------------------------
    def write_samples_csv(self, path: Path) -> None:
        """全サンプルの時系列を CSV 出力する（目視検証用）"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp",
                    "side",
                    "hud_visible",
                    "drive",
                    "drive_raw",
                    "drive_recover_raw",
                    "drive_burnout",
                    "burnout_candidate",
                    "sa_stock",
                    "sa_label",
                    "sa_score",
                    "sa_critical_art",
                    "sa_progress",
                    "health",
                    "health_raw",
                    "health_recoverable",
                    "health_recoverable_raw",
                ]
            )
            for sample in self.samples:
                for side in SIDES:
                    state = sample.states[side]
                    writer.writerow(
                        [
                            f"{sample.timestamp:.2f}",
                            side,
                            int(state.hud_visible),
                            "" if state.drive is None else f"{state.drive:.2f}",
                            "" if state.drive_raw is None else f"{state.drive_raw:.2f}",
                            ("" if state.drive_recover_raw is None else f"{state.drive_recover_raw:.3f}"),
                            int(state.drive_burnout),
                            int(state.burnout_candidate),
                            "" if state.sa_stock is None else state.sa_stock,
                            state.sa_label or "",
                            f"{state.sa_score:.3f}",
                            int(state.sa_critical_art),
                            "" if state.sa_progress is None else f"{state.sa_progress:.3f}",
                            "" if state.health is None else f"{state.health:.1f}",
                            "" if state.health_raw is None else f"{state.health_raw:.1f}",
                            "" if state.health_recoverable is None else f"{state.health_recoverable:.1f}",
                            ("" if state.health_recoverable_raw is None else f"{state.health_recoverable_raw:.1f}"),
                        ]
                    )
        logger.info("✅ Saved gauge samples CSV: %s", path)

    def save_snapshots(self, directory: Path) -> list[Path]:
        """要所の ROI クロップ画像を保存する（目視検証用）"""
        directory.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for index, snapshot in enumerate(self.snapshots[: self.MAX_SNAPSHOTS], 1):
            for side in SIDES:
                for kind, image in snapshot.get(side, {}).items():
                    path = directory / f"{index:03d}_{snapshot['timestamp']:.1f}s_{kind}_{side}.png"
                    cv2.imwrite(str(path), image)
                    saved.append(path)
        if saved:
            logger.info("✅ Saved %d gauge ROI snapshots: %s", len(saved), directory)
        return saved

    def _add_snapshot(self, frame: np.ndarray, timestamp: float, reason: str) -> None:
        if len(self.snapshots) >= self.MAX_SNAPSHOTS:
            return
        if self._frame_size is None:
            return
        entry: dict[str, Any] = {"timestamp": timestamp, "reason": reason}
        for side in SIDES:
            entry[side] = {
                "drive": self._crop(frame, self._roi["drive"][side]).copy(),
                "sa": self._crop(frame, self._roi["sa_digit"][side]).copy(),
                "health": self._crop(frame, self._roi["health"][side]).copy(),
            }
        self.snapshots.append(entry)


# ----------------------------------------------------------------------
# ラウンド統計（round_stats.parquet の行）生成
# ----------------------------------------------------------------------
def _series_stats(events: list[list[float]], end_time: float) -> tuple[float | None, float | None, float | None]:
    """変化点列（[相対秒, 値]）から時間重み付きの min / avg / 最終値 を求める"""
    if not events:
        return None, None, None

    total_weight = 0.0
    weighted_sum = 0.0
    minimum = float(events[0][1])
    for index, (time, value) in enumerate(events):
        next_time = events[index + 1][0] if index + 1 < len(events) else end_time
        weight = max(0.0, float(next_time) - float(time))
        weighted_sum += float(value) * weight
        total_weight += weight
        minimum = min(minimum, float(value))

    average = weighted_sum / total_weight if total_weight > 0 else float(events[-1][1])
    return round(minimum, 2), round(average, 2), round(float(events[-1][1]), 2)


def _counter_count_lookup(
    counter_result: dict[str, Any] | None,
) -> dict[tuple[str, int, str], tuple[int | None, int | None]]:
    """カウンター計測結果を (matchId, round, side) の索引に直す（ADR-049）"""
    lookup: dict[tuple[str, int, str], tuple[int | None, int | None]] = {}
    for match_id, match_data in ((counter_result or {}).get("matches") or {}).items():
        for round_data in match_data.get("rounds", []):
            round_index = int(round_data.get("round", 0))
            for side in SIDES:
                payload = round_data.get(side) or {}
                lookup[(match_id, round_index, side)] = (
                    payload.get("counterCount"),
                    payload.get("punishCounterCount"),
                )
    return lookup


# Battlelog round_results の勝利方法コード（ADR-037）。0=LOSS / 4=DRAW は勝ちではないので含めない
_ROUND_METHOD_CODES: dict[int, str] = {1: "V", 2: "C", 3: "T", 5: "OD", 6: "SA", 7: "CA", 8: "P"}


def _round_value_lookup(
    round_results_by_match: dict[str, dict[str, list[int]]] | None,
) -> dict[tuple[str, int, str], int]:
    """Battlelog のラウンド結果配列を (matchId, round, side) の索引に直す（ADR-051）"""
    lookup: dict[tuple[str, int, str], int] = {}
    for match_id, sides in (round_results_by_match or {}).items():
        for side in SIDES:
            for index, value in enumerate(sides.get(side) or [], start=1):
                lookup[(match_id, index, side)] = int(value)
    return lookup


def _round_result(value: int | None) -> str | None:
    """round_results の値からそのサイドの勝敗を返す（4=DRAW、0=LOSS、他=WIN）"""
    if value is None:
        return None
    if value == 4:
        return "draw"
    return "win" if value > 0 else "loss"


def _round_method(value1: int | None, value2: int | None) -> str | None:
    """そのラウンドの勝利方法コードを返す（勝者の値から取る。引き分け・未計測は None）"""
    for value in (value1, value2):
        if value is not None and value in _ROUND_METHOD_CODES:
            return _ROUND_METHOD_CODES[value]
    return None


# ADR-068: パーフェクト勝利の K.O. は K.O. バナーが照合できない（PERFECT 文字と重なる）。
# 敗者の体力がこの％以下になった最初の変化点を K.O. とみなす
PERFECT_KO_HEALTH_PERCENT = 5.0


def _perfect_ko_time(round_data: dict[str, Any]) -> float | None:
    """パーフェクト勝利ラウンドの K.O. 時刻（ラウンド開始からの相対秒）を体力から推定する（ADR-068）

    パーフェクトの敗者はラウンド中に一度もダメージを受けないため、体力が 5% 以下になるのは
    K.O. の瞬間だけである。パーフェクトでないラウンドには適用しない（削り合いを K.O. と
    誤認しないため）。
    """
    earliest: float | None = None
    for side in SIDES:
        for event in (round_data.get(side) or {}).get("health") or []:
            if float(event[1]) <= PERFECT_KO_HEALTH_PERCENT:
                rel = float(event[0])
                if earliest is None or rel < earliest:
                    earliest = rel
                break
    return earliest


def _max_drop(events: list[list[float]]) -> float | None:
    """体力の変化点列から最大の変化点間減少（％）を求める（ADR-051）

    変化点間には複数ヒット（コンボ）がまとまるため、この値は「1コンボあたりの
    被ダメージ合計（近似）」を表す。厳密なコンボ被ダメージは maxComboDamage
    （薄い黄色ゲージのピーク、ADR-058）を参照する。
    """
    if not events:
        return None
    biggest = 0.0
    for (_, previous), (_, current) in zip(events, events[1:], strict=False):
        drop = float(previous) - float(current)
        if drop > biggest:
            biggest = drop
    return round(biggest, 1)


def _max_value(events: list[list[float]]) -> tuple[float | None, float | None]:
    """変化点列の最大値とその相対時刻を返す（ADR-058 の薄い黄色ゲージのピーク＝コンボ被ダメージ）"""
    if not events:
        return None, None
    peak_time, peak_value = max(events, key=lambda event: float(event[1]))
    return round(float(peak_value), 1), round(float(peak_time), 2)


def _burnout_stats(periods: list[list[float]]) -> tuple[int, float]:
    """バーンアウト期間の回数と累計秒を求める（ADR-051）"""
    total = sum(max(0.0, float(end) - float(start)) for start, end in periods)
    return len(periods), round(total, 1)


def _last_value(events: list[list[float]]) -> float | None:
    """変化点列の最終値を返す（ADR-051 のラウンド終了時ストックなど）"""
    if not events:
        return None
    return float(events[-1][1])


def build_round_stats_rows(
    gauge_result: dict[str, Any],
    matches: list[dict[str, Any]],
    counter_result: dict[str, Any] | None = None,
    round_results_by_match: dict[str, dict[str, list[int]]] | None = None,
) -> list[dict[str, Any]]:
    """ゲージ計測結果（とカウンター・ラウンド勝敗）から round_stats.parquet の行を組み立てる

    Args:
        gauge_result: GaugeAnalyzer.build() の戻り値
        matches: main.py の match 辞書リスト（id / videoId / player1 / player2 を含む）
        counter_result: CounterAnalyzer.build() の戻り値（ADR-049）。None の場合は未計測として None を入れる
        round_results_by_match: matchId -> {"player1": [round_results], "player2": [...]} の辞書（ADR-051）。
            Battlelog 未マッチ・未計測の場合は None（roundResult / roundMethod が null になる）

    Returns:
        1行 = 1ラウンド x 1サイド の辞書リスト
    """
    match_map = {match.get("id"): match for match in matches}
    counter_lookup = _counter_count_lookup(counter_result)
    value_lookup = _round_value_lookup(round_results_by_match)
    rows: list[dict[str, Any]] = []

    for match_id, match_gauges in (gauge_result.get("matches") or {}).items():
        match = match_map.get(match_id, {})
        for round_data in match_gauges.get("rounds", []):
            round_index = int(round_data.get("round", 0))
            round_method = _round_method(
                value_lookup.get((match_id, round_index, "player1")),
                value_lookup.get((match_id, round_index, "player2")),
            )
            # ADR-068: パーフェクト勝利では PERFECT 文字が K.O. と重なりバナーが照合できない。
            # 勝利演出（4〜5秒）が durationSec に含まれるため、敗者の体力が 0% 付近に
            # 落ちた時刻を K.O. とみなしてラウンド終端を切り詰める
            perfect_ko_rel = _perfect_ko_time(round_data) if round_method == "P" else None
            for side in SIDES:
                payload = round_data.get(side) or {}
                drive_events = payload.get("drive") or []
                sa_events = payload.get("sa") or []
                health_events = payload.get("health") or []
                recoverable_events = payload.get("healthRecoverable") or []
                visible_from = float(payload.get("visibleFrom") or 0.0)
                visible_to = float(payload.get("visibleTo") or 0.0)
                round_start = float(round_data.get("roundStartTime", 0.0))

                drive_min, _, drive_end = _series_stats(drive_events, visible_to)
                _, _, health_end = _series_stats(health_events, visible_to)
                sa_values = [int(event[1]) for event in sa_events]
                sa_used = sum(
                    1 for previous, current in zip(sa_values, sa_values[1:], strict=False) if current < previous
                )
                # 未計測（HUD 非表示などで時系列が空）は null、計測済み 0 件は 0 と区別する
                if drive_events:
                    burnout_count, burnout_sec = _burnout_stats(payload.get("driveBurnout") or [])
                else:
                    burnout_count, burnout_sec = None, None
                sa_left = _last_value(sa_events)
                max_hit = _max_drop(health_events)
                max_combo_damage, max_combo_damage_at = _max_value(recoverable_events)

                player = match.get(side) or {}
                counter_counts = counter_lookup.get((match_id, round_index, side))
                round_result = _round_result(value_lookup.get((match_id, round_index, side)))
                round_end_time = int(round(round_start + visible_to))
                duration = round(max(0.0, visible_to - visible_from), 2)
                if perfect_ko_rel is not None and perfect_ko_rel < visible_to:
                    round_end_time = int(round(round_start + perfect_ko_rel))
                    duration = round(max(0.0, perfect_ko_rel - visible_from), 2)
                # K.O. 札着の敗者はゲーム上 0%。K.O. 演出中は HUD が消えて体力バーが 0 へ
                # 吸い込まれる演出を計測できないため、Battlelog の勝利方法から補正する（ADR-051）
                # （Time Up（T）の敗者は 0 にならないので補正しない。未マッチ時は計測値のまま）
                if round_result == "loss" and round_method not in (None, "T"):
                    health_end = 0.0
                # パーフェクト勝利（P）の勝者は無傷なので残体力は 100%。
                # K.O. 後の勝利演出（PERFECT / CAMMY WIN / RESULT 画面）では HUD が消えており、
                # 背景（桜の花びら等）を現在体力色として誤読した値が最終値になることがある（ADR-068）
                elif round_result == "win" and round_method == "P":
                    health_end = 100.0
                rows.append(
                    {
                        "videoId": match.get("videoId"),
                        "matchId": match_id,
                        "round": round_index,
                        "side": side,
                        "character": player.get("character"),
                        "roundStartTime": int(round(round_start + visible_from)),
                        "roundEndTime": round_end_time,
                        "durationSec": duration,
                        "roundResult": round_result,
                        "roundMethod": round_method,
                        "driveMin": drive_min,
                        "driveEnd": drive_end,
                        "saMax": max(sa_values) if sa_values else None,
                        "saUsedCount": sa_used,
                        "saLeftAtEnd": None if sa_left is None else int(sa_left),
                        "detectionCoverage": payload.get("coverage"),
                        "healthEnd": health_end,
                        "maxHitTaken": max_hit,
                        "maxComboDamage": max_combo_damage,
                        "maxComboDamageAt": max_combo_damage_at,
                        "burnoutCount": burnout_count,
                        "burnoutSec": burnout_sec,
                        "counterCount": None if counter_counts is None else counter_counts[0],
                        "punishCounterCount": None if counter_counts is None else counter_counts[1],
                    }
                )

    return rows
