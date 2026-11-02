# ADR-072: バックラー公開統計の R2 統合と公開 MCP のローカル限定化

## ステータス

採用 - 2026-11-02

## 文脈

### 現状

別リポジトリ [sf6-stats-mcp-server](https://github.com/kajiwara22/sf6-stats-mcp-server) で、Buckler's Boot Camp（以下バックラー）の公開統計を Cloudflare Workers + D1 の MCP サーバーとして配信している。

| ツール | 内容 | データ源 |
|---|---|---|
| `sf6_character_usage` | キャラクター使用率（年・月・ロケール・操作タイプ・リーグ別） | バックラー `stats/usagerate` を D1 にキャッシュ |
| `sf6_matchup_diagram` | キャラ別・相手別の勝率表（ランク・入力タイプ・月別） | バックラー `stats/dia` を D1 に投入した `matchup_stats` / `matchup_details` |

D1 へは GitHub Actions（`.github/workflows/monthly-import.yml`）が毎月第二木曜に `wrangler d1 execute --remote` で書き込む。

### 問題

1. **D1 無料枠の消費**: Workers Free の D1 は rows read 5,000,000/日・rows written 100,000/日・storage 5GB（DB あたり 500MB）。2026-09-01 以降、上限超過時はクエリ自体が失敗する。月次インポートの**書き込み**で警告が出ている。
2. **公開需要が未成立**: 公開 MCP としての利用者がほとんどいない。枠だけを消費している。
3. **データの二重管理**: sf6-chapter 側には R2 + Parquet + DuckDB-WASM の分析基盤（ADR-002, ADR-010, ADR-023, ADR-030）が既にあり、同じバックラー由来データを別基盤で持つ理由が薄い。
4. **読み取りも非効率**: `COUNT(*)` によるレンジスキャンと `SELECT DISTINCT data_month` の全走査で、1リクエストあたり数百〜数万行を読む。

### 実測（2026-11-02 に 202508 の dia API で確認）

| 項目 | 値 |
|---|---|
| ランク数 | 8 |
| キャラクター数（入力タイプ込み records） | 54 |
| `matchup_stats` 行数/月 | 432 |
| `matchup_details` 行数/月（values 合計） | 23,328 |
| **合計** | **23,760 行/月** |
| `characters` の `INSERT OR IGNORE`（毎回） | 432 行 |
| dia API レスポンスサイズ | 4.3 MB |

書き込みの試算:

| ケース | 行数 | 無料枠 100,000/日 に対する比率 |
|---|---|---|
| 新規月のインポート | 23,760 | 24% |
| 既存月の再実行（`INSERT OR REPLACE` = 削除 + 挿入） | 最大 47,520 | 48% |
| 33ヶ月のバックフィル（2023-06〜） | 約 784,000 | **784%（1日では完了不可）** |

読み取りの試算（`sf6_matchup_diagram` 1回）:

| クエリ | 行数 |
|---|---|
| `checkCharacterExists`（`LOWER()` で全走査） | 28 |
| `SELECT COUNT(*) FROM matchup_stats WHERE data_month = ?` | 448 |
| `matchup_details` 取得 | 56 |
| `ranks` | 1 |
| **合計** | **約 535** |
| データ月が存在しない場合（`SELECT DISTINCT data_month`） | **+約 15,000** |

### データの意味に関する重要な発見（既存実装の誤り）

dia API のマッチアップ値には似た形の数値が複数あり、意味が異なる。

| フィールド | 実体 | 実測レンジ（202508） | 例 |
|---|---|---|---|
| `_dsort` | **実際の勝率**（0〜1） | 0.399〜0.660 | 0.4678 = 46.8% |
| `val` | **相性スコア（10点満点）** | 0.0〜10.0（平均 5.005） | `5.320` = 5.32点 |
| `total` | キャラの総合評価値（10点満点、実測は `_win_rate × 10`） | 0.0〜10.0 | `5.120` |
| `records[]._win_rate` | キャラの総合勝率（0〜1） | 0.4〜0.6 | 0.512 |

`val` と `_dsort` の相関は **-0.388** で、`val` が高いほど勝率は低い。つまり `val` は「こちらが有利か」を表す値ではなく、**その対戦相手に対する相性スコア（10点満点、5.0 が基準）**であり、値が高いほどこちらが勝ちにくい。

既存の `scripts/import-sf6-data.ts` は `win_rate = val / 10` として保存しており、**勝率として符号の逆の値を入れている**。`sf6_matchup_diagram` の「有利/不利」表示もこの値に依存するため、実態と逆になりうる。本 ADR の移行時に `_dsort` へ切り替える。

欠損表現は3種類ある。

| 表現 | 件数（202508・全ランク） | 意味 | 扱い |
|---|---|---|---|
| `-` | 432 | ミラー（自分自身。`_oid` = 自分） | 行は残し、集計では除外 |
| `-.---` | 15 | サンプル不足 | `score` を NULL |
| `0.0` | 実データ | 相性スコア 0 点 | **NULL にしない**（欠損と区別） |

`val` は 0.0〜10.0 に実値として 0 が現れるため、欠損を 0 に潰すと「最悪の相性」と「データなし」が混ざる。NULL で保持すれば、SQL の `AVG()` は NULL を無視し、`COUNT(col)` は非 NULL のみを数えるため、除外条件を書かずに正しく集計できる。

## 要件

1. D1 の無料枠消費を実質ゼロにする（書き込み・読み取りとも）
2. バックラー公開統計を sf6-chapter の分析基盤（R2 / Parquet）に一元化する
3. report-generator・Web・動画解析後のレポートから同じデータを参照できるようにする
4. 月次更新（第二木曜に先月分が公開）に追随する
5. 既存の MCP ツールによる利用はローカル環境で継続できるようにする

## 選択肢

### 選択肢A: D1 を継続し、書き込みだけを削減する

`matchup_details` を廃止し、`matchup_stats` の1行に相手別勝率を JSON 列で持たせる。月次の書き込みは 432 行（**1/55**）に減り、`COUNT(*)` を `EXISTS ... LIMIT 1` に、`DISTINCT data_month` をメタテーブルに置き換えれば読み取りも約 4 行/req まで落ちる。

**変更範囲**: sf6-stats-mcp-server 内のスキーマ・インポートスクリプト・2ツール。

### 選択肢B: 統計を R2 の Parquet に移し、D1 を廃止する（MCP はローカル限定）

`packages/local` にバックラー統計の collector を追加し、月次で JSON → Parquet に変換して R2（`stats/` プレフィックス）へ配置する。D1 は使わない。公開 MCP は停止し、ローカルの stdio MCP（`scripts/local-mcp-server.ts`）で継続する。

**変更範囲**: sf6-stats-mcp-server（D1 削除・ローカル化）、packages/local（collector）、report-generator（参照）、packages/web（表示）。

### 選択肢C: D1 を R2 に置き換え、公開 MCP は R2 直読みで継続する

B と同じデータ配置にし、Workers は R2 の Parquet / JSON を返すだけの薄いアダプタにする。公開は継続。

**変更範囲**: B に加えて Workers の実装差し替えとレート制限・濫用対策。

### 選択肢D: プロジェクトを廃止する

統計の参照は手動（バックラーサイト）に戻す。

## 各選択肢の比較表

| 観点 | A: D1 継続＋削減 | B: R2 統合＋ローカル化 | C: R2 統合＋公開継続 | D: 廃止 |
|---|---|---|---|---|
| D1 書き込み | 432 行/月（1/55） | **0** | **0** | 0 |
| D1 読み取り | 約 4 行/req | **0** | **0** | 0 |
| 無料枠リスク | 低（残る） | **なし** | なし | なし |
| データの一元化 | ✕ 二重管理が残る | **◎ R2 に統合** | ◎ | − |
| report-generator / Web 連携 | △ 別基盤のまま | **◎ 同一 Parquet を DuckDB で参照** | ◎ | ✕ |
| 公開 MCP | 維持 | 停止（ローカルで継続） | 維持 | 停止 |
| 実装コスト | 小（半日） | 中（2〜3日） | 中〜大（+Worker 改修） | 極小 |
| 公開需要が生まれたとき | そのまま | R2 直読みで復活可能 | そのまま | 再構築 |

## 結論

**選択肢B** を採用する。

- バックラー統計は「月1回更新・全ユーザー同一・数MB」であり、リクエスト課金の D1 に載せる性質のデータではない。静的配信にすれば書き込みも読み取りも 0 になる
- R2 の無料枠は storage 10GB・Class B（読み取り）1,000万/月。dia を月別 Parquet にしても数MB/月で、余裕がある
- sf6-chapter は既に R2 + Parquet + DuckDB（CLI / WASM）を持ち、`battlelog_replays.parquet` と同一バケットに置けば JOIN できる。ADR-030（マッチアップチャート）の自然な延長になる
- 公開需要が未成立の段階で公開基盤（Workers・D1・ボット対策）を維持する理由がない。MCP はローカル stdio で同じツールを使い続けられる
- A は枠消費を減らすが、二重管理と公開基盤の維持コストは残る。C は需要が確認できてから選べばよい（B のデータ配置をそのまま使える）

## 帰結

### 肯定的影響

- D1 の無料枠消費がゼロになり、月次インポートの失敗・警告から解放される
- 公開統計と自分の対戦データ（`battlelog_replays.parquet`）を**同じ DuckDB で JOIN** でき、「自分の勝率 vs 同ランク帯の平均勝率」を出せる
- report-generator・Web・MCP が同じデータ源を参照し、数値の不一致が起きない
- R2 上のデータはバージョン管理されたオブジェクトとして残り、再処理・再集計が容易

### 否定的影響・制約

- 公開 MCP のエンドポイントがなくなる（外部から URL で叩けなくなる）
- 統計の参照には R2 認証（ローカル）または Web 経由が必要になる
- バックラー統計用の collector を新たに保守する必要がある（月1回のバッチ）
- Parquet 生成に失敗した場合、Web / レポート側は前月のデータを表示し続けることになる（鮮度の明示が必要）

### データ設計

R2 配置（既存バケット `sf6-chapter-data` に同居）:

```
stats/character_usage/{YYYYMM}_{locale}.parquet   # 使用率（小さい）
stats/matchup_stats/{YYYYMM}.parquet              # 月別（約 432 行）
stats/matchup_details/{YYYYMM}.parquet            # 月別（約 23,328 行）
stats/manifest.json                               # 最新データ月・生成日時・キャラ数
```

月別オブジェクトに分割する理由は、Web（DuckDB-WASM）が必要な月だけを読めるようにするため。全期間を1ファイルにすると details が 77 万行になり、初期ロードが重くなる。

スキーマ:

| テーブル | 列 |
|---|---|
| `character_usage` | `data_month`, `locale`, `operation_type`, `league_rank`, `character_alpha`, `character_tool_name`, `play_rate`, `previous_rate` |
| `matchup_stats` | `data_month`, `rank_id`, `rank_name`, `character_id`, `character_alpha`, `character_tool_name`, `input_type`, `total_score`, `win_rate` |
| `matchup_details` | `data_month`, `rank_id`, `character_id`, `input_type`, `opponent_character_id`, `opponent_tool_name`, `opponent_input_type`, `win_rate`, `score`, `sf`, `thm` |

型と NULL の扱い:

| 列 | 型 | 欠損 | 備考 |
|---|---|---|---|
| `win_rate` | `REAL` | なし | `_dsort` をそのまま格納（0〜1）。**`val / 10` は使わない** |
| `score` | `REAL` | `-.---` は NULL | `val`（0〜10）。`0.0` は実値として保持 |
| `total_score` | `REAL` | なし | `total`（0〜10） |
| `sf` / `thm` | `INTEGER` | なし | `-1` / `0` / `1` |
| ミラー | − | − | 列は持たず `character_id = opponent_character_id` で判定。`win_rate` は総合勝率が入るが集計から除外する |

`score_raw`（元の文字列）は持たない。`-.---` は NULL、それ以外は数値として復元できるため、文字列を残す必要がない。監査目的で必要になった時点で追加する。

### キャラクター名の正規化

バックラーは `character_alpha`（表示名。地域差あり: `gouki`/`AKUMA`、`vega`/`M. BISON`）と `character_tool_name`（`ryu`, `chunli` など）を持つ。

**Battlelog の `character_name` は日本語**（`ルーク`、`豪鬼`、`ベガ`、`C.ヴァイパー` など）である。2026-11 時点の実データで確認した。英数字以外を除去するだけの正規化では日本語名が空文字になり、元から英語の `A.K.I.` だけが一致するという症状が出る。

そのため、日本語名 → バックラーの `name_alpha` → 別名解決（GOUKI/AKUMA、VEGA/M. BISON）の順で正規化する。対応表は `packages/local/config/character_aliases.json` の日本語エイリアスと Battlelog の実データ（32名）に基づき、Web（`src/shared/characters.ts`）と report-generator（`src/external_stats.py`）の両方に持つ。

バックラーにまだ存在しないキャラ（アルジュン、ボシュ、ティファ）や、キャラ未選択の「ランダム」は照合できないため `-` 表示になる。

### 実装計画

| # | 作業 | 対象 | 目安 |
|---|---|---|---|
| 1 | バックラー統計 collector（`usagerate` / `dia` 取得 → JSON 保存 → Parquet 化 → R2 アップロード） | `packages/local` | 1〜2日 |
| 2 | 月次実行の組み込み（既存の月次バッチ or GitHub Actions） | `packages/local` / `.github` | 半日 |
| 3 | report-generator に `--external-stats`（自分 vs 同ランク帯平均） | `packages/report-generator` | 1日 |
| 4 | Web の試合詳細・マッチアップに「同ランク帯平均」列 | `packages/web` | 1日 |
| 5 | sf6-stats-mcp-server: D1 バインディング削除、ローカル Parquet 参照に変更、`win_rate` を `_dsort` に修正、公開デプロイ停止・リポジトリ archive | 別リポジトリ | 1日 |
| 6 | 動画解析後のレポートへの統計添付（`analyze-video` の出力拡張） | `packages/local` / `packages/report-generator` | 1日 |

ステップ 5 は collector の完成後に実施する。それまでは選択肢A相当の即効修正（`COUNT(*)` → `EXISTS`、`DISTINCT` → メタテーブル、インポートを当月のみに限定）だけ入れて、枠超過を止める。

### 検証

- collector: 1ヶ月分の取得結果が dia の `records` / `values` 件数と一致すること（432 / 23,328）
- Parquet: DuckDB で読めること、`matchup_stats` と `matchup_details` が `character_id` / `input_type` / `rank_id` / `data_month` で結合できること
- report-generator: 同一期間・同一ランクで、既存の自分の勝率と新規の平均勝率が両方出力されること
- Web: DuckDB-WASM で R2 の Parquet を読めること（CORS・Presigned URL の扱いを ADR-010 に合わせる）
- sf6-stats-mcp-server: ローカル stdio MCP で 2 ツールが従来と同じ出力を返すこと

### 将来の見直し条件

- 公開 MCP の需要が生まれた場合（利用者数・問い合わせ）は、選択肢C（R2 直読みの薄い Worker）に移行する。データ配置は本 ADR のままでよい
- バックラーの API 仕様・データ公開形態が変わった場合
- 統計の更新頻度が上がり、月次バッチでは追随できなくなった場合

## 決定事項（未決事項の解消）

| # | 論点 | 決定 |
|---|---|---|
| 1 | R2 バケット | 既存の `sf6-chapter-data` に `stats/` プレフィックスで同居 |
| 2 | ロケール | `ja-jp` / `en` の2つに限定（使用率のみロケール依存。dia は `ja-jp` 固定） |
| 3 | 比較対象ランク | Battlelog の直近試合から現在のリーグを推定する。推定できない場合はマスター（8）にフォールバックし、出力に使用ランクを明記 |
| 4 | sf6-stats-mcp-server | ローカル MCP 用として残したうえで archive。公開デプロイは停止 |
| 5 | `val` の欠損 | `score` 列を NULL 許容とし、`-.---` を NULL、`0.0` を実値として保持。ミラーは `character_id = opponent_character_id` で判定して集計から除外。`win_rate` は `_dsort` を使う |

### 実装状況（2026-11-02）

| # | 作業 | 状態 |
|---|---|---|
| 1 | バックラー統計 collector | 実装済み（`packages/local/src/sf6_stats/`） |
| 2 | 月次実行の組み込み | 実装済み（`.github/workflows/monthly-sf6-stats.yml`）。R2 の GitHub Secrets 登録が必要 |
| 3 | report-generator `--external-stats` | 実装済み |
| 4 | Web の「同ランク帯平均」列 | 実装済み（マッチアップタブ。自キャラ指定時に遅延読み込み） |
| 5 | sf6-stats-mcp-server のローカル化・公開停止・archive | 未着手（別リポジトリ） |
| 6 | 動画解析後レポートへの統計添付 | 実装済み（`--video-id`） |

検証結果:

- 202508 / 202609 の dia から Parquet を生成し、R2 へアップロード済み
  - 202508: stats 432 行 / details 23,328 行（27キャラ）
  - 202609: stats 496 行 / details 30,752 行（31キャラ。ALEX / C.VIPER / INGRID / YASMINE が追加）
- `score` は非 NULL 22,881 / `0.0` 35 / ミラー 864 行。欠損と 0 が区別されている
- `opponent_header` は同じ `id` を C/M で2回持つため、`_oid` だけでは入力タイプを区別できない。index 対応（432 records すべてで検証）で解決した
- 合成 Battlelog で GOUKI→AKUMA、VEGA→M. BISON の照合と、リーグ推定（LP 10,300 → GOLD）を確認
- `packages/local` 28件 / `packages/report-generator` 47件 / `packages/web` 203件のテストが pass、ruff clean・typecheck・build 成功
- **R2 の実データで突合を検証**: battlelog_replays（2026-02〜2026-10、1,767試合）と stats 202609 で、マッチアップ 53 行中 48 行に平均勝率が付与された。残りはアルジュン（バックラー未収録）・ミラー・ランダム（キャラ未選択）で、いずれも照合対象外として正しく `-` になる
- `ci-local.yml` / `ci-report-generator.yml` に pytest を追加

## 未決事項

- report-generator のオプション名（`--external-stats` / `--benchmark`）
- リーグ推定に使う Battlelog の期間（直近 N 試合か、直近 N 日か）
- `val` の指標としての正確な定義（バックラー画面の表示との対応）。collector 実装時に実画面と突合して確認する

## 関連

- [ADR-002: データ保存・検索基盤](002-data-storage-search.md)
- [ADR-010: Parquetデータ取得方式 - Presigned URL](010-parquet-presigned-url.md)
- [ADR-023: Battlelogデータ統合とParquet Web検索機能の実装](023-battlelog-data-integration-with-parquet-search.md)
- [ADR-030: Battlelogキャッシュデータを活用したマッチアップチャート機能](030-matchup-chart-from-battlelog-cache.md)
- [ADR-032: レポートジェネレーター](032-battlelog-report-generator.md)
- [ADR-070: レポートジェネレーターへのラウンドスコア分析の追加](070-round-score-analysis-in-report-generator.md)
