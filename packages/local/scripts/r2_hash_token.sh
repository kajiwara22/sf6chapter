#!/bin/bash
# r2_hash_token.sh - R2トークンValueをSHA-256ハッシュ化
#
# 使用方法:
#   chmod +x r2_hash_token.sh
#   ./r2_hash_token.sh

echo "R2 Token Value to SHA-256 Hash Converter"
echo "=========================================="
echo ""
echo "このスクリプトはCloudflare R2のAPIトークンValueをSHA-256ハッシュ化します。"
echo "ハッシュ化された値を R2_SECRET_ACCESS_KEY として .env に設定してください。"
echo ""
echo -n "Enter your R2 Token Value: "
read -s TOKEN_VALUE
echo ""
echo ""

# SHA-256ハッシュを計算（小文字）
if command -v shasum &> /dev/null; then
    # macOS/Linux (shasum available)
    SECRET_ACCESS_KEY=$(echo -n "$TOKEN_VALUE" | shasum -a 256 | awk '{print $1}')
elif command -v sha256sum &> /dev/null; then
    # Linux (sha256sum available)
    SECRET_ACCESS_KEY=$(echo -n "$TOKEN_VALUE" | sha256sum | awk '{print $1}')
else
    echo "エラー: shasum または sha256sum コマンドが見つかりません"
    exit 1
fi

echo "Results:"
echo "--------"
echo "Secret Access Key (use this in .env):"
echo "$SECRET_ACCESS_KEY"
echo ""
echo "Add to your .env file:"
echo "R2_SECRET_ACCESS_KEY=$SECRET_ACCESS_KEY"
echo ""
echo "Note: Token ID (not Value) を R2_ACCESS_KEY_ID に設定してください"
