# ADR-032: Battlelog レポート生成ツール（AI分析連携用テキスト出力）

## ステータス

提案 - 2026-03-18

## 文脈

### 現状

`battlelog_replays.parquet` が R2 に保存されており、Web UI（DuckDB-WASM）でマッチアップチャートとして閲覧できる（ADR-030）。しかし、以下の用途に対応できていない：

- **月次振り返り**: 毎月の対戦データを俯瞰し、改善ポイントを特定したい
- **AI分析連携**: Claude等のLLMにデータを渡して、キャラ別・入力タイプ別の勝率傾向やLP変動から改善点を分析してもらいたい
- **テキスト形式での出力**: Web UIはブラウザ上での閲覧に特化しており、LLMへの入力に適したテキスト形式での出力手段がない

### 要件

1. R2 上の `battlelog_replays.parquet` をソースとして、期間指定でレポートを生成
2. マッチアップ結果（キャラ別・入力タイプ別の勝率）をMarkdown形式で出力
3. 指定期間内のLP変動（試合ごとの推移）をMarkdown形式で出力
4. 出力ファイルをそのままClaudeに渡して分析できる粒度・形式
5. `packages/` 配下に新しいパッケージとして配置
6. R2へのアクセスはADR-005のS3互換API方式を使用

### 利用シナリオ

```bash
# 月次レポート生成
uv run python main.py --from 2026-02-01 --to 2026-03-01

# 処理フロー:
# 1. R2から battlelog_replays.parquet をS3互換APIでダウンロード
# 2. DuckDB（Python版）で集計クエリ実行
# 3. Markdown形式のレポートファイルを出力
# 4. 出力ファイルをClaudeに渡して分析
```

## 選択肢

### 選択肢A: スタンドアロンPythonパッケージ（`packages/report-generator/`）

新規パッケージとしてDuckDB（Python版）を使い、CLIツールとして実装。

**構成**:
```
packages/report-generator/
├── pyproject.toml
├── src/
│   ├── main.py           # CLIエントリーポイント
│   ├── r2_client.py      # R2ダウンロード（ADR-005方式）
│   ├── query.py           # DuckDBクエリ
│   └── formatter.py       # Markdown出力フォーマッタ
└── output/                # 生成レポート出力先（.gitignore対象）
```

**依存関係**:
- `duckdb` — Parquetクエリ
- `boto3` — R2 S3互換アクセス
- `click` または `argparse` — CLI引数

### 選択肢B: `packages/local/` 内のサブコマンドとして追加

既存のローカルパッケージにレポート生成機能を追加。

### 選択肢C: Jupyter Notebook

`packages/local/notebooks/` にNotebookとして実装。

## 各選択肢の比較表

| 観点 | A: スタンドアロン | B: local内サブコマンド | C: Notebook |
|------|-------------------|----------------------|-------------|
| 関心の分離 | ◎ 独立した責務 | △ localに機能追加 | △ 分析用途と混在 |
| 依存関係 | ◎ 最小限 | △ local全体の依存が必要 | △ Jupyter依存 |
| CLI自動化 | ◎ 直接実行可能 | ○ main.pyにモード追加 | × 手動操作が必要 |
| R2アクセスコード再利用 | △ 一部再実装 | ◎ 既存コード利用可 | ○ import可能 |
| 保守性 | ◎ 変更影響が限定的 | △ local全体に影響 | △ |
| LLM連携 | ◎ ファイル出力→即連携 | ○ | △ セル実行が必要 |

## 結論

**選択肢A: スタンドアロンPythonパッケージ** を採用。

## 結論を導いた重要な観点

1. **関心の分離**: 動画処理パイプライン（`packages/local/`）とレポート生成は異なる責務。独立パッケージにすることで変更影響を最小化
2. **CLI自動化**: コマンド一発で実行→出力→LLM連携のワークフローが完結
3. **依存関係の最小化**: DuckDB + boto3 のみで軽量に動作。localパッケージのOpenCV等の重い依存を引き込まない
4. **R2クライアントの再実装コスト**: boto3の初期化コードは軽微（20-30行程度）であり、localパッケージへの結合を避ける価値がある

## 詳細設計

### 出力フォーマット

生成されるMarkdownレポートは以下の構成：

```markdown
# SF6 対戦レポート
期間: 2026-02-01 〜 2026-03-01
プレイヤー: ゆたにぃPC (1319673732)
生成日時: 2026-03-18 12:00:00

## サマリー
- 総試合数: 150
- 勝利: 85 / 敗北: 65
- 総合勝率: 56.7%
- LP変動: 12,500 → 13,200 (+700)

## マッチアップ結果

### 使用キャラ: ケン

| 対戦キャラ | 試合数 | 勝利 | 敗北 | 勝率 | C勝率 | M勝率 |
|-----------|--------|------|------|------|-------|-------|
| リュウ     | 15     | 10   | 5    | 66.7% | 70.0% (7/10) | 60.0% (3/5) |
| ルーク     | 12     | 5    | 7    | 41.7% | 40.0% (4/10) | 50.0% (1/2) |
| ...       |        |      |      |      |       |       |
| **合計**   | **150** | **85** | **65** | **56.7%** | | |

### 使用キャラ: （複数キャラ使用時は別テーブル）

...

## LP推移

| # | 日時 | 対戦キャラ | 結果 | LP | LP変動 |
|---|------|-----------|------|-----|--------|
| 1 | 02-01 20:15 | リュウ | WIN | 12,500 | - |
| 2 | 02-01 20:22 | ルーク | LOSS | 12,430 | -70 |
| 3 | 02-01 20:30 | ジュリ | WIN | 12,510 | +80 |
| ... | | | | | |
| 150 | 02-28 23:45 | JP | WIN | 13,200 | +65 |
```

