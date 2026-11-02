"""バックラー公開統計（ADR-072）との突合

R2 の `stats/matchup_stats/{YYYYMM}.parquet` と `stats/matchup_details/{YYYYMM}.parquet`
を読み、Battlelog のマッチアップ集計に「同ランク帯の平均勝率」を付与する。

勝率の定義（ADR-072）:

- `matchup_stats.win_rate`    : キャラの総合勝率（元 `records[]._win_rate`）
- `matchup_details.win_rate`  : 対戦相手別の実際の勝率（元 `_dsort`）
- `matchup_details.score`     : 相性スコア 0〜10（元 `val`）。勝率ではない。欠損は NULL
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta

import duckdb

from .r2_client import download_parquet

# バックラー ja-jp の name_alpha → 英語（Battlelog）表記
NAME_ALIASES = {"GOUKI": "AKUMA", "VEGA": "M. BISON"}

# Battlelog は日本語名を返す（2026-11 時点）。バックラーの name_alpha は英語。
# packages/local/config/character_aliases.json の日本語エイリアスと実データの表記を統合する。
JA_TO_CANONICAL: dict[str, str] = {
    "リュウ": "RYU",
    "ケン": "KEN",
    "春麗": "CHUN-LI",
    "ガイル": "GUILE",
    "ザンギエフ": "ZANGIEF",
    "ダルシム": "DHALSIM",
    "本田": "E.HONDA",
    "エドモンド本田": "E.HONDA",
    "ブランカ": "BLANKA",
    "ジェイピー": "JP",
    "ジュリ": "JURI",
    "キンバリー": "KIMBERLY",
    "リリー": "LILY",
    "マノン": "MANON",
    "マリーザ": "MARISA",
    "ディージェイ": "DEE JAY",
    "キャミィ": "CAMMY",
    "ルーク": "LUKE",
    "ジェイミー": "JAMIE",
    "アキ": "A.K.I.",
    "豪鬼": "GOUKI",
    "ベガ": "VEGA",
    "テリー": "TERRY",
    "マイ": "MAI",
    "舞": "MAI",
    "不知火舞": "MAI",
    "サガット": "SAGAT",
    "アレックス": "ALEX",
    "ヴァイパー": "C.VIPER",
    "バイパー": "C.VIPER",
    "C.ヴァイパー": "C.VIPER",
    "イングリッド": "INGRID",
    "エレナ": "ELENA",
    "ヤスミン": "YASMINE",
    "エド": "ED",
    "ラシード": "RASHID",
    "ボシュ": "BOSCH",
    "アルジュン": "ARJUN",
    "ティファ": "TIFA",
}

# LP 帯（Rookie〜Diamond）。Master は MR で判定する
LEAGUE_LP_THRESHOLDS: tuple[tuple[int, int], ...] = (
    (1000, 1),  # ROOKIE   0-999
    (3000, 2),  # IRON     1000-2999
    (5000, 3),  # BRONZE   3000-4999
    (9000, 4),  # SILVER   5000-8999
    (13000, 5),  # GOLD     9000-12999
    (19000, 6),  # PLATINUM 13000-18999
    (25000, 7),  # DIAMOND  19000-24999
)
MASTER_RANK_ID = 8

LEAGUE_NAMES: dict[int, str] = {
    1: "ROOKIE",
    2: "IRON",
    3: "BRONZE",
    4: "SILVER",
    5: "GOLD",
    6: "PLATINUM",
    7: "DIAMOND",
    8: "MASTER",
}

# dia の input_type → レポートの表記
INPUT_TYPE_LABELS = {"C": "Classic", "M": "Modern"}

# バックラーの最古の公開データ
OLDEST_YEAR = 2023
OLDEST_MONTH = 6


def canonical_character_name(name: str) -> str:
    """キャラ名を照合用のキーに正規化する

    Battlelog は日本語名（`ルーク`）、バックラーは英語名（`LUKE`）を返すため、
    まず日本語名を英語の `name_alpha` に変換してから、地域別の別名
    （GOUKI/AKUMA、VEGA/M. BISON）を解決し、記号・空白を除去する。
    """
    trimmed = name.strip()
    base = JA_TO_CANONICAL.get(trimmed, trimmed)
    upper = base.upper()
    upper = NAME_ALIASES.get(upper, upper)
    return re.sub(r"[^A-Z0-9]", "", upper)


def league_rank_from_result(league_point: int | None, master_rating: int | None) -> int | None:
    """LP / MR からリーグ ID を推定する

    Master に到達すると LP ではなく MR で評価される。MR が正の値なら Master。
    """
    if master_rating is not None and master_rating > 0:
        return MASTER_RANK_ID
    if league_point is None:
        return None
    for threshold, rank_id in LEAGUE_LP_THRESHOLDS:
        if league_point < threshold:
            return rank_id
    return MASTER_RANK_ID


def latest_published_month(at: date | None = None) -> str:
    """指定日時点で公開済みの最新データ月（YYYYMM）を返す

    バックラーは毎月第二木曜日に先月分を公開する。第二木曜より前は先々月、
    以降は先月が最新。
    """
    at = at or date.today()
    first_day = at.replace(day=1)
    days_until_thursday = (3 - first_day.weekday()) % 7  # 木曜=3
    second_thursday = first_day + timedelta(days=days_until_thursday + 7)

    months_back = 2 if at < second_thursday else 1
    year, month = at.year, at.month - months_back
    while month <= 0:
        month += 12
        year -= 1

    if (year, month) < (OLDEST_YEAR, OLDEST_MONTH):
        return f"{OLDEST_YEAR}{OLDEST_MONTH:02d}"
    return f"{year}{month:02d}"


def download_stats_parquet(data_month: str, *, stats_dir: str | None = None) -> tuple[str, str]:
    """対象月の stats / details Parquet のローカルパスを返す

    Args:
        data_month: "YYYYMM"
        stats_dir: ローカルの stats ディレクトリ（`stats/` を含む）。指定時は R2 を使わない
    """
    if stats_dir:
        stats_path = os.path.join(stats_dir, "matchup_stats", f"{data_month}.parquet")
        details_path = os.path.join(stats_dir, "matchup_details", f"{data_month}.parquet")
        for path in (stats_path, details_path):
            if not os.path.exists(path):
                raise FileNotFoundError(f"統計 Parquet が見つかりません: {path}")
        return stats_path, details_path

    stats_path = download_parquet(f"stats/matchup_stats/{data_month}.parquet")
    details_path = download_parquet(f"stats/matchup_details/{data_month}.parquet")
    return stats_path, details_path


def create_views(con: duckdb.DuckDBPyConnection, stats_path: str, details_path: str) -> None:
    """DuckDB に統計ビューを作成する

    DuckDB は CREATE VIEW でプレースホルダを使えないため、パスをリテラルとして埋め込む。
    """
    stats_literal = stats_path.replace("'", "''")
    details_literal = details_path.replace("'", "''")
    con.execute(f"CREATE OR REPLACE VIEW ext_matchup_stats AS SELECT * FROM read_parquet('{stats_literal}')")
    con.execute(f"CREATE OR REPLACE VIEW ext_matchup_details AS SELECT * FROM read_parquet('{details_literal}')")


def query_benchmarks(
    con: duckdb.DuckDBPyConnection,
    data_month: str,
    rank_id: int,
) -> dict[tuple[str, str, str], float]:
    """同ランク帯の平均勝率（%）を (自分, 相手, 相手入力タイプ) で引ける辞書にする

    自分側の入力タイプ（Classic/Modern）は区別せず平均する。
    ミラー（同じキャラ同士）は勝率の意味がないため除外する。
    """
    rows = con.execute(
        """
        SELECT
            d.character_id,
            s.character_alpha,
            d.opponent_character_alpha,
            d.opponent_input_type,
            AVG(d.win_rate) * 100 AS avg_win_rate
        FROM ext_matchup_details d
        JOIN ext_matchup_stats s
          ON s.data_month = d.data_month
         AND s.rank_id = d.rank_id
         AND s.character_id = d.character_id
         AND s.input_type = d.input_type
        WHERE d.data_month = ?
          AND d.rank_id = ?
          AND d.character_id <> d.opponent_character_id
        GROUP BY d.character_id, s.character_alpha, d.opponent_character_alpha, d.opponent_input_type
        """,
        [data_month, rank_id],
    ).fetchall()

    benchmarks: dict[tuple[str, str, str], float] = {}
    for _, my_character, opponent_character, opponent_input_type, avg_win_rate in rows:
        if my_character is None or opponent_character is None or avg_win_rate is None:
            continue
        label = INPUT_TYPE_LABELS.get(opponent_input_type, opponent_input_type)
        key = (
            canonical_character_name(my_character),
            canonical_character_name(opponent_character),
            label,
        )
        benchmarks[key] = float(avg_win_rate)
    return benchmarks


def lookup_benchmark(
    benchmarks: dict[tuple[str, str, str], float],
    my_character: str,
    opponent_character: str,
    opponent_input_type: str,
) -> float | None:
    """1行分の平均勝率を引く"""
    key = (
        canonical_character_name(my_character),
        canonical_character_name(opponent_character),
        opponent_input_type,
    )
    return benchmarks.get(key)
