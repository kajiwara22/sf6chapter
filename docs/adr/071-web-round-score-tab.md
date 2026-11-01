# ADR-071: Web へのラウンドスコア分析タブの追加

## ステータス

採用 - 2026-10-31

## 文脈

### 現状

ADR-070 でレポートジェネレーターに `--round-analysis` を追加し、1R の勝敗・1P/2P 別・3R 勝率・決まり手を Markdown で出せるようになった。ただし確認には CLI の実行とファイルのオープンが必要で、期間を変えながら見る用途には向かない。

Web（`packages/web`）には「対戦検索」「マッチアップ」「対戦履歴」「LP推移」の4タブがあり、いずれも DuckDB-WASM で `battlelog_replays` / `matches` / `round_stats` を直接クエリしている。ラウンドスコアの集計に必要な `p*_round_results` は `battlelog_replays` に含まれており、追加のデータ取得は不要である。

### 要件

1. 新タブ「ラウンド分析」で、ADR-070 と同じ指標を表示する
2. 期間（日時）・自キャラクター・マッチタイプで絞り込める
3. `battlelog_replays` だけで完結させ、`round_stats` は読み込まない（初期ロードを増やさない）
4. 1P / 2P は自分視点に正規化する
5. `round_results` が空・不正・両者でラウンド数が不一致の試合は除外する
6. データがないときは案内を出し、表を描画しない

### 利用シナリオ

- 「1R を落とした試合はどれくらい負けるか」を、直近1か月・自分のメインキャラに絞って見る
- 決まり手の内訳から、OD/SA/CA で落とす割合（バーンアウトやゲージ消費からの崩れ）を確認する
- 3R 勝率が 50% を下回っていないかを、期間を変えて確認する

## 選択肢

### 選択肢A: 新タブ「ラウンド分析」を追加

`pages.tsx` にタブとビューを追加し、`search.ts` に `queryRoundScore()`、`components/RoundScorePanel.ts` に描画を実装する。

**変更ファイル**:
- `src/shared/types.ts` — `RoundScore` などの型
- `src/client/types.ts` — DOM ID
- `src/client/search.ts` — `queryRoundScore()`
- `src/client/components/RoundScorePanel.ts` — 描画・フォーム
- `src/client/main.ts` — 初期化とイベント
- `src/server/routes/pages.tsx` — タブとビュー
- `public/static/main.css` — スタイル
- `src/client/RoundScorePanel.test.ts` — テスト

### 選択肢B: 対戦履歴タブ内にセクションとして追加

既存タブの下に集計表を足す。タブを増やさないが、対戦履歴のフィルター（相手キャラ・操作タイプなど）と関心が混ざる。

### 選択肢C: 試合詳細ページにラウンド表を追加

`/matches/{matchId}` にラウンドごとの表を出す。既に `RoundGaugeChart` がラウンド単位の表示を持っており、集計（試合横断）には向かない。

## 各選択肢の比較表

| 観点 | A: 新タブ | B: 履歴内 | C: 試合詳細 |
|------|-----------|-----------|-------------|
| 期間を変えた比較 | ◎ タブ内で完結 | ○ | △ 1試合単位 |
| 既存タブとの関心の分離 | ◎ | △ 履歴の絞り込みと混ざる | ○ |
| 実装コスト | △ タブ・フォーム・CSS | ○ | ○ |
| 初期ロードへの影響 | ◎ なし（battlelog のみ） | ◎ | △ round_stats が必要 |

## 結論

**選択肢A** を採用する。

- ラウンドスコアは「期間を変えて傾向を見る」分析であり、対戦履歴（1行ずつの確認）や試合詳細（1試合の深掘り）とは用途が異なる
- `battlelog_replays` は ADR-055 のキャッシュで初期ロード済みのため、追加の Parquet 取得も初期化コストも増えない
- 既存のマッチアップタブと同じフォーム・表のパターンを踏襲でき、実装とテストの形を揃えられる

## 帰結

### 肯定的影響

- 期間・自キャラ・マッチタイプを変えながら、1R の重み・サイド差・3R 勝率・決まり手を即座に確認できる
- CLI レポート（ADR-070）と同じ解釈（ADR-037 の `0`=LOSS / `4`=DRAW / 他=WIN）を共有する
- 集計は `battlelog_replays` だけで完結し、OPFS キャッシュ（ADR-055）の対象テーブルを増やさない

### 否定的影響・制約

- ラウンド単位のゲージ・バーンアウト・被コンボは表示しない（`round_stats` を読み込まないため）
- 試合詳細ページのラウンド表とは別の集計経路になる（前者は動画検出のラウンド、後者は Battlelog の `round_results`）

### 検証

- DuckDB-WASM（`duckdb-node-blocking`）で本番と同じ SQL をローカルの `battlelog_replays.parquet` に対して実行し、CLI 版（ADR-070）と数値が一致することを確認した
  - 対象 1,732 試合、決まり手の内訳（V 1,413 / SA 154 / OD 144 / P 106 / CA 60 / C 42 / T 1、負け側も一致）、総ラウンド数 4,249
- `pnpm typecheck` / `pnpm test`（JST・UTC）/ `pnpm build` が成功
- `wrangler pages dev` で HTML にタブ・フォームが出力されることを確認

### 将来の見直し条件

- `round_stats` と突合して、ラウンドのゲージ指標（残体力・バーンアウト・被コンボ）を同じタブに追加するとき
- 集計の対象を「動画がある試合」に絞る必要が出たとき

## 関連

- [ADR-037: Battlelog round_results の値の意味と match_result 判定ロジックの修正](037-battlelog-round-results-value-semantics.md)
- [ADR-047: 対戦履歴へのラウンド単位結果表示](047-match-history-round-results-display.md)
- [ADR-051: ゲージ詳細ページの独立化とラウンド集計項目の改善視点での再設計](051-match-detail-page-and-round-stats-redesign.md)
- [ADR-055: OPFS によるクライアントキャッシュ](055-opfs-client-cache-for-parquet-and-duckdb.md)
- [ADR-070: レポートジェネレーターへのラウンドスコア分析の追加](070-round-score-analysis-in-report-generator.md)