### CLIインターフェース

```bash
# 基本的な使い方
uv run python main.py --from 2026-02-01 --to 2026-03-01

# オプション
uv run python main.py \
  --from 2026-02-01 \
  --to 2026-03-01 \
  --player-id 1319673732 \        # デフォルト: 設定ファイルまたは環境変数
  --battle-type ranked \           # ranked / battlehub / all（デフォルト: ranked）
  --output ./output/report.md \    # 出力先（デフォルト: ./output/YYYY-MM_report.md）
  --compare-prev                   # 前月比較を含める（オプション）
```

### R2アクセス

ADR-005の方式に従い、以下の環境変数を使用：
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`

`packages/local/` の既存コードと同じ環境変数名を使用することで、同一マシンでの`.env`共有が可能。

### DuckDBクエリ例

**マッチアップ集計**:
```sql
SELECT
  CASE WHEN p1_short_id = ? THEN p1_character_name
       ELSE p2_character_name END AS my_character,
  CASE WHEN p1_short_id = ? THEN p2_character_name
       ELSE p1_character_name END AS opponent_character,
  CASE WHEN p1_short_id = ? THEN p2_input_type
       ELSE p1_input_type END AS opponent_input_type,
  COUNT(*) AS total,
  SUM(CASE WHEN (p1_short_id = ? AND match_result = 'win')
            OR (p2_short_id = ? AND match_result = 'loss')
       THEN 1 ELSE 0 END) AS wins
FROM battlelog_replays
WHERE uploaded_at BETWEEN ? AND ?
GROUP BY my_character, opponent_character, opponent_input_type
ORDER BY my_character, total DESC
```

**LP推移**:
```sql
SELECT
  uploaded_at,
  CASE WHEN p1_short_id = ? THEN p2_character_name
       ELSE p1_character_name END AS opponent_character,
  CASE WHEN (p1_short_id = ? AND match_result = 'win')
        OR (p2_short_id = ? AND match_result = 'loss')
       THEN 'WIN' ELSE 'LOSS' END AS result,
  CASE WHEN p1_short_id = ? THEN p1_league_point
       ELSE p2_league_point END AS lp
FROM battlelog_replays
WHERE uploaded_at BETWEEN ? AND ?
ORDER BY uploaded_at ASC
```

### 前月比較（オプション `--compare-prev`）

`--compare-prev` 指定時、指定期間と同じ長さの前期間を自動計算し、差分を出力：

```markdown
## 前月比較
| 指標 | 前月 | 今月 | 差分 |
|------|------|------|------|
| 総試合数 | 120 | 150 | +30 |
| 勝率 | 52.5% | 56.7% | +4.2pt |
| LP変動 | +200 | +700 | +500 |

### キャラ別勝率変化（試合数5以上）
| 対戦キャラ | 前月勝率 | 今月勝率 | 変化 |
|-----------|---------|---------|------|
| リュウ     | 50.0%   | 66.7%   | +16.7pt |
| ルーク     | 55.0%   | 41.7%   | -13.3pt ⚠ |
```

## 帰結

### メリット
- LLMへの月次分析データ連携が自動化される
- 独立パッケージのため、動画処理パイプラインへの影響がゼロ
- DuckDB（Python版）により、Web UIと同等の集計をローカルで実行可能

### デメリット
- R2アクセスコードが `packages/local/` と一部重複する（軽微）
- 新しいパッケージの追加によるリポジトリの管理対象が増える

### 将来の拡張可能性
- Claude API連携を組み込み、レポート生成→分析を一気通貫で実行
- MCP Server化して、Claude Desktopから直接呼び出し
- 時系列グラフの画像出力（matplotlib等）を追加し、画像もLLMに渡す

## 実装チェックリスト

- [ ] `packages/report-generator/` パッケージ作成（pyproject.toml, src/）
- [ ] R2クライアント実装（S3互換API、Parquetダウンロード）
- [ ] DuckDBクエリ実装（マッチアップ集計、LP推移）
- [ ] Markdownフォーマッタ実装
- [ ] CLIインターフェース実装（argparse）
- [ ] 前月比較オプション実装（`--compare-prev`）
- [ ] 出力ディレクトリの.gitignore設定
- [ ] 動作確認（実データでのテスト）
