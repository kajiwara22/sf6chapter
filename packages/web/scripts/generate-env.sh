#!/usr/bin/env bash
#
# .mise.tomlから環境変数を抽出して.envファイルを作成
#
# Usage:
#   ./scripts/generate-env.sh                    # .envを生成
#   ./scripts/generate-env.sh output.env         # 出力先を指定
#   ./scripts/generate-env.sh --cloudflare-only  # Cloudflare用のみ表示

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$(dirname "$SCRIPT_DIR")"
MISE_TOML="$WEB_DIR/.mise.toml"

# Cloudflare Dashboard用の表示のみ
if [ "${1:-}" = "--cloudflare-only" ]; then
    if [ ! -f "$MISE_TOML" ]; then
        echo "❌ Error: .mise.toml not found at $MISE_TOML"
        exit 1
    fi

    echo "📋 Cloudflare Dashboard 環境変数設定用"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    gawk '
    BEGIN { in_env = 0 }
    /^\[env\]/ { in_env = 1; next }
    /^\[/ && in_env { in_env = 0 }
    in_env && /^[A-Z0-9_]+=/ {
        # 変数名と値を分離
        match($0, /^([A-Z0-9_]+)=(.*)$/, arr)
        var_name = arr[1]
        var_value = arr[2]

        # コメントを除去
        gsub(/#.*$/, "", var_value)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", var_value)

        # ダブルクォートを除去
        gsub(/^"|"$/, "", var_value)

        if (length(var_value) > 0) {
            printf "Variable name: %s\n", var_name
            printf "Value:         %s\n\n", var_value
        }
    }
    ' "$MISE_TOML"

    exit 0
fi

OUTPUT_FILE="${1:-$WEB_DIR/.env}"

# .mise.tomlの存在確認
if [ ! -f "$MISE_TOML" ]; then
    echo "❌ Error: .mise.toml not found at $MISE_TOML"
    exit 1
fi

echo "📂 Reading from: $MISE_TOML"
echo "✍️  Writing to: $OUTPUT_FILE"
echo ""

# .envファイルを生成
{
    echo "# Generated from .mise.toml"
    echo "# Generated at: $(date -Iseconds)"
    echo ""

    # [env]セクションから環境変数を抽出
    awk '
    BEGIN { in_env = 0 }
    /^\[env\]/ { in_env = 1; next }
    /^\[/ && in_env { in_env = 0 }
    in_env && /^[A-Z0-9_]+=/ {
        # 行全体を保存
        line = $0

        # コメント部分を抽出（行末の #... パターン）
        comment = ""
        if (match(line, /#.*$/)) {
            comment = substr(line, RSTART, RLENGTH)
            line = substr(line, 1, RSTART - 1)
        }

        # 行末の空白を削除
        gsub(/[[:space:]]+$/, "", line)

        # 変数定義があれば出力
        if (length(line) > 0) {
            if (length(comment) > 0) {
                printf "%s  %s\n", line, comment
            } else {
                print line
            }
        }
    }
    ' "$MISE_TOML"
} > "$OUTPUT_FILE"

echo "✅ Successfully generated $OUTPUT_FILE"
echo ""
echo "📋 Environment variables:"
grep -v "^#" "$OUTPUT_FILE" | grep -v "^$" || true
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💡 Cloudflare Dashboard での設定を表示:"
echo "   ./scripts/generate-env.sh --cloudflare-only"
