# ADR-046: LP推移グラフのWeb表示機能

## ステータス

採用 - 2026-10-03

## 文脈

### 現状

自分のリーグポイント（LP）の推移は、現在 [sfbuff.site](https://sfbuff.site/fighters/1319673732/matches) などの外部サービスでしか確認できない。外部サービスには以下の制約がある：

- データの取得タイミングや更新頻度が不明
- サービス停止・仕様変更のリスク
- YouTube チャプターデータ（自前の `matches.parquet`）との連携ができない

また、自前の `packages/report-generator/` には `query_lp_history()`（LP推移を時系列で取得するSQL）が既に実装されているが、CLI から Markdown テキストを出力するのみで、Web からは確認できない。

### 要件

添付の要望は「LP の変遷を折れ線グラフで Web から確認したい」というもの。参考にしたグラフ（添付画像）の特徴：

- x軸: 試合日時（分単位、`2026/09/02 01:43` 形式）
- y軸: LP（21,600〜23,200 を 200 刻み）
- 1試合ごとの LP を折れ線でプロット
- 期間は直近1ヶ月程度で約250点

### 活用可能な既存資産

**`battlelog_replays.parquet`**（ADR-030/031 で実装済み、Web で読み込み済み）:

| カラム | 用途 |
|--------|------|
| `p1_league_point` / `p2_league_point` | LP 値 |
| `p1_master_rating` / `p2_master_rating` | MR（今回は未使用） |
| `p1_short_id` / `p2_short_id` | 自分（`MY_PLAYER_ID = 1319673732`）の判定 |
| `p1_character_name` / `p2_character_name` | 自キャラ・相手キャラ |
| `uploaded_at` | 試合日時（UTC TIMESTAMP） |
| `battle_type` | 1=Ranked |
| `match_result` | P1視点の勝敗（ADR-037 未修正のため今回未使用） |

**既存の実装パターン**:
- Parquet + DuckDB-WASM + Presigned URL（ADR-002/010）
- `MY_PLAYER_ID` による P1/P2 視点統一（ADR-030/034）
- 期間フィルター（JST 日付＋時刻 → UTC 変換、`convertJstDateTimeToTimestamp` を共用）
- `parseUploadedAt` / `formatAbsoluteTime` による JST 表示（ADR-034 `MatchHistory.ts`）
- 既存タブ構成: 「対戦検索」「マッチアップ」「対戦履歴」

### 参考にした sfbuff の実装

LP 推移の参考にしている [sfbuff](https://github.com/alanoliveira/sfbuff) は Rails + Chart.js で実装されている。横軸の取り方を含め、実装を確認した。

| 項目 | sfbuff の実装 | 出典 |
|------|--------------|------|
| x スケール | Chart.js `timeseries`（各データ点を等間隔に配置） | `app/views/charts/_ranked_history_chart.json.jbuilder` |
| x 値 | `replay.uploaded_at`（今回の `uploaded_at` と同じ） | `app/models/battle/from_replay.rb` |
| y 値 | `player_info.league_point`（今回と同じ） | 同上 |
| 線 | `tension: 0.4`（なめらかな曲線） | 同 jbuilder |
| 右端 | プロフィールの現在 LP を `now` の位置に追加 | `app/charts/ranked_history_chart.rb` |
| 初期期間 | 今日1日 | `app/models/matches_filter.rb` |
| y軸 | LP と MR の2軸＋ランク帯マーカー | 同 jbuilder |

Chart.js の `timeseries` スケールは公式ドキュメントに「for the time series scale, each data point is spread equidistant」とあり、実装（`scale.timeseries.js`）でも位置を `i / (n - 1)` で決めている。

このうち x スケール（等間隔）・現在地点・線の補間を本 ADR で取り込む（決定4〜6）。MR 軸とランク帯マーカーは今回のスコープ外とする。

### データ実測（`packages/local/battlelog_cache.db`、2026-10-02時点）

自分のリプレイ 1,525 件（うち Ranked 1,500 件）、期間 2026-02-13 〜 2026-10-01。

| 項目 | 実測値 |
|------|--------|
| Ranked リプレイ数 | 1,500 件 |
| LP 範囲 | 21,280 〜 23,265 |
| 使用キャラ | JP のみ |
| MR | 全件 0（マスター未満） |
| 直近1ヶ月（9月〜10月） | 250 点程度 |

### 重要な技術的発見: `league_point` は「試合開始時点」の値

時系列順（`uploaded_at` 昇順）に並べたとき、`LP[i] - LP[i-1]` の符号と **1つ前の試合（i-1）の勝敗** を突き合わせると **1,496 / 1,498 件（99.9%）が一致**する。逆に **その試合（i）の勝敗** と突き合わせると 767 / 731 件とほぼ半々になる。

```
試合 i-1 の勝敗  →  LP[i] - LP[i-1]  … 一致率 99.9%
試合 i   の勝敗  →  LP[i] - LP[i-1]  … 一致率 約51%
```

したがって、各リプレイの `league_point` は **その試合を始める前の LP** である。グラフの点は「各試合の開始時点の LP」を表すことになる。

この解釈は LP 増減の分布とも整合する：
- 敗北時は `-40` が支配的（822件）
- 勝利時は `+50` 前後で変動（相手の LP に依存）

### 制約・前提

- **`match_result` の信頼性**: ADR-037（`round_results` の値の意味と判定ロジック修正）が未実装のため、`battlelog_replays.match_result` には `round_results` の単純合計に起因する誤判定が混在する。本機能では `match_result` を使わず、`round_results` から自分視点の勝利ラウンド数を算出する。
- **データ網羅性**: `battlelog_cache.db` の収集範囲に依存し、2026-02 より前は表示できない（ADR-025 の増分取得範囲）。
- **MR の検証不能**: 現状 MR は全件 0 であり、マスター帯の表示は検証できない。

## 決定

### 1. 新タブ「LP推移」を追加

既存の3タブ（対戦検索 / マッチアップ / 対戦履歴）に並ぶ4つ目のタブとして追加する。独立ページやダッシュボードは作らない。

### 2. データソースは既存の `battlelog_replays.parquet` を流用

新しい Parquet ファイル・API エンドポイントは追加しない。`loadBattlelogParquetData()` で既にロード済みの `battlelog_replays` テーブルに対してクエリするだけとする。

### 3. 描画は自作 SVG（グラフライブラリを追加しない）

既存 UI はテーブルのみでグラフライブラリは未導入。折れ線＋ツールチップという要件に対しては自作 SVG で十分であり、バンドルサイズの増加を避ける。

### 4. 1試合 = 1点。x軸は試合ごとの等間隔で配置。LP は試合開始時点の値

- 点の粒度は 1試合ごと（現状最大1,500点）。日次集計やダウンサンプリングは行わない。
- **x軸は試合の並び順で等間隔に配置する**。時刻の長さは横方向の間隔に反映しない。10日空いた期間も、連戦した日も、隣り合う試合は同じ幅になる。
  - sfbuff は Chart.js の `timeseries` スケールを使っており、公式ドキュメントに「for the time series scale, each data point is spread equidistant」とある。実装（`scale.timeseries.js`）でも位置を `i / (n - 1)` で決めている。
  - 当初は実時間比例で実装したが、sfbuff と見た目が一致しないため等間隔に変更した。
- `league_point` は取得値のままプロットし、**「試合開始時点の LP」** として扱う。1つずらして試合終了時に補正する処理は入れない（最終試合の結果を反映できないため）。
- この仕様が直感に反しないよう、ツールチップに「試合開始時」と明記する。

### 5. 右端に現在地点（最新の対戦時点の LP）を追加

- グラフの右端に、最新の対戦時点の LP を1点追加する（sfbuff がプロフィールの現在 LP を `now` の位置に追加する挙動に相当）。
- 追加するのは、期間終了が未指定または今日以降をカバーしている場合のみ（sfbuff の `cover_today?` と同じ）。
- ツールチップでは「最新の対戦時点」と表示し、アクセント色のマーカーで区別する。
- **厳密な「現在の LP」ではない**点に注意。Battlelog の `league_point` は試合開始時点の値のため、最新の試合の結果は反映されない。プロフィールから現在 LP を取得して渡す仕組みは将来の見直しとする。

### 6. 線はなめらかに補間する

- sfbuff の `tension: 0.4` に合わせ、Catmull-Rom スプラインを3次ベジェに変換して描画する（`buildLinePath()`）。
- 直線ではなく曲線になるため、変動の傾向が視覚的に追いやすくなる。

### 7. グラフ上に勝敗は表現しない

点の色分け・マーカー・背景帯など、グラフの視覚表現に勝敗を持ち込まない。LP の推移そのものに集中する（ADR-037 の誤判定の影響をグラフの見た目に持ち込まないため）。

### 8. ツールチップに 日時（JST）・LP・相手キャラ・勝敗 を表示

ホバー時に以下を表示する：

| 項目 | 内容 |
|------|------|
| 日時 | JST 表記（`2026/09/02 01:43`） |
| LP | カンマ区切り＋「（試合開始時）」の注記 |
| 相手キャラ | `opponent_character` |
| 勝敗 | win / loss / draw のテキスト |

勝敗は `match_result` を使わず、**`round_results`（各ラウンドの勝利方法IDのJSON配列）から自分視点の勝利ラウンド数を `v > 0` で数えて算出**する。これは ADR-037 が定める正しい判定ロジックと同じ規則であり、`convert_battlelog_to_parquet.py` の修正と Parquet 再生成を待たずに正確な勝敗を得られる。

```
自分視点の round_results: [1, 0, 1] → v > 0 は 2 → 2勝
相手視点の round_results: [0, 2, 0] → v > 0 は 1 → 1勝
2 > 1 → win
```

両者の勝利ラウンド数が同数の場合は `draw` とする。`round_results` が NULL の場合は 0 勝として扱う。

算出はクエリ結果を受け取った後の TypeScript 側（`countRoundWins()` / `determineResultFromRounds()`）で行う。SQL 内で JSON を展開する必要がなく、判定ロジックをユニットテストできる。

### 9. フィルターは日付・時刻の手入力のみ（プリセットなし）

既存タブと同じ操作感とする。プリセットボタン（1週 / 1ヶ月 / 3ヶ月 / 全期間）は設けない。

| フィルター | 入力 | 挙動 |
|-----------|------|------|
| 開始日 | `YYYY-MM-DD` | 未指定なら最古から |
| 開始時刻 | `HH:MM`（JST） | 開始日と組み合わせ（既存と同じ） |
| 終了日 | `YYYY-MM-DD` | 未指定なら最新まで |
| 終了時刻 | `HH:MM`（JST） | 終了日と組み合わせ（既存と同じ） |

初期表示はフィルターなし（全期間）。時刻変換は `convertJstDateTimeToTimestamp` を共用する。

対象は **Ranked（`battle_type = 1`）のみ**とし、モード選択は設けない。LP はランクマッチの指標であり、他モードには意味のある LP が存在しないため。また `league_point > 0` の行のみをプロット対象とする。

**自キャラクターのフィルターは設けない。** 現状の使用キャラは JP のみで系列が混在せず、SF6 の LP はキャラクターごとに別管理されるため、複数キャラ運用を始めた時点で改めて対応する（将来の見直し条件）。

### 10. MR（マスターレーティング）は今回対象外

LP のみをプロットする。MR はデータ上 `p1_master_rating` / `p2_master_rating` に既に存在するが、現状全件 0 で検証不能なため、LP/MR 切替 UI は作らない（将来の見直し条件に記載）。

### 11. 過去データの遡及取得はスコープ外

`battlelog_cache.db` に存在する範囲のみを表示対象とし、Battlelog API を遡って過去分を取得する処理は今回実装しない。既知の制約として ADR に明記する。

### 12. テストはクエリ関数のユニットテスト＋手動確認

ADR-040 のテスト戦略に沿い、`search.ts` のクエリ関数（P1/P2 視点統一・LP 抽出・期間フィルター・ranked 絞り込み）を vitest で検証する。SVG 描画は手動確認とする。

## 実装方針

### クエリ（DuckDB-WASM）

`report-generator/src/query.py` の `query_lp_history()` を踏襲し、Ranked 絞り込み・LP > 0 条件を加える。`round_results` は SQL では展開せず、そのまま取得して TypeScript 側で判定する。

```sql
SELECT
  uploaded_at,
  CASE WHEN p1_short_id = 1319673732 THEN p1_league_point
       ELSE p2_league_point END AS league_point,
  CASE WHEN p1_short_id = 1319673732 THEN p2_character_name
       ELSE p1_character_name END AS opponent_character,
  CASE WHEN p1_short_id = 1319673732 THEN p1_round_results
       ELSE p2_round_results END AS my_rounds,
  CASE WHEN p1_short_id = 1319673732 THEN p2_round_results
       ELSE p1_round_results END AS opp_rounds
FROM battlelog_replays
WHERE (p1_short_id = 1319673732 OR p2_short_id = 1319673732)
  AND battle_type = 1
  AND (CASE WHEN p1_short_id = 1319673732 THEN p1_league_point
            ELSE p2_league_point END) > 0
  -- 期間フィルター（JST → UTC 変換済みの値をバインド）
  AND uploaded_at >= $1::TIMESTAMP
  AND uploaded_at <= $2::TIMESTAMP
ORDER BY uploaded_at ASC
```

勝敗は取得した `my_rounds` / `opp_rounds`（`"[1,0,1]"` のような JSON 文字列）を `JSON.parse` し、`v > 0` の要素数を数えて判定する。DuckDB の JSON 関数（`from_json` 等）に依存しないため、DuckDB-WASM のバージョン差を気にせず、ロジックを vitest で検証できる。

### 型定義（`packages/web/src/shared/types.ts`）

```ts
export interface LpHistoryRow {
  uploadedAt: string;          // DuckDB TIMESTAMP（Unix ミリ秒数値文字列）
  leaguePoint: number;         // 試合開始時点の LP
  opponentCharacter: string;
  result: 'win' | 'loss' | 'draw';
}

export interface LpHistoryFilters {
  dateFrom?: string;  // YYYY-MM-DD（JST）
  dateTo?: string;
  timeFrom?: string;  // HH:MM（JST）
  timeTo?: string;
}
```

### SVG チャート（`packages/web/src/client/components/LpChart.ts`）

- `viewBox` ベースでレスポンシブ対応。`polyline` で折れ線を描画。
- y軸: 値域から 200 刻みの目盛りを自動生成（画像と同様）。
- x軸: 表示幅に応じてラベルを間引き、数点のみ表示。
- ツールチップ: `mousemove` で最近傍の点を求め、HTML の `div` を重ねて表示。1,500 点程度なら点数分の `<circle>` を置かず、最近傍探索で実装する。
- 点が多い場合でも `<circle>` を全点描画しないことで DOM ノード増加を避ける。

## 選択肢の比較

### UI の配置

#### 選択肢A: 新タブ「LP推移」を追加（採用）

| 観点 | 評価 |
|------|------|
| 既存UIとの一貫性 | ◎ 既存3タブと同じ操作感 |
| 発見しやすさ | ◎ タブとして常時見える |
| 実装コスト | ○ 既存のタブ初期化・ビュー追加パターンを流用 |
| 他機能との干渉 | ◎ 既存ビューに変更を加えない |

#### 選択肢B: 対戦履歴タブの上部にグラフ

| 観点 | 評価 |
|------|------|
| 実装コスト | △ 履歴フィルターとグラフの連動ロジックが必要 |
| 画面の情報量 | △ 履歴テーブルと競合し圧迫する |
| 一覧性 | ○ 結果とグラフを同時に見られる |

#### 選択肢C: 独立ページ / ダッシュボード新設

| 観点 | 評価 |
|------|------|
| 実装コスト | △ ルーティング・レイアウトの追加 |
| 既存UIとの一貫性 | △ SPA のタブ構成から逸脱 |
| 拡張性 | ○ 将来的に分析機能を集約しやすい |

### グラフ描画方式

#### 選択肢A: 自作 SVG（採用）

| 観点 | 評価 |
|------|------|
| バンドルサイズ | ◎ 追加なし |
| 要件充足 | ◎ 折れ線＋ツールチップは十分実装可能 |
| テスト容易性 | ○ 座標計算を純関数に切り出せる |
| 拡張性 | △ ズーム・パン等は自前実装が必要 |

#### 選択肢B: uPlot を追加（約40KB）

| 観点 | 評価 |
|------|------|
| パフォーマンス | ◎ 大量点に強い |
| バンドルサイズ | ○ 軽量 |
| 型・保守 | △ 公式型定義が薄い |
| 現状の必要性 | △ 1,500点では自作で足りる |

#### 選択肢C: Chart.js（約200KB） / ECharts（約1MB）

| 観点 | 評価 |
|------|------|
| 機能 | ◎ 高機能 |
| バンドルサイズ | ✕ 今回の要件に対して過大 |
| 時系列対応 | △ 日付アダプタ等の追加依存が必要 |

### データソース

#### 選択肢A: `battlelog_replays.parquet` を流用（採用）

| 観点 | 評価 |
|------|------|
| 実装コスト | ◎ ロード済みテーブルにクエリするだけ |
| データ整合性 | ◎ 既存機能と常に同一データ |
| ファイル管理 | ◎ 新規ファイル・APIなし |
| 転送量 | ○ 全カラムを既に取得済みのため追加なし |

#### 選択肢B: LP推移専用の軽量 Parquet を新規生成

| 観点 | 評価 |
|------|------|
| 転送量 | ○ 小さくなる |
| 実装コスト | △ 変換スクリプト・アップロード経路・API の追加 |
| 保守性 | △ スキーマ変更時に二重管理 |

#### 選択肢C: サーバー側で集計して JSON API

| 観点 | 評価 |
|------|------|
| リアルタイム性 | ○ サーバーで集計 |
| 既存方式との一貫性 | ✕ クライアント側クエリ方式から逸脱 |
| 実装コスト | △ サーバーロジックの追加 |

### 点の粒度

#### 選択肢A: 1試合 = 1点（採用）

| 観点 | 評価 |
|------|------|
| 情報量 | ◎ 変動が最もよく分かる |
| 参考画像との一致 | ◎ 画像と同じ見え方 |
| パフォーマンス | ○ 1,500点なら SVG で描画可能 |
| 長期表示 | △ 数万点規模では要見直し |

#### 選択肢B: 日次代表値 / 日次終値

| 観点 | 評価 |
|------|------|
| 長期トレンド | ○ 見やすい |
| 情報量 | ✕ 日内の上下が消える |
| 参考画像との一致 | ✕ 画像と異なる |

#### 選択肢C: 自動ダウンサンプリング

| 観点 | 評価 |
|------|------|
| 将来性 | ◎ 大量点に強い |
| 初期実装 | △ 表示幅連動の間引きロジックが必要 |
| 現状の必要性 | △ 1,500点では不要 |

### SVG チャート（`packages/web/src/client/components/LpChart.ts`）

- `viewBox` ベースでレスポンシブ対応。`path`（3次ベジェ）でなめらかな折れ線を描画。
- x軸: `computeEquidistantPositions()` で各試合を等間隔に配置。ラベルは間引いて表示し、現在地点は「現在」と表示。
- y軸: 値域から 200 刻みの目盛りを自動生成。
- 現在地点: 右端に追加し、`.lp-current-point`（アクセント色）で表示。
- ツールチップ: `mousemove` で最近傍の点を求め、HTML の `div` を重ねて表示。1,500 点程度なら点数分の `<circle>` を置かず、最近傍探索で実装する。
- 点が多い場合でも `<circle>` を全点描画しないことで DOM ノード増加を避ける。

### x軸の取り方

#### 選択肢A: 試合ごとの等間隔（採用）

| 観点 | 評価 |
|------|------|
| sfbuff との一致 | ◎ 同じ見え方になる |
| 試合密度の見やすさ | ◎ 全試合が同じ幅で並び、試合単位の変動を追いやすい |
| 時間の長さの反映 | ✕ 空白期間の長さは分からない |
| 実装コスト | ◎ 位置を `i / (n - 1)` で計算するだけ |

#### 選択肢B: 実時間比例

| 観点 | 評価 |
|------|------|
| 時間の長さの反映 | ◎ 空白期間の長さが分かる |
| sfbuff との一致 | ✕ 連戦日は点が密集し、sfbuff と見た目が異なる |
| 試合密度の見やすさ | △ 長く空いた期間で点が潰れる |

#### 選択肢C: 等間隔 / 時間比例の切替

| 観点 | 評価 |
|------|------|
| 柔軟性 | ◎ 両方の見方ができる |
| 実装コスト | △ 切替 UI とテストが増える |
| 現状の必要性 | △ まずは sfbuff と同じ見た目を優先 |

### ツールチップの勝敗の算出元

#### 選択肢A: `round_results` から自前計算（採用）

| 観点 | 評価 |
|------|------|
| 正確性 | ◎ ADR-037 と同じ正しい規則（`v > 0`） |
| ADR-037 への依存 | ◎ 修正・Parquet 再生成を待たない |
| 実装コスト | △ DuckDB での JSON 配列パースが必要 |
| 保守性 | △ `round_results` の値仕様変更時に追従が必要 |

#### 選択肢B: `match_result` をそのまま使う

| 観点 | 評価 |
|------|------|
| 実装コスト | ◎ カラムを選ぶだけ |
| 正確性 | ✕ ADR-037 修正まで `round_results` の単純合計による誤判定が混在 |
| ADR-037 への依存 | ✕ 修正と Parquet 再生成が前提になる |

### LP の意味の扱い

#### 選択肢A: 試合開始時 LP としてそのまま表示（採用）

| 観点 | 評価 |
|------|------|
| 取得値への忠実さ | ◎ 推測補正をしない |
| 実装コスト | ◎ 追加処理なし |
| 直感性 | △ ツールチップでの注記が必要 |

#### 選択肢B: 1つずらして試合終了時 LP に補正

| 観点 | 評価 |
|------|------|
| 直感性 | ○ 「現在の LP」に近い |
| 正確性 | ✕ 最終試合の結果を反映できず、系列全体が1試合分ずれる |
| 実装コスト | △ 先頭・末尾の特別処理が必要 |

## トレードオフと帰結

### メリット

- 外部サービス（sfbuff）に依存せず、自分のデータで LP 推移を確認できる
- **新規 Parquet・API・依存ライブラリの追加が一切不要**。既存の `battlelog_replays` テーブルとタブ UI パターンだけで完結する
- 1,500点規模は自作 SVG で十分軽量に描画できる
- 既存の P1/P2 視点統一・期間フィルター・JST 変換の実装をそのまま再利用できる
- 将来 YouTube リンクや勝敗マーカーを足す余地がある（ツールチップの JOIN 追加など）

### デメリット・注意点

- **データ網羅性**: `battlelog_cache.db` の収集範囲（現状 2026-02 以降）に依存し、それ以前は表示できない
- **データ鮮度**: `main.py` パイプラインの実行タイミングに依存し、リアルタイムではない
- **`round_results` の解釈への依存**: 勝敗は `round_results` を TypeScript 側で `JSON.parse` して自前計算する。将来 `round_results` の値仕様が変わった場合は ADR-037 とあわせて見直しが必要
- **「試合開始時 LP」という仕様**: 一般的な「現在 LP の推移」という直感とは1試合分ずれる。ツールチップでの注記で補う
- **拡張性**: ズーム・パン・複数系列・移動平均などの分析機能は自作 SVG では都度実装が必要
- **プレイヤーID固定**: `MY_PLAYER_ID` のハードコードは既存機能と同様

### 互換性

- 既存の「対戦検索」「マッチアップ」「対戦履歴」に影響なし
- `battlelog_replays` テーブルは既にロード済みのため、追加のダウンロードは発生しない
- 新規 Parquet・API エンドポイントの追加なし

### 将来の見直し条件

- **MR > 0 のデータが発生した場合**: LP / MR の切替 UI を検討する
- **複数キャラの運用を開始した場合**: SF6 の LP はキャラクターごとに別管理のため、キャラ別フィルターと系列分割が必要になる（現状は JP のみで実害なし）
- **プロット点数が数万規模になった場合**: ダウンサンプリングの導入、または uPlot / Canvas 描画への移行を検討する
- **厳密な「現在の LP」を表示したくなった場合**: 現在地点は最新の対戦時点の LP で、最新の試合の結果が反映されていない。`site_client.py` でプロフィールから現在 LP を取得し、Parquet 経由で Web に渡す仕組みを検討する
- **ADR-037 の修正が完了した場合**: ツールチップの自前計算を `match_result` に置き換えられるか（性能・簡便性の観点で）再評価する。あわせてグラフ上への勝敗表現も再検討する
- **過去データの遡及取得を別 ADR で設計した場合**: その取得範囲に合わせてグラフ期間が伸びる

## 実装状況（2026-10-03）

実装完了。検証結果は以下のとおり。

| 検証 | 結果 |
|------|------|
| `pnpm typecheck` | エラーなし |
| `pnpm test` | 2 files / 43 tests passed（既存テスト＋`countRoundWins` / `determineResultFromRounds` / `computeLpAxisTicks` / `computeEquidistantPositions` / `buildLinePath` / `findNearestIndex`） |
| `pnpm build` | 成功（クライアントバンドル 235KB / gzip 55.6KB。ライブラリ追加なし） |
| R2 実データでの SQL 検証 | `battlelog_replays.parquet` から 1,500 行取得。期間 2026-02-14 〜 2026-10-02 |
| ブラウザでの描画確認（Playwright） | 初版（実時間比例）で全期間1,500点・期間指定236点・ツールチップを確認。等間隔・現在点・曲線への変更後は、実行環境から Playwright のブラウザ依存ライブラリを導入できず未確認 |

実装時に判明した追加事項：

- **sfbuff との横軸の違い**: sfbuff は Chart.js の `timeseries` スケールで各データ点を等間隔に配置する。当初の実時間比例実装では見た目が一致しないため、等間隔・現在点・曲線補間へ変更した（決定4〜6）。
- **LP 初期化の独立化**: `packages/web/src/client/main.ts` で、LP 推移の初期化を既存の「マッチアップ／対戦履歴」の try ブロックから分離し、`battlelog_replays` のみに依存する独立した try ブロックにした。既存タブ側の失敗（`matches` テーブル不在など）で LP 推移が初期化されなくなるのを防ぐ。
- **x軸ラベルの間引き**: 端のラベルは `text-anchor` を `start` / `end` に切り替え、さらに最後のラベルが直前のラベルと近い場合（`MIN_X_LABEL_GAP` 未満）は直前のラベルを間引く。ラベルの重なり・見切れを防ぐ。

## 実装チェックリスト

- [x] `packages/web/src/shared/types.ts`: `LpHistoryRow` / `LpHistoryFilters` の型定義追加
- [x] `packages/web/src/client/types.ts`: `DOM_IDS` に TAB_LP / VIEW_LP / LP_FORM / LP_DATE_FROM / LP_TIME_FROM / LP_DATE_TO / LP_TIME_TO / LP_CHART / LP_LOADING / LP_ERROR を追加、`LpHistoryQueryRow` を追加
- [x] `packages/web/src/client/search.ts`: `queryLpHistory()`（P1/P2視点統一・Ranked絞り込み・LP>0・期間フィルター・`uploaded_at ASC`）、`getLatestLp()`、`countRoundWins()` / `determineResultFromRounds()` を追加
- [x] `packages/web/src/client/components/LpChart.ts`: 自作 SVG チャート（等間隔x軸・現在地点・なめらか補間・軸目盛り・ツールチップ・JST表示・最近傍探索）を作成
- [x] `packages/web/src/client/main.ts`: LP 推移ロード、現在点の取得、フォーム初期化、フィルターハンドラ追加（独立した try ブロック）
- [x] `packages/web/src/server/routes/pages.tsx`: 「LP推移」タブ・ビュー・フィルターフォーム・チャートコンテナの追加
- [x] `packages/web/public/static/main.css`: チャート・ツールチップ・軸ラベル・現在地点マーカーのスタイル追加
- [x] `packages/web/src/client/search.test.ts`: `countRoundWins` / `determineResultFromRounds` のユニットテスト追加（0/1以外の値、NULL、引き分けを含む）
- [x] `packages/web/src/client/LpChart.test.ts`: `computeLpAxisTicks` / `computeEquidistantPositions` / `buildLinePath` / `findNearestIndex` のユニットテスト追加
- [ ] 等間隔x軸・現在地点・曲線補間への変更後の見た目を手動確認（ブラウザ環境が必要）

## 関連ADR

- [ADR-002: データ保存・検索基盤](002-data-storage-search.md) - Parquet + DuckDB-WASM の基盤設計
- [ADR-010: Parquetデータ取得方式（Presigned URL）](010-parquet-presigned-url.md) - Presigned URL パターン
- [ADR-023: Battlelogデータ統合とParquet Web検索機能の実装](023-battlelog-data-integration-with-parquet-search.md) - `battlelog_replays` の由来
- [ADR-025: Battlelog API 増分取得の最適化](025-battlelog-api-incremental-fetching-optimization.md) - キャッシュ収集範囲の制約
- [ADR-030: Battlelogキャッシュデータを活用したマッチアップチャート機能](030-matchup-chart-from-battlelog-cache.md) - P1/P2視点統一パターン、`MY_PLAYER_ID`
- [ADR-031: Battlelog Parquet 変換・アップロードの main.py パイプライン統合](031-battlelog-parquet-pipeline-integration.md) - データパイプライン
- [ADR-032: Battlelog レポート生成ツール](032-battlelog-report-generator.md) - `query_lp_history()` の既存実装
- [ADR-034: 対戦結果一覧ページの実装](034-match-history-page-with-youtube-links.md) - タブ追加パターン、JST表示ユーティリティ
- [ADR-037: Battlelog round_results の値の意味と match_result 判定ロジックの修正](037-battlelog-round-results-value-semantics.md) - 勝敗算出に用いる `round_results` の解釈の根拠
- [ADR-040: packages/web のテスト戦略](040-web-package-testing-strategy.md) - テスト方針
