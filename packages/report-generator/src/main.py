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

from .external_stats import (
    LEAGUE_NAMES,
    MASTER_RANK_ID,
    create_views,
    download_stats_parquet,
    latest_published_month,
    league_rank_from_result,
    lookup_benchmark,
    query_benchmarks,
)
from .formatter import format_comparison, format_report
from .query import (
    load_parquet,
    query_hourly_win_rate,
    query_latest_league_result,
    query_lp_history,
    query_matchups,
    query_round_score,
    query_summary,
)
from .r2_client import download_parquet
from .video_report import (
    create_matches_view,
    query_video_date_range,
    query_video_lp_history,
    query_video_matchups,
    query_video_summary,
)

DEFAULT_PLAYER_ID = "1319673732"
DEFAULT_PLAYER_NAME = "ゆたにぃPC"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SF6 Battlelog レポート生成ツール")
    parser.add_argument("--from", dest="date_from", default=None, help="開始日 (YYYY-MM-DD)。--video-id 指定時は不要")
    parser.add_argument("--to", dest="date_to", default=None, help="終了日 (YYYY-MM-DD)。--video-id 指定時は不要")
    parser.add_argument(
        "--video-id",
        default=None,
        help="YouTube 動画ID。その配信に含まれる試合だけを集計する",
    )
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
    parser.add_argument(
        "--hourly-analysis",
        action="store_true",
        help="時間帯別勝率分析を含める（JST換算、1時間単位）",
    )
    parser.add_argument(
        "--round-analysis",
        action="store_true",
        help="ラウンドスコア分析を含める（1R別・1P/2P別・3R勝率・決まり手）",
    )
    parser.add_argument(
        "--external-stats",
        action="store_true",
        help="バックラー公開統計と比較する（同ランク帯の平均勝率を付与）",
    )
    parser.add_argument(
        "--stats-month",
        default=None,
        help="統計の対象月（YYYYMM）。省略時はレポート末日時点の最新公開月",
    )
    parser.add_argument(
        "--stats-rank",
        type=int,
        default=None,
        choices=range(1, 9),
        metavar="1-8",
        help="統計のランクID（省略時は Battlelog から推定）",
    )
    parser.add_argument(
        "--stats-dir",
        default=None,
        help="ローカルの stats ディレクトリ（指定時は R2 ダウンロードをスキップ）",
    )
    parser.add_argument("--local", default=None, help="ローカルParquetファイルパス（R2ダウンロードをスキップ）")
    parser.add_argument("--matches-local", default=None, help="ローカルの matches.parquet（--video-id の検証用）")
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

    if args.video_id is None and (not args.date_from or not args.date_to):
        print("エラー: --from と --to、または --video-id を指定してください", file=sys.stderr)
        sys.exit(2)

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

    date_from = args.date_from
    date_to = args.date_to

    # メインクエリ
    if args.video_id:
        # 動画単位（ADR-072 #6）
        print(f"動画 {args.video_id} に含まれる試合を集計中...")
        matches_path = args.matches_local or download_parquet("matches.parquet")
        create_matches_view(con, matches_path)
        date_from, date_to = query_video_date_range(con, args.video_id)
        if date_from is None or date_to is None:
            print(
                f"エラー: 動画 {args.video_id} に紐づく Battlelog リプレイがありません",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"対象期間: {date_from} 〜 {date_to}")
        summary = query_video_summary(con, args.video_id, args.player_id)
        matchups = query_video_matchups(con, args.video_id, args.player_id)
        lp_history = query_video_lp_history(con, args.video_id, args.player_id)
        hourly = None
        round_score = None
        if args.hourly_analysis or args.round_analysis:
            print("  ※ --hourly-analysis / --round-analysis は動画単位では未対応です", file=sys.stderr)
        if args.compare_prev:
            print("  ※ --compare-prev は動画単位では未対応です", file=sys.stderr)
    else:
        print(f"集計中: {date_from} 〜 {date_to} (player: {args.player_id}, type: {args.battle_type})")
        summary = query_summary(con, args.player_id, date_from, date_to, args.battle_type)
        matchups = query_matchups(con, args.player_id, date_from, date_to, args.battle_type)
        lp_history = query_lp_history(con, args.player_id, date_from, date_to, args.battle_type)

        # 時間帯別勝率（フラグが立っている場合のみ）
        hourly = None
        if args.hourly_analysis:
            print("時間帯別勝率を集計中...")
            hourly = query_hourly_win_rate(con, args.player_id, date_from, date_to, args.battle_type)

        # ラウンドスコア分析（フラグが立っている場合のみ）
        round_score = None
        if args.round_analysis:
            print("ラウンドスコアを集計中...")
            round_score = query_round_score(con, args.player_id, date_from, date_to, args.battle_type)

    # バックラー公開統計との突合（--external-stats 時のみ）
    benchmark_label = None
    if args.external_stats:
        print("バックラー公開統計と突合中...")
        stats_month = args.stats_month or latest_published_month(datetime.strptime(date_to, "%Y-%m-%d").date())
        rank_id = args.stats_rank
        if rank_id is None:
            lp, mr = query_latest_league_result(con, args.player_id, date_to, args.battle_type)
            rank_id = league_rank_from_result(lp, mr)
            if rank_id is None:
                rank_id = MASTER_RANK_ID
                print("  リーグを推定できないため MASTER を既定にします", file=sys.stderr)
            else:
                print(f"  リーグ推定: LP={lp} / MR={mr} -> {LEAGUE_NAMES[rank_id]}")

        stats_path, details_path = download_stats_parquet(stats_month, stats_dir=args.stats_dir)
        create_views(con, stats_path, details_path)
        benchmarks = query_benchmarks(con, stats_month, rank_id)

        matched = 0
        for row in matchups:
            row.benchmark_win_rate = lookup_benchmark(
                benchmarks, row.my_character, row.opponent_character, row.opponent_input_type
            )
            if row.benchmark_win_rate is not None:
                matched += 1

        benchmark_label = f"{stats_month[:4]}年{int(stats_month[4:])}月・{LEAGUE_NAMES[rank_id]}"
        print(f"  統計: {benchmark_label} / 突合 {matched}/{len(matchups)} 行")

    # レポート生成
    report = format_report(
        summary,
        matchups,
        lp_history,
        date_from=date_from,
        date_to=date_to,
        player_id=args.player_id,
        player_name=args.player_name,
        battle_type=args.battle_type,
        hourly=hourly,
        round_score=round_score,
        benchmark_label=benchmark_label,
        video_id=args.video_id,
    )

    # 前期間比較
    if args.compare_prev and not args.video_id:
        prev_from, prev_to = _compute_previous_period(date_from, date_to)
        print(f"前期間比較: {prev_from} 〜 {prev_to}")
        prev_summary = query_summary(con, args.player_id, prev_from, prev_to, args.battle_type)
        prev_matchups = query_matchups(con, args.player_id, prev_from, prev_to, args.battle_type)
        comparison = format_comparison(
            summary,
            prev_summary,
            matchups,
            prev_matchups,
            current_period=f"{date_from} 〜 {date_to}",
            previous_period=f"{prev_from} 〜 {prev_to}",
        )
        report += "\n\n" + comparison

    # 出力
    if args.output:
        output_path = args.output
    elif args.video_id:
        output_path = os.path.join("output", f"{args.video_id}_report.md")
    else:
        output_path = _default_output_path(date_from, date_to)
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
