"""
DuckDBクエリによるBattlelogデータ集計
"""

from collections import defaultdict
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

# 勝利方法ID（ADR-037 / ADR-051）。0=LOSS, 4=DRAW は勝ちではない
ROUND_METHOD_MAP = {
    1: "V",
    2: "C",
    3: "T",
    5: "OD",
    6: "SA",
    7: "CA",
    8: "P",
}

# 表示用の名称
ROUND_METHOD_LABELS = {
    "V": "通常KO",
    "C": "Chip KO",
    "T": "時間切れ",
    "OD": "OD KO",
    "SA": "SA KO",
    "CA": "CA KO",
    "P": "パーフェクト",
    "UNKNOWN": "不明",
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
    # ADR-072: 同ランク帯の平均勝率（%）。--external-stats 指定時のみ埋まる
    benchmark_win_rate: float | None = None

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
class HourlyRow:
    """時間帯別勝率集計の1行"""

    hour: int  # 0〜23（JST）
    total: int
    wins: int
    losses: int

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total * 100) if self.total > 0 else 0.0


@dataclass
class FirstRoundRow:
    """1ラウンド目の勝敗ごとの試合成績"""

    won: bool
    total: int
    wins: int

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total * 100) if self.total > 0 else 0.0


@dataclass
class SideScoreRow:
    """1P / 2P 別の試合成績"""

    side: str  # "1P" / "2P"
    total: int
    wins: int
    full_round_total: int
    full_round_wins: int

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total * 100) if self.total > 0 else 0.0

    @property
    def full_round_win_rate(self) -> float | None:
        if self.full_round_total <= 0:
            return None
        return self.full_round_wins / self.full_round_total * 100


@dataclass
class RoundMethodRow:
    """決まり手の集計1行"""

    method: str  # V / C / T / OD / SA / CA / P / UNKNOWN
    count: int
    total: int

    @property
    def label(self) -> str:
        return ROUND_METHOD_LABELS.get(self.method, self.method)

    @property
    def share(self) -> float:
        return (self.count / self.total * 100) if self.total > 0 else 0.0


@dataclass
class RoundScore:
    """ラウンドスコア分析の集計結果"""

    total_matches: int
    # 1R を取った / 落とした別（won=True, False の順）
    first_round: list[FirstRoundRow]
    # 1P / 2P 別
    sides: list[SideScoreRow]
    # 1-1 から 3R に入った試合（len=3 の試合と同義）
    full_round_total: int
    full_round_wins: int
    # 自分が取ったラウンドの決まり手 / 落としたラウンドの決まり手
    won_methods: list[RoundMethodRow]
    lost_methods: list[RoundMethodRow]
    total_rounds_won: int
    total_rounds_lost: int


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


def query_latest_league_result(
    con: duckdb.DuckDBPyConnection,
    player_id: str,
    date_to: str,
    battle_type: str = "ranked",
) -> tuple[int | None, int | None]:
    """期間末時点の直近試合から (league_point, master_rating) を取得する

    ADR-072: バックラー統計の比較対象ランクを推定するために使う。
    LP/MR はランクマッチでのみ意味を持つため、ranked 以外では (None, None) を返す。
    """
    if battle_type != "ranked":
        return None, None

    pid = int(player_id)
    row = con.execute(
        """
        SELECT
            CASE WHEN p1_short_id = ? THEN p1_league_point
                 ELSE p2_league_point END AS league_point,
            CASE WHEN p1_short_id = ? THEN p1_master_rating
                 ELSE p2_master_rating END AS master_rating
        FROM battlelog_replays
        WHERE (p1_short_id = ? OR p2_short_id = ?)
          AND uploaded_at < ?::TIMESTAMP
          AND battle_type = 1
        ORDER BY uploaded_at DESC
        LIMIT 1
        """,
        [pid, pid, pid, pid, date_to],
    ).fetchone()

    if row is None:
        return None, None
    return row[0], row[1]


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


