"""ドライブゲージ・SAゲージ計測のユニットテスト（ADR-048）"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from src.detection.config import load_detection_params
from src.detection.gauge import (
    GaugeAnalysisParams,
    GaugeAnalyzer,
    GaugeSample,
    SideGaugeState,
    _fill_short_gaps,
    _median_filter,
    _merge_periods,
    _series_stats,
    build_round_stats_rows,
)

APP_ROOT = Path(__file__).parent.parent

# ドライブゲージのノーマル（黄緑）に相当する BGR
# B=60, G=220, R=220 → HSV は H=30 付近, S≈185, V=220
NORMAL_BGR = (60, 220, 220)
DARK_BGR = (30, 30, 30)


def make_params() -> GaugeAnalysisParams:
    """設定ファイルからゲージ計測パラメータを取得する"""
    params = load_detection_params(profile="production").gauge_analysis
    assert params is not None
    return params


def make_frame() -> np.ndarray:
    return np.full((1080, 1920, 3), DARK_BGR, dtype=np.uint8)


class TestParams:
    def test_load_from_config(self):
        params = make_params()
        assert params.enabled is True
        assert params.base_width == 1920
        assert params.drive_roi["player1"][0] < params.drive_roi["player1"][2]
        assert set(params.sa_digit_templates) == {"0", "1", "2", "3", "ca"}

    def test_validate_rejects_bad_roi(self):
        params = make_params()
        params.drive_roi["player1"] = (100, 100, 50, 200)
        with pytest.raises(ValueError):
            params._validate()

    def test_validate_rejects_bad_scale(self):
        params = make_params()
        params.banner_scale = 0.0
        with pytest.raises(ValueError):
            params._validate()


class TestDriveMeasurement:
    """ROI の塗り分けで作った合成フレームからドライブ本数を計測する"""

    def _analyzer(self, frame: np.ndarray) -> GaugeAnalyzer:
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        analyzer._prepare_geometry(frame)
        return analyzer

    def test_full_gauge_is_six(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        frame[y1:y2, x1:x2] = NORMAL_BGR
        assert analyzer._measure_drive(frame, "player1") == pytest.approx(6.0, abs=0.05)

    def test_half_gauge_is_three(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        # 内側（右）半分だけ塗る
        middle = (x1 + x2) // 2
        frame[y1:y2, middle:x2] = NORMAL_BGR
        assert analyzer._measure_drive(frame, "player1") == pytest.approx(3.0, abs=0.1)

    def test_empty_gauge_returns_none(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        assert analyzer._measure_drive(frame, "player1") is None

    def test_player2_roi_is_used(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player2"]
        frame[y1:y2, x1:x2] = NORMAL_BGR
        assert analyzer._measure_drive(frame, "player2") == pytest.approx(6.0, abs=0.05)
        assert analyzer._measure_drive(frame, "player1") is None


class TestSaMeasurement:
    def test_bar_progress_from_synthetic_frame(self):
        frame = make_frame()
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        analyzer._prepare_geometry(frame)
        x1, y1, x2, y2 = make_params().sa_bar_roi["player1"]
        middle = (x1 + x2) // 2
        frame[y1:y2, x1:middle] = NORMAL_BGR
        _, _, score, progress, _ = analyzer._measure_sa(frame, "player1")
        assert progress == pytest.approx(0.5, abs=0.1)
        # 数字グリフは無いのでスコアは採用閾値を下回る
        assert score < make_params().thresholds.sa_digit_min_score


class TestRoundBannerDetection:
    def test_detects_template_in_search_region(self):
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        template = cv2.imread(str(APP_ROOT / "template/gauge/round_banner.png"))
        assert template is not None

        frame = make_frame()
        analyzer._prepare_geometry(frame)
        x1, y1, x2, y2 = make_params().round_banner_search_region
        # 探索領域の中央にテンプレートを貼り付ける
        top = y1 + (y2 - y1 - template.shape[0]) // 2
        left = x1 + (x2 - x1 - template.shape[1]) // 2
        frame[top : top + template.shape[0], left : left + template.shape[1]] = template

        assert analyzer._detect_round_banner(frame, 21.0) is True
        # 直後のフレームは多重検出しない（検出済み時刻を登録してから確認）
        analyzer.round_banner_times.append(21.0)
        assert analyzer._detect_round_banner(frame, 21.25) is False
        analyzer.round_banner_times.clear()
        assert analyzer._detect_round_banner(frame, 30.0) is True

    def test_returns_false_without_banner(self):
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        frame = make_frame()
        analyzer._prepare_geometry(frame)
        assert analyzer._detect_round_banner(frame, 50.0) is False


class TestFilters:
    def test_median_filter_removes_spike(self):
        values = [5.0, 5.0, 1.0, 5.0, 5.0]
        assert _median_filter(values, 3) == [5.0, 5.0, 5.0, 5.0, 5.0]

    def test_median_filter_ignores_none(self):
        values = [None, 4.0, None, None, 6.0]
        assert _median_filter(values, 3) == [4.0, 4.0, 4.0, 6.0, 6.0]

    def test_median_filter_window_one_is_identity(self):
        values = [1.0, None, 3.0]
        assert _median_filter(values, 1) == values

    def test_fill_short_gaps(self):
        timestamps = [0.0, 0.1, 0.2, 0.3, 0.4]
        values = [1.0, None, None, 2.0, None]
        filled = _fill_short_gaps(values, timestamps, max_gap_sec=0.5)
        assert filled == [1.0, 1.0, 1.0, 2.0, None]

    def test_fill_long_gaps_keeps_none(self):
        timestamps = [0.0, 1.0, 2.0, 3.0]
        values = [1.0, None, None, 2.0]
        filled = _fill_short_gaps(values, timestamps, max_gap_sec=0.5)
        assert filled == [1.0, None, None, 2.0]

    def test_merge_periods(self):
        assert _merge_periods([[1.0, 2.0], [2.2, 3.0], [10.0, 11.0]], 0.5) == [[1.0, 3.0], [10.0, 11.0]]

    def test_series_stats(self):
        minimum, average, end = _series_stats([[0.0, 6.0], [1.0, 2.0]], end_time=2.0)
        assert minimum == 2.0
        assert average == pytest.approx(4.0)
        assert end == 2.0

    def test_series_stats_empty(self):
        assert _series_stats([], end_time=10.0) == (None, None, None)

    def test_extend_flags(self):
        timestamps = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
        flags = [False, False, True, False, False, False]
        # 前後 0.6 秒以内を True に広げる（1.0 秒離れた両端は False のまま）
        assert GaugeAnalyzer._extend_flags(flags, timestamps, max_gap_sec=0.6) == [
            False,
            True,
            True,
            True,
            False,
            False,
        ]
        # 境界（ちょうど max_gap）は含める
        assert GaugeAnalyzer._extend_flags(flags, timestamps, max_gap_sec=1.0) == [
            True,
            True,
            True,
            True,
            True,
            False,
        ]

    def test_extend_flags_without_true(self):
        timestamps = [0.0, 0.5]
        assert GaugeAnalyzer._extend_flags([False, False], timestamps, max_gap_sec=1.0) == [False, False]


class TestDeriveStates:
    """平滑化・欠損補完・バーンアウト判定の検証"""

    def _analyzer_with_samples(self, states: list[tuple[float, float | None, bool, int | None]]) -> GaugeAnalyzer:
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        for timestamp, drive_raw, hud_visible, sa_stock in states:
            analyzer.samples.append(
                GaugeSample(
                    timestamp=timestamp,
                    states={
                        "player1": SideGaugeState(
                            hud_visible=hud_visible,
                            drive_raw=drive_raw,
                            burnout_candidate=hud_visible and drive_raw is None,
                            sa_stock=sa_stock,
                        ),
                        "player2": SideGaugeState(),
                    },
                )
            )
        analyzer._derive_states()
        return analyzer

    def test_burnout_run_is_detected(self):
        # 6秒分のサンプル: 前半は通常、後半は HUD 表示中に黄緑なし（バーンアウト）
        states = [(i * 0.1, 5.0, True, 0) for i in range(20)]
        states += [(2.0 + i * 0.1, None, True, 0) for i in range(20)]
        analyzer = self._analyzer_with_samples(states)

        periods = analyzer.burnout_periods["player1"]
        assert len(periods) == 1
        assert periods[0][0] == pytest.approx(2.0, abs=0.11)
        assert periods[0][1] == pytest.approx(3.9, abs=0.11)

        # バーンアウト期間のドライブは 0.0 になる
        burnout_samples = [s for s in analyzer.samples if s.timestamp >= 2.0]
        assert all(s.states["player1"].drive == 0.0 for s in burnout_samples)
        assert all(s.states["player1"].drive_burnout for s in burnout_samples)

    def test_short_burnout_is_ignored(self):
        # 0.3秒だけ黄緑が消える（単発の誤検出）→ バーンアウト扱いしない
        states = [(i * 0.1, 5.0, True, 0) for i in range(20)]
        states += [(2.0, None, True, 0), (2.1, None, True, 0), (2.2, None, True, 0)]
        states += [(2.3 + i * 0.1, 5.0, True, 0) for i in range(10)]
        analyzer = self._analyzer_with_samples(states)

        assert analyzer.burnout_periods["player1"] == []
        assert not any(s.states["player1"].drive_burnout for s in analyzer.samples)

    def test_hud_hidden_samples_have_no_drive(self):
        # ラウンド移行など HUD 非表示の区間は drive が None のまま
        states = [(i * 0.1, 5.0, True, 0) for i in range(10)]
        states += [(1.0 + i * 0.1, None, False, None) for i in range(30)]
        states += [(4.0 + i * 0.1, 5.0, True, 1) for i in range(10)]
        analyzer = self._analyzer_with_samples(states)

        # HUD 非表示の中央付近は補完されず None のまま（端は前後 1 秒まで補完される）
        hidden = [s for s in analyzer.samples if 2.0 <= s.timestamp <= 2.9]
        assert hidden and all(s.states["player1"].drive is None for s in hidden)
        assert analyzer.burnout_periods["player1"] == []

    def test_sa_spike_is_removed(self):
        states = []
        for i in range(10):
            states.append((i * 0.1, 5.0, True, 3))
        states.append((1.0, 5.0, True, 1))  # 単発の誤検出
        for i in range(11, 20):
            states.append((i * 0.1, 5.0, True, 3))
        analyzer = self._analyzer_with_samples(states)
        assert all(s.states["player1"].sa_stock == 3 for s in analyzer.samples)


class TestBuildRoundStatsRows:
    def test_builds_rows_per_round_and_side(self):
        gauge_result = {
            "matches": {
                "vid_100": {
                    "matchId": "vid_100",
                    "rounds": [
                        {
                            "round": 1,
                            "roundStartTime": 100.0,
                            "roundEndTime": 150.0,
                            "endReason": "match_end",
                            "player1": {
                                "visibleFrom": 1.0,
                                "visibleTo": 49.0,
                                "coverage": 0.9,
                                "drive": [[1.0, 6.0], [10.0, 0.0]],
                                "sa": [[1.0, 0], [20.0, 3], [30.0, 2]],
                                "driveBurnout": [[10.0, 20.0]],
                                "saCriticalArt": [],
                                "saProgress": [],
                            },
                            "player2": {
                                "visibleFrom": 1.0,
                                "visibleTo": 49.0,
                                "coverage": 0.8,
                                "drive": [[1.0, 4.0]],
                                "sa": [[1.0, 1]],
                                "driveBurnout": [],
                                "saCriticalArt": [],
                                "saProgress": [],
                            },
                        }
                    ],
                }
            }
        }
        matches = [
            {
                "id": "vid_100",
                "videoId": "vid",
                "player1": {"character": "JP"},
                "player2": {"character": "GOUKI"},
            }
        ]

        rows = build_round_stats_rows(gauge_result, matches)
        assert len(rows) == 2

        p1 = rows[0]
        assert p1["videoId"] == "vid"
        assert p1["matchId"] == "vid_100"
        assert p1["side"] == "player1"
        assert p1["character"] == "JP"
        assert p1["roundStartTime"] == 101
        assert p1["roundEndTime"] == 149
        assert p1["durationSec"] == 48.0
        assert p1["driveMin"] == 0.0
        assert p1["driveEnd"] == 0.0
        assert p1["saMax"] == 3
        assert p1["saUsedCount"] == 1
        assert p1["detectionCoverage"] == 0.9

        p2 = rows[1]
        assert p2["side"] == "player2"
        assert p2["character"] == "GOUKI"
        assert p2["saMax"] == 1
        assert p2["saUsedCount"] == 0

    def test_missing_match_metadata(self):
        gauge_result = {"matches": {"unknown": {"rounds": [{"round": 1, "roundStartTime": 0, "player1": {}}]}}}
        rows = build_round_stats_rows(gauge_result, [])
        assert len(rows) == 2
        assert rows[0]["videoId"] is None
        assert rows[0]["character"] is None
        assert rows[0]["driveMin"] is None


class TestSaveGaugeData:
    """main.SF6ChapterProcessor._save_gauge_data の結合確認（R2無効時）"""

    def test_writes_intermediate_files_and_verifies_round_count(self, tmp_path):
        from main import SF6ChapterProcessor

        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        analyzer.samples.append(
            GaugeSample(
                timestamp=21.0,
                states={
                    "player1": SideGaugeState(hud_visible=True, drive_raw=6.0, sa_stock=0),
                    "player2": SideGaugeState(hud_visible=True, drive_raw=6.0, sa_stock=0),
                },
            )
        )
        gauge_result = {
            "matches": {
                "vid_21": {
                    "matchId": "vid_21",
                    "rounds": [
                        {
                            "round": 1,
                            "roundStartTime": 21.0,
                            "roundEndTime": 60.0,
                            "endReason": "match_end",
                            "player1": {
                                "visibleFrom": 1.0,
                                "visibleTo": 39.0,
                                "coverage": 0.9,
                                "drive": [[1.0, 6.0]],
                                "sa": [[1.0, 0]],
                                "driveBurnout": [],
                                "saCriticalArt": [],
                                "saProgress": [],
                            },
                            "player2": {
                                "visibleFrom": 1.0,
                                "visibleTo": 39.0,
                                "coverage": 0.9,
                                "drive": [[1.0, 6.0]],
                                "sa": [[1.0, 0]],
                                "driveBurnout": [],
                                "saCriticalArt": [],
                                "saProgress": [],
                            },
                        }
                    ],
                }
            }
        }

        processor = object.__new__(SF6ChapterProcessor)
        processor.gauge_analyzer = analyzer
        processor.gauge_result = gauge_result
        processor.enable_r2 = False
        processor.r2_uploader = None

        matches = [
            {"id": "vid_21", "videoId": "vid", "player1": {"character": "JP"}, "player2": {"character": "GOUKI"}}
        ]
        chapters = [
            {
                "matchId": "vid_21",
                "matched": True,
                "replay_id": "ABCDE",
                "player1_result": "win",
                "player2_result": "loss",
                "round_count": 2,
            }
        ]

        processor._save_gauge_data("vid", matches, chapters, tmp_path)

        assert (tmp_path / "gauges" / "gauges.json").exists()
        assert (tmp_path / "gauges" / "gauges_samples.csv").exists()
        assert (tmp_path / "gauges" / "round_stats_preview.json").exists()

        match_gauges = gauge_result["matches"]["vid_21"]
        assert match_gauges["detectedRoundCount"] == 1
        assert match_gauges["battlelogRoundCount"] == 2
        assert match_gauges["roundCountMatch"] is False

    def test_no_gauge_data_is_noop(self, tmp_path):
        from main import SF6ChapterProcessor

        processor = object.__new__(SF6ChapterProcessor)
        processor.gauge_analyzer = None
        processor.gauge_result = None
        processor.enable_r2 = False
        processor.r2_uploader = None

        processor._save_gauge_data("vid", [], [], tmp_path)
        assert not (tmp_path / "gauges").exists()


class TestHudFlickerTolerance:
    def test_short_hidden_gap_is_treated_as_visible(self):
        # HUD が 0.3 秒だけ途切れる（スコアの揺れ）→ 表示中として扱う
        states = [(i * 0.1, 5.0, True, 0) for i in range(10)]
        states += [(1.0 + i * 0.1, 5.0, False, 0) for i in range(3)]
        states += [(1.3 + i * 0.1, 5.0, True, 0) for i in range(10)]
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        for timestamp, drive_raw, hud_visible, sa_stock in states:
            analyzer.samples.append(
                GaugeSample(
                    timestamp=timestamp,
                    states={
                        "player1": SideGaugeState(
                            hud_visible=hud_visible,
                            drive_raw=drive_raw,
                            burnout_candidate=hud_visible and drive_raw is None,
                            sa_stock=sa_stock,
                        ),
                        "player2": SideGaugeState(),
                    },
                )
            )
        analyzer._derive_states()
        assert all(s.states["player1"].drive is not None for s in analyzer.samples)


# ADR-050: 体力ゲージ
MAGENTA_BGR = (200, 30, 200)  # P1 の現在体力色（H≈150 のマゼンタ）
BLUE_BGR = (200, 100, 30)  # P2 の現在体力色（H≈105 の青）
YELLOW_BGR = (0, 220, 220)  # 回復可能ダメージ（黄）


class TestHealthMeasurement:
    def _analyzer(self, frame: np.ndarray) -> GaugeAnalyzer:
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        analyzer._prepare_geometry(frame)
        return analyzer

    def test_full_health_is_100_percent(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        frame[y1:y2, x1:x2] = MAGENTA_BGR
        assert analyzer._measure_health(frame, "player1") == pytest.approx(100.0, abs=0.5)

    def test_half_health_is_50_percent(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        # 内側（右）半分だけ現在体力（キャリブレーション係数を考慮して検証する）
        middle = (x1 + x2) // 2
        frame[y1:y2, middle:x2] = MAGENTA_BGR
        scale = make_params().health_fill_scale["player1"]
        assert analyzer._measure_health(frame, "player1") == pytest.approx(50.0 * scale, abs=1.0)

    def test_player2_uses_blue(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player2"]
        frame[y1:y2, x1:x2] = BLUE_BGR
        assert analyzer._measure_health(frame, "player2") == pytest.approx(100.0, abs=0.5)
        # P1 の色域はマゼンタ〜赤なので、青は P1 では計測されない
        assert analyzer._measure_health(frame, "player1") is None

    def test_recoverable_yellow_is_not_counted(self):
        # ADR-050 決定1: 回復可能（黄）は現在体力に含めない
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        frame[y1:y2, x1:x2] = YELLOW_BGR
        assert analyzer._measure_health(frame, "player1") is None

    def test_empty_health_returns_none(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        assert analyzer._measure_health(frame, "player1") is None


class TestHealthDerivation:
    def _analyzer_with_health(self, values: list[tuple[float, float | None, bool]]) -> GaugeAnalyzer:
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        for timestamp, health_raw, hud_visible in values:
            analyzer.samples.append(
                GaugeSample(
                    timestamp=timestamp,
                    states={
                        "player1": SideGaugeState(hud_visible=hud_visible, health_raw=health_raw),
                        "player2": SideGaugeState(),
                    },
                )
            )
        analyzer._derive_states()
        return analyzer

    def test_spike_is_smoothed(self):
        values = [(i * 0.1, 100.0, True) for i in range(5)]
        values += [(0.5, 10.0, True)]  # 単発の外れ値
        values += [(0.6 + i * 0.1, 100.0, True) for i in range(5)]
        analyzer = self._analyzer_with_health(values)
        assert all(s.states["player1"].health == pytest.approx(100.0, abs=0.1) for s in analyzer.samples)

    def test_hud_hidden_has_no_health(self):
        values = [(i * 0.1, 100.0, True) for i in range(5)]
        values += [(0.5 + i * 0.1, None, False) for i in range(20)]
        values += [(2.5 + i * 0.1, 80.0, True) for i in range(5)]
        analyzer = self._analyzer_with_health(values)
        hidden = [s for s in analyzer.samples if 1.2 <= s.timestamp <= 2.0]
        assert hidden and all(s.states["player1"].health is None for s in hidden)


class TestHealthRoundStats:
    def test_health_columns_are_built(self):
        gauge_result = {
            "matches": {
                "vid_100": {
                    "matchId": "vid_100",
                    "rounds": [
                        {
                            "round": 1,
                            "roundStartTime": 100.0,
                            "roundEndTime": 150.0,
                            "endReason": "match_end",
                            "player1": {
                                "visibleFrom": 1.0,
                                "visibleTo": 49.0,
                                "coverage": 0.9,
                                "healthCoverage": 0.95,
                                "health": [[1.0, 100.0], [10.0, 40.0], [20.0, 0.0]],
                                "drive": [[1.0, 6.0]],
                                "sa": [[1.0, 0]],
                                "driveBurnout": [],
                                "saCriticalArt": [],
                                "saProgress": [],
                            },
                            "player2": {
                                "visibleFrom": 1.0,
                                "visibleTo": 49.0,
                                "coverage": 0.9,
                                "healthCoverage": 0.0,
                                "health": [],
                                "drive": [[1.0, 6.0]],
                                "sa": [[1.0, 0]],
                                "driveBurnout": [],
                                "saCriticalArt": [],
                                "saProgress": [],
                            },
                        }
                    ],
                }
            }
        }
        matches = [
            {"id": "vid_100", "videoId": "vid", "player1": {"character": "GOUKI"}, "player2": {"character": "RYU"}}
        ]

        rows = build_round_stats_rows(gauge_result, matches)
        p1 = rows[0]
        assert p1["healthMin"] == 0.0
        assert p1["healthEnd"] == 0.0
        assert p1["healthAvg"] is not None and 0.0 < p1["healthAvg"] < 100.0

        p2 = rows[1]
        assert p2["healthMin"] is None
        assert p2["healthAvg"] is None
        assert p2["healthEnd"] is None
