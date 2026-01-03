#!/bin/bash
# ローカルR2にテストデータをアップロード

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
R2_DIR="$PROJECT_ROOT/.wrangler/state/v3/r2/sf6-chapter-data-dev"

echo "📦 ローカルR2ディレクトリを作成: $R2_DIR"
mkdir -p "$R2_DIR/index"

echo "📝 テストデータ（matches.parquet）を作成"

# DuckDBでサンプルParquetを生成
cat > /tmp/create_test_parquet.sql <<'EOF'
CREATE TABLE matches AS
SELECT
    'test_video_001' AS videoId,
    'test_001_' || row_number() OVER () AS id,
    (row_number() OVER () - 1) * 180 AS startTime,
    (row_number() OVER () - 1) * 180 + 120 AS endTime,
    CASE (row_number() OVER () % 5)
        WHEN 0 THEN 'Ryu'
        WHEN 1 THEN 'Ken'
        WHEN 2 THEN 'Chun-Li'
        WHEN 3 THEN 'Guile'
        WHEN 4 THEN 'JP'
    END AS player1_character,
    CASE ((row_number() OVER () + 1) % 5)
        WHEN 0 THEN 'Ryu'
        WHEN 1 THEN 'Ken'
        WHEN 2 THEN 'Chun-Li'
        WHEN 3 THEN 'Guile'
        WHEN 4 THEN 'JP'
    END AS player2_character,
    'left' AS player1_side,
    'right' AS player2_side,
    '2026-01-' || LPAD((row_number() OVER () % 30 + 1)::VARCHAR, 2, '0') || 'T12:00:00Z' AS detectedAt,
    0.95 AS confidence
FROM generate_series(1, 20);

COPY matches TO '$R2_DIR/index/matches.parquet' (FORMAT PARQUET);
EOF

# DuckDBがインストールされているか確認
if ! command -v duckdb &> /dev/null; then
    echo "❌ DuckDB がインストールされていません"
    echo ""
    echo "インストール方法:"
    echo "  macOS: brew install duckdb"
    echo "  Linux: https://duckdb.org/docs/installation/"
    exit 1
fi

# Parquet生成
echo "🦆 DuckDBでテストデータを生成中..."
duckdb < /tmp/create_test_parquet.sql

# 構造体フィールドに変換（手動での修正が必要な場合）
# 注: DuckDBの制約により、ネストした構造体を直接生成できない場合は
# Python/Node.jsで生成することを推奨

echo "✅ テストデータのアップロード完了"
echo ""
echo "📍 ファイル: $R2_DIR/index/matches.parquet"
echo ""
echo "次のコマンドでアプリケーションを起動:"
echo "  cd $PROJECT_ROOT"
echo "  pnpm dev"
