"""
SF6 Battlelog レポート生成CLIツール

使用例:
    uv run python src/main.py --from 2026-02-01 --to 2026-03-01
    uv run python src/main.py --from 2026-02-01 --to 2026-03-01 --compare-prev
    uv run python src/main.py --from 2026-02-01 --to 2026-03-01 --local path/to/file.parquet
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

from .formatter import format_comparison, format_report
from .query import load_parquet, query_lp_history, query_matchups, query_summary
from .r2_client import download_parquet

DEFAULT_PLAYER_ID = "1319673732"
DEFAULT_PLAYER_NAME = "ゆたにぃPC"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SF6 Battlelog レポート生成ツール")
    parser.add_argument("--from", dest="date_from", required=True, help="開始日 (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", required=True, help="終了日 (YYYY-MM-DD)")
    parser.add_argument(
        "--player-id", default=DEFAULT_PLAYER_ID, help=f"プレイヤーID (デフォルト: {DEFAULT_PLAYER_ID})"
    )
    parser.add_argument(
        "--player-name", default=DEFAULT_PLAYER_NAME, help=f"プレイヤー名 (デフォルト: {DEFAULT_PLAYER_NAME})"
    )
    parser.add_argument(
        "--battle-type",
        default="ranked",
        choices=["ranked", "battlehub", "custom", "all"],
        help="バトルタイプ (デフォルト: ranked)",
    )
    parser.add_argument("--output", default=None, help="出力ファイルパス (デフォルト: ./output/YYYY-MM_report.md)")
    parser.add_argument("--compare-prev", action="store_true", help="前期間比較を含める")
    parser.add_argument("--local", default=None, help="ローカルParquetファイルパス（R2ダウンロードをスキップ）")
    return parser.parse_args(argv)


def _compute_previous_period(date_from: str, date_to: str) -> tuple[str, str]:
    """指定期間と同じ長さの前期間を計算"""
    dt_from = datetime.strptime(date_from, "%Y-%m-%d")
    dt_to = datetime.strptime(date_to, "%Y-%m-%d")
    delta = dt_to - dt_from
    prev_to = dt_from
    prev_from = prev_to - delta
    return prev_from.strftime("%Y-%m-%d"), prev_to.strftime("%Y-%m-%d")


def _default_output_path(date_from: str, date_to: str) -> str:
    """デフォルト出力パスを生成"""
    dt_from = datetime.strptime(date_from, "%Y-%m-%d")
    dt_to = datetime.strptime(date_to, "%Y-%m-%d") - timedelta(days=1)
    if dt_from.year == dt_to.year and dt_from.month == dt_to.month:
        name = dt_from.strftime("%Y-%m")
    else:
        name = f"{dt_from.strftime('%Y-%m-%d')}_{dt_to.strftime('%Y-%m-%d')}"
    return os.path.join("output", f"{name}_report.md")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # Parquetファイル取得
    if args.local:
        parquet_path = args.local
        if not os.path.exists(parquet_path):
            print(f"エラー: ファイルが見つかりません: {parquet_path}", file=sys.stderr)
            sys.exit(1)
        print(f"ローカルファイルを使用: {parquet_path}")
    else:
        print("R2からParquetファイルをダウンロード中...")
        parquet_path = download_parquet()
        print(f"ダウンロード完了: {parquet_path}")

    # DuckDB接続
    con = load_parquet(parquet_path)

    # メインクエリ
    print(f"集計中: {args.date_from} 〜 {args.date_to} (player: {args.player_id}, type: {args.battle_type})")
    summary = query_summary(con, args.player_id, args.date_from, args.date_to, args.battle_type)
    matchups = query_matchups(con, args.player_id, args.date_from, args.date_to, args.battle_type)
    lp_history = query_lp_history(con, args.player_id, args.date_from, args.date_to, args.battle_type)

    # レポート生成
    report = format_report(
        summary,
        matchups,
        lp_history,
        date_from=args.date_from,
        date_to=args.date_to,
        player_id=args.player_id,
        player_name=args.player_name,
        battle_type=args.battle_type,
    )

    # 前期間比較
    if args.compare_prev:
        prev_from, prev_to = _compute_previous_period(args.date_from, args.date_to)
        print(f"前期間比較: {prev_from} 〜 {prev_to}")
        prev_summary = query_summary(con, args.player_id, prev_from, prev_to, args.battle_type)
        prev_matchups = query_matchups(con, args.player_id, prev_from, prev_to, args.battle_type)
        comparison = format_comparison(
            summary,
            prev_summary,
            matchups,
            prev_matchups,
            current_period=f"{args.date_from} 〜 {args.date_to}",
            previous_period=f"{prev_from} 〜 {prev_to}",
        )
        report += "\n\n" + comparison

    # 出力
    output_path = args.output or _default_output_path(args.date_from, args.date_to)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nレポート生成完了: {output_path}")
    print(
        f"  総試合数: {summary.total_matches}  勝率: {summary.wins / summary.total_matches * 100:.1f}%"
        if summary.total_matches > 0
        else "  データなし"
    )

    con.close()


if __name__ == "__main__":
    main()
