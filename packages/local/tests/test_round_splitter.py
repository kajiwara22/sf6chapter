"""round_splitter のユニットテスト（ADR-048）"""

from src.detection.round_splitter import (
    MAX_ROUNDS,
    merge_banner_times,
    split_rounds,
)


class TestMergeBannerTimes:
    def test_merges_close_banners(self):
        assert merge_banner_times([21.0, 21.25, 21.5, 72.25, 72.5]) == [21.0, 72.25]

    def test_keeps_separated_banners(self):
        assert merge_banner_times([21.0, 72.25, 128.5]) == [21.0, 72.25, 128.5]

    def test_sorts_input(self):
        assert merge_banner_times([72.25, 21.0]) == [21.0, 72.25]

    def test_empty(self):
        assert merge_banner_times([]) == []


class TestSplitRounds:
    def test_two_rounds(self):
        windows = split_rounds(match_start=20.87, match_end=128.5, round_banner_times=[21.0, 72.25, 128.5])
        # 128.5 は次試合の開始と同時刻なので範囲外（< match_end）になる
        assert [w.index for w in windows] == [1, 2]
        assert windows[0].start_time == 21.0
        assert windows[0].boundary_time == 72.25
        assert windows[0].end_reason == "next_round"
        assert windows[1].start_time == 72.25
        assert windows[1].boundary_time == 128.5
        assert windows[1].end_reason == "match_end"

    def test_three_rounds_with_final(self):
        windows = split_rounds(match_start=100.0, match_end=260.0, round_banner_times=[100.2, 150.0, 200.0])
        assert [w.index for w in windows] == [1, 2, 3]
        assert windows[2].boundary_time == 260.0
        assert windows[2].end_reason == "match_end"

    def test_first_banner_lead_before_match_start(self):
        # 検出時刻よりバナーが少し手前にあるケースを許容する
        windows = split_rounds(match_start=21.5, match_end=80.0, round_banner_times=[21.0])
        assert len(windows) == 1
        assert windows[0].start_time == 21.0
        assert windows[0].banner_detected is True

    def test_no_banner_fallback(self):
        windows = split_rounds(match_start=20.87, match_end=100.0, round_banner_times=[])
        assert len(windows) == 1
        assert windows[0].start_time == 20.87
        assert windows[0].boundary_time == 100.0
        assert windows[0].banner_detected is False

    def test_late_first_banner_prepends_match_start(self):
        windows = split_rounds(match_start=20.87, match_end=200.0, round_banner_times=[40.0, 80.0])
        assert len(windows) == 3
        assert windows[0].start_time == 20.87
        assert windows[1].start_time == 40.0
        assert windows[2].start_time == 80.0

    def test_caps_at_max_rounds(self):
        windows = split_rounds(match_start=10.0, match_end=200.0, round_banner_times=[10.5, 50.0, 90.0, 130.0])
        assert len(windows) == MAX_ROUNDS

    def test_ignores_banners_outside_match(self):
        windows = split_rounds(match_start=100.0, match_end=200.0, round_banner_times=[20.0, 150.0, 300.0])
        assert len(windows) == 2
        assert windows[0].start_time == 100.0
        assert windows[1].start_time == 150.0

    def test_empty_match_range(self):
        windows = split_rounds(match_start=100.0, match_end=100.0, round_banner_times=[])
        assert len(windows) == 1
        assert windows[0].start_time == 100.0
        assert windows[0].boundary_time >= windows[0].start_time


class TestTrailingBanner:
    """次試合の ROUND 1 バナーを現在の試合に取り込まない"""

    def test_next_match_banner_is_excluded(self):
        # 次試合は 897.17 に検出され、そのバナーが 896.75 にある場合
        windows = split_rounds(match_start=772.5, match_end=897.17, round_banner_times=[772.5, 815.25, 896.75])
        assert [w.index for w in windows] == [1, 2]
        assert windows[-1].boundary_time == 897.17

    def test_final_round_banner_is_kept(self):
        # 3ラウンド制の最終ラウンド開始は試合終端より十分手前
        windows = split_rounds(match_start=100.0, match_end=300.0, round_banner_times=[100.2, 150.0, 200.0])
        assert [w.index for w in windows] == [1, 2, 3]
        assert windows[2].start_time == 200.0


class TestSyntheticRoundFlag:
    def test_prepended_round_is_flagged(self):
        # 第1ラウンドのバナーを取りこぼした場合、試合開始時刻を代用しつつ
        # banner_detected=False で「実測ではない」ことを示す
        windows = split_rounds(match_start=215.67, match_end=411.0, round_banner_times=[265.75])
        assert [w.index for w in windows] == [1, 2]
        # 試合開始時刻を代用したラウンドはバナー検出ではない
        assert windows[0].start_time == 215.67
        assert windows[0].banner_detected is False
        assert windows[1].start_time == 265.75
        assert windows[1].banner_detected is True
