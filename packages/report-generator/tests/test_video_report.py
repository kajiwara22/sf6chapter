"""動画単位のレポート集計（ADR-072 #6）のユニットテスト"""

import duckdb
import pytest

from src.video_report import (
    query_video_date_range,
    query_video_lp_history,
    query_video_matchups,
    query_video_summary,
)

PLAYER_ID = "1319673732"


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE battlelog_replays AS
        SELECT * FROM (VALUES
            ('r1', 1319673732, 111, 'LUKE', 'AKUMA',    0, 0, 'win',  TIMESTAMP '2026-02-05 12:00:00', 1, 10100, 0, 0, 0),
            ('r2', 1319673732, 222, 'LUKE', 'AKUMA',    0, 0, 'loss', TIMESTAMP '2026-02-05 12:05:00', 1, 10150, 0, 0, 0),
            ('r3', 1319673732, 333, 'LUKE', 'M. BISON', 0, 1, 'win',  TIMESTAMP '2026-02-05 12:10:00', 1, 10200, 0, 0, 0),
            ('r4', 1319673732, 444, 'LUKE', 'LUKE',     0, 0, 'loss', TIMESTAMP '2026-02-06 12:00:00', 1, 10250, 0, 0, 0),
            ('r5', 555, 1319673732, 'JP', 'KEN',        0, 0, 'loss', TIMESTAMP '2026-02-07 12:00:00', 1, 0, 10300, 0, 1500)
        ) t(replay_id, p1_short_id, p2_short_id, p1_character_name, p2_character_name,
            p1_input_type, p2_input_type, match_result, uploaded_at, battle_type,
            p1_league_point, p2_league_point, p1_master_rating, p2_master_rating)
        """
    )
    connection.execute(
        """
        CREATE TABLE matches AS
        SELECT * FROM (VALUES
            ('m1', 'VIDEO001', 'r1'),
            ('m2', 'VIDEO001', 'r2'),
            ('m3', 'VIDEO001', 'r3'),
            ('m4', 'VIDEO002', 'r4'),
            ('m5', 'VIDEO002', 'r5'),
            ('m6', 'VIDEO003', NULL)
        ) t(id, videoId, battlelogReplayId)
        """
    )
    return connection


class TestVideoDateRange:
    def test_scopes_to_video(self, con):
        assert query_video_date_range(con, "VIDEO001") == ("2026-02-05", "2026-02-05")
        assert query_video_date_range(con, "VIDEO002") == ("2026-02-06", "2026-02-07")

    def test_returns_none_without_matched_replays(self, con):
        assert query_video_date_range(con, "VIDEO003") == (None, None)
        assert query_video_date_range(con, "UNKNOWN") == (None, None)


class TestVideoSummary:
    def test_counts_only_video_matches(self, con):
        summary = query_video_summary(con, "VIDEO001", PLAYER_ID)
        assert summary.total_matches == 3
        assert summary.wins == 2
        assert summary.losses == 1
        assert summary.first_lp == 10100
        assert summary.last_lp == 10200


class TestVideoMatchups:
    def test_groups_by_opponent(self, con):
        matchups = query_video_matchups(con, "VIDEO001", PLAYER_ID)
        by_opponent = {row.opponent_character: row for row in matchups}

        assert set(by_opponent) == {"AKUMA", "M. BISON"}
        assert by_opponent["AKUMA"].total == 2
        assert by_opponent["AKUMA"].wins == 1
        assert by_opponent["M. BISON"].opponent_input_type == "Modern"

    def test_does_not_include_other_videos(self, con):
        matchups = query_video_matchups(con, "VIDEO001", PLAYER_ID)
        assert all(row.opponent_character != "LUKE" for row in matchups)


class TestVideoLpHistory:
    def test_returns_chronological_rows(self, con):
        history = query_video_lp_history(con, "VIDEO002", PLAYER_ID)
        assert [row.result for row in history] == ["LOSS", "WIN"]
        # r5 は 2P 側だが、自分視点で勝敗とレートが取れる
        assert history[1].lp == 10300
        assert history[1].master_rating == 1500
