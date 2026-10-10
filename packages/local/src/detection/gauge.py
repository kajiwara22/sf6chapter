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
- HUD 表示中にドライブゲージの黄緑（通常ゲージ）が検出できない状態は
  バーンアウト（銀＝回復済み／赤＝未回復の回復バー）とみなす
- 単発の誤検出を抑えるため、メディアンによる平滑化と最小継続時間フィルタをかける
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


@dataclass
class GaugeThresholds:
    """ゲージ計測の閾値"""

    drive_filled_v: int = 150
    drive_filled_s: int = 100
    drive_filled_h_min: int = 25
    drive_filled_h_max: int = 60
    drive_burnout_silver_v: int = 150
    drive_burnout_silver_s_max: int = 60
    drive_burnout_red_h_max: int = 18
    drive_column_fill_ratio: float = 0.5
    drive_detect_min_fraction: float = 0.03
    drive_smoothing_window: int = 7
    drive_max_gap_sec: float = 1.0
    drive_event_epsilon: float = 0.25
    hud_flicker_tolerance_sec: float = 0.5
    burnout_min_duration_sec: float = 1.0
    burnout_merge_gap_sec: float = 1.0
    sa_digit_min_score: float = 0.45
    sa_bar_filled_v: int = 140
    sa_bar_filled_s: int = 100
    sa_max_gap_sec: float = 1.0
    sa_progress_event_epsilon: float = 0.15
    ca_merge_gap_sec: float = 1.0
    round_banner_threshold: float = 0.4

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    def log(self) -> None:
        logger.info("  [Gauge Thresholds]")
        for key, value in self.__dict__.items():
            logger.info("    %-32s %s", f"{key}:", value)


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
    round_banner_search_region: tuple[int, int, int, int]
    thresholds: GaugeThresholds
    sa_digit_templates: dict[str, str]
    round_banner_template: str
    drive_fill_scale: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GaugeAnalysisParams:
        """設定ファイルの gauge_analysis セクションから生成"""
        thresholds = GaugeThresholds(**data.get("thresholds", {}))
        calibration = data.get("calibration", {}) or {}
        drive_fill_scale = {side: float(calibration.get("drive_fill_scale", {}).get(side, 1.0)) for side in SIDES}
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
            round_banner_search_region=tuple(data["round_banner_search_region"]),
            thresholds=thresholds,
            sa_digit_templates=dict(templates.get("sa_digits") or {}),
            round_banner_template=str(templates.get("round_banner", "")),
            drive_fill_scale=drive_fill_scale,
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
            "round_banner_search_region": list(self.round_banner_search_region),
            "thresholds": self.thresholds.to_dict(),
            "templates": {
                "sa_digits": dict(self.sa_digit_templates),
                "round_banner": self.round_banner_template,
            },
            "calibration": {"drive_fill_scale": dict(self.drive_fill_scale)},
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
        }.items():
            for side, values in roi.items():
                if len(values) != 4:
                    raise ValueError(f"{name}[{side}] must have 4 elements, got {values}")
                if values[2] <= values[0] or values[3] <= values[1]:
                    raise ValueError(f"{name}[{side}] must be (x1, y1, x2, y2) with x2>x1, y2>y1, got {values}")
        if len(self.round_banner_search_region) != 4:
            raise ValueError(f"round_banner_search_region must have 4 elements, got {self.round_banner_search_region}")

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
        logger.info("    round_banner_region:      %s", self.round_banner_search_region)
        self.thresholds.log()


