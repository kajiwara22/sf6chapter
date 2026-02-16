#!/bin/bash
# Street Fighter 6 対戦ログページ取得スクリプト
#
# 使用方法:
#   export BUCKLER_ID_COOKIE="your-buckler-id-cookie"
#   export BUILD_ID="your-build-id"
#   export PLAYER_ID="1319673732"  # オプション（デフォルト: 1319673732）
#   ./getLog.bash
#
# 環境変数:
#   BUCKLER_ID_COOKIE: 認証用 buckler_id クッキー (必須)
#   BUILD_ID: Next.js buildId (オプション)
#   PLAYER_ID: プレイヤーID (デフォルト: 1319673732)

set -e

# 環境変数の確認
if [ -z "$BUCKLER_ID_COOKIE" ]; then
    echo "❌ エラー: BUCKLER_ID_COOKIE 環境変数が設定されていません"
    echo ""
    echo "使用方法:"
    echo "  export BUCKLER_ID_COOKIE='your-cookie-value'"
    echo "  export BUILD_ID='your-build-id'  # オプション"
    echo "  export PLAYER_ID='1319673732'    # オプション"
    echo "  ./getLog.bash"
    exit 1
fi

# デフォルト値
PLAYER_ID="${PLAYER_ID:-1319673732}"
BUILD_ID_HEADER=""

# BUILD_ID が設定されていればヘッダーに追加
if [ -n "$BUILD_ID" ]; then
    BUILD_ID_HEADER="-H 'X-Build-ID: $BUILD_ID'"
    echo "ℹ️  Build ID: $BUILD_ID"
fi

echo "ℹ️  Player ID: $PLAYER_ID"
echo "ℹ️  Cookie長: ${#BUCKLER_ID_COOKIE} 文字"
echo "ℹ️  リクエスト開始..."
echo ""

# Curlリクエスト実行
eval "curl -O 'https://www.streetfighter.com/6/buckler/ja-jp/profile/$PLAYER_ID/battlelog' \
  -H 'accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7' \
  -H 'accept-language: ja,en-US;q=0.9,en;q=0.8' \
  -H 'cache-control: no-cache' \
  -b \"buckler_id=$BUCKLER_ID_COOKIE\" \
  $BUILD_ID_HEADER \
  -H 'user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36'"

echo ""
echo "✓ ダウンロード完了"
echo "  ファイル: battlelog"
