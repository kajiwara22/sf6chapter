"""カウンター・パニッシュカウンターの回数計測（ADR-049）

対戦動画から 1P/2P それぞれの
- COUNTER（カウンター）
- PUNISH COUNTER（パニッシュカウンター）
の発生回数をラウンド単位で数える。

計測は固定 ROI のグレースケールテンプレートマッチングのみで行い、
学習モデルや VLM は使わない。既存の TemplateMatcher のデコードループから
feed() を呼び出すため、動画の再デコードは発生しない。

数え方の考え方:

- バナーは「カウンターを決めた側」に表示される（左=1P / 右=2P）
- マッチスコアが閾値を超えた区間（ON 区間）を 1 回として数える
- 再トリガーでバナーが連続表示される場合は、merge_gap_sec 以内の空白は
  同一バナーとみなして連結し、それを超える空白で別カウントにする
- min_duration_sec 未満の単発検出はノイズとして捨てる
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..utils.logger import get_logger
from .round_splitter import RoundWindow, split_rounds

logger = get_logger()

SIDES: tuple[str, str] = ("player1", "player2")

# バナーの種別（値はそのまま保存キー・表示ラベルに使う）
COUNTER = "counter"
PUNISH_COUNTER = "punish_counter"
COUNTER_TYPES: tuple[str, str] = (COUNTER, PUNISH_COUNTER)

# ラウンド境界の手前側に許容する幅（秒）。バナーは ROUND バナーより後に出るが、
# 最初のラウンドで開始直後に出た場合の丸め誤差を吸収する。
ROUND_START_TOLERANCE_SEC = 0.5


@dataclass
class CounterThresholds:
    """カウンター計測の閾値"""

    match_score: float = 0.7
    min_duration_sec: float = 0.4
    merge_gap_sec: float = 0.25

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    def log(self) -> None:
        logger.info("  [Counter Thresholds]")
        for key, value in self.__dict__.items():
            logger.info("    %-32s %s", f"{key}:", value)


@dataclass
class CounterAnalysisParams:
    """カウンター計測パラメータ（座標は base_width x base_height 基準）"""

    enabled: bool
    base_width: int
    base_height: int
    sample_interval_sec: float
    roi: dict[str, tuple[int, int, int, int]]
    thresholds: CounterThresholds
    templates: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CounterAnalysisParams:
        """設定ファイルの counter_analysis セクションから生成"""
        templates = data.get("templates", {}) or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            base_width=int(data.get("base_width", 1920)),
            base_height=int(data.get("base_height", 1080)),
            sample_interval_sec=float(data.get("sample_interval_sec", 0.1)),
            roi={side: tuple(data["roi"][side]) for side in SIDES},
            thresholds=CounterThresholds(**data.get("thresholds", {})),
            templates={
                ctype: {side: str(path) for side, path in (templates.get(ctype) or {}).items()}
                for ctype in COUNTER_TYPES
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_width": self.base_width,
            "base_height": self.base_height,
            "sample_interval_sec": self.sample_interval_sec,
            "roi": {side: list(values) for side, values in self.roi.items()},
            "thresholds": self.thresholds.to_dict(),
            "templates": {ctype: dict(paths) for ctype, paths in self.templates.items()},
        }

    def _validate(self) -> None:
        if self.sample_interval_sec <= 0:
            raise ValueError(f"sample_interval_sec must be positive, got {self.sample_interval_sec}")
        for side, values in self.roi.items():
            if len(values) != 4:
                raise ValueError(f"roi[{side}] must have 4 elements, got {values}")
            if values[2] <= values[0] or values[3] <= values[1]:
                raise ValueError(f"roi[{side}] must be (x1, y1, x2, y2) with x2>x1, y2>y1, got {values}")
        for ctype in COUNTER_TYPES:
            for side in SIDES:
                if not self.templates.get(ctype, {}).get(side):
                    raise ValueError(f"templates[{ctype}][{side}] is required")

    def log_params(self) -> None:
        logger.info("  [Counter Analysis]")
        logger.info("    enabled:                  %s", self.enabled)
        logger.info("    base size:                %dx%d", self.base_width, self.base_height)
        logger.info("    sample_interval_sec:      %.2f", self.sample_interval_sec)
        for side in SIDES:
            logger.info("    roi[%s]:             %s", side, self.roi[side])
        for ctype in COUNTER_TYPES:
            for side in SIDES:
                logger.info("    template[%s][%s]: %s", ctype, side, self.templates[ctype][side])
        self.thresholds.log()


@dataclass
class SideCounterScores:
    """1サンプル時点の片側のマッチスコア"""

    counter: float = 0.0
    punish_counter: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"counter": round(self.counter, 4), "punishCounter": round(self.punish_counter, 4)}


@dataclass
class CounterSample:
    """1サンプル時点の両サイドのスコア"""

    timestamp: float
    scores: dict[str, SideCounterScores]


@dataclass
class CounterOccurrence:
    """カウンター1回分の ON 区間"""

    type: str
    side: str
    start_time: float
    end_time: float
    peak_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "side": self.side,
            "start": round(self.start_time, 2),
            "end": round(self.end_time, 2),
            "peakScore": round(self.peak_score, 3),
        }


def _find_runs(flags: list[bool]) -> list[tuple[int, int]]:
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


def classify_scores(scores: SideCounterScores, match_score: float) -> str | None:
    """1サンプルのスコアから種別を決める（閾値未満は None）

    両方が閾値を超えた場合はスコアが大きい方を採用する（ADR-049 決定1）。
    同点は PUNISH COUNTER を優先する（誤検出時は判別力の高い方を残す方が安全なため）。
    """
    if scores.punish_counter >= match_score and scores.punish_counter >= scores.counter:
        return PUNISH_COUNTER
    if scores.counter >= match_score:
        return COUNTER
    return None


def _classify_samples(samples: list[CounterSample], side: str, match_score: float) -> list[str | None]:
    """各サンプルで閾値を超えた種別を返す（超えていなければ None）"""
    return [classify_scores(sample.scores[side], match_score) for sample in samples]


def extract_occurrences(
    samples: list[CounterSample],
    side: str,
    thresholds: CounterThresholds,
) -> list[CounterOccurrence]:
    """サンプル列から ON 区間（カウンター 1 回分）を抽出する

    feed() で貯めたスコア列をまとめて処理する純関数。テストしやすいよう
    Analyzer から分離している。

    Args:
        samples: 時刻昇順のサンプル列
        side: "player1" | "player2"
        thresholds: 閾値（match_score / min_duration_sec / merge_gap_sec）

    Returns:
        発生順（開始時刻昇順）の CounterOccurrence リスト
    """
    if not samples:
        return []

    timestamps = [sample.timestamp for sample in samples]
    types = _classify_samples(samples, side, thresholds.match_score)

    occurrences: list[CounterOccurrence] = []
    for ctype in COUNTER_TYPES:
        flags = [value == ctype for value in types]
        runs = _find_runs(flags)
        if not runs:
            continue

        # merge_gap_sec 以内の空白は同一バナーとみなして連結する
        merged: list[tuple[int, int]] = []
        for start, end in runs:
            if merged and timestamps[start] - timestamps[merged[-1][1] - 1] <= thresholds.merge_gap_sec:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))

        for start, end in merged:
            duration = timestamps[end - 1] - timestamps[start]
            if duration < thresholds.min_duration_sec:
                continue
            peak = max(getattr(sample.scores[side], ctype) for sample in samples[start:end])
            occurrences.append(
                CounterOccurrence(
                    type=ctype,
                    side=side,
                    start_time=timestamps[start],
                    end_time=timestamps[end - 1],
                    peak_score=peak,
                )
            )

    occurrences.sort(key=lambda occurrence: occurrence.start_time)
    return occurrences


class CounterAnalyzer:
    """デコードループから呼び出されるカウンター計測器

    使い方::

        analyzer = CounterAnalyzer(params, app_root)
        matcher.set_counter_analyzer(analyzer)   # detect_matches() のループ内で feed() が呼ばれる
        detections = matcher.detect_matches(...)
        counter_data = analyzer.build(matches, round_banner_times=gauge.banner_times)
    """

    # 検証用スナップショットの保存上限
    MAX_SNAPSHOTS = 80

    def __init__(self, params: CounterAnalysisParams, app_root: Path):
        params._validate()
        self.params = params
        self.app_root = Path(app_root)

        self.samples: list[CounterSample] = []
        self.snapshots: list[dict[str, Any]] = []

        self._last_sample_time: float | None = None
        self._prev_types: dict[str, str | None] = dict.fromkeys(SIDES)

        # テンプレートを読み込む（種別 -> サイド -> グレースケール画像）
        self._templates: dict[str, dict[str, np.ndarray]] = {ctype: {} for ctype in COUNTER_TYPES}
        for ctype in COUNTER_TYPES:
            for side in SIDES:
                path = params.templates.get(ctype, {}).get(side)
                template = cv2.imread(str(self._resolve(path)), cv2.IMREAD_GRAYSCALE) if path else None
                if template is None:
                    logger.warning("⚠️ Counter template not found: %s (%s/%s)", path, ctype, side)
                    continue
                self._templates[ctype][side] = template

        # 実フレームサイズに応じたスケール済み ROI（最初の feed で確定）
        self._frame_size: tuple[int, int] | None = None
        self._roi: dict[str, tuple[int, int, int, int]] = {}

    # ------------------------------------------------------------------
    # 計測本体
    # ------------------------------------------------------------------
    def feed(self, frame: np.ndarray, timestamp: float) -> None:
        """デコードループから毎フレーム呼び出す（間隔判定は内部で行う）"""
        if not self.params.enabled:
            return
        if not self._prepare_geometry(frame):
            return

        interval = self.params.sample_interval_sec
        if self._last_sample_time is not None and timestamp - self._last_sample_time < interval:
            return
        self._last_sample_time = timestamp

        scores: dict[str, SideCounterScores] = {}
        for side in SIDES:
            band = self._crop(frame, self._roi[side])
            if band.size == 0:
                scores[side] = SideCounterScores()
                continue
            gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY) if band.ndim == 3 else band
            values: dict[str, float] = {}
            for ctype in COUNTER_TYPES:
                template = self._templates[ctype].get(side)
                if template is None or template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
                    values[ctype] = -1.0
                    continue
                values[ctype] = float(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED).max())
            scores[side] = SideCounterScores(counter=values[COUNTER], punish_counter=values[PUNISH_COUNTER])

        self.samples.append(CounterSample(timestamp=timestamp, scores=scores))
        self._capture_start_snapshots(frame, timestamp, scores)

    def build(
        self,
        matches: list[tuple[str, float]],
        round_banner_times: list[float] | None = None,
        video_end: float | None = None,
    ) -> dict[str, Any]:
        """検出済みマッチ情報からラウンド単位のカウンター回数を構築する

        Args:
            matches: (match_id, 開始時刻[秒]) のリスト（時系列順）
            round_banner_times: ROUND バナー時刻（ADR-048 の GaugeAnalyzer.banner_times）
            video_end: 動画長（秒）。最後の試合の終端に使う

        Returns:
            {"matches": {match_id: {"matchId":..., "rounds": [...]}}, "occurrences": [...]}
        """
        round_banner_times = list(round_banner_times or [])

        if video_end is None:
            video_end = self.samples[-1].timestamp if self.samples else 0.0

        # 全編の発生区間を先に求める（ラウンド境界をまたぐ二重カウントを避けるため、
        # 区間は開始時刻でラウンドに割り当てる）
        occurrences_by_side: dict[str, list[CounterOccurrence]] = {
            side: extract_occurrences(self.samples, side, self.params.thresholds) for side in SIDES
        }
        all_occurrences = sorted(
            (occurrence for values in occurrences_by_side.values() for occurrence in values),
            key=lambda occurrence: occurrence.start_time,
        )

        out_matches: dict[str, Any] = {}
        for index, (match_id, start_time) in enumerate(matches):
            end_time = matches[index + 1][1] if index + 1 < len(matches) else video_end
            windows = split_rounds(
                match_start=start_time,
                match_end=end_time,
                round_banner_times=round_banner_times,
            )
            rounds = [self._round_payload(window, all_occurrences) for window in windows]
            out_matches[match_id] = {"matchId": match_id, "rounds": rounds}
            logger.info(
                "[Counter] matchId=%s start=%.2f end=%.2f rounds=%d counters=%s",
                match_id,
                start_time,
                end_time,
                len(rounds),
                [
                    f"R{r['round']}:{r['player1']['counterCount']}"
                    f"/{r['player1']['punishCounterCount']}-"
                    f"{r['player2']['counterCount']}/{r['player2']['punishCounterCount']}"
                    for r in rounds
                ],
            )

        return {
            "matches": out_matches,
            "occurrences": [occurrence.to_dict() for occurrence in all_occurrences],
            "roundBannerTimes": round_banner_times,
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
        self._roi = {
            side: (
                int(round(self.params.roi[side][0] * scale_x)),
                int(round(self.params.roi[side][1] * scale_y)),
                int(round(self.params.roi[side][2] * scale_x)),
                int(round(self.params.roi[side][3] * scale_y)),
            )
            for side in SIDES
        }
        self._frame_size = (width, height)
        logger.info("[Counter] Geometry prepared for %dx%d (scale x%.3f, y%.3f)", width, height, scale_x, scale_y)
        return True

    def _crop(self, frame: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = roi
        height, width = frame.shape[:2]
        x1 = max(0, min(x1, width - 1))
        x2 = max(x1 + 1, min(x2, width))
        y1 = max(0, min(y1, height - 1))
        y2 = max(y1 + 1, min(y2, height))
        return frame[y1:y2, x1:x2]

    def _round_payload(self, window: RoundWindow, occurrences: list[CounterOccurrence]) -> dict[str, Any]:
        """1ラウンドぶんのカウンター回数をまとめる"""
        # 試合開始時刻を代用したラウンド（バナー未検出の第1ラウンド）だけ、
        # 開始時刻の丸め誤差を吸収する許容幅を下側に持たせる
        tolerance = ROUND_START_TOLERANCE_SEC if not window.banner_detected else 0.0
        lower = window.start_time - tolerance
        upper = window.boundary_time if window.boundary_time is not None else window.end_time

        in_round = [occurrence for occurrence in occurrences if lower <= occurrence.start_time < upper]

        payload: dict[str, Any] = {
            "round": window.index,
            "roundStartTime": round(window.start_time, 2),
            "roundEndTime": round(window.end_time, 2),
            "endReason": window.end_reason,
            "bannerDetected": window.banner_detected,
        }
        for side in SIDES:
            side_occurrences = [occurrence for occurrence in in_round if occurrence.side == side]
            payload[side] = {
                "counterCount": sum(1 for occurrence in side_occurrences if occurrence.type == COUNTER),
                "punishCounterCount": sum(1 for occurrence in side_occurrences if occurrence.type == PUNISH_COUNTER),
                # occurrences は中間ファイル（目視検証）用。parquet には保存しない
                "occurrences": [occurrence.to_dict() for occurrence in side_occurrences],
            }
        return payload

    # ------------------------------------------------------------------
    # 検証用の中間ファイル出力（ADR-049 決定11）
    # ------------------------------------------------------------------
    def write_samples_csv(self, path: Path) -> None:
        """全サンプルのスコア時系列を CSV 出力する（目視検証用）"""
        import csv

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "side", "counter_score", "punish_counter_score", "active_type"])
            for sample in self.samples:
                for side in SIDES:
                    scores = sample.scores[side]
                    active = classify_scores(scores, self.params.thresholds.match_score) or ""
                    writer.writerow(
                        [
                            f"{sample.timestamp:.2f}",
                            side,
                            f"{scores.counter:.4f}",
                            f"{scores.punish_counter:.4f}",
                            active,
                        ]
                    )
        logger.info("✅ Saved counter samples CSV: %s", path)

    def write_events_json(self, path: Path, counter_result: dict[str, Any]) -> None:
        """ラウンド別の回数と ON 区間を JSON 出力する（目視検証・再計算用）"""
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(counter_result, f, ensure_ascii=False, indent=2)
        logger.info("✅ Saved counter events: %s", path)

    def save_snapshots(self, directory: Path) -> list[Path]:
        """カウンター開始時点のバナー切り出し画像を保存する（目視検証用）"""
        directory.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for index, snapshot in enumerate(self.snapshots[: self.MAX_SNAPSHOTS], 1):
            path = directory / (f"{index:03d}_{snapshot['timestamp']:.1f}s_{snapshot['type']}_{snapshot['side']}.png")
            cv2.imwrite(str(path), snapshot["image"])
            saved.append(path)
        if saved:
            logger.info("✅ Saved %d counter snapshots: %s", len(saved), directory)
        return saved

    def _capture_start_snapshots(
        self, frame: np.ndarray, timestamp: float, scores: dict[str, SideCounterScores]
    ) -> None:
        """カウンターの発生開始とみられるフレームのバナー画像を残す"""
        if len(self.snapshots) >= self.MAX_SNAPSHOTS or self._frame_size is None:
            return
        threshold = self.params.thresholds.match_score
        for side in SIDES:
            active = classify_scores(scores[side], threshold)

            # 種別の開始（無 → あり）と種別の切り替わり（COUNTER → PUNISH COUNTER 等）を記録する
            if active is not None and active != self._prev_types[side]:
                self.snapshots.append(
                    {
                        "timestamp": timestamp,
                        "type": active,
                        "side": side,
                        "image": self._crop(frame, self._roi[side]).copy(),
                    }
                )
            self._prev_types[side] = active
