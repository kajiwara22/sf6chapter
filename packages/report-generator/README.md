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

# 時間帯別勝率分析付き（JST換算、1時間単位）
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --hourly-analysis

# ラウンドスコア分析付き（1R別・1P/2P別・3R勝率・決まり手）
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --round-analysis

# バックラー公開統計と比較（同ランク帯の平均勝率をマッチアップ表に追加）
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --external-stats

# 統計の対象月・ランクを明示（省略時はレポート末日時点の最新公開月／Battlelog から推定）
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --external-stats --stats-month 202508 --stats-rank 5

# ローカルの統計 Parquet を使う（R2 ダウンロードをスキップ。検証用）
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --external-stats --stats-dir ../local/tmp/sf6_stats/stats

# 動画（配信）単位のレポート。その配信に含まれる試合だけを集計する
uv run python -m src.main --video-id ovM5BMIsyKw --external-stats
```

### 動画単位のレポート（`--video-id`）

`matches.parquet` の `battlelogReplayId` を介して `battlelog_replays` を絞り込むため、
期間ではなく「その配信で実際に対戦した試合」に一致します。

- 出力先の既定は `output/{video_id}_report.md`
- `--from` / `--to` は不要（指定しない）
- `--hourly-analysis` / `--round-analysis` / `--compare-prev` は未対応
- `--external-stats` と併用可能（同ランク帯平均をマッチアップ表に追加）

# 複数オプションの組み合わせ
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --hourly-analysis --compare-prev

# 全バトルタイプ対象
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --battle-type all

# 出力先指定
uv run python -m src.main --from 2026-02-01 --to 2026-03-01 --output ./my_report.md
```

## 出力

`output/YYYY-MM_report.md` にMarkdownファイルが生成されます。

### セクション構成

| セクション | 条件 |
|-----------|------|
| サマリー | 常時出力 |
| マッチアップ結果 | 常時出力 |
| LP推移 | 常時出力 |
| 時間帯別勝率（JST） | `--hourly-analysis` 指定時のみ |
| ラウンドスコア分析 | `--round-analysis` 指定時のみ |
| 動画単位の集計 | `--video-id` 指定時 |
| 同ランク帯平均（マッチアップ表内） | `--external-stats` 指定時のみ |
| 前期間比較 | `--compare-prev` 指定時のみ |

### バックラー公開統計との比較（`--external-stats`）

バックラーの公開統計（R2 の `stats/matchup_*.parquet`、ADR-072）を読み、
マッチアップ表に「同ランク帯平均」「差分」の列を追加します。

- 対象月は省略時、レポート末日時点で公開済みの最新月（毎月第二木曜に先月分が公開）
- 比較ランクは省略時、Battlelog の直近ランクマッチの LP / MR から推定（推定できなければ MASTER）
- 自分側の操作タイプ（Classic / Modern）は区別せず平均
- ミラー（同じキャラ同士）は勝率の意味がないため集計から除外
- `score`（相性スコア）は勝率ではないため比較には使わない。勝率は `_dsort` 由来

### ラウンドスコア分析（`--round-analysis`）

`battlelog_replays.parquet` だけで集計します（`round_stats.parquet` は不要）。

- **1R の勝敗と試合勝率**: 1Rを取った/落とした試合の勝率と差
- **1P / 2P 別**: サイド別の勝率と 3R 勝率
- **1-1 から 3R に入った試合**: フルラウンド率と 3R 勝率
- **決まり手**: 自分が取ったラウンド／落としたラウンドの内訳（V / C / T / OD / SA / CA / P）

`round_results` の値は ADR-037 の規則（`0`=LOSS、`4`=DRAW、それ以外=WIN）で解釈し、
自分の side に正規化してから集計します。`round_results` が空・不正・両者でラウンド数が
一致しない試合は除外しています。

詳細は [ADR-032](../../docs/adr/032-battlelog-report-generator.md)・[ADR-035](../../docs/adr/035-hourly-win-rate-analysis-in-report-generator.md) を参照。
