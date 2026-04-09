# ADR-034: 対戦結果一覧ページの実装（SFBUFFライク + YouTubeリンク統合）

## ステータス

提案 - 2026-04-09

## 文脈

### 現状

[sfbuff.site](https://sfbuff.site/fighters/1319673732/matches) の対戦結果ページを日常的に参照している。このページでは以下の情報が一覧表示される：

| カラム | 内容 |
|--------|------|
| 私（プレイヤー名） | リンク付き |
| 使用キャラ | テキスト |
| 操作タイプ | C / M |
| 勝負 | win / loss（色分け） |
| 相手名 | リンク付き |
| 相手キャラ | テキスト |
| 相手操作タイプ | C / M |
| ゲームモード | ランクマッチ等 |
| リプレイID | SFBUFFの対戦詳細ページへのリンク |
| 試合日 | 相対時刻表示 |

フィルター機能：自キャラクター、自操作タイプ、相手キャラクター、相手操作タイプ、ゲームモード、日付範囲

### SFBUFFの制約

- 外部サービスであり、サービス停止のリスクがある
- リプレイIDのリンク先は SFBUFF の対戦詳細ページであり、YouTube 動画への直接リンクはない
- Cloudflare Turnstile 認証が毎回必要

### 活用可能な既存資産

**`battlelog_replays.parquet`**（ADR-030/031 で実装済み）:
- `replay_id`, `uploaded_at`, `battle_type`, `battle_type_name`
- `p1_character_name`, `p1_input_type`, `p1_short_id`, `p1_fighter_id`
- `p2_character_name`, `p2_input_type`, `p2_short_id`, `p2_fighter_id`
- `p1_league_point`, `p1_master_rating`, `p1_round_results`
- `match_result`（P1視点の win/loss/draw）

**`matches.parquet`**（既存のチャプターデータ）:
- `videoId`, `startTime` — YouTube リンク生成に必要
- `battlelogReplayId` — `battlelog_replays.replay_id` との結合キー

**既存の実装パターン**:
- `MY_PLAYER_ID = 1319673732` によるP1/P2視点の統一（ADR-030 マッチアップチャートで実装済み）
- DuckDB-WASM でのクライアントサイド SQL 実行
- Presigned URL 経由の Parquet 配信

## 決定

### 1. DuckDB-WASM で 2 つの Parquet を JOIN して対戦結果を表示

既にクライアントで `battlelog_replays` と `matches` の 2 テーブルがロードされているため、DuckDB-WASM の `LEFT JOIN` で結合する。事前マージの Parquet は作成しない。

**JOINクエリ例**:

```sql
SELECT
  -- 自分の情報（P1/P2を統一）
  CASE WHEN b.p1_short_id = 1319673732 THEN b.p1_character_name
       ELSE b.p2_character_name END AS my_character,
  CASE WHEN b.p1_short_id = 1319673732 THEN b.p1_input_type
       ELSE b.p2_input_type END AS my_input_type,
  -- 勝敗（自分視点に反転）
  CASE WHEN (b.p1_short_id = 1319673732 AND b.match_result = 'win')
       OR (b.p2_short_id = 1319673732 AND b.match_result = 'loss')
       THEN 'win' ELSE 'loss' END AS result,
  -- 相手の情報
  CASE WHEN b.p1_short_id = 1319673732 THEN b.p2_fighter_id
       ELSE b.p1_fighter_id END AS opponent_name,
  CASE WHEN b.p1_short_id = 1319673732 THEN b.p2_character_name
       ELSE b.p1_character_name END AS opponent_character,
  CASE WHEN b.p1_short_id = 1319673732 THEN b.p2_input_type
       ELSE b.p1_input_type END AS opponent_input_type,
  -- 共通情報
  b.battle_type_name,
  b.replay_id,
  b.uploaded_at,
  -- YouTube リンク（JOINで取得、NULL許容）
  m.videoId AS video_id,
  m.startTime AS start_time
FROM battlelog_replays b
LEFT JOIN matches m ON b.replay_id = m.battlelogReplayId
ORDER BY b.uploaded_at DESC
LIMIT 20 OFFSET ?
```

### 2. リプレイIDを YouTube チャプターへのリンクにする

- `LEFT JOIN` により `videoId` と `startTime` が取得できた場合:
  - `https://youtube.com/watch?v={videoId}&t={startTime}s` のリンクを表示
  - アイコンや色で YouTube リンクであることを視覚的に示す
- `videoId` が NULL の場合（配信されていない対戦）:
  - リプレイID をテキストのみで表示（リンクなし）

これが **SFBUFF との最大の差別化ポイント**。対戦結果から直接 YouTube の該当シーンに飛べる。

### 3. P1/P2 視点の統一

既存のマッチアップチャート（ADR-030）と同じパターンで、`MY_PLAYER_ID`（`p1_short_id` / `p2_short_id`）を使って「私」と「相手」を判定し、勝敗も自分視点に反転する。

### 4. フィルター機能

SFBUFFと同等のフィルターに加え、マッチアップチャート（ADR-030）と同様の**時間指定**にも対応する。

| フィルター | SQL条件 | 備考 |
|-----------|---------|------|
| 自キャラクター | `my_character = ?`（サブクエリまたは CASE WHEN） | |
| 自操作タイプ | `my_input_type = ?` | |
| 相手キャラクター | `opponent_character = ?` | |
| 相手操作タイプ | `opponent_input_type = ?` | |
| ゲームモード | `b.battle_type = ?` | |
| 開始日 | `b.uploaded_at >= ?` | YYYY-MM-DD |
| 終了日 | `b.uploaded_at <= ?` | YYYY-MM-DD |
| 開始時刻 | 開始日と組み合わせ | HH:MM（JST指定） |
| 終了時刻 | 終了日と組み合わせ | HH:MM（JST指定） |

**時間指定の挙動**（マッチアップチャートと同一）:
- 時刻はJSTで指定し、内部で UTC に変換して `uploaded_at` と比較する（`convertJstDateTimeToTimestamp` を共用）
- 時刻未指定時: 開始日は `00:00:00 JST`、終了日は `23:59:59 JST`
- 時刻指定時: 開始は `HH:MM:00 JST`、終了は `HH:MM:59 JST`
- 用途例: 「今日の夜の部だけ見たい」→ 開始時刻 `21:00`、終了時刻 `23:59` のように絞り込める

キャラクター選択肢は `battlelog_replays` テーブルから動的に取得（ADR-030 と同じ方式）。

### 5. ページネーション

DuckDB-WASM の `LIMIT ? OFFSET ?` で実装。1ページ20件（SFBUFFと同じ）。

### 6. UI の配置

既存の Web UI に新しいタブ「対戦履歴」として追加。既存の「チャプター検索」「マッチアップチャート」と並ぶ3つ目のビュー。

## 表示カラム

| カラム | 内容 | 備考 |
|--------|------|------|
| 使用キャラ | 自キャラクター名 | P1/P2統一済み |
| 操作タイプ | C / M | `input_type`: 0→C, 1→M |
| 勝負 | win / loss | 色分けバッジ、自分視点に反転済み |
| 相手名 | fighter_id | |
| 相手キャラ | 相手キャラクター名 | |
| 相手操作タイプ | C / M | |
| ゲームモード | battle_type_name | |
| リプレイID / YouTube | リンク | YouTube リンクがある場合はYouTubeアイコン付き |
| 試合日 | uploaded_at | 相対時刻表示 |

## 選択肢の比較

### データ結合方式

#### 選択肢A: DuckDB-WASM でクライアントサイド JOIN（採用）

| 観点 | 評価 |
|------|------|
| 実装コスト | ○ 既存の2テーブルをそのまま使える |
| データ整合性 | ◎ 常に最新のデータで結合 |
| 柔軟性 | ◎ JOINの有無で表示を切り替え可能 |
| パフォーマンス | ○ データ量が少ないため問題なし |
| ファイル管理 | ◎ 新しいParquetファイルの追加不要 |

#### 選択肢B: 事前マージ済み Parquet を新規作成

| 観点 | 評価 |
|------|------|
| 実装コスト | △ 変換スクリプトの作成・メンテナンスが必要 |
| データ整合性 | △ マージタイミングのずれが発生しうる |
| 柔軟性 | △ スキーマ変更時に変換スクリプトも更新必要 |
| パフォーマンス | ◎ JOINが不要で高速 |
| ファイル管理 | △ R2に3つ目のParquetファイルが追加される |

### YouTube リンクの表示方式

#### 選択肢A: YouTube リンクがある場合のみリンク表示（採用）

`LEFT JOIN` を使い、`matches` テーブルにマッチする行がある場合のみ YouTube リンクを表示。ない場合はリプレイIDのテキスト表示。

#### 選択肢B: SFBUFF へのフォールバックリンク

YouTube リンクがない場合に `https://sfbuff.site/battles/{replay_id}` へのリンクを表示。外部依存が増えるため不採用。

## トレードオフと帰結

### メリット

- SFBUFF と同等の対戦結果一覧を自前で確認できる
- **リプレイIDから YouTube の該当チャプターに直接ジャンプ可能**（SFBUFF にはない機能）
- 既存のアーキテクチャ（Parquet + DuckDB-WASM）をフル活用し、新規データパイプラインの追加が不要
- P1/P2 視点統一の実装パターンが既に確立済み（ADR-030）

### デメリット・注意点

- **YouTube リンクの網羅性**: すべての対戦に YouTube 動画があるわけではない（非配信日、PS5アップロード漏れなど）。YouTube リンクがない対戦が一定数存在する
- **データ鮮度**: SFBUFF ほどリアルタイムではない。`main.py` パイプライン実行タイミングに依存
- **プレイヤーID固定**: `MY_PLAYER_ID` がハードコード（ADR-030 と同様）
- **2ファイルのダウンロード**: `battlelog_replays.parquet` と `matches.parquet` の両方をロードする必要があるが、両テーブルは既存機能でロード済みのため追加コストは実質なし

### 互換性

- 既存の「チャプター検索」「マッチアップチャート」機能に影響なし
- 新しいParquetファイルやAPIエンドポイントの追加は不要
- DuckDB-WASM の同一インスタンスで既存2テーブルを JOIN するだけ

## 実装チェックリスト

- [ ] `packages/web/src/shared/types.ts`: 対戦履歴関連の型定義追加（`MatchHistoryRow`, `MatchHistoryFilters`）。フィルターに `timeFrom` / `timeTo`（HH:MM、JST）を含める（`MatchupChartFilters` と同様）
- [ ] `packages/web/src/client/search.ts`: 対戦履歴クエリ関数追加（JOIN + P1/P2統一 + フィルター + ページネーション）。時間フィルターは既存の `convertJstDateTimeToTimestamp` を共用
- [ ] `packages/web/src/client/search.ts`: 対戦履歴用キャラクターリスト取得関数追加
- [ ] `packages/web/src/client/components/MatchHistory.ts`: 対戦履歴テーブル UI コンポーネント作成
- [ ] `packages/web/src/client/components/MatchHistoryFilters.ts`: フィルターフォーム UI コンポーネント作成
- [ ] `packages/web/src/server/routes/pages.tsx`: 「対戦履歴」タブの追加
- [ ] YouTube リンク表示: `videoId` が存在する行はYouTubeアイコン付きリンク、NULL行はテキスト表示

## 関連ADR

- [ADR-002: データ保存・検索基盤](002-data-storage-search.md) - Parquet + DuckDB-WASM の基盤設計
- [ADR-010: Parquetデータ取得方式（Presigned URL）](010-parquet-presigned-url.md) - Presigned URL パターン
- [ADR-021: YouTubeチャプターとBattlelogリプレイのマッピング実装](021-battlelog-chapter-mapping-implementation.md) - `battlelogReplayId` の由来
- [ADR-023: Battlelogデータ統合とParquet Web検索機能の実装](023-battlelog-data-integration-with-parquet-search.md) - 既存の Battlelog-Web 連携
- [ADR-030: Battlelogキャッシュデータを活用したマッチアップチャート機能](030-matchup-chart-from-battlelog-cache.md) - P1/P2視点統一パターン、`MY_PLAYER_ID`
- [ADR-031: Battlelog Parquet 変換・アップロードの main.py パイプライン統合](031-battlelog-parquet-pipeline-integration.md) - データパイプライン
