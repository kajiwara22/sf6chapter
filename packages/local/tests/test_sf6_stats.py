"""バックラー統計 collector（ADR-072）のユニットテスト"""

from datetime import date

import pytest

from src.sf6_stats import parquet
from src.sf6_stats.buckler_client import (
    BucklerAPIError,
    fetch_usage_rates,
    format_data_month,
    latest_available_month,
    parse_data_month,
)


class TestLatestAvailableMonth:
    """第二木曜日の前後で最新公開月が切り替わる"""

    @pytest.mark.parametrize(
        ("today", "expected"),
        [
            # 2026-11 の第二木曜は 11/12
            (date(2026, 11, 2), (2026, 9)),
            (date(2026, 11, 11), (2026, 9)),
            (date(2026, 11, 12), (2026, 10)),
            (date(2026, 11, 30), (2026, 10)),
            # 年跨ぎ: 2027-01 の第二木曜は 1/14
            (date(2027, 1, 5), (2026, 11)),
        ],
    )
    def test_returns_latest_month(self, today, expected):
        assert latest_available_month(today) == expected

    def test_rejects_before_oldest_data(self):
        with pytest.raises(ValueError):
            latest_available_month(date(2023, 6, 1))


class TestDataMonth:
    def test_format_and_parse(self):
        assert format_data_month(2025, 8) == "202508"
        assert parse_data_month("202508") == (2025, 8)

    @pytest.mark.parametrize("value", ["2025-08", "2025081", "2025aa", "202513"])
    def test_rejects_invalid(self, value):
        with pytest.raises(ValueError):
            parse_data_month(value)

    def test_rejects_unsupported_locale(self):
        with pytest.raises(ValueError):
            fetch_usage_rates("202508", locale="fr")


class TestToFloat:
    @pytest.mark.parametrize("value", ["-", "-.---", "", None, "null", "abc"])
    def test_missing_values_become_none(self, value):
        assert parquet.to_float(value) is None

    def test_zero_is_kept(self):
        """相性スコア 0.0 は実値。None にしてはいけない"""
        assert parquet.to_float("0.000") == 0.0
        assert parquet.to_float(0) == 0.0

    def test_numeric_string(self):
        assert parquet.to_float("5.320") == pytest.approx(5.32)


def _usage_payload() -> dict:
    return {
        "usagerateData": [
            {
                "operation_type": 0,
                "val": [
                    {
                        "league_rank": 8,
                        "league_alpha": "MASTER",
                        "val": [
                            {
                                "character_alpha": "KEN",
                                "character_tool_name": "ken",
                                "play_rate": "6.5",
                                "previous_rate": "6.1",
                            },
                            {
                                "character_alpha": "RYU",
                                "character_tool_name": "ryu",
                                "play_rate": "-",
                                "previous_rate": "",
                            },
                        ],
                    }
                ],
            }
        ]
    }


def _matchup_payload() -> dict:
    return {
        "diaData": {
            "ci": {
                "ci_sort": {
                    "5": {
                        "opponent_header": [
                            {"id": 1, "name_alpha": "RYU", "tool_name": "ryu", "input_type": "C"},
                            {"id": 1, "name_alpha": "RYU", "tool_name": "ryu", "input_type": "M"},
                            {"id": 2, "name_alpha": "KEN", "tool_name": "ken", "input_type": "C"},
                        ],
                        "records": [
                            {
                                "id": 1,
                                "name_alpha": "RYU",
                                "tool_name": "ryu",
                                "input_type": "C",
                                "total": "4.900",
                                "_win_rate": 0.49,
                                "values": [
                                    {"_oid": 1, "_dsort": 0.49, "sf": 0, "thm": 0, "val": "-"},
                                    {"_oid": 1, "_dsort": 0.47, "sf": 0, "thm": 0, "val": "-.---"},
                                    {"_oid": 2, "_dsort": 0.52, "sf": 1, "thm": 1, "val": "0.000"},
                                ],
                            }
                        ],
                    }
                }
            }
        }
    }


class TestUsageRows:
    def test_flattens_operations_and_leagues(self):
        rows = parquet.usage_rows(_usage_payload(), "202508", "ja-jp")
        assert len(rows) == 2
        assert rows[0]["league_name"] == "MASTER"
        assert rows[0]["play_rate"] == pytest.approx(6.5)
        assert rows[1]["play_rate"] is None
        assert rows[1]["previous_rate"] is None

    def test_rejects_invalid_payload(self):
        with pytest.raises(ValueError):
            parquet.usage_rows({}, "202508", "ja-jp")


class TestMatchupRows:
    def test_splits_stats_and_details(self):
        stats, details = parquet.matchup_rows(_matchup_payload(), "202508")
        assert len(stats) == 1
        assert len(details) == 3
        # stats の勝率は records[]._win_rate
        assert stats[0]["win_rate"] == pytest.approx(0.49)
        assert stats[0]["total_score"] == pytest.approx(4.9)
        assert stats[0]["rank_name"] == "GOLD"

    def test_opponent_input_type_is_not_collapsed(self):
        """opponent_header は同じ id を C/M で2回持つ。index 対応で潰さずに取る"""
        _, details = parquet.matchup_rows(_matchup_payload(), "202508")
        assert [row["opponent_input_type"] for row in details] == ["C", "M", "C"]

    def test_score_keeps_zero_and_drops_missing(self):
        _, details = parquet.matchup_rows(_matchup_payload(), "202508")
        assert details[0]["score"] is None  # ミラー "-"
        assert details[1]["score"] is None  # サンプル不足 "-.---"
        assert details[2]["score"] == 0.0  # 実値 0 点

    def test_mirror_detection(self):
        _, details = parquet.matchup_rows(_matchup_payload(), "202508")
        assert [parquet.is_mirror(row) for row in details] == [True, True, False]

    def test_rejects_invalid_payload(self):
        with pytest.raises(ValueError):
            parquet.matchup_rows({}, "202508")


class TestBucklerClientErrors:
    def test_error_is_runtime_error(self):
        assert issubclass(BucklerAPIError, RuntimeError)
