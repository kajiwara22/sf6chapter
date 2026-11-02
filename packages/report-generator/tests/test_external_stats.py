"""バックラー統計との突合（ADR-072）のユニットテスト"""

from datetime import date

import pytest

from src.external_stats import (
    canonical_character_name,
    latest_published_month,
    league_rank_from_result,
    lookup_benchmark,
)
from src.formatter import _format_matchups
from src.query import MatchupRow


class TestCanonicalCharacterName:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("LUKE", "LUKE"),
            ("GOUKI", "AKUMA"),
            ("AKUMA", "AKUMA"),
            ("VEGA", "MBISON"),
            ("M. BISON", "MBISON"),
            ("A.K.I.", "AKI"),
            ("E.HONDA", "EHONDA"),
            ("DEE JAY", "DEEJAY"),
            ("CHUN-LI", "CHUNLI"),
            # Battlelog は日本語名を返す
            ("ルーク", "LUKE"),
            ("豪鬼", "AKUMA"),
            ("ベガ", "MBISON"),
            ("C.ヴァイパー", "CVIPER"),
            ("舞", "MAI"),
            ("不知火舞", "MAI"),
            ("エドモンド本田", "EHONDA"),
            ("エド", "ED"),
            ("アルジュン", "ARJUN"),
            ("春麗", "CHUNLI"),
        ],
    )
    def test_normalizes(self, name, expected):
        assert canonical_character_name(name) == expected


class TestLeagueRankFromResult:
    @pytest.mark.parametrize(
        ("lp", "mr", "expected"),
        [
            (0, 0, 1),
            (999, 0, 1),
            (1000, 0, 2),
            (2999, 0, 2),
            (3000, 0, 3),
            (8999, 0, 4),
            (9000, 0, 5),
            (12999, 0, 5),
            (13000, 0, 6),
            (19000, 0, 7),
            (24999, 0, 7),
            (25000, 0, 8),
            (None, 1500, 8),  # マスターは MR で判定
            (None, 0, None),
        ],
    )
    def test_maps_lp_to_rank(self, lp, mr, expected):
        assert league_rank_from_result(lp, mr) == expected


class TestLatestPublishedMonth:
    @pytest.mark.parametrize(
        ("today", "expected"),
        [
            (date(2026, 11, 2), "202609"),
            (date(2026, 11, 12), "202610"),
            (date(2027, 1, 5), "202611"),
        ],
    )
    def test_returns_month(self, today, expected):
        assert latest_published_month(today) == expected


class TestLookupBenchmark:
    def test_hits_alias_and_input_type(self):
        benchmarks = {("LUKE", "AKUMA", "Classic"): 46.7}
        assert lookup_benchmark(benchmarks, "LUKE", "AKUMA", "Classic") == 46.7
        # バックラー側の表記（GOUKI）でも同じキーに寄る
        assert lookup_benchmark(benchmarks, "LUKE", "GOUKI", "Classic") == 46.7
        assert lookup_benchmark(benchmarks, "LUKE", "AKUMA", "Modern") is None

    def test_matches_japanese_battlelog_name(self):
        """Battlelog の日本語名でもバックラーの英語名に寄る"""
        benchmarks = {("LUKE", "AKUMA", "Classic"): 46.7}
        assert lookup_benchmark(benchmarks, "ルーク", "豪鬼", "Classic") == 46.7


def _row(my_character: str, opponent: str, input_type: str, total: int, wins: int, benchmark=None) -> MatchupRow:
    return MatchupRow(
        my_character=my_character,
        opponent_character=opponent,
        opponent_input_type=input_type,
        total=total,
        wins=wins,
        losses=total - wins,
        benchmark_win_rate=benchmark,
    )


class TestFormatMatchupsWithBenchmark:
    def test_adds_benchmark_columns(self):
        matchups = [
            _row("LUKE", "AKUMA", "Classic", 2, 1, benchmark=46.7),
            _row("LUKE", "M. BISON", "Modern", 1, 1, benchmark=53.0),
        ]
        text = _format_matchups(matchups, "2025年8月・GOLD")

        assert "同ランク帯平均" in text
        assert "2025年8月・GOLD" in text
        assert "46.7%" in text
        assert "53.0%" in text
        # 自分 50.0% - 平均 46.7% = +3.3pt
        assert "+3.3pt" in text

    def test_keeps_legacy_columns_without_benchmark(self):
        matchups = [_row("LUKE", "AKUMA", "Classic", 2, 1)]
        text = _format_matchups(matchups)
        assert "同ランク帯平均" not in text
        assert "| 対戦キャラ | 試合数 | 勝利 | 敗北 | 勝率 | Classic勝率 |" in text

    def test_missing_benchmark_shows_dash(self):
        matchups = [
            _row("LUKE", "AKUMA", "Classic", 2, 1, benchmark=46.7),
            _row("LUKE", "LUKE", "Classic", 1, 0, benchmark=None),
        ]
        text = _format_matchups(matchups, "2025年8月・GOLD")
        mirror_line = next(line for line in text.splitlines() if line.startswith("| LUKE |"))
        assert mirror_line.count("-") >= 2
