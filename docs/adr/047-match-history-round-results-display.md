# ADR-047: 対戦履歴へのラウンド単位結果表示（sfbuff 準拠）

## ステータス

採用 - 2026-10-06（実装済み）

## 文脈

### 要望

対戦履歴ページ（ADR-034）は現在、1試合につき「WIN / LOSS / DRAW」のバッジしか表示しない。しかし Battlelog は各ラウンドの決着方法まで保持しており、「どのラウンドをどう取ったか」を確認したいという要望がある。

参考として [sfbuff](https://github.com/alanoliveira/sfbuff) が同等の機能を実装している。sfbuff は各ラウンドを**決着方法ごとに色分けしたバッジ**として、自サイド・相手サイドそれぞれに縦に並べて表示する。

### round_results の値の意味（ADR-037）

Battlelog API が返す `round_results` の各要素は、そのラウンドの**決着方法ID**である（体力残量ではない）。

| 値 | 表示 | 勝敗 | 意味 |
|----|------|------|------|
| 0 | L | LOSS | 負け |
| 1 | V | WIN | 通常勝利 (Vanilla KO) |
| 2 | C | WIN | Chip KO |
| 3 | T | WIN | Time Up |
| 4 | D | DRAW | 引き分け |
| 5 | OD | WIN | Overdrive KO |
| 6 | SA | WIN | Super Art KO |
| 7 | CA | WIN | Critical Art KO |
| 8 | P | WIN | Perfect |

勝敗は `value > 0` をそのラウンドの勝利として集計する（sfbuff の `Round#win?`、本リポジトリの `countRoundWins()` と同じ規則）。

### sfbuff の実装

| 項目 | sfbuff の実装 | 出典 |
|------|--------------|------|
| 値の定義 | `Round` enum（id, name, result） | `app/models/round.rb` |
| 勝敗判定 | `p1_rounds.count(&:win?)` vs `p2_rounds.count(&:win?)` | `app/models/battle.rb` |
| 表示 | `p1_rounds` / `p2_rounds` をそれぞれ縦にバッジ表示 | `app/views/battles/_challenger.html.erb` |
| 色 | 決着方法ごとの背景色・文字色マップ | `app/helpers/rounds_helper.rb` |

色マップ（`COLOR_MAP`、背景色 / 文字色）:

| 表示 | 背景 | 文字 |
|------|------|------|
| L | `#2D3644` | `#C7C7C8` |
| V | `#2C003E` | `#E297FF` |
| C | `#003A3D` | `#9BFAFF` |
| T | `#00123E` | `#97B4FF` |
| D | `#363636` | `#CBCBCB` |
| OD | `#113D00` | `#BFFFA6` |
| SA | `#5F003A` | `#FF93D5` |
| CA | `#442600` | `#FFD097` |
| P | `#605C00` | `#FFFB97` |

### 活用可能な既存資産

**`battlelog_replays.parquet`**（ADR-030/031、Web で読み込み済み）に既にラウンド情報が存在する。**新規 Parquet・API・カラム追加は不要**。

| カラム | 用途 |
|--------|------|
| `p1_round_results` / `p2_round_results` | 各プレイヤーの決着方法IDの JSON 配列文字列 |
| `p1_short_id` / `p2_short_id` | 自分（`MY_PLAYER_ID = 1319673732`）の判定 |
| `match_result` | P1視点の勝敗（round_results から算出） |

**既存の実装パターン**:
- `MY_PLAYER_ID` による P1/P2 視点統一（ADR-030/034）
- `countRoundWins()` / `determineResultFromRounds()`（ADR-046 の LP推移で実装済み、`search.ts`）
- FULL OUTER JOIN による Battlelog / YouTube の突合（ADR-034）
- 純関数のみを Vitest でテストする方針（ADR-040）

### データ実測（`packages/local/output/battlelog_replays.parquet`、2026-10-06時点）

| 項目 | 実測値 |
|------|--------|
| 総行数 | 1,568 件 |
| round_results あり | 1,568 件（全件） |
| P1が自分 / P2が自分 | 587 件 / 981 件 |
| 自分視点のラウンド値分布 | 0:2109, 1:1281, 2:36, 3:1, 4:1, 5:126, 6:142, 7:55, 8:88 |
| `match_result` と `v > 0` 判定の一致 | 1,568 / 1,568（P1視点） |

**補足（重要な前提の訂正）**: 上記ローカル Parquet の `match_result` は ADR-037 修正後の `v > 0` ロジックで生成済みであり、P1視点で完全一致する。一方、**R2 上の `battlelog_replays.parquet` は ADR-037 の再生成が未完了**（同 ADR のチェックリスト参照）であり、古い `sum()` ベースの誤判定が残っている可能性がある。本 ADR の round_results 起点判定はこの状態にも依存しない。

### 制約

- Battlelog 未マッチの YouTube 側のみの行（`replay_id IS NULL`）は `round_results` が NULL。この場合はラウンド列を「-」表示し、勝敗は `matches.player1.result` にフォールバックする。
- `round_results` の値の意味（ADR-037）に依存する。Battlelog が新しい決着方法IDを追加した場合は enum の更新が必要。

## 決定

### 1. 対戦履歴テーブルに「ラウンド」列を新規追加

既存の「勝負」列の隣に「ラウンド」列を追加する。行クリックや展開・モーダルは採用せず、テーブルの1列として常時表示する。

### 2. 表示は sfbuff 準拠の決着方法バッジ（色分け）

各ラウンドを `L / V / C / T / D / OD / SA / CA / P` のバッジで表示し、sfbuff の `COLOR_MAP` と同じ配色を使う。

`MatchHistoryRow` は1試合1行のため、sfbuff のような左右2カラムは取れない。**列内で上段に自分側、下段に相手側**のラウンドバッジを縦に並べる。

```
ラウンド
[V][C]      ← 自分（2-0）
[L][L]      ← 相手
```

### 3. 勝敗判定を round_results 起点に統一

`queryMatchHistory()` の `result` は、Battlelog 行では `round_results` から `determineResultFromRounds()` で算出する。`match_result` 列への依存をやめ、YouTube 側のみの行でのみ `matches.player1.result` にフォールバックする。

これにより、R2 上の古い Parquet（`match_result` が `sum()` ベースで誤判定）でも正しい勝敗を表示でき、LP推移グラフ（ADR-046、既に round_results 起点）と判定基準が揃う。

### 4. データソース・API・Parquet は変更しない

`battlelog_replays.parquet` の既存カラムのみを使う。Parquet の再生成・R2 への再アップロード・新規 API エンドポイントは不要。`queryMatchHistory()` の SELECT に `round_results` を追加するのみ。

### 5. Round の定義とロジックは純関数モジュールに集約

`Round`（id, name, outcome, description, 配色）と `ROUNDS`、`getRound()` / `parseRoundIds()` / `countRoundWins()` / `determineResultFromRounds()` を `packages/web/src/shared/rounds.ts` に集約する。DOM に依存しない純関数とし、ADR-040 の方針に沿って Vitest でテストする（`rounds.test.ts`）。既存 `search.ts` の判定関数は同モジュールからの re-export に置き換える。

バッジ HTML の生成は表示層の責務として `components/MatchHistory.ts` の `createRoundBadge()` / `createRoundCell()` に置く。`escapeHtml()` は DOM 非依存の文字列置換に変更し、Node 環境の Vitest からもテストできるようにする（`MatchHistory.test.ts`）。

## 選択肢の比較

### ラウンド表示の形式

| 選択肢 | 情報量 | 実装コスト | 採用 |
|--------|--------|-----------|------|
| A: 決着方法バッジ（sfbuff 準拠、色分け） | ◎ 決着方法まで分かる | 中（色定義・バッジ） | ✅ |
| B: ○/×/△ の勝敗マークのみ | △ 勝敗のみ | 低 | - |
| C: ラウンドスコアのみ（2-1） | △ 内訳が分からない | 低 | - |

### 表示位置

| 選択肢 | 常時視認性 | テーブル幅 | 採用 |
|--------|-----------|-----------|------|
| A: 「ラウンド」列を追加 | ◎ | △（1列増） | ✅ |
| B: 既存「勝負」列を拡張 | ◎ | ○ | - |
| C: 行クリックで展開 | △（クリック必要） | ◎ | - |

### 勝敗判定のソース

| 選択肢 | 正確性 | 実装コスト | 採用 |
|--------|--------|-----------|------|
| A: `round_results` 起点に統一 | ◎ R2 の古い Parquet にも依存しない | 低（既存関数を流用） | ✅ |
| B: `match_result` を維持 | △ R2 再生成待ち | - | - |

## 結論を導いた重要な観点

### 既存資産で完結する

`round_results` は既に Parquet の全行に存在し、Web も `battlelog_replays.parquet` をロード済み。パイプライン・スキーマ・API の変更が一切不要で、フロントエンドの変更のみで実現できる。

### 判定ソースの一本化

LP推移グラフは既に `round_results` 起点で判定している（ADR-046）。対戦履歴も同じ規則に揃えることで、同一試合の勝敗がページ間で食い違うリスクをなくす。これは ADR-037 が指摘した「ページ間の結果不一致」の恒久的な防止にもなる。

### 純関数化によるテスト担保

バッジ生成は「round_results 文字列 → 表示要素」の純粋な変換であり、DOM から切り離せる。ADR-040 の「純粋関数のみテストする」方針に合致する。

## 帰結

### 影響範囲

| ファイル | 変更内容 |
|----------|----------|
| `packages/web/src/shared/rounds.ts` | **新規**。`Round` enum、色定義、`parseRounds` / `countRoundWins` / `determineResultFromRounds` |
| `packages/web/src/shared/types.ts` | `MatchHistoryRow` に `myRounds: string \| null` / `oppRounds: string \| null` を追加 |
| `packages/web/src/client/types.ts` | `MatchHistoryQueryRow` に `my_rounds` / `opp_rounds` を追加 |
| `packages/web/src/client/search.ts` | `queryMatchHistory()` の SELECT に round_results を追加、`result` を `determineResultFromRounds()` に変更、判定関数を `rounds.ts` へ移設（re-export 維持） |
| `packages/web/src/client/components/MatchHistory.ts` | 「ラウンド」列のヘッダ・セル生成、`createRoundBadge()` / `createRoundCell()` 追加、`escapeHtml()` を DOM 非依存化 |
| `packages/web/public/static/main.css` | `.round-list` / `.round-side` / `.round-badge` 追加、モバイル幅の調整 |
| `packages/web/src/client/search.test.ts` | round_results 判定のテストを `shared/rounds.test.ts` へ移設 |
| `packages/web/src/shared/rounds.test.ts` | **新規**。Round 定義・`parseRoundIds`・`countRoundWins`・`determineResultFromRounds` のテスト |
| `packages/web/src/client/MatchHistory.test.ts` | **新規**。`createRoundBadge` / `createRoundCell` のテスト |

**変更不要**: `battlelog_replays.parquet` の再生成、R2 アップロード、`packages/local` の処理、API エンドポイント、JSON スキーマ。

### メリット

- 対戦履歴から各ラウンドの決着方法を確認できる
- 勝敗判定がページ間で統一され、R2 の古い Parquet にも影響されない
- パイプライン変更なし・データ再生成なしで低コストに実現できる

### トレードオフ

- テーブルの列が1つ増え、横幅が広がる（モバイルでは縮小表示の調整が必要）
- `round_results` の値の意味（ADR-037）に依存するため、Battlelog 仕様変更時は enum 更新が必要

### 将来の見直し条件

- Battlelog が新しい決着方法ID（`0` 以外の LOSS、`8` 超の WIN 種別など）を追加した場合
- ADR-037 の R2 再生成が完了した場合（`match_result` フォールバックの扱いを見直す）
- 対戦履歴に MR / リーグ情報を併記する拡張を行う場合

## 実装結果（2026-10-06）

- [x] `shared/rounds.ts` を新規作成（Round 定義・判定・配色）
- [x] `queryMatchHistory()` に round_results を追加し、勝敗判定を round_results 起点に統一
- [x] 対戦履歴テーブルに「ラウンド」列を追加（自分＝上段 / 相手＝下段）
- [x] ラウンドバッジの CSS を追加（配色は `Round` 定義から inline style で適用）
- [x] ユニットテスト追加（`rounds.test.ts` / `MatchHistory.test.ts`）、`tsc --noEmit` と `vite build` 通過
- [ ] R2 上の Parquet を使った本番表示確認（デプロイ後）

## 関連 ADR

- [ADR-023: Battlelog データ統合と Parquet Web 検索機能の実装](023-battlelog-data-integration-with-parquet-search.md)
- [ADR-030: Battlelogキャッシュデータを活用したマッチアップチャート機能](030-matchup-chart-from-battlelog-cache.md)
- [ADR-034: 対戦結果一覧ページの実装](034-match-history-page-with-youtube-links.md)
- [ADR-037: Battlelog round_results の値の意味と match_result 判定ロジックの修正](037-battlelog-round-results-value-semantics.md)
- [ADR-040: packages/web のテスト戦略](040-web-package-testing-strategy.md)
- [ADR-046: LP推移グラフのWeb表示機能](046-lp-history-chart.md)
