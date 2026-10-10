"""カウンター・パニッシュカウンター回数計測のユニットテスト（ADR-049）"""

from pathlib import Path

import pytest

from src.detection.config import load_detection_params
from src.detection.counter import (
    COUNTER,
    PUNISH_COUNTER,
    CounterAnalysisParams,
    CounterAnalyzer,
    CounterSample,
    CounterThresholds,
    SideCounterScores,
    extract_occurrences,
)
from src.detection.gauge import build_round_stats_rows

APP_ROOT = Path(__file__).parent.parent
SIDES = ("player1", "player2")


def make_params() -> CounterAnalysisParams:
    """設定ファイルからカウンター計測パラメータを取得する"""
    params = load_detection_params(profile="production").counter_analysis
    assert params is not None
    return params


def make_sample(timestamp: float, **scores: float) -> CounterSample:
    """指定サイドのスコアだけを入れたサンプルを作る"""
    states = {side: SideCounterScores() for side in SIDES}
    for key, value in scores.items():
        side, field = key.split("__")
        setattr(states[side], field, value)
    return CounterSample(timestamp=timestamp, scores=states)


def make_series(
    start: float = 0.0,
    count: int = 20,
    step: float = 0.1,
    **scores: float,
) -> list[CounterSample]:
    """同一スコアが連続するサンプル列を作る"""
    return [make_sample(round(start + index * step, 2), **scores) for index in range(count)]


def make_scores(
    values: list[float],
    start: float = 0.0,
    step: float = 0.1,
    side: str = "player1",
    ctype: str = "punish_counter",
) -> list[CounterSample]:
    """サンプルごとのスコア列からサンプル列を作る（空白区間は低スコアで表現する）"""
    return [
        make_sample(round(start + index * step, 2), **{f"{side}__{ctype}": value}) for index, value in enumerate(values)
    ]


class TestParams:
    def test_load_from_config(self):
        params = make_params()
        assert params.enabled is True
        assert params.base_width == 1920
        assert params.thresholds.match_score == 0.7
        assert set(params.templates) == {COUNTER, PUNISH_COUNTER}
        for ctype in (COUNTER, PUNISH_COUNTER):
            assert set(params.templates[ctype]) == set(SIDES)

    def test_round_trip_to_dict(self):
        params = make_params()
        restored = CounterAnalysisParams.from_dict(params.to_dict())
        assert restored.roi == params.roi
        assert restored.thresholds.to_dict() == params.thresholds.to_dict()
        assert restored.templates == params.templates

    def test_validate_rejects_bad_roi(self):
        params = make_params()
        params.roi["player1"] = (100, 100, 50, 200)
        with pytest.raises(ValueError):
            params._validate()

    def test_validate_rejects_missing_template(self):
        params = make_params()
        del params.templates[COUNTER]["player1"]
        with pytest.raises(ValueError):
            params._validate()

    def test_validate_rejects_non_positive_interval(self):
        params = make_params()
        params.sample_interval_sec = 0
        with pytest.raises(ValueError):
            params._validate()


