"""
DuckDBクエリによるBattlelogデータ集計
"""

from dataclasses import dataclass
from datetime import datetime

import duckdb

# バトルタイプのマッピング
BATTLE_TYPE_MAP = {
    1: "ranked",
    3: "battlehub",
    4: "custom",
}

# 入力タイプのマッピング
INPUT_TYPE_MAP = {
    0: "Classic",
    1: "Modern",
    2: "Dynamic",
}


@dataclass
class MatchupRow:
    """マッチアップ集計の1行"""

    my_character: str
    opponent_character: str
    opponent_input_type: str
    total: int
    wins: int
    losses: int

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total * 100) if self.total > 0 else 0.0


@dataclass
class LPRow:
    """LP推移の1行"""

    uploaded_at: datetime
    opponent_character: str
    result: str
    lp: int
    master_rating: int


@dataclass
class Summary:
    """サマリー情報"""

    total_matches: int
    wins: int
    losses: int
    first_lp: int | None
    last_lp: int | None
    first_mr: int | None
    last_mr: int | None


def _battle_type_filter(battle_type: str) -> str:
    """battle_type引数をSQL条件に変換"""
    if battle_type == "all":
        return ""
    type_ids = [k for k, v in BATTLE_TYPE_MAP.items() if v == battle_type]
    if not type_ids:
        return ""
    return f"AND battle_type = {type_ids[0]}"


def query_summary(
    con: duckdb.DuckDBPyConnection,
    player_id: str,
    date_from: str,
    date_to: str,
    battle_type: str = "ranked",
) -> Summary:
    """サマリー情報を取得"""
    bt_filter = _battle_type_filter(battle_type)

    result = con.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE
                WHEN (p1_short_id = ? AND match_result = 'win')
                  OR (p2_short_id = ? AND match_result = 'loss')
                THEN 1 ELSE 0 END) AS wins
        FROM battlelog_replays
        WHERE (p1_short_id = ? OR p2_short_id = ?)
          AND uploaded_at >= ?::TIMESTAMP
          AND uploaded_at < ?::TIMESTAMP
          {bt_filter}
        """,
        [int(player_id)] * 4 + [date_from, date_to],
    ).fetchone()

    total = result[0] if result else 0
    wins = result[1] if result and result[1] is not None else 0

    # LP/MR推移の先頭・末尾
    lp_result = con.execute(
        f"""
        SELECT
            uploaded_at,
            CASE WHEN p1_short_id = ? THEN p1_league_point ELSE p2_league_point END AS lp,
            CASE WHEN p1_short_id = ? THEN p1_master_rating ELSE p2_master_rating END AS mr
        FROM battlelog_replays
        WHERE (p1_short_id = ? OR p2_short_id = ?)
          AND uploaded_at >= ?::TIMESTAMP
          AND uploaded_at < ?::TIMESTAMP
          {bt_filter}
        ORDER BY uploaded_at ASC
        """,
        [int(player_id)] * 4 + [date_from, date_to],
    ).fetchall()

    first_lp = lp_result[0][1] if lp_result else None
    last_lp = lp_result[-1][1] if lp_result else None
    first_mr = lp_result[0][2] if lp_result else None
    last_mr = lp_result[-1][2] if lp_result else None

    return Summary(
        total_matches=total,
        wins=wins,
        losses=total - wins,
        first_lp=first_lp,
        last_lp=last_lp,
        first_mr=first_mr,
        last_mr=last_mr,
    )


def query_matchups(
    con: duckdb.DuckDBPyConnection,
    player_id: str,
    date_from: str,
    date_to: str,
    battle_type: str = "ranked",
) -> list[MatchupRow]:
    """マッチアップ集計を取得（キャラ別・入力タイプ別）"""
    bt_filter = _battle_type_filter(battle_type)
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
            SUM(CASE
                WHEN (p1_short_id = ? AND match_result = 'win')
                  OR (p2_short_id = ? AND match_result = 'loss')
                THEN 1 ELSE 0 END) AS wins
        FROM battlelog_replays
        WHERE (p1_short_id = ? OR p2_short_id = ?)
          AND uploaded_at >= ?::TIMESTAMP
          AND uploaded_at < ?::TIMESTAMP
          {bt_filter}
        GROUP BY my_character, opponent_character, opponent_input_type
        ORDER BY my_character, total DESC
        """,
        [pid] * 7 + [date_from, date_to],
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


def query_lp_history(
    con: duckdb.DuckDBPyConnection,
    player_id: str,
    date_from: str,
    date_to: str,
    battle_type: str = "ranked",
) -> list[LPRow]:
    """LP推移を取得"""
    bt_filter = _battle_type_filter(battle_type)
    pid = int(player_id)

    rows = con.execute(
        f"""
        SELECT
            uploaded_at,
            CASE WHEN p1_short_id = ? THEN p2_character_name
                 ELSE p1_character_name END AS opponent_character,
            CASE WHEN (p1_short_id = ? AND match_result = 'win')
                  OR (p2_short_id = ? AND match_result = 'loss')
                 THEN 'WIN' ELSE 'LOSS' END AS result,
            CASE WHEN p1_short_id = ? THEN p1_league_point
                 ELSE p2_league_point END AS lp,
            CASE WHEN p1_short_id = ? THEN p1_master_rating
                 ELSE p2_master_rating END AS mr
        FROM battlelog_replays
        WHERE (p1_short_id = ? OR p2_short_id = ?)
          AND uploaded_at >= ?::TIMESTAMP
          AND uploaded_at < ?::TIMESTAMP
          {bt_filter}
        ORDER BY uploaded_at ASC
        """,
        [pid] * 7 + [date_from, date_to],
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


def load_parquet(parquet_path: str) -> duckdb.DuckDBPyConnection:
    """Parquetファイルを読み込み、DuckDB接続を返す"""
    con = duckdb.connect()
    con.execute(f"CREATE TABLE battlelog_replays AS SELECT * FROM read_parquet('{parquet_path}')")
    return con
