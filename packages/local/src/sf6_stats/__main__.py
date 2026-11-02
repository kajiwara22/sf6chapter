"""バックラー統計 collector の CLI（ADR-072）

使用例:

    # 最新月を取得して R2 に配置
    uv run python -m src.sf6_stats --latest

    # 特定月をローカルにだけ出力（R2 へは上げない）
    uv run python -m src.sf6_stats --month 202508 --no-upload --output-dir ./tmp/stats
"""

from __future__ import annotations

import argparse
import sys

from . import buckler_client
from .buckler_client import SUPPORTED_USAGE_LOCALES, BucklerAPIError, format_data_month, latest_available_month
from .collector import BucklerStatsCollector


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="バックラー公開統計を取得して R2 に Parquet を配置する")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--month", default=None, help="対象月（YYYYMM）。省略時は最新月")
    group.add_argument("--latest", action="store_true", help="取得可能な最新月を使用する")

    parser.add_argument(
        "--locales",
        default=",".join(SUPPORTED_USAGE_LOCALES),
        help=f"使用率を取得するロケール（カンマ区切り。対応: {', '.join(SUPPORTED_USAGE_LOCALES)}）",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="R2 へアップロードせず --output-dir に Parquet を保存する",
    )
    parser.add_argument("--output-dir", default="./tmp/sf6_stats", help="--no-upload 時の Parquet 出力先")
    parser.add_argument("--raw-dir", default=None, help="生 JSON の保存先（省略時は保存しない）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.month:
        year, month = buckler_client.parse_data_month(args.month)
    else:
        year, month = latest_available_month()

    locales = tuple(item.strip() for item in args.locales.split(",") if item.strip())
    unknown = [locale for locale in locales if locale not in SUPPORTED_USAGE_LOCALES]
    if unknown:
        print(
            f"エラー: 未対応のロケールです: {', '.join(unknown)}（対応: {', '.join(SUPPORTED_USAGE_LOCALES)}）",
            file=sys.stderr,
        )
        return 1

    print(f"対象月: {format_data_month(year, month)} / ロケール: {', '.join(locales)}")

    r2_uploader = None
    if not args.no_upload:
        from ..storage.r2_uploader import R2Uploader

        try:
            r2_uploader = R2Uploader()
        except ValueError as e:
            print(f"エラー: {e}", file=sys.stderr)
            print("R2 を使わない場合は --no-upload を指定してください", file=sys.stderr)
            return 1

    collector = BucklerStatsCollector(
        r2_uploader=r2_uploader,
        output_dir=args.output_dir,
        raw_dir=args.raw_dir,
    )

    try:
        result = collector.collect_month(year, month, locales=locales, upload=not args.no_upload)
    except (BucklerAPIError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    print("\n収集完了")
    print(f"  対象月: {result.data_month}")
    for locale, rows in result.usage_rows.items():
        print(f"  使用率（{locale}）: {rows}行")
    print(f"  マッチアップ stats: {result.stats_rows}行")
    print(f"  マッチアップ details: {result.details_rows}行")
    for key in result.uploaded_keys:
        print(f"  アップロード: {key}")
    for path in result.local_files:
        print(f"  保存: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
