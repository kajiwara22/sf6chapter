#!/usr/bin/env python3
"""
SF6 Battlelog 認証情報の詳細診断スクリプト

実際のブラウザでログインしたときの:
- buildId
- クッキー情報（値、長さ、形式）
- battlelogページのエンドポイント候補
- リクエストヘッダーの詳細
- Friends API 呼び出しテスト

を出力して、現在の実装との差分を確認します
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sf6_battlelog import (
    BattlelogCollector,
    BattlelogSiteClient,
    CapcomIdAuthenticator,
)


async def main():
    print("=" * 70)
    print("ログイン情報詳細診断スクリプト")
    print("=" * 70)

    # Step 1: buildId 取得
    print("\n[Step 1] buildId を取得...")
    try:
        site_client = BattlelogSiteClient()
        build_id = await site_client.get_build_id()
        print(f"✓ buildId: {build_id}")
        print(f"  長さ: {len(build_id)} 文字")
    except Exception as e:
        print(f"✗ エラー: {e}")
        return

    # Step 2: ログイン（環境変数から Cookie を取得）
    print("\n[Step 2] 認証クッキーを取得...")
    try:
        authenticator = CapcomIdAuthenticator()
        auth_cookie = await authenticator.login()
        print(f"✓ auth_cookie: {auth_cookie[:50]}...")
        print(f"  長さ: {len(auth_cookie)} 文字")
        print(f"  開始: {auth_cookie[:20]}")
        print(f"  終了: ...{auth_cookie[-20:]}")
    except Exception as e:
        print(f"✗ エラー: {e}")
        return

    # Step 3: API エンドポイント候補
    print("\n[Step 3] API エンドポイント候補")
    endpoints = [
        "https://www.streetfighter.com/6/buckler/api/fighters/{player_id}/matches",
        "https://api.streetfighter.com/v1/fighters/{player_id}/matches",
        "https://www.streetfighter.com/6/buckler/api/fighters",
        "https://www.streetfighter.com/6/api/fighters",
        "https://api.streetfighter.com/v1/fighters",
    ]
    for i, endpoint in enumerate(endpoints, 1):
        print(f"  {i}. {endpoint}")

    # Step 4: リクエストヘッダー確認
    print("\n[Step 4] リクエストヘッダーの詳細")
    headers_info = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": f"buckler_id={auth_cookie}",
        "X-Build-ID": build_id,
        "Accept": "application/json",
        "Referer": "https://www.streetfighter.com/6/buckler/",
    }
    print(json.dumps(headers_info, indent=2, ensure_ascii=False))

    # Step 5: 簡単なAPI呼び出しテスト
    print("\n[Step 5] API接続テスト（Friends API）")
    try:
        api_client = BattlelogCollector(
            build_id=build_id,
            auth_cookie=auth_cookie,
        )
        friends = await api_client.get_friends()
        print(f"✓ Friends API 成功")
        print(f"  レスポンスタイプ: {type(friends).__name__}")
        print(f"  レスポンスキー: {list(friends.keys())[:10]}")
    except BattlelogCollector.PageNotFound:
        print(f"! Friends API は存在しない (404)")
        print(f"  → 対戦ログAPIは存在する可能性があります")
    except BattlelogCollector.Unauthorized:
        print(f"✗ 認証エラー (401)")
        print(f"  → buildId または auth_cookie が無効かもしれません")
    except Exception as e:
        print(f"! その他のエラー: {type(e).__name__}: {e}")

    print("\n" + "=" * 70)
    print("診断完了")
    print("=" * 70)
    print("\n📋 確認事項:")
    print("  1. ✓ buildId が正常に取得できているか")
    print("  2. ✓ auth_cookie が正常に取得できているか（長さが充分か）")
    print("  3. ✓ Friends API の結果")
    print("     - 成功 → 認証OK、対戦ログAPI呼び出しテスト推奨")
    print("     - 404 → 対戦ログAPIエンドポイント異なる可能性")
    print("     - 401 → 認証情報に問題")
    print("\n🔧 buildId が取得されていない場合:")
    print("  → プロフィールページのHTML構造が変わった可能性")
    print("  → ブラウザで https://www.streetfighter.com/6/buckler/ を開いて")
    print("     __NEXT_DATA__ スクリプトタグを確認してください")
    print("\n🔧 auth_cookie が取得されていない場合:")
    print("  → クッキーの名前が 'buckler_id' でない可能性")
    print("  → ブラウザの開発者ツール → アプリケーション → クッキー で確認してください")


if __name__ == "__main__":
    asyncio.run(main())