class TestExtractOccurrences:
    """スコア列 → ON 区間（カウンター1回分）の抽出"""

    thresholds = CounterThresholds(match_score=0.7, min_duration_sec=0.4, merge_gap_sec=0.25)

    def test_single_punish_counter(self):
        samples = make_series(count=20, player1__punish_counter=0.9)
        occurrences = extract_occurrences(samples, "player1", self.thresholds)
        assert len(occurrences) == 1
        assert occurrences[0].type == PUNISH_COUNTER
        assert occurrences[0].side == "player1"
        assert occurrences[0].start_time == 0.0
        assert occurrences[0].end_time == pytest.approx(1.9)
        assert occurrences[0].peak_score == pytest.approx(0.9)

    def test_single_counter(self):
        samples = make_series(count=20, player2__counter=0.85)
        occurrences = extract_occurrences(samples, "player2", self.thresholds)
        assert len(occurrences) == 1
        assert occurrences[0].type == COUNTER

    def test_other_side_is_not_counted(self):
        samples = make_series(count=20, player2__counter=0.9)
        assert extract_occurrences(samples, "player1", self.thresholds) == []

    def test_below_threshold_is_ignored(self):
        samples = make_series(count=20, player1__counter=0.69)
        assert extract_occurrences(samples, "player1", self.thresholds) == []

    def test_short_blip_is_ignored(self):
        # 0.2 秒しか続かない検出はノイズとして捨てる
        samples = make_series(count=3, player1__counter=0.9)
        assert extract_occurrences(samples, "player1", self.thresholds) == []

    def test_gap_below_merge_gap_is_merged(self):
        # 0.2 秒の空白は同一バナー（再トリガーの検出ゆらぎ）
        samples = make_scores([0.9] * 10 + [0.2] + [0.9] * 10)
        occurrences = extract_occurrences(samples, "player1", self.thresholds)
        assert len(occurrences) == 1

    def test_gap_above_merge_gap_is_separate(self):
        # 0.4 秒の空白は別のカウンター
        samples = make_scores([0.9] * 10 + [0.2] * 3 + [0.9] * 10)
        occurrences = extract_occurrences(samples, "player1", self.thresholds)
        assert len(occurrences) == 2
        assert occurrences[0].end_time < occurrences[1].start_time

    def test_type_switch_creates_two_occurrences(self):
        samples = make_scores([0.9] * 15, ctype="punish_counter")
        samples += make_scores([0.9] * 15, start=1.5, ctype="counter")
        occurrences = extract_occurrences(sorted(samples, key=lambda s: s.timestamp), "player1", self.thresholds)
        assert [occurrence.type for occurrence in occurrences] == [PUNISH_COUNTER, COUNTER]

    def test_both_above_threshold_prefers_higher_score(self):
        samples = [
            make_sample(round(index * 0.1, 2), player1__counter=0.8, player1__punish_counter=0.95)
            for index in range(15)
        ]
        occurrences = extract_occurrences(samples, "player1", self.thresholds)
        assert len(occurrences) == 1
        assert occurrences[0].type == PUNISH_COUNTER

    def test_both_above_threshold_prefers_counter_when_higher(self):
        samples = [
            make_sample(round(index * 0.1, 2), player1__counter=0.95, player1__punish_counter=0.8)
            for index in range(15)
        ]
        occurrences = extract_occurrences(samples, "player1", self.thresholds)
        assert len(occurrences) == 1
        assert occurrences[0].type == COUNTER

    def test_empty_samples(self):
        assert extract_occurrences([], "player1", self.thresholds) == []


class TestBuild:
    """マッチ・ラウンドへの割り当て"""

    def _analyzer(self) -> CounterAnalyzer:
        return CounterAnalyzer(make_params(), APP_ROOT)

    @staticmethod
    def _add_occurrence(analyzer: CounterAnalyzer, side: str, ctype: str, start: float, duration: float) -> None:
        """指定時刻から duration 秒ぶんの ON 区間をサンプル列に追加する"""
        step = analyzer.params.sample_interval_sec
        count = int(round(duration / step)) + 1
        for index in range(count):
            timestamp = round(start + index * step, 2)
            sample = next((s for s in analyzer.samples if s.timestamp == timestamp), None)
            if sample is None:
                sample = CounterSample(timestamp, {s: SideCounterScores() for s in SIDES})
                analyzer.samples.append(sample)
            setattr(sample.scores[side], ctype, 0.9)
        analyzer.samples.sort(key=lambda s: s.timestamp)

    def test_assigns_occurrences_to_rounds(self):
        analyzer = self._analyzer()
        self._add_occurrence(analyzer, "player1", PUNISH_COUNTER, 110.0, 1.5)
        self._add_occurrence(analyzer, "player1", COUNTER, 150.0, 1.5)
        self._add_occurrence(analyzer, "player2", COUNTER, 140.0, 1.5)

        result = analyzer.build(
            [("vid_100", 100.0), ("vid_200", 200.0)],
            round_banner_times=[100.0, 130.0],
            video_end=300.0,
        )

        rounds = result["matches"]["vid_100"]["rounds"]
        assert [item["round"] for item in rounds] == [1, 2]

        round1, round2 = rounds
        assert round1["player1"]["punishCounterCount"] == 1
        assert round1["player1"]["counterCount"] == 0
        assert round1["player2"]["counterCount"] == 0
        assert round2["player1"]["counterCount"] == 1
        assert round2["player2"]["counterCount"] == 1

        # 中間ファイル用の ON 区間も保持する
        assert round1["player1"]["occurrences"][0]["type"] == PUNISH_COUNTER
        assert round1["player1"]["occurrences"][0]["start"] == 110.0

    def test_match_without_banner_falls_back_to_single_round(self):
        analyzer = self._analyzer()
        self._add_occurrence(analyzer, "player2", COUNTER, 210.0, 1.5)

        result = analyzer.build([("vid_200", 200.0)], round_banner_times=[], video_end=300.0)
        rounds = result["matches"]["vid_200"]["rounds"]
        assert len(rounds) == 1
        assert rounds[0]["round"] == 1
        assert rounds[0]["bannerDetected"] is False
        assert rounds[0]["player2"]["counterCount"] == 1

    def test_occurrence_counts_only_once_at_boundary(self):
        """ラウンド境界をまたぐ ON 区間も、開始時刻のラウンドにだけ数える"""
        analyzer = self._analyzer()
        self._add_occurrence(analyzer, "player1", COUNTER, 129.5, 2.0)

        result = analyzer.build([("vid_100", 100.0)], round_banner_times=[100.0, 130.0], video_end=200.0)
        rounds = result["matches"]["vid_100"]["rounds"]
        assert rounds[0]["player1"]["counterCount"] == 1
        assert rounds[1]["player1"]["counterCount"] == 0

    def test_no_matches(self):
        analyzer = self._analyzer()
        result = analyzer.build([], video_end=10.0)
        assert result["matches"] == {}


