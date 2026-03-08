#!/usr/bin/env python3
"""
battlelog_cache.db → battlelog_replays.parquet 変換スクリプト

SQLiteキャッシュから全リプレイデータを読み込み、Parquetファイルに変換する。
生成されたParquetはR2にアップロードしてWeb UIのマッチアップチャートで使用する。

Usage:
    python scripts/convert_battlelog_to_parquet.py [--db-path PATH] [--output PATH]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pyarrow as pa
import pyarrow.parquet as pq

from src.sf6_battlelog.cache import BattlelogCacheManager
from src.utils.logger import get_logger

logger = get_logger()

# バトルタイプ名のマッピング
BATTLE_TYPE_NAMES = {
    1: "Ranked",
    3: "Battle Hub",
    4: "Custom Room",
}


def get_battlelog_replays_schema() -> pa.Schema:
    """battlelog_replays.parquet のスキーマを定義"""
    return pa.schema([
        pa.field("replay_id", pa.string()),
        pa.field("uploaded_at", pa.timestamp("s", tz="UTC")),
        pa.field("battle_type", pa.int32()),
        pa.field("battle_type_name", pa.string()),
        pa.field("p1_character_id", pa.int32()),
        pa.field("p1_character_name", pa.string()),
        pa.field("p1_input_type", pa.int32()),
        pa.field("p1_league_point", pa.int32()),
        pa.field("p1_league_rank", pa.int32()),
        pa.field("p1_master_rating", pa.int32()),
        pa.field("p1_short_id", pa.int64()),
        pa.field("p1_fighter_id", pa.string()),
        pa.field("p1_round_results", pa.string()),
        pa.field("p2_character_id", pa.int32()),
        pa.field("p2_character_name", pa.string()),
        pa.field("p2_input_type", pa.int32()),
        pa.field("p2_league_point", pa.int32()),
        pa.field("p2_league_rank", pa.int32()),
        pa.field("p2_master_rating", pa.int32()),
        pa.field("p2_short_id", pa.int64()),
        pa.field("p2_fighter_id", pa.string()),
        pa.field("p2_round_results", pa.string()),
        pa.field("match_result", pa.string()),
    ])


def determine_match_result(p1_round_results: list[int], p2_round_results: list[int]) -> str:
    """
    P1視点の勝敗を判定

    round_results の合計値で判定:
    - P1の合計 > P2の合計 → "win"
    - P1の合計 < P2の合計 → "loss"
    - 同数 → "draw"
    """
    p1_wins = sum(p1_round_results)
    p2_wins = sum(p2_round_results)

    if p1_wins > p2_wins:
        return "win"
    elif p1_wins < p2_wins:
        return "loss"
    else:
        return "draw"


def convert_replay_to_row(replay: dict) -> dict | None:
    """リプレイデータを Parquet 行に変換"""
    try:
        p1 = replay.get("player1_info", {})
        p2 = replay.get("player2_info", {})

        p1_round = p1.get("round_results", [])
        p2_round = p2.get("round_results", [])

        uploaded_at_ts = replay.get("uploaded_at")
        if uploaded_at_ts is None:
            logger.warning("replay missing uploaded_at, skipping: %s", replay.get("replay_id"))
            return None

        battle_type = replay.get("replay_battle_type", 0)

        return {
            "replay_id": replay.get("replay_id", ""),
            "uploaded_at": datetime.fromtimestamp(int(uploaded_at_ts), tz=timezone.utc),
            "battle_type": battle_type,
            "battle_type_name": BATTLE_TYPE_NAMES.get(battle_type, str(battle_type)),
            "p1_character_id": p1.get("character_id", 0),
            "p1_character_name": p1.get("character_name", ""),
            "p1_input_type": p1.get("battle_input_type", 0),
            "p1_league_point": p1.get("league_point", 0),
            "p1_league_rank": p1.get("league_rank", 0),
            "p1_master_rating": p1.get("master_rating", 0),
            "p1_short_id": p1.get("player", {}).get("short_id", 0),
            "p1_fighter_id": p1.get("player", {}).get("fighter_id", ""),
            "p1_round_results": json.dumps(p1_round),
            "p2_character_id": p2.get("character_id", 0),
            "p2_character_name": p2.get("character_name", ""),
            "p2_input_type": p2.get("battle_input_type", 0),
            "p2_league_point": p2.get("league_point", 0),
            "p2_league_rank": p2.get("league_rank", 0),
            "p2_master_rating": p2.get("master_rating", 0),
            "p2_short_id": p2.get("player", {}).get("short_id", 0),
            "p2_fighter_id": p2.get("player", {}).get("fighter_id", ""),
            "p2_round_results": json.dumps(p2_round),
            "match_result": determine_match_result(p1_round, p2_round),
        }
    except Exception:
        logger.exception("Failed to convert replay: %s", replay.get("replay_id"))
        return None


def convert_battlelog_to_parquet(
    db_path: str = "./battlelog_cache.db",
    output_path: str = "./output/battlelog_replays.parquet",
) -> int:
    """
    SQLiteキャッシュからParquetファイルを生成

    Returns:
        変換されたレコード数
    """
    cache = BattlelogCacheManager(db_path=db_path)
    replays = cache.get_all_cached_replays()

    if not replays:
        logger.warning("No cached replays found in %s", db_path)
        return 0

    logger.info("Converting %d replays to Parquet...", len(replays))

    rows = []
    for replay in replays:
        row = convert_replay_to_row(replay)
        if row:
            rows.append(row)

    if not rows:
        logger.warning("No valid rows after conversion")
        return 0

    # Parquet書き出し
    schema = get_battlelog_replays_schema()
    table = pa.Table.from_pylist(rows, schema=schema)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(output), compression="snappy")

    logger.info("Written %d rows to %s", len(rows), output)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Battlelog cache → Parquet 変換")
    parser.add_argument(
        "--db-path",
        default="./battlelog_cache.db",
        help="SQLite キャッシュDBのパス (default: ./battlelog_cache.db)",
    )
    parser.add_argument(
        "--output",
        default="./output/battlelog_replays.parquet",
        help="出力Parquetファイルのパス (default: ./output/battlelog_replays.parquet)",
    )
    args = parser.parse_args()

    count = convert_battlelog_to_parquet(args.db_path, args.output)

    if count > 0:
        print(f"✅ Converted {count} replays to {args.output}")
    else:
        print("⚠️ No replays converted")
        sys.exit(1)


if __name__ == "__main__":
    main()
