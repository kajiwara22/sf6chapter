#!/usr/bin/env python3
"""
ローカルで生成したJSONファイルからParquetを生成してR2にアップロード

Usage:
    python scripts/upload_to_r2.py
    python scripts/upload_to_r2.py --battlelog  # Battlelog Parquetのみアップロード
"""

import argparse
import json
import os
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.storage.r2_uploader import R2Uploader
from src.utils.logger import get_logger

logger = get_logger()


def load_json_files(output_dir: Path) -> tuple[list[dict], list[dict]]:
    """
    出力ディレクトリからJSON ファイルを読み込む

    Returns:
        (videos, matches) のタプル
    """
    videos = []
    matches = []

    video_files = list(output_dir.glob("*_video.json"))
    match_files = list(output_dir.glob("*_matches.json"))

    print(f"   Found {len(video_files)} video files and {len(match_files)} match files")

    # ビデオデータ読み込み
    for video_file in video_files:
        try:
            with open(video_file) as f:
                video_data = json.load(f)
                videos.append(video_data)
                print(f"   ✅ Loaded video: {video_data.get('videoId')}")
        except Exception as e:
            print(f"   ❌ Error loading {video_file}: {e}")

    # マッチデータ読み込み
    for match_file in match_files:
        try:
            with open(match_file) as f:
                match_data = json.load(f)
                if isinstance(match_data, list):
                    matches.extend(match_data)
                else:
                    matches.append(match_data)
                count = len(match_data) if isinstance(match_data, list) else 1
                print(f"   ✅ Loaded {count} matches from {match_file.name}")
        except Exception as e:
            print(f"   ❌ Error loading {match_file}: {e}")

    return videos, matches


def upload_battlelog_parquet(uploader: R2Uploader, output_dir: Path) -> bool:
    """
    Battlelog Parquetファイルを R2 にアップロード

    Returns:
        アップロード成功時 True
    """
    parquet_path = output_dir / "battlelog_replays.parquet"

    if not parquet_path.exists():
        print(f"⚠️ Battlelog Parquet not found: {parquet_path}")
        print("   Run 'python scripts/convert_battlelog_to_parquet.py' first")
        return False

    import pyarrow.parquet as pq

    table = pq.read_table(str(parquet_path))
    row_count = table.num_rows

    print(f"⬆️  Uploading battlelog_replays.parquet ({row_count} rows)...")
    uploader.upload_parquet(table.to_pylist(), "battlelog_replays.parquet")
    print(f"   ✅ Uploaded battlelog_replays.parquet ({row_count} rows)")
    return True


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description="R2へのデータアップロード")
    parser.add_argument(
        "--battlelog",
        action="store_true",
        help="Battlelog Parquetのみアップロード",
    )
    args = parser.parse_args()

    # 環境変数確認
    required_vars = ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT_URL"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]

    if missing_vars:
        print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        print("Please set them in .env file or environment")
        sys.exit(1)

    # 出力ディレクトリ
    output_dir = project_root / "output"

    # R2 Uploader初期化
    print("🔧 Initializing R2 Uploader...")
    uploader = R2Uploader()

    # --battlelog モード: Battlelog Parquetのみアップロード
    if args.battlelog:
        if not output_dir.exists():
            print(f"❌ Output directory not found: {output_dir}")
            sys.exit(1)

        success = upload_battlelog_parquet(uploader, output_dir)
        if not success:
            sys.exit(1)
        print("\n🎉 Battlelog upload completed!")
        return

    # 通常モード: JSON + matches Parquet のアップロード
    if not output_dir.exists():
        print(f"❌ Output directory not found: {output_dir}")
        sys.exit(1)

    # JSONファイル読み込み
    print("📂 Loading JSON files from output directory...")
    videos, matches = load_json_files(output_dir)

    if not videos and not matches:
        print("❌ No data found in output directory")
        sys.exit(1)

    print(f"✅ Loaded {len(videos)} videos and {len(matches)} matches")

    # ビデオデータをJSONとしてアップロード
    if videos:
        print("⬆️  Uploading videos.json...")
        uploader.upload_json(videos, "videos.json")
        print(f"   ✅ Uploaded {len(videos)} videos")

    # マッチデータをJSONとParquetでアップロード
    if matches:
        print("⬆️  Uploading matches.json...")
        uploader.upload_json(matches, "matches.json")
        print(f"   ✅ Uploaded matches.json ({len(matches)} matches)")

        print("⬆️  Uploading matches.parquet...")
        uploader.upload_parquet(matches, "matches.parquet")
        print(f"   ✅ Uploaded matches.parquet ({len(matches)} matches)")

    # Battlelog Parquetがあればそれもアップロード
    upload_battlelog_parquet(uploader, output_dir)

    print("\n🎉 Upload completed successfully!")
    print(f"  - Videos: {len(videos)}")
    print(f"  - Matches: {len(matches)}")


if __name__ == "__main__":
    main()