class TestRoundStatsIntegration:
    """build_round_stats_rows へのカウンター列のマージ（ADR-049 決定7）"""

    @staticmethod
    def _gauge_result() -> dict:
        return {
            "matches": {
                "vid_100": {
                    "rounds": [
                        {
                            "round": 1,
                            "roundStartTime": 100.0,
                            "roundEndTime": 150.0,
                            "player1": {"visibleFrom": 0, "visibleTo": 48, "coverage": 0.9, "drive": [], "sa": []},
                            "player2": {"visibleFrom": 0, "visibleTo": 48, "coverage": 0.9, "drive": [], "sa": []},
                        }
                    ]
                }
            }
        }

    @staticmethod
    def _matches() -> list[dict]:
        return [
            {
                "id": "vid_100",
                "videoId": "vid",
                "player1": {"character": "JP"},
                "player2": {"character": "GOUKI"},
            }
        ]

    def test_counter_columns_are_merged(self):
        counter_result = {
            "matches": {
                "vid_100": {
                    "rounds": [
                        {
                            "round": 1,
                            "player1": {"counterCount": 2, "punishCounterCount": 1},
                            "player2": {"counterCount": 0, "punishCounterCount": 3},
                        }
                    ]
                }
            }
        }
        rows = build_round_stats_rows(self._gauge_result(), self._matches(), counter_result=counter_result)
        assert rows[0]["counterCount"] == 2
        assert rows[0]["punishCounterCount"] == 1
        assert rows[1]["counterCount"] == 0
        assert rows[1]["punishCounterCount"] == 3

    def test_counter_columns_are_none_when_not_measured(self):
        rows = build_round_stats_rows(self._gauge_result(), self._matches())
        assert rows[0]["counterCount"] is None
        assert rows[0]["punishCounterCount"] is None


class TestSaveCounterData:
    """main.SF6ChapterProcessor._save_counter_data の結合確認（R2無効時）"""

    @staticmethod
    def _analyzer_with_occurrence() -> CounterAnalyzer:
        analyzer = CounterAnalyzer(make_params(), APP_ROOT)
        TestBuild._add_occurrence(analyzer, "player1", PUNISH_COUNTER, 110.0, 1.5)
        return analyzer

    def test_writes_intermediate_files(self, tmp_path):
        from main import SF6ChapterProcessor

        analyzer = self._analyzer_with_occurrence()
        counter_result = analyzer.build([("vid_100", 100.0)], round_banner_times=[100.0], video_end=200.0)

        processor = object.__new__(SF6ChapterProcessor)
        processor.counter_analyzer = analyzer
        processor.counter_result = counter_result

        processor._save_counter_data("vid", tmp_path)

        assert (tmp_path / "counters" / "counters.json").exists()
        assert (tmp_path / "counters" / "counters_samples.csv").exists()
        assert (tmp_path / "counters" / "banners").is_dir()

    def test_no_counter_data_is_noop(self, tmp_path):
        from main import SF6ChapterProcessor

        processor = object.__new__(SF6ChapterProcessor)
        processor.counter_analyzer = None
        processor.counter_result = None

        processor._save_counter_data("vid", tmp_path)
        assert not (tmp_path / "counters").exists()
