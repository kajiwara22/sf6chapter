# ADR-030: Battlelogキャッシュデータを活用したマッチアップチャート機能

## ステータス

提案 - 2026-03-08

## 文脈

### 現状

sfbuff.site では、プレイヤーのマッチアップチャート（キャラ別勝敗表）を期間指定で閲覧できる。例：
```
https://sfbuff.site/fighters/1319673732/matchup_chart?played_from=2025-12-22&played_to=2026-01-28
```

しかし sfbuff は外部サービスであり、以下の制約がある：
- データの取得タイミングや更新頻度が不明
- サービス停止のリスク
- 自分のデータと YouTube チャプターデータとの連携ができない

### 活用可能な既存資産

`packages/local/battlelog_cache.db`（SQLite）に Battlelog API のリプレイデータをキャッシュ済み（ADR-022）。現在314件、約3週間分のデータを保持。

各リプレイレコードには以下の情報が含まれる：
- 両プレイヤーのキャラクター（`character_id`, `character_name`）
- 入力タイプ（`battle_input_type`: 0=クラシック, 1=モダン）
- ラウンド結果（`round_results`: 各ラウンドの勝敗配列）
- 対戦日時（`uploaded_at`: UNIXタイムスタンプ）
- マッチタイプ（`replay_battle_type`: 1=Ranked, 3=Battle Hub, 4=Custom Room）
- LP・ランク情報（`league_point`, `league_rank`）

### 既存Webアーキテクチャ

`packages/web/` は以下の構成で動作している：
- **サーバー**: Hono（Cloudflare Pages Functions）
- **データ配信**: R2 → Presigned URL → クライアントでダウンロード
- **クエリ**: DuckDB-WASM でクライアント側 SQL 実行
- **データ形式**: Parquet

この既存パターンに沿って、Battlelog データも同様の方式で配信・クエリできる。

## 決定

### 1. Battlelogキャッシュデータを Parquet に変換し R2 にアップロード

ローカル処理パイプラインに、`battlelog_cache.db` → Parquet 変換ステップを追加する。

**Parquet スキーマ（`battlelog_replays.parquet`）**:

| カラム | 型 | 説明 |
|--------|------|------|
| `replay_id` | STRING | リプレイID |
| `uploaded_at` | TIMESTAMP | 対戦日時 |
| `battle_type` | INT32 | マッチタイプ（1=Ranked, 3=BattleHub, 4=CustomRoom） |
| `battle_type_name` | STRING | マッチタイプ名 |
| `p1_character_id` | INT32 | P1キャラクターID |
| `p1_character_name` | STRING | P1キャラクター名 |
| `p1_input_type` | INT32 | P1入力タイプ（0=クラシック, 1=モダン） |
| `p1_league_point` | INT32 | P1 LP |
| `p1_league_rank` | INT32 | P1 ランク |
| `p1_master_rating` | INT32 | P1 マスターレーティング |
| `p1_short_id` | INT64 | P1 プレイヤーID |
| `p1_fighter_id` | STRING | P1 ファイター名 |
| `p1_round_results` | STRING | P1 ラウンド結果（JSON配列） |
| `p2_*` | 同上 | P2の各フィールド |
| `match_result` | STRING | P1視点の勝敗（"win" / "loss" / "draw"） |

**勝敗判定ロジック**:
- `round_results` の合計値が多い方が勝利
- P1の勝ちラウンド数 > P2の勝ちラウンド数 → `"win"`
- P1の勝ちラウンド数 < P2の勝ちラウンド数 → `"loss"`
- 同数 → `"draw"`

### 2. Web UI にマッチアップチャートページを追加

既存の SPA に新しいビュー（タブまたはページ）としてマッチアップチャートを追加。

**表示内容**:
- キャラクター別の勝敗数・勝率テーブル
- 入力タイプ別の内訳（クラシック / モダン）
- 合計行

**フィルター**:
- 期間指定（開始日・終了日）
- 自キャラクター選択
- マッチタイプ（Ranked / Battle Hub / Custom Room / All）
- 入力タイプ（クラシック / モダン / All）

**集計クエリ例**（DuckDB-WASM で実行）:
```sql
SELECT
  CASE WHEN p1_short_id = 1319673732 THEN p2_character_name
       ELSE p1_character_name END AS opponent_character,
  CASE WHEN p1_short_id = 1319673732 THEN p2_input_type
       ELSE p1_input_type END AS opponent_input_type,
  COUNT(*) AS total,
  SUM(CASE WHEN (p1_short_id = 1319673732 AND match_result = 'win')
            OR (p2_short_id = 1319673732 AND match_result = 'loss')
       THEN 1 ELSE 0 END) AS wins,
  COUNT(*) - SUM(...) AS losses
FROM battlelog_replays
WHERE uploaded_at BETWEEN ? AND ?
GROUP BY opponent_character, opponent_input_type
ORDER BY total DESC
```