def query_hourly_win_rate(
    con: duckdb.DuckDBPyConnection,
    player_id: str,
    date_from: str,
    date_to: str,
    battle_type: str = "ranked",
) -> list[HourlyRow]:
    """時間帯別（JST）勝率を取得"""
    bt_filter = _battle_type_filter(battle_type)
    pid = int(player_id)

    rows = con.execute(
        f"""
        SELECT
            DATE_PART('hour', uploaded_at AT TIME ZONE 'Asia/Tokyo') AS hour_jst,
            COUNT(*) AS total,
            SUM(CASE
                WHEN (p1_short_id = ? AND match_result = 'win')
                  OR (p2_short_id = ? AND match_result = 'loss')
                THEN 1 ELSE 0 END) AS wins
        FROM battlelog_replays
        WHERE (p1_short_id = ? OR p2_short_id = ?)
          AND uploaded_at >= ?::TIMESTAMPTZ
          AND uploaded_at < ?::TIMESTAMPTZ
          {bt_filter}
        GROUP BY hour_jst
        ORDER BY hour_jst
        """,
        [pid] * 4 + [date_from, date_to],
    ).fetchall()

    return [HourlyRow(hour=r[0], total=r[1], wins=r[2], losses=r[1] - r[2]) for r in rows]


def query_round_score(
    con: duckdb.DuckDBPyConnection,
    player_id: str,
    date_from: str,
    date_to: str,
    battle_type: str = "ranked",
) -> RoundScore:
    """
    ラウンドスコア分析を取得する。

    battlelog_replays.parquet だけで完結する（round_stats / gauges は不要）。
    - 1Rの勝敗と試合勝率
    - 1P / 2P 別の試合勝率と 3R 勝率
    - 1-1 から 3R に入った試合の勝率
    - 取ったラウンド / 落としたラウンドの決まり手
    """
    bt_filter = _battle_type_filter(battle_type)
    pid = int(player_id)

    # 自分視点に正規化した CTE。round_results の同じ添字が同じラウンドを指す
    base_sql = f"""
        WITH base AS (
            SELECT *,
                CASE WHEN p1_short_id = {pid} THEN 1 ELSE 2 END AS my_pos
            FROM battlelog_replays
            WHERE (p1_short_id = {pid} OR p2_short_id = {pid})
              AND uploaded_at >= ?::TIMESTAMPTZ
              AND uploaded_at < ?::TIMESTAMPTZ
              {bt_filter}
        ),
        n AS (
            SELECT *,
                CASE WHEN my_pos = 1 THEN match_result
                     WHEN match_result = 'win' THEN 'loss'
                     WHEN match_result = 'loss' THEN 'win'
                     ELSE match_result END AS my_result,
                CASE WHEN my_pos = 1 AND json_valid(p1_round_results)
                     THEN from_json(p1_round_results, '["INTEGER"]') END AS my_rounds,
                CASE WHEN my_pos = 1 AND json_valid(p2_round_results)
                     THEN from_json(p2_round_results, '["INTEGER"]') END AS opp_rounds_1p,
                CASE WHEN my_pos = 2 AND json_valid(p2_round_results)
                     THEN from_json(p2_round_results, '["INTEGER"]') END AS my_rounds_2p,
                CASE WHEN my_pos = 2 AND json_valid(p1_round_results)
                     THEN from_json(p1_round_results, '["INTEGER"]') END AS opp_rounds_2p,
                CASE WHEN my_pos = 1 THEN '1P' ELSE '2P' END AS my_side
            FROM base
        ),
        r AS (
            SELECT *,
                COALESCE(my_rounds, my_rounds_2p) AS my_rr,
                COALESCE(opp_rounds_1p, opp_rounds_2p) AS opp_rr
            FROM n
        ),
        valid AS (
            SELECT * FROM r
            WHERE my_rr IS NOT NULL AND opp_rr IS NOT NULL
              AND len(my_rr) > 0 AND len(my_rr) = len(opp_rr)
        )
    """
    params = [date_from, date_to]

    def _query(sql: str) -> list[tuple]:
        return con.execute(base_sql + sql, params).fetchall()

    total_matches = _query("SELECT COUNT(*) FROM valid")[0][0]

    # 1ラウンド目の勝敗ごとの試合成績
    first_round = [
        FirstRoundRow(won=bool(won), total=total, wins=wins or 0)
        for won, total, wins in _query(
            """
            SELECT my_rr[1] > 0 AS won,
                   COUNT(*) AS total,
                   SUM(CASE WHEN my_result = 'win' THEN 1 ELSE 0 END) AS wins
            FROM valid
            GROUP BY won
            ORDER BY won DESC
            """
        )
    ]

    # 1P / 2P 別（3R 勝率付き）
    sides = [
        SideScoreRow(
            side=side,
            total=total,
            wins=wins or 0,
            full_round_total=full_total or 0,
            full_round_wins=full_wins or 0,
        )
        for side, total, wins, full_total, full_wins in _query(
            """
            SELECT my_side,
                   COUNT(*) AS total,
                   SUM(CASE WHEN my_result = 'win' THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN len(my_rr) = 3 THEN 1 ELSE 0 END) AS full_total,
                   SUM(CASE WHEN len(my_rr) = 3 AND my_result = 'win' THEN 1 ELSE 0 END) AS full_wins
            FROM valid
            GROUP BY my_side
            ORDER BY my_side
            """
        )
    ]

    # 1-1 から 3R に入った試合（3ラウンド行がある試合は 2-0 以外は 1-1 の後の 3R）
    full_row = _query(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN my_result = 'win' THEN 1 ELSE 0 END) AS wins
        FROM valid
        WHERE len(my_rr) = 3
        """
    )[0]
    full_round_total = full_row[0] or 0
    full_round_wins = full_row[1] or 0

    # ラウンド単位に展開して決まり手を集計
    round_rows = _query(
        """
        SELECT my_v, opp_v FROM (
            SELECT unnest(my_rr) AS my_v, unnest(opp_rr) AS opp_v
            FROM valid
        )
        """
    )

    won_counts: dict[str, int] = defaultdict(int)
    lost_counts: dict[str, int] = defaultdict(int)
    for my_v, opp_v in round_rows:
        if my_v is None:
            continue
        if my_v > 0 and my_v != 4:
            won_counts[ROUND_METHOD_MAP.get(my_v, "UNKNOWN")] += 1
        elif my_v == 0:
            if opp_v is not None and opp_v > 0 and opp_v != 4:
                lost_counts[ROUND_METHOD_MAP.get(opp_v, "UNKNOWN")] += 1
            else:
                lost_counts["UNKNOWN"] += 1

    total_rounds_won = sum(won_counts.values())
    total_rounds_lost = sum(lost_counts.values())

    def _sorted_rows(counts: dict[str, int], total: int) -> list[RoundMethodRow]:
        order = list(ROUND_METHOD_MAP.values()) + ["UNKNOWN"]
        return [RoundMethodRow(method=m, count=counts[m], total=total) for m in order if counts.get(m)]

    return RoundScore(
        total_matches=total_matches,
        first_round=first_round,
        sides=sides,
        full_round_total=full_round_total,
        full_round_wins=full_round_wins,
        won_methods=_sorted_rows(won_counts, total_rounds_won),
        lost_methods=_sorted_rows(lost_counts, total_rounds_lost),
        total_rounds_won=total_rounds_won,
        total_rounds_lost=total_rounds_lost,
    )


def load_parquet(parquet_path: str) -> duckdb.DuckDBPyConnection:
    """Parquetファイルを読み込み、DuckDB接続を返す"""
    con = duckdb.connect()
    con.execute(f"CREATE TABLE battlelog_replays AS SELECT * FROM read_parquet('{parquet_path}')")
    return con
