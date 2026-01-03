#!/bin/bash
set -e

# mise から環境変数を読み込み
eval "$(mise env)"

# .dev.vars を生成
cat > .dev.vars <<EOF
R2_ENDPOINT_URL=${R2_ENDPOINT_URL}
R2_ACCESS_KEY_ID=${R2_ACCESS_KEY_ID}
R2_SECRET_ACCESS_KEY=${R2_SECRET_ACCESS_KEY}
R2_BUCKET_NAME=${R2_BUCKET_NAME:-sf6-chapter-data-dev}
EOF

echo "✅ .dev.vars を生成しました"
