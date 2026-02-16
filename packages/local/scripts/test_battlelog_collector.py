#!/usr/bin/env python3
"""
SF6 Battlelog 対戦ログ収集テストスクリプト

以下の流れでStreet Fighter 6のbattlelogページから対戦ログを取得:
1. Next.jsサイトからbuildIdを取得
2. Playwrightでログインして認証クッキーを取得
3. battlelogページから対戦ログを収集
4. ページング情報を取得
5. レスポンスを検査して出力

使用方法:
    uv run scripts/test_battlelog_collector.py \\
        --player-id 1319673732 \\
        [--page 1] \\
        [--output-format json|pretty]

環境変数:
    BUCKLER_ID_COOKIE: 認証用 buckler_id クッキー（指定時はログインをスキップ）
    BUCKLER_EMAIL: Capcom ID メールアドレス（BUCKLER_ID_COOKIE 未指定時に使用）
    BUCKLER_PASSWORD: Capcom ID パスワード（BUCKLER_ID_COOKIE 未指定時に使用）
    DEFAULT_USER_AGENT: HTTPリクエスト用User-Agent (オプション)
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトのsrcディレクトリをpythonpathに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sf6_battlelog import (
    BattlelogCollector,
    BattlelogSiteClient,
    CapcomIdAuthenticator,
)
from utils.logger import get_logger

logger = get_logger()


async def main(
    player_id: str,
    output_format: str = "pretty",
    skip_auth: bool = False,
    auth_cookie: str | None = None,
    build_id: str | None = None,
    page: int = 1,
):
    """
    SFBuff API テストを実行

    Args:
        player_id: プレイヤーID
        output_format: 出力形式（json または pretty）
        skip_auth: ログインをスキップして既存の認証情報を使用
        auth_cookie: 既存の認証クッキー
        build_id: 既存のbuildId
        page: battlelog ページ番号（1-10）
    """
    print("\n" + "=" * 70)
    print("SFBuff API テスト")
    print("=" * 70)

    results = {
        "timestamp": datetime.now().isoformat(),
        "player_id": player_id,
        "page": page,
        "steps": {},
    }

    # 環境変数 BUCKLER_ID_COOKIE が設定されていれば、フラグで指定されたものを優先
    if not auth_cookie:
        auth_cookie = os.environ.get("BUCKLER_ID_COOKIE")
        if auth_cookie:
            logger.debug("Using BUCKLER_ID_COOKIE from environment variable")

    try:
        # Step 1: buildId取得
        print("\n[Step 1] Next.jsサイトからbuildIdを取得...")
        if build_id:
            print(f"  → buildIdはスキップ（指定値: {build_id[:20]}...）")
            results["steps"]["get_build_id"] = {
                "status": "skipped",
                "build_id": build_id,
            }
        else:
            try:
                site_client = BattlelogSiteClient()
                build_id = await site_client.get_build_id()
                print(f"  ✓ buildId取得成功: {build_id[:30]}...")
                results["steps"]["get_build_id"] = {
                    "status": "success",
                    "build_id": build_id,
                }
            except Exception as e:
                print(f"  ✗ エラー: {e}")
                results["steps"]["get_build_id"] = {
                    "status": "failed",
                    "error": str(e),
                }
                raise

        # Step 2: 認証クッキー取得
        print("\n[Step 2] Playwrightでログイン...")
        if auth_cookie:
            print(f"  → 認証クッキーはスキップ（指定値: {auth_cookie[:20]}...）")
            results["steps"]["login"] = {
                "status": "skipped",
                "auth_cookie": auth_cookie,
            }
        else:
            try:
                authenticator = CapcomIdAuthenticator()
                print("loginします。")
                auth_cookie = await authenticator.login()
                print("  ✓ ログイン成功")
                print(f"    認証クッキー: {auth_cookie[:50]}...")
                results["steps"]["login"] = {
                    "status": "success",
                    "auth_cookie_preview": auth_cookie[:50] + "...",
                }
            except Exception as e:
                print(f"  ✗ ログイン失敗: {e}")
                results["steps"]["login"] = {
                    "status": "failed",
                    "error": str(e),
                }
                raise

        # Step 3: APIクライアントを初期化
        api_client = BattlelogCollector(
            build_id=build_id,
            auth_cookie=auth_cookie,
        )

        # Step 4: battlelog ページから対戦ログを取得
        print("\n[Step 4] battlelog ページから対戦ログを取得...")
        print(f"  プレイヤーID: {player_id}")
        print("  ページ: 1")

        try:
            replay_list = await api_client.get_replay_list(
                player_id=player_id,
                page=page,
            )

            print("  ✓ 対戦ログ取得成功")
            print(f"    対戦数: {len(replay_list) if isinstance(replay_list, list) else 'N/A'}")

            results["steps"]["get_replay_list"] = {
                "status": "success",
                "replay_count": len(replay_list) if isinstance(replay_list, list) else None,
                "response_type": type(replay_list).__name__,
            }

            # Step 5: ページング情報を取得
            print("\n[Step 5] ページング情報を取得...")
            try:
                pagination_info = await api_client.get_pagination_info(
                    player_id=player_id,
                    page=page,
                )
                print("  ✓ ページング情報取得成功")
                print(f"    現在ページ: {pagination_info['current_page']}")
                print(f"    総ページ数: {pagination_info['total_page']}")

                results["steps"]["get_pagination_info"] = {
                    "status": "success",
                    "pagination_info": pagination_info,
                }
            except Exception as e:
                print(f"  ! ページング情報取得エラー: {e}")
                results["steps"]["get_pagination_info"] = {
                    "status": "failed",
                    "error": str(e),
                }

            matches = replay_list

            # Step 6: レスポンス構造の検査
            print("\n[Step 6] レスポンス構造の検査...")
            if isinstance(matches, list) and len(matches) > 0:
                first_match = matches[0]
                print("  最初の対戦データ:")
                print(f"    キー: {list(first_match.keys())}")

                # 重要なフィールドをチェック（battlelog HTML構造に対応）
                important_fields = [
                    "replay_id",
                    "uploaded_at",
                    "player1_info",
                    "player2_info",
                    "replay_battle_type",
                    "replay_battle_sub_type",
                ]

                found_fields = {field: field in first_match for field in important_fields}
                print("\n    主要フィールド:")
                for field, found in found_fields.items():
                    status = "✓" if found else "✗"
                    print(f"      {status} {field}")

                results["steps"]["response_inspection"] = {
                    "status": "success",
                    "first_match_keys": list(first_match.keys()),
                    "expected_fields_found": found_fields,
                }
            else:
                print("  対戦データがありません")
                results["steps"]["response_inspection"] = {
                    "status": "skipped",
                    "note": "No matches found",
                }

            # 最終結果
            print("\n" + "=" * 70)
            print("テスト完了")
            print("=" * 70)

            # 出力フォーマットに応じて結果を表示
            if output_format == "json":
                print("\n[JSON形式でのレスポンス]")
                print(json.dumps(results, indent=2, ensure_ascii=False))

                # 対戦データもJSON形式で出力
                if isinstance(matches, list) and len(matches) > 0:
                    print("\n[対戦ログAPIレスポンス（最初の3件）]")
                    print(json.dumps(matches[:3], indent=2, ensure_ascii=False))
            else:
                # Pretty形式
                print("\n[テスト結果]")
                for step, details in results["steps"].items():
                    status = details.get("status", "unknown")
                    print(f"  {step}: {status}")

                if isinstance(matches, list) and len(matches) > 0:
                    print("\n[対戦データサンプル（最初1件）]")
                    print(json.dumps(matches[0], indent=2, ensure_ascii=False))

            results["final_status"] = "success"

        except BattlelogCollector.Unauthorized:
            print("  ✗ 認証エラー (401)")
            results["steps"]["get_replay_list"] = {
                "status": "failed",
                "error": "Unauthorized (401)",
            }
            results["final_status"] = "failed"
            raise

        except (BattlelogCollector.PageNotFound, ValueError, RuntimeError) as e:
            print(f"  ✗ データ取得エラー: {e}")
            results["steps"]["get_replay_list"] = {
                "status": "failed",
                "error": str(e),
            }
            results["final_status"] = "failed"
            raise
        except Exception as e:
            print(f"  ✗ 対戦ログ取得失敗: {e}")
            results["steps"]["get_replay_list"] = {
                "status": "failed",
                "error": str(e),
            }
            raise

    except Exception as e:
        print(f"\n✗ テスト失敗: {e}")
        results["final_status"] = "failed"
        results["error"] = str(e)
        return results

    return results


def main_sync():
    """同期版のエントリーポイント"""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--player-id",
        required=True,
        help="プレイヤーID（例: 1319673732）",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="battlelog ページ番号（デフォルト: 1）",
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "pretty"],
        default="pretty",
        help="出力形式（デフォルト: pretty）",
    )
    parser.add_argument(
        "--auth-cookie",
        help="既存の認証クッキー（指定時はログインをスキップ）",
    )
    parser.add_argument(
        "--build-id",
        help="既存のbuildId（指定時はサイト取得をスキップ）",
    )

    args = parser.parse_args()

    results = asyncio.run(
        main(
            player_id=args.player_id,
            output_format=args.output_format,
            auth_cookie=args.auth_cookie,
            build_id=args.build_id,
            page=args.page,
        )
    )

    # 失敗時は終了コード1
    sys.exit(0 if results.get("final_status") == "success" else 1)


if __name__ == "__main__":
    main_sync()