@dataclass
class SideGaugeState:
    """1サンプル時点の片側のゲージ状態

    feed() 直後は raw 値のみが入っており、build() 内の派生処理で
    drive / drive_burnout（平滑化・バーンアウト判定後）が埋まる。
    """

    hud_visible: bool = False
    drive_raw: float | None = None  # 黄緑の充填率から換算した本数（0〜6）。None=黄緑なし
    burnout_candidate: bool = False  # HUD表示中に黄緑が検出できない状態
    drive: float | None = None  # 平滑化・バーンアウト判定後の本数
    drive_burnout: bool = False
    sa_stock: int | None = None
    sa_label: str | None = None
    sa_score: float = 0.0
    sa_critical_art: bool = False
    sa_progress: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hudVisible": self.hud_visible,
            "drive": self.drive,
            "driveRaw": self.drive_raw,
            "driveBurnout": self.drive_burnout,
            "saStock": self.sa_stock,
            "saLabel": self.sa_label,
            "saScore": round(self.sa_score, 3),
            "saCriticalArt": self.sa_critical_art,
            "saProgress": self.sa_progress,
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

        self._round_banner_full: np.ndarray | None = None
        round_template = cv2.imread(str(self._resolve(params.round_banner_template)), cv2.IMREAD_COLOR)
        if round_template is not None:
            self._round_banner_full = round_template
        else:
            logger.warning("⚠️ Round banner template not found: %s", params.round_banner_template)

        # 実フレームサイズに応じたスケール済み ROI（最初の feed で確定）
        self._frame_size: tuple[int, int] | None = None
        self._roi: dict[str, dict[str, tuple[int, int, int, int]]] = {}
        self._round_banner_search: tuple[int, int, int, int] | None = None
        self._round_banner_scaled: np.ndarray | None = None

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

        interval = self.params.sample_interval_sec
        if self._last_sample_time is not None and timestamp - self._last_sample_time < interval:
            return
        self._last_sample_time = timestamp

        states: dict[str, SideGaugeState] = {}
        for side in SIDES:
            raw_drive = self._measure_drive(frame, side)
            sa_stock, sa_label, sa_score, sa_progress, sa_ca = self._measure_sa(frame, side)
            hud_visible = sa_score >= self.params.thresholds.sa_digit_min_score
            states[side] = SideGaugeState(
                hud_visible=hud_visible,
                drive_raw=raw_drive,
                burnout_candidate=hud_visible and raw_drive is None,
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

    def build(self, matches: list[tuple[str, float]], video_end: float | None = None) -> dict[str, Any]:
        """検出済みマッチ情報からラウンド単位のゲージデータを構築する

        Args:
            matches: (match_id, 開始時刻[秒]) のリスト（時系列順）
            video_end: 動画長（秒）。最後の試合の終端に使う

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
            rounds = self._build_match_rounds(match_id, start_time, end_time)
            out_matches[match_id] = {"matchId": match_id, "rounds": rounds}

        return {
            "matches": out_matches,
            "roundBannerTimes": list(self.round_banner_times),
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
        }
        self._round_banner_search = scale_roi(self.params.round_banner_search_region)
        self._frame_size = (width, height)

        if self._round_banner_full is not None:
            banner_scale = self.params.banner_scale
            resized = cv2.resize(
                self._round_banner_full, None, fx=banner_scale, fy=banner_scale, interpolation=cv2.INTER_AREA
            )
            self._round_banner_scaled = preprocess_for_matching(resized)
        else:
            self._round_banner_scaled = None

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
        """ROUND バナー（ラウンド開始）を検出する"""
        if self._round_banner_scaled is None or self._round_banner_search is None:
            return False

        region = self._crop(frame, self._round_banner_search)
        scale = self.params.banner_scale
        scaled = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        edges = preprocess_for_matching(scaled)

        template = self._round_banner_scaled
        if template.shape[0] > edges.shape[0] or template.shape[1] > edges.shape[1]:
            return False

        score = float(cv2.matchTemplate(edges, template, cv2.TM_CCOEFF_NORMED).max())
        if score < self.params.thresholds.round_banner_threshold:
            return False

        # 近接フレームの多重検出を抑制（バナーは約1.5秒表示される）
        return not (self.round_banner_times and timestamp - self.round_banner_times[-1] < 3.0)

    def _measure_drive(self, frame: np.ndarray, side: str) -> float | None:
        """ドライブゲージの黄緑（通常ゲージ）の充填量を本数で返す

        Returns:
            0〜6（小数あり）。黄緑が検出できない場合は None
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

        width = float(hsv.shape[1])
        filled_fraction = float((normal.mean(axis=0) >= thresholds.drive_column_fill_ratio).sum()) / width
        if filled_fraction < thresholds.drive_detect_min_fraction:
            return None

        raw = min(DRIVE_MAX, filled_fraction * DRIVE_MAX)
        return round(min(DRIVE_MAX, raw * self.params.drive_fill_scale.get(side, 1.0)), 2)

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

            # バーンアウト: HUD表示中に黄緑がない状態が一定時間続いた区間（近接区間は結合）
            candidates = [hud[i] and raw_values[i] is None for i in range(len(states))]
            self.burnout_periods[side] = _merge_periods(
                _runs_to_periods(_find_runs(candidates, timestamps), timestamps),
                thresholds.burnout_merge_gap_sec,
            )
            self.burnout_periods[side] = [
                period
                for period in self.burnout_periods[side]
                if period[1] - period[0] >= thresholds.burnout_min_duration_sec
            ]
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
            progress_values = [state.sa_progress for state in states]
            progress_filled = _fill_short_gaps(progress_values, timestamps, thresholds.sa_max_gap_sec)

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
    def _build_match_rounds(self, match_id: str, start_time: float, end_time: float) -> list[dict[str, Any]]:
        """1試合ぶんのラウンド構造を構築する"""
        windows: list[RoundWindow] = split_rounds(
            match_start=start_time,
            match_end=end_time,
            round_banner_times=self.round_banner_times,
        )

        rounds: list[dict[str, Any]] = []
        for window in windows:
            rounds.append(
                {
                    "round": window.index,
                    "roundStartTime": round(window.start_time, 2),
                    "roundEndTime": round(window.end_time, 2),
                    "endReason": window.end_reason,
                    "bannerDetected": window.banner_detected,
                    "player1": self._side_round_payload(window, "player1"),
                    "player2": self._side_round_payload(window, "player2"),
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

    def _side_round_payload(self, window: RoundWindow, side: str) -> dict[str, Any]:
        """ラウンド内の片側の変化点列を作る（時刻はラウンド開始からの相対秒）"""
        base = window.start_time
        samples = self._round_samples(window)
        valid_samples = sum(1 for sample in samples if sample.states[side].drive is not None)
        coverage = round(valid_samples / len(samples), 3) if samples else 0.0

        drive_events: list[list[float]] = []
        sa_events: list[list[float]] = []
        progress_events: list[list[float]] = []
        visible_from: float | None = None
        visible_to: float | None = None
        previous_drive: float | None = None
        previous_stock: int | None = None
        previous_progress: float | None = None

        thresholds = self.params.thresholds
        for sample in samples:
            state = sample.states[side]
            rel = round(sample.timestamp - base, 2)

            if state.drive is not None or state.sa_stock is not None:
                if visible_from is None:
                    visible_from = rel
                visible_to = rel

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

        # ラウンド内のバーンアウト期間・CA期間を相対時刻で切り出す
        burnout_periods = self._clip_periods(self.burnout_periods[side], window, base)
        ca_periods = self._collect_ca_periods(samples, side, base, thresholds.ca_merge_gap_sec)

        return {
            "visibleFrom": visible_from,
            "visibleTo": visible_to,
            "coverage": coverage,
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
                    "drive_burnout",
                    "burnout_candidate",
                    "sa_stock",
                    "sa_label",
                    "sa_score",
                    "sa_critical_art",
                    "sa_progress",
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
                            int(state.drive_burnout),
                            int(state.burnout_candidate),
                            "" if state.sa_stock is None else state.sa_stock,
                            state.sa_label or "",
                            f"{state.sa_score:.3f}",
                            int(state.sa_critical_art),
                            "" if state.sa_progress is None else f"{state.sa_progress:.3f}",
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


def build_round_stats_rows(gauge_result: dict[str, Any], matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ゲージ計測結果とマッチ情報から round_stats.parquet の行を組み立てる

    Args:
        gauge_result: GaugeAnalyzer.build() の戻り値
        matches: main.py の match 辞書リスト（id / videoId / player1 / player2 を含む）

    Returns:
        1行 = 1ラウンド x 1サイド の辞書リスト
    """
    match_map = {match.get("id"): match for match in matches}
    rows: list[dict[str, Any]] = []

    for match_id, match_gauges in (gauge_result.get("matches") or {}).items():
        match = match_map.get(match_id, {})
        for round_data in match_gauges.get("rounds", []):
            for side in SIDES:
                payload = round_data.get(side) or {}
                drive_events = payload.get("drive") or []
                sa_events = payload.get("sa") or []
                visible_from = float(payload.get("visibleFrom") or 0.0)
                visible_to = float(payload.get("visibleTo") or 0.0)
                round_start = float(round_data.get("roundStartTime", 0.0))

                drive_min, drive_avg, drive_end = _series_stats(drive_events, visible_to)
                sa_values = [int(event[1]) for event in sa_events]
                sa_used = sum(
                    1 for previous, current in zip(sa_values, sa_values[1:], strict=False) if current < previous
                )

                player = match.get(side) or {}
                rows.append(
                    {
                        "videoId": match.get("videoId"),
                        "matchId": match_id,
                        "round": int(round_data.get("round", 0)),
                        "side": side,
                        "character": player.get("character"),
                        "roundStartTime": int(round(round_start + visible_from)),
                        "roundEndTime": int(round(round_start + visible_to)),
                        "durationSec": round(max(0.0, visible_to - visible_from), 2),
                        "driveMin": drive_min,
                        "driveAvg": drive_avg,
                        "driveEnd": drive_end,
                        "saMax": max(sa_values) if sa_values else None,
                        "saUsedCount": sa_used,
                        "detectionCoverage": payload.get("coverage"),
                    }
                )

    return rows
