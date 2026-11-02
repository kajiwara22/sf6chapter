"""バックラー API レスポンス → Parquet 行への変換（ADR-072）

数値の意味（202508 の実データで確認済み）:

- `_dsort`   : 対戦相手別の実際の勝率（0〜1）。matchup_details.win_rate はこれを使う
- `val`      : 相性スコア（0〜10、5.0 が基準）。勝率ではない
- `total`    : キャラの総合評価値（10点満点。実測は `_win_rate * 10`）
- `records[]._win_rate` : キャラの総合勝率（0〜1）。matchup_stats.win_rate はこれを使う

`val` は 0.0〜10.0 に実値として 0 が現れるため、欠損を 0 に潰してはならない。
`-.---`（サンプル不足）と `-`（ミラー）は None として保持し、集計時に NULL を
無視できるようにする。ミラーは `character_id == opponent_character_id` で判定する。
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from .buckler_client import LEAGUE_NAMES

# 欠損を表す文字列表現
MISSING_VALUES = frozenset({"", "-", "-.---", "null", "None", "nan"})

USAGE_SCHEMA = pa.schema(
    [
        pa.field("data_month", pa.string(), nullable=False),
        pa.field("locale", pa.string(), nullable=False),
        pa.field("operation_type", pa.int32(), nullable=False),
        pa.field("league_rank", pa.int32(), nullable=False),
        pa.field("league_name", pa.string(), nullable=True),
        pa.field("character_alpha", pa.string(), nullable=False),
        pa.field("character_tool_name", pa.string(), nullable=False),
        pa.field("play_rate", pa.float64(), nullable=True),
        pa.field("previous_rate", pa.float64(), nullable=True),
    ]
)

MATCHUP_STATS_SCHEMA = pa.schema(
    [
        pa.field("data_month", pa.string(), nullable=False),
        pa.field("rank_id", pa.int32(), nullable=False),
        pa.field("rank_name", pa.string(), nullable=False),
        pa.field("character_id", pa.int32(), nullable=False),
        pa.field("character_alpha", pa.string(), nullable=False),
        pa.field("character_tool_name", pa.string(), nullable=False),
        pa.field("input_type", pa.string(), nullable=False),
        pa.field("total_score", pa.float64(), nullable=True),
        pa.field("win_rate", pa.float64(), nullable=False),
    ]
)

MATCHUP_DETAILS_SCHEMA = pa.schema(
    [
        pa.field("data_month", pa.string(), nullable=False),
        pa.field("rank_id", pa.int32(), nullable=False),
        pa.field("character_id", pa.int32(), nullable=False),
        pa.field("input_type", pa.string(), nullable=False),
        pa.field("opponent_character_id", pa.int32(), nullable=False),
        pa.field("opponent_character_alpha", pa.string(), nullable=True),
        pa.field("opponent_tool_name", pa.string(), nullable=True),
        pa.field("opponent_input_type", pa.string(), nullable=True),
        pa.field("win_rate", pa.float64(), nullable=False),
        pa.field("score", pa.float64(), nullable=True),
        pa.field("sf", pa.int32(), nullable=True),
        pa.field("thm", pa.int32(), nullable=True),
    ]
)


def to_float(value: Any) -> float | None:
    """欠損表現を None に変換しつつ float 化する"""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if text in MISSING_VALUES:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value: Any, default: int | None = None) -> int | None:
    """欠損表現を default に変換しつつ int 化する"""
    if value is None:
        return default
    text = str(value).strip()
    if text in MISSING_VALUES:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def is_mirror(row: dict[str, Any]) -> bool:
    """ミラー（自分自身との対戦行）かどうか"""
    return row["character_id"] == row["opponent_character_id"]


def usage_rows(payload: dict[str, Any], data_month: str, locale: str) -> list[dict[str, Any]]:
    """使用率 API のレスポンスを行に変換する"""
    operations = payload.get("usagerateData")
    if not isinstance(operations, list):
        raise ValueError("usagerateData が見つかりません（レスポンス形式が不正です）")

    rows: list[dict[str, Any]] = []
    for operation in operations:
        operation_type = to_int(operation.get("operation_type"), default=0)
        leagues = operation.get("val")
        if not isinstance(leagues, list):
            continue
        for league in leagues:
            league_rank = to_int(league.get("league_rank"), default=0)
            characters = league.get("val")
            if not isinstance(characters, list):
                continue
            for character in characters:
                rows.append(
                    {
                        "data_month": data_month,
                        "locale": locale,
                        "operation_type": operation_type,
                        "league_rank": league_rank,
                        "league_name": league.get("league_alpha"),
                        "character_alpha": character.get("character_alpha"),
                        "character_tool_name": character.get("character_tool_name"),
                        "play_rate": to_float(character.get("play_rate")),
                        "previous_rate": to_float(character.get("previous_rate")),
                    }
                )
    return rows


def matchup_rows(payload: dict[str, Any], data_month: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """マッチアップ API のレスポンスを (stats 行, details 行) に変換する"""
    try:
        ci_sort = payload["diaData"]["ci"]["ci_sort"]
    except (KeyError, TypeError) as e:
        raise ValueError("diaData.ci.ci_sort が見つかりません（レスポンス形式が不正です）") from e

    stats_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []

    for rank_key, rank_data in ci_sort.items():
        rank_id = to_int(rank_key)
        if rank_id is None:
            continue
        rank_name = LEAGUE_NAMES.get(rank_id, str(rank_id))

        # opponent_header は「全キャラの C → 全キャラの M」の順で並んでおり、
        # records[].values と index が一致する（432 records すべてで検証済み）。
        # _oid だけでは C/M を区別できないため、index を主キーとする。
        header_list = rank_data.get("opponent_header", [])
        header_by_id = {to_int(entry.get("id")): entry for entry in header_list if to_int(entry.get("id")) is not None}

        for record in rank_data.get("records", []):
            character_id = to_int(record.get("id"))
            if character_id is None:
                continue
            input_type = record.get("input_type")

            # records[]._win_rate がキャラの総合勝率（0〜1）。
            # _dsort は values（対戦相手別）にのみ存在する
            win_rate = to_float(record.get("_win_rate"))
            if win_rate is None:
                # 勝率が取れない行はマッチアップ統計として成立しない
                continue

            stats_rows.append(
                {
                    "data_month": data_month,
                    "rank_id": rank_id,
                    "rank_name": rank_name,
                    "character_id": character_id,
                    "character_alpha": record.get("name_alpha"),
                    "character_tool_name": record.get("tool_name"),
                    "input_type": input_type,
                    "total_score": to_float(record.get("total")),
                    "win_rate": win_rate,
                }
            )

            for index, value in enumerate(record.get("values", [])):
                opponent_id = to_int(value.get("_oid"))
                if opponent_id is None:
                    continue
                # 通常は index で引く。順序が崩れた場合のみ id でフォールバックする
                opponent = header_list[index] if index < len(header_list) else None
                if opponent is None or to_int(opponent.get("id")) != opponent_id:
                    opponent = header_by_id.get(opponent_id)
                opponent_win_rate = to_float(value.get("_dsort"))
                if opponent_win_rate is None:
                    continue

                detail_rows.append(
                    {
                        "data_month": data_month,
                        "rank_id": rank_id,
                        "character_id": character_id,
                        "input_type": input_type,
                        "opponent_character_id": opponent_id,
                        "opponent_character_alpha": opponent.get("name_alpha") if opponent else None,
                        "opponent_tool_name": opponent.get("tool_name") if opponent else None,
                        "opponent_input_type": opponent.get("input_type") if opponent else None,
                        "win_rate": opponent_win_rate,
                        # val は相性スコア。`-`（ミラー）/`-.---`（サンプル不足）は None
                        "score": to_float(value.get("val")),
                        "sf": to_int(value.get("sf"), default=0),
                        "thm": to_int(value.get("thm"), default=0),
                    }
                )

    return stats_rows, detail_rows
