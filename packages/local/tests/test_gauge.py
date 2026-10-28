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
    _is_poison_character,
    _median_filter,
    _merge_periods,
    _perfect_ko_time,
    _series_stats,
    _suppress_transient_reverts,
    build_round_stats_rows,
)
from src.detection.round_splitter import RoundWindow

APP_ROOT = Path(__file__).parent.parent

# ドライブゲージのノーマル（黄緑）に相当する BGR
# B=60, G=220, R=220 → HSV は H=30 付近, S≈185, V=220
NORMAL_BGR = (60, 220, 220)
# ADR-065: 低ドライブ警告の金色バー（H≈20, S≈255, V≈130）
GOLD_BGR = (0, 87, 130)
# ADR-065: 空きトラックの暗い青（H≈120, S≈255, V≈15）
EMPTY_TRACK_BGR = (15, 0, 0)
# ADR-065: バーンアウト中の回復バー（白/銀）
WHITE_BGR = (170, 170, 170)
# ADR-066: バーンアウト開始時に出る EMPTY 文字の金色（H≈22, S≈160, V≈245）
BANNER_GOLD_BGR = (90, 200, 245)
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

    def test_low_drive_gold_bar_is_counted_as_drive(self):
        # ADR-065: 2本以下で残りのバーが金色（低ドライブ警告）になっても、それは残っているドライブ
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        frame[y1:y2, x1:x2] = GOLD_BGR
        assert analyzer._measure_drive(frame, "player1") == pytest.approx(6.0, abs=0.05)

    def test_two_gold_cells_are_two_bars(self):
        # ゴールド（低ドライブ警告） 2 セルだけ = 2 本（バーンアウトではない）
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        cell = (x2 - x1) // 6
        frame[y1:y2, x1 + cell * 4 : x2] = GOLD_BGR
        assert analyzer._measure_drive(frame, "player1") == pytest.approx(2.0, abs=0.2)


