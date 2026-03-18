# SF6 Battlelog レポート生成ツール

R2上の `battlelog_replays.parquet` から期間指定でMarkdownレポートを生成し、Claude等のLLMに渡して分析するためのCLIツール。

## セットアップ

```bash
cd packages/report-generator
uv sync
```

## 環境変数

R2アクセスに必要（`--local` オプション使用時は不要）:

```
R2_ACCESS_KEY_ID=xxx
R2_SECRET_ACCESS_KEY=xxx
R2_ENDPOINT_URL=xxx.r2.cloudflarestorage.com
R2_BUCKET_NAME=sf6-chapter-data
```

## 使用方法

```bash
# 月次レポート生成（R2からダウンロード）
uv run python -m src.main --from 2026-02-01 --to 2026-03-01

# ローカルParquetファイルを使用
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --local ./path/to/battlelog_replays.parquet

# 前月比較付き
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --compare-prev

# 全バトルタイプ対象
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --battle-type all

# 出力先指定
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --output ./my_report.md
```

## 出力

`output/YYYY-MM_report.md` にMarkdownファイルが生成されます。

詳細は [ADR-032](../../docs/adr/032-battlelog-report-generator.md) を参照。
