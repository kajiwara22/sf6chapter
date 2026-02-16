#!/usr/bin/env python3
"""
BattlelogCacheManager テストスクリプト

キャッシング機構の動作確認：
1. キャッシュの基本操作（保存・取得・統計）
2. BattlelogCollector との統合
3. API レスポンス + キャッシュのマージ動作

使用方法:
    uv run scripts/test_battlelog_cache.py \\
        --player-id 1319673732 \\
        [--output-format json|pretty]
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトのsrcディレクトリをpythonpathに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sf6_battlelog import BattlelogCollector, BattlelogSiteClient, BattlelogCacheManager
from utils.logger import get_logger

logger = get_logger()


def print_pretty(data: Any) -> None:
    """Pretty形式で出力"""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                print(f"{key}:")
                print(f"  {json.dumps(value, ensure_ascii=False, indent=2)}")
            else:
                print(f"{key}: {value}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def test_cache_basic_operations(cache: BattlelogCacheManager) -> None:
    """キャッシュの基本操作をテスト"""
    print("\n" + "=" * 60)
    print("Test 1: キャッシュの基本操作")
    print("=" * 60)

    player_id = "test_player_123"

    # サンプル対戦ログ
    sample_replays = [
        {
            "id": "REPLAY001",
            "uploaded_at": "2026-02-17T10:00:00Z",
            "myCharacter": "RYU",
            "opponentCharacter": "JP",
            "result": "win",
        },
        {
            "id": "REPLAY002",
            "uploaded_at": "2026-02-17T11:00:00Z",
            "myCharacter": "GOUKI",
            "opponentCharacter": "BLANKA",
            "result": "loss",
        },
        {
            "id": "REPLAY003",
            "uploaded_at": "2026-02-17T12:00:00Z",
            "myCharacter": "JP",
            "opponentCharacter": "RYU",
            "result": "win",
        },
    ]

    # 1. キャッシュに保存
    print("\n1. キャッシュに保存...")
    cached_count = cache.cache_replays(player_id, sample_replays)
    print(f"   → {cached_count} 件のレプレイをキャッシュ")

    # 2. キャッシュから取得
    print("\n2. キャッシュから取得...")
    cached_replays = cache.get_cached_replays(player_id)
    print(f"   → {len(cached_replays)} 件のレプレイを取得")
    for replay in cached_replays:
        print(f"      - {replay['id']}: {replay['myCharacter']} vs {replay['opponentCharacter']} ({replay['result']})")

    # 3. キャッシュ済み uploaded_at を取得
    print("\n3. キャッシュ済み uploaded_at を取得...")
    cached_set = cache.get_cached_uploaded_at_set(player_id)
    print(f"   → {len(cached_set)} 件のユニークな uploaded_at")
    for uploaded_at in sorted(cached_set):
        print(f"      - {uploaded_at}")

    # 4. 重複排除テスト
    print("\n4. 重複排除テスト...")
    duplicate_replay = {
        "id": "REPLAY001_DUP",
        "uploaded_at": "2026-02-17T10:00:00Z",  # 既存のものと同じ uploaded_at
        "myCharacter": "KEN",
        "opponentCharacter": "GUILE",
        "result": "draw",
    }
    is_new = cache.cache_replay(player_id, duplicate_replay)
    if not is_new:
        print("   ✓ 重複の回避成功（UNIQUE制約で保護）")
    else:
        print("   ✗ 重複が挿入された（予期しない）")

    # 5. 統計情報
    print("\n5. キャッシュ統計情報...")
    stats = cache.get_cache_stats()
    print(f"   総レコード数: {stats['total_records']}")
    print(f"   ユニークプレイヤー数: {stats['unique_players']}")
    print(f"   プレイヤーごとのレコード数: {stats['unique_replays_by_player']}")
    print(f"   DBサイズ: {stats['db_size_bytes']} bytes")


def test_cache_with_collector(
    player_id: str,
    output_format: str = "pretty"
) -> None:
    """BattlelogCollector とのキャッシング統合をテスト"""
    print("\n" + "=" * 60)
    print("Test 2: BattlelogCollector との統合テスト")
    print("=" * 60)

    # 環境変数確認
    build_id = os.environ.get("NEXT_DATA_BUILD_ID")
    auth_cookie = os.environ.get("BUCKLER_ID_COOKIE")

    if not build_id or not auth_cookie:
        print("\n⚠️  スキップ: 環境変数が不足しています")
        print("   必要: NEXT_DATA_BUILD_ID, BUCKLER_ID_COOKIE")
        return

    try:
        # 1. buildId を確認
        print("\n1. buildId 確認...")
        print(f"   buildId: {build_id[:20]}...")

        # 2. キャッシュマネージャーを初期化
        print("\n2. キャッシュマネージャーを初期化...")
        cache = BattlelogCacheManager(db_path="./test_battlelog_cache.db")
        stats_before = cache.get_cache_stats()
        print(f"   初期状態: {stats_before['total_records']} 件のレコード")

        # 3. BattlelogCollector を初期化
        print("\n3. BattlelogCollector を初期化...")
        collector = BattlelogCollector(
            build_id=build_id,
            auth_cookie=auth_cookie,
            cache=cache,
        )
        print("   ✓ 初期化成功")

        # 4. 初回実行（キャッシュなし）
        print("\n4. 初回実行（API から取得）...")
        print(f"   対象: player_id={player_id}, page=1")
        replays_1st = asyncio.run(
            collector.get_replay_list(player_id=player_id, page=1)
        )
        print(f"   ✓ {len(replays_1st)} 件取得")

        stats_after_1st = cache.get_cache_stats()
        print(f"   キャッシュ状態: {stats_after_1st['total_records']} 件のレコード")
        print(f"   （新規追加: {stats_after_1st['total_records'] - stats_before['total_records']} 件）")

        # 5. 2回目実行（キャッシュあり）
        print("\n5. 2回目実行（キャッシュ + API）...")
        print(f"   対象: player_id={player_id}, page=1")
        import time
        start_time = time.time()
        replays_2nd = asyncio.run(
            collector.get_replay_list(player_id=player_id, page=1)
        )
        elapsed = time.time() - start_time
        print(f"   ✓ {len(replays_2nd)} 件取得（{elapsed:.2f}秒）")

        stats_after_2nd = cache.get_cache_stats()
        print(f"   キャッシュ状態: {stats_after_2nd['total_records']} 件のレコード")
        print(f"   （新規追加: {stats_after_2nd['total_records'] - stats_after_1st['total_records']} 件）")

        # 6. 結果出力
        if replays_1st:
            print("\n6. サンプルレプレイ（最初の1件）...")
            sample = replays_1st[0]
            if output_format == "json":
                print(json.dumps(sample, ensure_ascii=False, indent=2))
            else:
                print_pretty(sample)

    except Exception as e:
        logger.error(f"Integration test failed: {e}", exc_info=True)
        print(f"\n✗ テスト失敗: {e}")


def main() -> None:
    """メイン処理"""
    parser = argparse.ArgumentParser(
        description="BattlelogCacheManager テストスクリプト"
    )
    parser.add_argument(
        "--player-id",
        type=str,
        default="1319673732",
        help="テスト対象のプレイヤーID",
    )
    parser.add_argument(
        "--output-format",
        type=str,
        choices=["json", "pretty"],
        default="pretty",
        help="出力形式（デフォルト: pretty）",
    )
    parser.add_argument(
        "--skip-integration",
        action="store_true",
        help="統合テストをスキップ（基本操作テストのみ実行）",
    )
    parser.add_argument(
        "--skip-basic",
        action="store_true",
        help="基本操作テストをスキップ（統合テストのみ実行）",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("BattlelogCacheManager テストスイート")
    print("=" * 60)
    print(f"実行時刻: {datetime.now().isoformat()}")
    print(f"プレイヤーID: {args.player_id}")

    # テスト1: 基本操作
    if not args.skip_basic:
        try:
            cache = BattlelogCacheManager(db_path="./test_battlelog_cache_basic.db")
            test_cache_basic_operations(cache)
            cache.clear_cache()  # テスト用DBをクリア
        except Exception as e:
            logger.error(f"Basic operations test failed: {e}", exc_info=True)

    # テスト2: 統合テスト
    if not args.skip_integration:
        test_cache_with_collector(args.player_id, args.output_format)

    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