### 3. API エンドポイント追加

既存パターンに従い、Presigned URL エンドポイントを追加：

```
GET /api/data/index/battlelog_replays.parquet
  → { url: "https://r2...presigned", expiresIn: 3600 }
```

### 4. データパイプライン

```
battlelog_cache.db (SQLite)
  → convert_battlelog_to_parquet.py（新規スクリプト）
  → battlelog_replays.parquet
  → R2アップロード（既存の upload_to_r2.py を拡張）
```

このスクリプトは既存の `main.py` パイプラインに組み込むか、独立して実行可能にする。

## 選択肢の比較

### データ配信方式

#### 選択肢A: Parquet + DuckDB-WASM（採用）

| 観点 | 評価 |
|------|------|
| 既存パターンとの一貫性 | ◎ 既存の matches.parquet と同じ方式 |
| クエリの柔軟性 | ◎ DuckDB-WASM で任意の集計が可能 |
| 実装コスト | ○ 既存インフラを再利用 |
| パフォーマンス | ○ Parquet のカラムナ形式で集計に有利 |

#### 選択肢B: SQLite を直接 R2 にアップロードし sql.js で実行

| 観点 | 評価 |
|------|------|
| 既存パターンとの一貫性 | △ 新しいライブラリ追加が必要 |
| クエリの柔軟性 | ◎ SQLite の全機能が使える |
| 実装コスト | △ sql.js の追加と初期化が必要 |
| パフォーマンス | △ SQLite はカラムナ形式でないため集計が遅い |

#### 選択肢C: サーバーサイドで集計して JSON API で返す

| 観点 | 評価 |
|------|------|
| 既存パターンとの一貫性 | △ 現在のクライアント側クエリ方式と異なる |
| クエリの柔軟性 | △ API で提供する集計パターンに限定 |
| 実装コスト | △ サーバー側のロジック追加が多い |
| パフォーマンス | ○ サーバー側で処理、クライアント負荷低 |

## トレードオフと帰結

### メリット

- sfbuff に依存せず、自分のデータで自由に分析可能
- 既存の Web アーキテクチャ（Parquet + DuckDB-WASM）を再利用でき、実装コストが低い
- YouTube チャプターデータとの将来的な連携が可能（同一ページ内）
- 期間指定やフィルターを自由にカスタマイズ可能

### デメリット・注意点

- **データ量の制約**: キャッシュに存在するデータのみ表示可能。過去の取得漏れ期間は空白になる
- **プレイヤーID固定**: 現時点では自分（`1319673732`）のデータのみ。将来的に複数プレイヤー対応する場合はフィルターの拡張が必要
- **データ更新頻度**: Parquet の R2 アップロードタイミングに依存。リアルタイムではない
- **Parquet ファイルサイズ**: 現在314件で極めて小さいが、データ量増加時も Parquet の圧縮効率で問題にならない見込み

### 互換性

- 既存の対戦検索機能（matches.parquet）に影響なし
- 新しい Parquet ファイル（`battlelog_replays.parquet`）を独立して追加
- DuckDB-WASM インスタンスで複数テーブルを同時に扱える

## 実装チェックリスト

- [ ] `packages/local/convert_battlelog_to_parquet.py`: SQLite → Parquet 変換スクリプト作成
- [ ] `packages/local/upload_to_r2.py`: `battlelog_replays.parquet` のアップロード対応追加
- [ ] `packages/web/src/server/routes/api.ts`: `/api/data/index/battlelog_replays.parquet` エンドポイント追加
- [ ] `packages/web/src/client/search.ts`: DuckDB-WASM で `battlelog_replays` テーブルの登録・クエリ追加
- [ ] `packages/web/src/client/components/MatchupChart.ts`: マッチアップチャート UI コンポーネント作成
- [ ] `packages/web/src/client/components/SearchForm.ts`: マッチアップチャート用フィルター追加（期間、キャラ、マッチタイプ）
- [ ] `packages/web/src/server/routes/pages.tsx`: マッチアップチャートページまたはタブの追加
- [ ] `packages/web/src/shared/types.ts`: マッチアップチャート関連の型定義追加

## 関連ADR

- [ADR-002: データ保存・検索基盤](002-data-storage-search.md) - Parquet + DuckDB-WASM の基盤設計
- [ADR-010: Parquetデータ取得方式（Presigned URL）](010-parquet-presigned-url.md) - Presigned URL パターン
- [ADR-020: SF6 Battlelog対戦ログ収集システムの実装](020-sf6-battlelog-collector-implementation.md) - Battlelog データ収集
- [ADR-022: Battlelog API キャッシング機構（SQLite）](022-battlelog-api-caching-with-sqlite.md) - キャッシュDB の設計
- [ADR-023: Battlelogデータ統合とParquet Web検索機能の実装](023-battlelog-data-integration-with-parquet-search.md) - 既存の Battlelog-Web 連携