class TestDriveRecoverMeasurement:
    """バーンアウト中の白/銀回復バーの計測（ADR-065）"""

    def _analyzer(self, frame: np.ndarray) -> GaugeAnalyzer:
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        analyzer._prepare_geometry(frame)
        return analyzer

    def test_center_side_bar_is_measured(self):
        # 1P は右端（画面中央側）、2P は左端から回復バーが伸びる
        for side, half in (("player1", "right"), ("player2", "left")):
            frame = make_frame()
            analyzer = self._analyzer(frame)
            x1, y1, x2, y2 = make_params().drive_roi[side]
            middle = (x1 + x2) // 2
            if half == "right":
                frame[y1:y2, middle:x2] = WHITE_BGR
            else:
                frame[y1:y2, x1:middle] = WHITE_BGR
            assert analyzer._measure_drive_recover(frame, side) == pytest.approx(0.5, abs=0.03)

    def test_outer_side_white_is_not_counted(self):
        # 中央側から連続していない白は回復バーではない（1P の左半分）
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        middle = (x1 + x2) // 2
        frame[y1:y2, x1:middle] = WHITE_BGR
        assert analyzer._measure_drive_recover(frame, "player1") is None

    def test_normal_gauge_is_not_recover_bar(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        frame[y1:y2, x1:x2] = NORMAL_BGR
        assert analyzer._measure_drive_recover(frame, "player1") is None

    def test_gold_low_drive_bar_is_not_recover_bar(self):
        # 低ドライブ警告の金色バーは白/銀ではない（H≈20, S≈255）
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        frame[y1:y2, x1:x2] = GOLD_BGR
        assert analyzer._measure_drive_recover(frame, "player1") is None

    def test_empty_track_is_not_recover_bar(self):
        # 空きトラックは暗い青（V≈15）で白ではない
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        frame[y1:y2, x1:x2] = EMPTY_TRACK_BGR
        assert analyzer._measure_drive_recover(frame, "player1") is None

    def test_gauge_frame_white_is_ignored(self):
        # ゲージ上下の白い枠線だけでは回復バーと判定しない（内側の行だけを見る）
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        frame[y1 : y1 + 3, x1:x2] = WHITE_BGR
        frame[y2 - 3 : y2, x1:x2] = WHITE_BGR
        assert analyzer._measure_drive_recover(frame, "player1") is None

    def test_thin_bar_is_ignored(self):
        # 最小幅（デフォルト 3%）未満の白は回復バーと判定しない
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().drive_roi["player1"]
        width = x2 - x1
        frame[y1:y2, x2 - int(width * 0.01) : x2] = WHITE_BGR
        assert analyzer._measure_drive_recover(frame, "player1") is None


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
    def _paste_banner(self, analyzer, frame, name: str) -> None:
        spec = next(b for b in make_params().round_banners if b.name == name)
        template = cv2.imread(str(APP_ROOT / spec.template))
        assert template is not None
        x1, y1, x2, y2 = spec.search_region
        # 探索領域の中央にテンプレートを貼り付ける
        top = y1 + (y2 - y1 - template.shape[0]) // 2
        left = x1 + (x2 - x1 - template.shape[1]) // 2
        frame[top : top + template.shape[0], left : left + template.shape[1]] = template

    def test_detects_round_template_in_search_region(self):
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        frame = make_frame()
        analyzer._prepare_geometry(frame)
        self._paste_banner(analyzer, frame, "round")

        assert analyzer._detect_round_banner(frame, 21.0) is True
        # 直後のフレームは多重検出しない（検出済み時刻を登録してから確認）
        analyzer.round_banner_times.append(21.0)
        assert analyzer._detect_round_banner(frame, 21.25) is False
        analyzer.round_banner_times.clear()
        assert analyzer._detect_round_banner(frame, 30.0) is True

    def test_detects_final_round_template(self):
        """FINAL ROUND は「ROUND」とは別テンプレートで検出する（ADR-052）"""
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        frame = make_frame()
        analyzer._prepare_geometry(frame)
        self._paste_banner(analyzer, frame, "final_round")
        assert analyzer._detect_round_banner(frame, 100.0) is True

    def test_returns_false_without_banner(self):
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        frame = make_frame()
        analyzer._prepare_geometry(frame)
        assert analyzer._detect_round_banner(frame, 50.0) is False


class TestKoColorMaskDetection:
    """K.O. 文字の白/銀マスク照合（ADR-063）"""

    def _prepare(self) -> tuple[GaugeAnalyzer, np.ndarray]:
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        frame = make_frame()
        analyzer._prepare_geometry(frame)
        # エッジテンプレート経路を無効化し、色マスク経路だけを検証する
        analyzer._ko_banner_prepared = []
        return analyzer, frame

    @staticmethod
    def _paste_ko(frame: np.ndarray) -> None:
        template = cv2.imread(str(APP_ROOT / "template/gauge/ko_banner.png"))
        assert template is not None
        frame[360 : 360 + template.shape[0], 640 : 640 + template.shape[1]] = template

    def test_config_enables_color_mask(self):
        params = make_params()
        assert params.ko_color_mask.enabled is True
        assert params.ko_color_mask.min_consecutive >= 2

    def test_validate_rejects_bad_threshold(self):
        params = make_params()
        params.ko_color_mask.threshold = 0.0
        with pytest.raises(ValueError):
            params._validate()

    def test_color_score_high_for_ko_frame(self):
        analyzer, frame = self._prepare()
        self._paste_ko(frame)
        assert analyzer._ko_color_score(frame) >= 0.9

    def test_color_score_zero_for_empty_frame(self):
        analyzer, frame = self._prepare()
        assert analyzer._ko_color_score(frame) == 0.0

    def test_requires_consecutive_detections(self):
        analyzer, frame = self._prepare()
        self._paste_ko(frame)
        # 1回目は確定しない
        assert analyzer._detect_ko(frame, 10.0) is None
        # 2回連続で、最初に閾値を超えた時刻を返す
        assert analyzer._detect_ko(frame, 10.25) == 10.0

    def test_streak_resets_on_miss(self):
        analyzer, frame = self._prepare()
        self._paste_ko(frame)
        assert analyzer._detect_ko(frame, 10.0) is None
        assert analyzer._detect_ko(make_frame(), 10.25) is None
        # リセット後は再び2回連続が必要
        assert analyzer._detect_ko(frame, 10.5) is None
        assert analyzer._detect_ko(frame, 10.75) == 10.5

    def test_edge_template_detects_immediately(self):
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        frame = make_frame()
        analyzer._prepare_geometry(frame)
        self._paste_ko(frame)
        assert analyzer._detect_ko(frame, 20.0) == 20.0
        # 直近3秒以内の多重検出は抑制する
        analyzer.ko_times.append(20.0)
        assert analyzer._detect_ko(frame, 20.5) is None


class TestBurnoutBannerDetection:
    """バーンアウト開始の EMPTY 文字（金色マスク照合）の検証（ADR-066）"""

    def _analyzer(self, frame: np.ndarray) -> GaugeAnalyzer:
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        analyzer._prepare_geometry(frame)
        return analyzer

    def _draw_template(self, frame: np.ndarray, side: str, template_name: str) -> None:
        mask = cv2.imread(str(APP_ROOT / "template" / template_name), cv2.IMREAD_GRAYSCALE)
        x1, y1, _, _ = make_params().burnout_banner.search_region[side]
        region = frame[y1 : y1 + mask.shape[0], x1 : x1 + mask.shape[1]]
        region[mask > 127] = BANNER_GOLD_BGR

    def test_detects_empty_banner_after_two_frames(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        self._draw_template(frame, "player1", "burnout_empty_player1.png")
        analyzer._detect_burnout_banner(frame, "player1", 1.0)
        assert analyzer.burnout_banner_times["player1"] == []
        analyzer._detect_burnout_banner(frame, "player1", 1.1)
        assert analyzer.burnout_banner_times["player1"] == [pytest.approx(1.0)]

    def test_player2_template_is_used(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        self._draw_template(frame, "player2", "burnout_empty_player2.png")
        analyzer._detect_burnout_banner(frame, "player2", 1.0)
        analyzer._detect_burnout_banner(frame, "player2", 1.1)
        assert analyzer.burnout_banner_times["player2"] == [pytest.approx(1.0)]

    def test_gold_block_is_not_detected(self):
        # 低ドライブ警告の金色バーや金色の演出は precision が低いため検出しない
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().burnout_banner.search_region["player1"]
        frame[y1:y2, x1:x2] = BANNER_GOLD_BGR
        for step in range(3):
            analyzer._detect_burnout_banner(frame, "player1", 1.0 + step * 0.1)
        assert analyzer.burnout_banner_times["player1"] == []

    def test_effective_times_ignore_same_time_other_side(self):
        # 両サイドでほぼ同時に検出された場合は全画面演出として除外する
        frame = make_frame()
        analyzer = self._analyzer(frame)
        analyzer.burnout_banner_times["player1"] = [10.0, 30.0]
        analyzer.burnout_banner_times["player2"] = [10.2]
        assert analyzer._effective_burnout_banner_times("player1") == [pytest.approx(30.0)]


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

    def test_suppress_transient_reverts_removes_multi_sample_dip(self):
        # 2サンプル（0.2秒）だけ 1→0→1 と戻る下振れは検出ノイズとして除去する
        values = [1.0] * 5 + [0.0, 0.0] + [1.0] * 5
        timestamps = [i * 0.1 for i in range(len(values))]
        assert _suppress_transient_reverts(values, timestamps, max_revert_sec=1.0) == [1.0] * 12

    def test_suppress_transient_reverts_keeps_real_decrease(self):
        # 本当にスーパーアーツを使って減少したストックは戻らないので残す
        values = [3.0] * 5 + [2.0] * 5
        timestamps = [i * 0.1 for i in range(len(values))]
        assert _suppress_transient_reverts(values, timestamps, max_revert_sec=1.0) == values

    def test_suppress_transient_reverts_keeps_slow_recovery(self):
        # 復帰まで 1.0 秒を超える場合は本当にゲージを使った後の再獲得とみなして残す
        values = [1.0, 0.0, 0.0, 1.0]
        timestamps = [0.0, 1.0, 2.0, 3.0]
        assert _suppress_transient_reverts(values, timestamps, max_revert_sec=1.0) == values

    def test_suppress_transient_reverts_handles_dip_after_real_drop(self):
        # 3→1 の本当の減少の直後に起きる 1→0→1 の下振れも除去する
        # （直前値 3 への復帰だけを待つと内側の 1↔0 を取り逃すため）
        values = [3.0, 3.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        timestamps = [i * 0.1 for i in range(len(values))]
        result = _suppress_transient_reverts(values, timestamps, max_revert_sec=1.0)
        assert result == [3.0, 3.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

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

    def _analyzer_with_samples(
        self,
        states: list[tuple[float, float | None, bool, int | None]],
        recover_raws: list[float | None] | None = None,
        banner_times: list[float] | None = None,
    ) -> GaugeAnalyzer:
        """サンプル列から GaugeAnalyzer を構築して派生状態を計算する。

        `recover_raws` を省略した場合は「HUD 表示中に黄緑が無い」サンプルで
        白/銀の回復バーが観測されたものとして扱う（ADR-065 のバーンアウト判定条件）。
        `banner_times` は EMPTY 文字（ADR-066）の検出時刻として与える。
        """
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        if banner_times:
            analyzer.burnout_banner_times["player1"] = list(banner_times)
        for index, (timestamp, drive_raw, hud_visible, sa_stock) in enumerate(states):
            if recover_raws is None:
                drive_recover_raw = 0.3 if (hud_visible and drive_raw is None) else None
            else:
                drive_recover_raw = recover_raws[index]
            analyzer.samples.append(
                GaugeSample(
                    timestamp=timestamp,
                    states={
                        "player1": SideGaugeState(
                            hud_visible=hud_visible,
                            drive_raw=drive_raw,
                            drive_recover_raw=drive_recover_raw,
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
        # 6秒分のサンプル: 前半は通常、後半は HUD 表示中に黄緑なし＋回復バーあり（バーンアウト）
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

    def test_drive_gap_without_recover_bar_is_not_burnout(self):
        # ADR-056 / ADR-065: HUD 表示中でも回復バーが観測されない黄緑の欠落はバーンアウトではない
        # （ラウンド開始直後のゲージ未表示や瞬間的な検出漏れを想定）
        states = [(i * 0.1, 5.0, True, 0) for i in range(20)]
        states += [(2.0 + i * 0.1, None, True, 0) for i in range(20)]
        analyzer = self._analyzer_with_samples(states, recover_raws=[None] * len(states))

        assert analyzer.burnout_periods["player1"] == []
        assert not any(s.states["player1"].drive_burnout for s in analyzer.samples)

    def test_low_drive_gold_bar_is_not_burnout(self):
        # ADR-065: ドライブ 1〜2 本の低ドライブ警告（金色バー）では黄緑が検出されないが、
        # 白/銀の回復バーが無いのでバーンアウトではない
        states = [(i * 0.1, 5.0, True, 0) for i in range(10)]
        states += [(1.0 + i * 0.1, None, True, 0) for i in range(30)]
        analyzer = self._analyzer_with_samples(states, recover_raws=[None] * len(states))

        assert analyzer.burnout_periods["player1"] == []
        assert not any(s.states["player1"].drive_burnout for s in analyzer.samples)

    def test_recover_bar_without_drive_gap_is_burnout(self):
        # ADR-065: 黄緑の有無にかかわらず、白/銀の回復バーが連続する区間をバーンアウトとする
        states = [(i * 0.1, 5.0, True, 0) for i in range(10)]
        states += [(1.0 + i * 0.1, None, True, 0) for i in range(20)]
        recover = [None] * 10 + [0.2] * 20
        analyzer = self._analyzer_with_samples(states, recover_raws=recover)

        assert len(analyzer.burnout_periods["player1"]) == 1
        assert analyzer.burnout_periods["player1"][0][0] == pytest.approx(1.0, abs=0.11)

    def test_white_flash_over_full_gauge_is_not_burnout(self):
        # 演出の白フラッシュがゲージ全体を覆った場合は、黄緑が観測されているため候補にならない
        states = [(i * 0.1, 5.6, True, 0) for i in range(10)]
        states += [(1.0 + i * 0.1, 5.6, True, 0) for i in range(20)]
        recover = [None] * 10 + [0.8] * 20
        analyzer = self._analyzer_with_samples(states, recover_raws=recover)

        assert analyzer.burnout_periods["player1"] == []
        assert not any(s.states["player1"].drive_burnout for s in analyzer.samples)

    def test_single_white_blip_is_not_burnout(self):
        # ADR-065: ヒット演出による単発の白（回復バーが連続しない）はバーンアウトではない
        states = [(i * 0.1, None, True, 0) for i in range(40)]
        recover = [None] * 10 + [0.1] + [None] * 6 + [0.1] + [None] * 22
        analyzer = self._analyzer_with_samples(states, recover_raws=recover)

        assert analyzer.burnout_periods["player1"] == []

    def test_short_gauge_gap_with_white_is_not_burnout(self):
        # ADR-065: 黄緑が 1 サンプル途切れただけ（ゲージの検出揺れ）はバーンアウトではない
        states = [(i * 0.1, 5.0, True, 0) for i in range(10)]
        states += [(1.0, None, True, 0), (1.1, None, True, 0)]
        states += [(1.2 + i * 0.1, 5.0, True, 0) for i in range(10)]
        recover = [None] * 10 + [0.4, 0.4] + [None] * 10
        analyzer = self._analyzer_with_samples(states, recover_raws=recover)

        assert analyzer.burnout_periods["player1"] == []

    def test_burnout_flash_with_empty_banner_is_burnout(self):
        # 開始時の白フラッシュ＋EMPTY 文字（ADR-066）で確定する
        states = [(i * 0.1, None, True, 0) for i in range(30)]
        recover = [None] * 15 + [0.6] + [None] * 14
        analyzer = self._analyzer_with_samples(states, recover_raws=recover, banner_times=[1.5])

        assert len(analyzer.burnout_periods["player1"]) == 1
        # 開始はフラッシュの時刻（低ドライブ警告の金色バー区間を含めない）
        assert analyzer.burnout_periods["player1"][0][0] == pytest.approx(1.5, abs=0.11)

    def test_flash_without_empty_banner_is_not_burnout(self):
        # ADR-066: 単発の白フラッシュ（ヒット演出など）は EMPTY 文字が無ければ確定しない
        states = [(i * 0.1, None, True, 0) for i in range(30)]
        recover = [None] * 15 + [0.6] + [None] * 14
        analyzer = self._analyzer_with_samples(states, recover_raws=recover)

        assert analyzer.burnout_periods["player1"] == []

    def test_persistent_recover_bar_without_banner_is_burnout(self):
        # 回復バーが連続して観測されれば EMPTY 文字なしでも確定する（バー本体の検出）
        states = [(i * 0.1, None, True, 0) for i in range(30)]
        recover = [None] * 10 + [0.3] * 20
        analyzer = self._analyzer_with_samples(states, recover_raws=recover)

        assert len(analyzer.burnout_periods["player1"]) == 1

    def test_same_time_banner_on_both_sides_is_ignored(self):
        # ADR-066: 両サイド同時の検出は全画面の金色演出なのでバーンアウトの確証にしない
        states = [(i * 0.1, None, True, 0) for i in range(30)]
        recover = [None] * 15 + [0.6] + [None] * 14
        analyzer = self._analyzer_with_samples(states, recover_raws=recover)
        analyzer.burnout_banner_times["player1"] = [1.5]
        analyzer.burnout_banner_times["player2"] = [1.6]
        analyzer._derived = False
        analyzer._derive_states()

        assert analyzer.burnout_periods["player1"] == []

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

    def test_sa_dip_and_immediate_revert_is_removed(self):
        # SA ゲージは一時的に減って即座に戻ることはないため、下振れは誤検出として除去する
        states = []
        for i in range(10):
            states.append((i * 0.1, 5.0, True, 1))
        states.append((1.0, 5.0, True, 0))
        states.append((1.1, 5.0, True, 0))
        for i in range(12, 20):
            states.append((i * 0.1, 5.0, True, 1))
        analyzer = self._analyzer_with_samples(states)
        assert all(s.states["player1"].sa_stock == 1 for s in analyzer.samples)


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
# ADR-061: 低体力（概ね25%以下）の現在体力は「明るい黄色」で描画される
BRIGHT_YELLOW_BGR = (98, 231, 249)  # H≈26 S≈155 V≈249
# コンボダメージ／回復可能ダメージは「暗い黄〜オリーブ」で描画される
DARK_YELLOW_BGR = (35, 118, 133)  # H≈25 S≈189 V≈133
# ADR-062: A.K.I. の毒状態では現在体力バーが紫に変わる
POISON_PURPLE_BGR = (176, 82, 146)  # H≈140 S≈136 V≈176


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

    def test_dark_yellow_is_not_counted(self):
        # ADR-050 決定1 / ADR-061: 暗い黄（コンボ／回復可能）は現在体力に含めない
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        frame[y1:y2, x1:x2] = DARK_YELLOW_BGR
        assert analyzer._measure_health(frame, "player1") is None

    def test_low_health_bright_yellow_is_current_health(self):
        # ADR-061: 低体力時（概ね25%以下）はバーが明るい黄色に変わるため現在体力として計測する
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        frame[y1:y2, x1:x2] = BRIGHT_YELLOW_BGR
        assert analyzer._measure_health(frame, "player1") == pytest.approx(100.0, abs=0.5)

    def test_half_low_health_bright_yellow_is_50_percent(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        middle = (x1 + x2) // 2
        frame[y1:y2, middle:x2] = BRIGHT_YELLOW_BGR
        scale = make_params().health_fill_scale["player1"]
        assert analyzer._measure_health(frame, "player1") == pytest.approx(50.0 * scale, abs=1.0)

    def test_poison_purple_is_current_health(self):
        # ADR-062: A.K.I. の毒でバーが紫に変わっても現在体力として計測する
        frame = make_frame()
        analyzer = self._analyzer(frame)
        for _side, roi_key in (("player1", "player1"), ("player2", "player2")):
            x1, y1, x2, y2 = make_params().health_roi[roi_key]
            frame[y1:y2, x1:x2] = POISON_PURPLE_BGR
        assert analyzer._measure_health(frame, "player1") == pytest.approx(100.0, abs=0.5)
        assert analyzer._measure_health(frame, "player2") == pytest.approx(100.0, abs=0.5)

    def test_half_poison_purple_is_50_percent(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        middle = (x1 + x2) // 2
        frame[y1:y2, middle:x2] = POISON_PURPLE_BGR
        scale = make_params().health_fill_scale["player1"]
        assert analyzer._measure_health(frame, "player1") == pytest.approx(50.0 * scale, abs=1.0)

    def test_poison_purple_is_excluded_when_not_poison_match(self):
        # ADR-062: A.K.I. を含まない試合では毒の紫を現在体力に含めない
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        frame[y1:y2, x1:x2] = POISON_PURPLE_BGR
        assert analyzer._measure_health(frame, "player1", include_poison=False) is None

    def test_recoverable_yellow_is_measured_separately(self):
        # ADR-054 / ADR-061: 暗い黄（コンボ／回復可能）を別系列として計測する
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        frame[y1:y2, x1:x2] = DARK_YELLOW_BGR
        assert analyzer._measure_health_recoverable(frame, "player1") == pytest.approx(100.0, abs=0.5)
        # 暗い黄は現在体力には含まれない
        assert analyzer._measure_health(frame, "player1") is None

    def test_bright_low_health_yellow_is_recoverable_side(self):
        # ADR-061: `healthRecoverable`（ADR-054/058）の判定は今回変更しない。
        # 低体力の明るい黄もこの色域に含まれるため、別系列として引き続き計測される。
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        frame[y1:y2, x1:x2] = BRIGHT_YELLOW_BGR
        assert analyzer._measure_health_recoverable(frame, "player1") == pytest.approx(100.0, abs=0.5)
        # 現在体力としても計測される（ADR-061）
        assert analyzer._measure_health(frame, "player1") == pytest.approx(100.0, abs=0.5)

    def test_half_recoverable_is_50_percent(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        # 外側（左）半分を回復可能（暗い黄）、内側（右）半分を現在体力（マゼンタ）にする
        middle = (x1 + x2) // 2
        frame[y1:y2, x1:middle] = DARK_YELLOW_BGR
        frame[y1:y2, middle:x2] = MAGENTA_BGR
        assert analyzer._measure_health_recoverable(frame, "player1") == pytest.approx(50.0, abs=1.5)
        scale = make_params().health_fill_scale["player1"]
        assert analyzer._measure_health(frame, "player1") == pytest.approx(50.0 * scale, abs=1.5)

    def test_current_health_is_not_recoverable(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        x1, y1, x2, y2 = make_params().health_roi["player1"]
        frame[y1:y2, x1:x2] = MAGENTA_BGR
        assert analyzer._measure_health_recoverable(frame, "player1") is None

    def test_empty_health_returns_none(self):
        frame = make_frame()
        analyzer = self._analyzer(frame)
        assert analyzer._measure_health(frame, "player1") is None


class TestPoisonCharacter:
    def test_is_poison_character(self):
        assert _is_poison_character("A.K.I.")
        assert _is_poison_character("AKI")
        assert _is_poison_character("aki")
        assert not _is_poison_character("JP")
        assert not _is_poison_character(None)
        assert not _is_poison_character("")


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
        assert p1["healthEnd"] == 0.0
        # ADR-051: 100% -> 40% の 60% が最大被弾
        assert p1["maxHitTaken"] == 60.0

        p2 = rows[1]
        assert p2["healthEnd"] is None
        assert p2["maxHitTaken"] is None


class TestImprovementRoundStats:
    """ADR-051 の改善指標（勝敗・勝利方法・バーンアウト・SA 使い残し）"""

    def _gauge_result(self):
        return {
            "matches": {
                "vid_100": {
                    "matchId": "vid_100",
                    "rounds": [
                        {
                            "round": 1,
                            "roundStartTime": 100.0,
                            "roundEndTime": 150.0,
                            "player1": {
                                "visibleFrom": 1.0,
                                "visibleTo": 49.0,
                                "coverage": 0.9,
                                "health": [[1.0, 100.0], [10.0, 30.0]],
                                "drive": [[1.0, 6.0], [5.0, 0.0]],
                                "sa": [[1.0, 0], [20.0, 1], [30.0, 2]],
                                "driveBurnout": [[5.0, 12.5], [30.0, 33.0]],
                                "saCriticalArt": [],
                                "saProgress": [],
                            },
                            "player2": {
                                "visibleFrom": 1.0,
                                "visibleTo": 49.0,
                                "coverage": 0.9,
                                "health": [[1.0, 100.0], [45.0, 5.0]],
                                "drive": [[1.0, 6.0]],
                                "sa": [[1.0, 0], [40.0, 1]],
                                "driveBurnout": [],
                                "saCriticalArt": [],
                                "saProgress": [],
                            },
                        }
                    ],
                }
            }
        }

    def test_win_loss_method_and_derived_metrics(self):
        matches = [
            {"id": "vid_100", "videoId": "vid", "player1": {"character": "GOUKI"}, "player2": {"character": "RYU"}}
        ]
        # 1P が CA（7）で勝利したラウンド
        round_results = {"vid_100": {"player1": [7], "player2": [0]}}

        rows = build_round_stats_rows(self._gauge_result(), matches, round_results_by_match=round_results)
        p1, p2 = rows[0], rows[1]

        assert p1["roundResult"] == "win"
        assert p2["roundResult"] == "loss"
        assert p1["roundMethod"] == "CA"
        assert p2["roundMethod"] == "CA"  # 勝者の方法を両サイドに持たせる

        assert p1["maxHitTaken"] == 70.0
        assert p2["maxHitTaken"] == 95.0
        assert p1["burnoutCount"] == 2
        assert p1["burnoutSec"] == 10.5
        assert p1["saLeftAtEnd"] == 2
        assert p2["saLeftAtEnd"] == 1

    def test_draw_and_unmeasured(self):
        matches = [
            {"id": "vid_100", "videoId": "vid", "player1": {"character": "GOUKI"}, "player2": {"character": "RYU"}}
        ]
        round_results = {"vid_100": {"player1": [4], "player2": [4]}}

        rows = build_round_stats_rows(self._gauge_result(), matches, round_results_by_match=round_results)
        assert rows[0]["roundResult"] == "draw"
        assert rows[0]["roundMethod"] is None

        # round_results が無い場合は勝敗不明（null）
        rows_unknown = build_round_stats_rows(self._gauge_result(), matches)
        assert rows_unknown[0]["roundResult"] is None
        assert rows_unknown[0]["roundMethod"] is None

    def test_ko_loser_health_is_clamped_to_zero(self):
        """K.O. 札着の敗者は残体力 0%（Time Up は補正しない）（ADR-051）"""
        matches = [
            {"id": "vid_100", "videoId": "vid", "player1": {"character": "GOUKI"}, "player2": {"character": "RYU"}}
        ]
        gauge = self._gauge_result()

        # 1P が K.O. で敗北（method V）→ p1 の残体力は 0、p2 は計測値のまま
        rows = build_round_stats_rows(
            gauge, matches, round_results_by_match={"vid_100": {"player1": [0], "player2": [1]}}
        )
        p1 = next(r for r in rows if r["side"] == "player1")
        p2 = next(r for r in rows if r["side"] == "player2")
        assert p1["healthEnd"] == 0.0
        assert p2["healthEnd"] == 5.0

        # Time Up（method T）で敗北 → 補正しない（計測値のまま）
        rows_timeup = build_round_stats_rows(
            gauge, matches, round_results_by_match={"vid_100": {"player1": [0], "player2": [3]}}
        )
        p1_timeup = next(r for r in rows_timeup if r["side"] == "player1")
        assert p1_timeup["healthEnd"] == 30.0

    def test_perfect_winner_health_is_clamped_to_full(self):
        """パーフェクト勝利（method P）の勝者は残体力 100%（ADR-068）

        K.O. 後の勝利演出で HUD が消え、背景を現在体力色として誤読した値が
        最終値になることがあるため、Battlelog の勝利方法から補正する。
        """
        matches = [
            {"id": "vid_100", "videoId": "vid", "player1": {"character": "GOUKI"}, "player2": {"character": "RYU"}}
        ]
        gauge = self._gauge_result()

        # 1P がパーフェクト（8）で勝利 → p1 は 100%、敗者は 0%
        rows = build_round_stats_rows(
            gauge, matches, round_results_by_match={"vid_100": {"player1": [8], "player2": [0]}}
        )
        p1 = next(r for r in rows if r["side"] == "player1")
        p2 = next(r for r in rows if r["side"] == "player2")
        assert p1["roundMethod"] == "P"
        assert p1["healthEnd"] == 100.0
        assert p2["healthEnd"] == 0.0

        # パーフェクトでない勝利（V）は補正しない（計測値のまま）
        rows_v = build_round_stats_rows(
            gauge, matches, round_results_by_match={"vid_100": {"player1": [1], "player2": [0]}}
        )
        p1_v = next(r for r in rows_v if r["side"] == "player1")
        assert p1_v["healthEnd"] == 30.0

        # 引き分け（4）は勝敗が付かないため補正しない
        rows_draw = build_round_stats_rows(
            gauge, matches, round_results_by_match={"vid_100": {"player1": [4], "player2": [4]}}
        )
        assert rows_draw[0]["healthEnd"] == 30.0

    def test_burnout_is_null_without_drive_series(self):
        gauge_result = self._gauge_result()
        for side in ("player1", "player2"):
            gauge_result["matches"]["vid_100"]["rounds"][0][side]["drive"] = []
        gauge_result["matches"]["vid_100"]["rounds"][0]["player2"]["sa"] = []
        matches = [
            {"id": "vid_100", "videoId": "vid", "player1": {"character": "GOUKI"}, "player2": {"character": "RYU"}}
        ]

        rows = build_round_stats_rows(gauge_result, matches)
        assert rows[0]["burnoutCount"] is None
        assert rows[0]["burnoutSec"] is None
        assert rows[1]["saLeftAtEnd"] is None


class TestHealthRecoverableGating:
    """回復可能ダメージ（白ゲージ）による回復ゲート（ADR-054）"""

    def _payload(
        self,
        values: list[tuple[float, float | None, float | None]],
        character: str | None = None,
        sa_stock: list[int | None] | None = None,
    ) -> dict:
        analyzer = GaugeAnalyzer(make_params(), APP_ROOT)
        for index, (timestamp, health, recoverable) in enumerate(values):
            analyzer.samples.append(
                GaugeSample(
                    timestamp=timestamp,
                    states={
                        "player1": SideGaugeState(
                            hud_visible=True,
                            health=health,
                            health_recoverable=recoverable,
                            sa_stock=None if sa_stock is None else sa_stock[index],
                        ),
                        "player2": SideGaugeState(),
                    },
                )
            )
        window = RoundWindow(index=1, start_time=0.0, end_time=10.0, boundary_time=10.0, end_reason="match_end")
        return analyzer._side_round_payload(window, "player1", character)

    def test_increase_without_recoverable_is_suppressed(self):
        payload = self._payload(
            [(2.0, 99.0, 0.0), (2.5, 99.0, 0.0), (3.0, 60.0, 0.0), (3.5, 90.0, 0.0), (4.0, 90.0, 0.0)]
        )
        assert payload["health"] == [[2.0, 99.0], [3.0, 60.0]]

    def test_increase_backed_by_recoverable_is_allowed(self):
        payload = self._payload(
            [(2.0, 99.0, 0.0), (2.5, 99.0, 0.0), (3.0, 60.0, 30.0), (3.5, 62.5, 27.5), (4.0, 65.0, 25.0)]
        )
        assert payload["health"] == [[2.0, 99.0], [3.0, 60.0], [3.5, 62.5], [4.0, 65.0]]
        assert payload["healthRecoverable"] == [[2.0, 0.0], [3.0, 30.0], [3.5, 27.5], [4.0, 25.0]]

    def test_rate_cap_still_applies(self):
        # 回復可能分は十分あるが、5%/s のレート上限を超える増加は抑えられる
        payload = self._payload([(2.0, 99.0, 0.0), (2.5, 99.0, 0.0), (3.0, 50.0, 40.0), (3.5, 90.0, 30.0)])
        assert payload["health"] == [[2.0, 99.0], [3.0, 50.0], [3.5, 52.5]]

    def test_elena_sa2_allows_direct_heal(self):
        values = [(2.0, 99.0, 0.0), (2.5, 99.0, 0.0), (3.0, 50.0, 0.0), (3.5, 90.0, 0.0)]
        stocks = [3, 3, 3, 1]
        payload = self._payload(values, character="ELENA", sa_stock=stocks)
        assert payload["health"] == [[2.0, 99.0], [3.0, 50.0], [3.5, 90.0]]

        # エレナ以外は同じ入力でも回復として扱わない
        payload_other = self._payload(values, character="JP", sa_stock=stocks)
        assert payload_other["health"] == [[2.0, 99.0], [3.0, 50.0]]


class TestHealthDespike:
    def test_multi_sample_dip_is_removed(self):
        # 遮蔽・ヒット演出による 0.4 秒の低値は前値で塗り直す
        values = [(i * 0.1, 100.0, True) for i in range(5)]
        values += [(0.5 + i * 0.1, 20.0, True) for i in range(4)]
        values += [(0.9 + i * 0.1, 100.0, True) for i in range(8)]
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
        assert all(s.states["player1"].health == pytest.approx(100.0, abs=0.1) for s in analyzer.samples)


class TestPerfectKoTime:
    """パーフェクト勝利ラウンドの体力ベース K.O. 推定（ADR-068）"""

    def test_ko_time_from_loser_health(self):
        # 敗者（player2）の体力が 5% 以下になった最初の変化点を K.O. とする
        round_data = {
            "player1": {"health": [[1.0, 99.0], [2.0, 100.0]]},
            "player2": {"health": [[1.0, 100.0], [5.0, 40.0], [23.6, 2.4], [27.9, 0.0]]},
        }
        assert _perfect_ko_time(round_data) == pytest.approx(23.6)

    def test_no_drop_returns_none(self):
        round_data = {
            "player1": {"health": [[1.0, 100.0]]},
            "player2": {"health": [[1.0, 100.0], [20.0, 30.0]]},
        }
        assert _perfect_ko_time(round_data) is None

    def test_perfect_round_duration_is_trimmed(self):
        gauge_result = {
            "matches": {
                "vid_100": {
                    "matchId": "vid_100",
                    "rounds": [
                        {
                            "round": 1,
                            "roundStartTime": 100.0,
                            "roundEndTime": 130.0,
                            "player1": {
                                "visibleFrom": 1.0,
                                "visibleTo": 28.0,
                                "coverage": 0.4,
                                "health": [[1.0, 100.0]],
                                "drive": [],
                                "sa": [],
                                "driveBurnout": [],
                                "saCriticalArt": [],
                                "saProgress": [],
                            },
                            "player2": {
                                "visibleFrom": 1.0,
                                "visibleTo": 28.0,
                                "coverage": 0.4,
                                "health": [[1.0, 100.0], [22.0, 2.0]],
                                "drive": [],
                                "sa": [],
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

        # パーフェクト勝利 → K.O. 推定時刻（23.0 秒 = 22.0 + visibleFrom 1.0）まで切り詰める
        rows = build_round_stats_rows(
            gauge_result, matches, round_results_by_match={"vid_100": {"player1": [8], "player2": [0]}}
        )
        p1 = next(r for r in rows if r["side"] == "player1")
        assert p1["durationSec"] == pytest.approx(21.0)
        assert p1["roundEndTime"] == 122
        assert p1["healthEnd"] == 100.0

        # パーフェクトでない勝利 → 切り詰めない（計測値のまま）
        rows_v = build_round_stats_rows(
            gauge_result, matches, round_results_by_match={"vid_100": {"player1": [1], "player2": [0]}}
        )
        p1_v = next(r for r in rows_v if r["side"] == "player1")
        assert p1_v["durationSec"] == pytest.approx(27.0)
        assert p1_v["roundEndTime"] == 128
