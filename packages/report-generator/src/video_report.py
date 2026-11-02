"""動画単位のレポート集計（ADR-072 #6）

配信1本に含まれる試合だけを対象に集計する。`matches.parquet` の
`battlelogReplayId` を介して `battlelog_replays` を絞り込むため、
期間指定ではなく「その動画で実際に対戦した試合」に一致する。

前提: `matches` ビューが DuckDB に登録されていること（`create_matches_view`）。
"""

from __future__ import annotations

import duckdb

from .query import INPUT_TYPE_MAP, LPRow, MatchupRow, Summary

# 動画に紐づく Battlelog リプレイ ID
_SCOPED_REPLAYS = """
    SELECT DISTINCT battlelogReplayId AS replay_id
    FROM matches
    WHERE videoId = ? AND battlelogReplayId IS NOT NULL
"""

_WIN_CONDITION = """
    (p1_short_id = ? AND match_result = 'win')
    OR (p2_short_id = ? AND match_result = 'loss')
"""


def create_matches_view(con: duckdb.DuckDBPyConnection, matches_path: str) -> None:
    """matches.parquet を DuckDB のビューとして登録する"""
    literal = matches_path.replace("'", "''")
    con.execute(f"CREATE OR REPLACE VIEW matches AS SELECT * FROM read_parquet('{literal}')")


def query_video_date_range(
    con: duckdb.DuckDBPyConnection,
    video_id: str,
) -> tuple[str | None, str | None]:
    """動画に紐づく試合の日付範囲（YYYY-MM-DD）を返す"""
    row = con.execute(
        f"""
        SELECT MIN(uploaded_at), MAX(uploaded_at)
        FROM battlelog_replays
        WHERE replay_id IN ({_SCOPED_REPLAYS})
        """,
        [video_id],
    ).fetchone()

    if row is None or row[0] is None:
        return None, None
    return row[0].strftime("%Y-%m-%d"), row[1].strftime("%Y-%m-%d")


def query_video_summary(
    con: duckdb.DuckDBPyConnection,
    video_id: str,
    player_id: str,
) -> Summary:
    """動画に含まれる試合のサマリーを取得する"""
    pid = int(player_id)

    result = con.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN {_WIN_CONDITION} THEN 1 ELSE 0 END) AS wins
        FROM battlelog_replays
        WHERE replay_id IN ({_SCOPED_REPLAYS})
          AND (p1_short_id = ? OR p2_short_id = ?)
        """,
        [pid, pid, video_id, pid, pid],
    ).fetchone()

    total = result[0] if result else 0
    wins = result[1] if result and result[1] is not None else 0

    lp_rows = con.execute(
        f"""
        SELECT
            uploaded_at,
            CASE WHEN p1_short_id = ? THEN p1_league_point ELSE p2_league_point END AS lp,
            CASE WHEN p1_short_id = ? THEN p1_master_rating ELSE p2_master_rating END AS mr
        FROM battlelog_replays
        WHERE replay_id IN ({_SCOPED_REPLAYS})
          AND (p1_short_id = ? OR p2_short_id = ?)
        ORDER BY uploaded_at ASC
        """,
        [pid, pid, video_id, pid, pid],
    ).fetchall()

    return Summary(
        total_matches=total,
        wins=wins,
        losses=total - wins,
        first_lp=lp_rows[0][1] if lp_rows else None,
        last_lp=lp_rows[-1][1] if lp_rows else None,
        first_mr=lp_rows[0][2] if lp_rows else None,
        last_mr=lp_rows[-1][2] if lp_rows else None,
    )


def query_video_matchups(
    con: duckdb.DuckDBPyConnection,
    video_id: str,
    player_id: str,
) -> list[MatchupRow]:
    """動画に含まれる試合のマッチアップ集計を取得する"""
    pid = int(player_id)

    rows = con.execute(
        f"""
        SELECT
            CASE WHEN p1_short_id = ? THEN p1_character_name
                 ELSE p2_character_name END AS my_character,
            CASE WHEN p1_short_id = ? THEN p2_character_name
                 ELSE p1_character_name END AS opponent_character,
            CASE WHEN p1_short_id = ? THEN p2_input_type
                 ELSE p1_input_type END AS opponent_input_type,
            COUNT(*) AS total,
            SUM(CASE WHEN {_WIN_CONDITION} THEN 1 ELSE 0 END) AS wins
        FROM battlelog_replays
        WHERE replay_id IN ({_SCOPED_REPLAYS})
          AND (p1_short_id = ? OR p2_short_id = ?)
        GROUP BY my_character, opponent_character, opponent_input_type
        ORDER BY my_character, total DESC
        """,
        [pid, pid, pid, pid, pid, video_id, pid, pid],
    ).fetchall()

    return [
        MatchupRow(
            my_character=r[0],
            opponent_character=r[1],
            opponent_input_type=INPUT_TYPE_MAP.get(r[2], str(r[2])),
            total=r[3],
            wins=r[4],
            losses=r[3] - r[4],
        )
        for r in rows
    ]


def query_video_lp_history(
    con: duckdb.DuckDBPyConnection,
    video_id: str,
    player_id: str,
) -> list[LPRow]:
    """動画に含まれる試合のLP推移を取得する"""
    pid = int(player_id)

    rows = con.execute(
        f"""
        SELECT
            uploaded_at,
            CASE WHEN p1_short_id = ? THEN p2_character_name
                 ELSE p1_character_name END AS opponent_character,
            CASE WHEN {_WIN_CONDITION} THEN 'WIN' ELSE 'LOSS' END AS result,
            CASE WHEN p1_short_id = ? THEN p1_league_point
                 ELSE p2_league_point END AS lp,
            CASE WHEN p1_short_id = ? THEN p1_master_rating
                 ELSE p2_master_rating END AS mr
        FROM battlelog_replays
        WHERE replay_id IN ({_SCOPED_REPLAYS})
          AND (p1_short_id = ? OR p2_short_id = ?)
        ORDER BY uploaded_at ASC
        """,
        [pid, pid, pid, pid, pid, video_id, pid, pid],
    ).fetchall()

    return [
        LPRow(
            uploaded_at=r[0],
            opponent_character=r[1],
            result=r[2],
            lp=r[3],
            master_rating=r[4],
        )
        for r in rows
    ]
