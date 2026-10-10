# ADR-051: ゲージ詳細ページの独立化とラウンド集計項目の改善視点での再設計

## ステータス

採用 - 2026-10-10（実装完了 2026-10-10）

## 文脈

### きっかけ

[ADR-048](048-round-drive-sa-gauge-timeline-capture.md) / [ADR-049](049-round-counter-count-capture.md) / [ADR-050](050-health-gauge-timeline-and-integrated-view.md)
でラウンド単位の計測を実装し R2 へ反映した。しかし公開後の振り返りで次の 2 点が課題になった。

1. **ゲージ詳細が独立していない**: 対戦検索タブの結果行クリックで開くパネルで、URL を持たず共有・戻る・直接アクセスができない。特定の試合を見返す導線として弱い。
2. **ラウンド集計が「計測値の一覧」になっている**: 勝敗情報が無いため、体力最小などの値が「追い詰めて勝った」のか「追い詰められて負けた」のか読めない。格闘ゲームの上達に直結しない項目（体力平均、計測率）が並んでいる。

### この機能の目的

本機能は**プレイ改善（自分の対戦の振り返り）**のためのものである。格闘ゲーム（SF6）の上達は
おおむね次の 2 点に集約される。

- **与ダメージの奪い合い**: どのくらい与え、どのくらい被弾したか。最大の被弾（＝大きなミス）はどこか
- **有限リソースの管理**: ドライブゲージ（バーンアウト）と SA ストックを活かせたか

したがって集計項目は「測れた値」ではなく、**プレイヤーが次の試合で改善できる問い**に対応させるべきである。

### 改善視点でプレイヤーが知りたい 3 つの問い

| # | 問い | 必要な指標 |
|---|------|-----------|
| ① | なぜ勝った / 負けた？ | 勝敗・勝利方法・最大被弾 |
| ② | どこで崩れた / 崩せた？ | 体力（最小・残）・最大被弾・バーンアウト |
| ③ | リソースを活かせたか？ | バーンアウト・SA 残し・カウンター |

### 勝敗データは既に取得できていた

| 粒度 | データ | 所在 | 従来の利用 |
|------|--------|------|-----------|
| 試合 | `player1/player2.result`（RESULT 画面検出、ADR-026） | `matches.parquet` | 対戦検索・履歴 |
| ラウンド | `round_results`（`0`=L, `1`=V, `2`=C, `3`=T, `4`=D, `5`=OD, `6`=SA, `7`=CA, `8`=P） | `battlelog_replays.parquet` | 対戦履歴のバッジのみ（ADR-047） |

`matches.battlelogReplayId` 経由でラウンド単位の勝敗と**勝利方法**まで取得できるにもかかわらず、
`round_stats` には反映されていなかった（ADR-048 で意図的に除外していた）。

## 決定

### 1. ゲージ詳細を独立ページ `/matches/{matchId}` にする（SPA ルート）

- サーバは `/` と同じ HTML シェルを `/matches/:matchId` にも配信し、**クライアントが `location.pathname` で表示ビューを切り替える**
- 対戦検索の結果行クリックは**詳細ページへの遷移**とし、従来の詳細パネルは廃止する
- 長所: URL 共有・ブックマーク・ブラウザの戻るが機能する。ビルド構成の変更が不要（Vite マルチページ化しない）
- 直接 URL を開いた場合に備え、ページ初期化時に必要な Parquet（matches / battlelog_replays / round_stats）を都度ロードする

### 2. ラウンド勝敗・勝利方法を `round_stats.parquet` に追加する

- `roundResult`: `win` / `loss` / `draw`（Battlelog `round_results`。`4`=draw、`0`=loss、他=win）
- `roundMethod`: 勝利方法コード `V` / `C` / `T` / `OD` / `SA` / `CA` / `P`（勝者の値から取る。引き分け・未マッチは null）
- `roundMethod` は**両サイドの行に同じ値**を持たせる（敗者側でも「どう負けたか」が読めるようにする）
- 試合の勝敗は `gauges/{matchId}.json` に `player1Result` / `player2Result` としても保持し、詳細ページが単一ファイルでも判定できるようにする

### 3. 改善指標を `round_stats.parquet` に追加する（算出はローカル生成時）

| 追加列 | 改善での意味 | 算出元 |
|--------|-------------|--------|
| `maxHitTaken` | 最大の単発被弾（％）。一番大きなミス | `gauges.health` の最大落差 |
| `burnoutCount` / `burnoutSec` | バーンアウト回数・累計秒。明確な負け筋 | `gauges.driveBurnout` |
| `saLeftAtEnd` | ラウンド終了時の SA ストック（使い残しの検知） | `gauges.sa` の最終値 |

- いずれも `gauges/{matchId}.json` の時系列から**決定的に**計算できるため、ローカル生成時に列として持つ
  - Web が軽い、`round_stats` で「バーンアウトしたラウンドの勝率」等の集計が将来可能
  - **動画の再デコードは不要**（既存の `gauges.json` から再生成できる）
- 未計測の表現は ADR-049 と同じ（未計測は null、計測済み 0 は 0）。ドライブ時系列が空のときはバーンアウトを null とする

### 4. 集計から削除・縮小する項目

| 項目 | 扱い | 理由 |
|------|------|------|
| `driveAvg` | **削除** | 時間重み付き平均は直感に合わず、`driveMin` / `driveEnd` とバーンアウトで足りる |
| `healthAvg` | **削除** | 同上。勝敗判断には `healthMin`（窮地）と `healthEnd`（残体力）で足りる |
| `detectionCoverage` | 列は保持、**表からは外す** | 計測品質の内部指標。低いラウンドがある場合のみページに注記を出す |

### 5. 詳細ページの構成

1. **試合サマリ**: 自分視点の勝敗（WIN/LOSE）、ラウンドスコア（1P - 2P）、使用キャラ、LP/MR（Battlelog にある場合）、公開日・試合開始時刻・YouTube リンク
2. **ラウンドごとの 3 ゲージチャート**（ADR-048/050 の既存実装。バーンアウト帯・CA マーカー・低計測率の注記）
3. **ラウンド集計テーブル**: ラウンド / サイド / キャラ / 勝敗 / 方法 / 体力最小 / 残体力 / 最大被弾 / ドライブ（最小→終了）/ バーンアウト（回数・秒）/ SA（最大・使用・残し）/ カウンタ / パニッシュ / 時間

### 6. 今回は採用しなかった指標（将来の拡張候補）

- 与ダメ/被ダメ合計（画面側で導出可能なので、必要になったら追加）
- CA 使用フラグ（`roundMethod = CA` で一部代替できる）
- ラウンドごとのセットスコア推移（マッチポイント表示）
- 逆転勝ちフラグ（例: 残体力 20% 未満から勝利）

## 選択肢の比較

### 別ページの実現方式

| 方式 | URL 共有 | 実装コスト | 判定 |
|------|---------|-----------|------|
| A. 既存 SPA に `/matches/{matchId}` を追加（同一 HTML） | ◎ | ◎ | **採用** |
| B. Vite マルチページで専用 HTML | ◎ | △ ビルド設定・エントリ追加 | 次点 |
| C. 新タブ「ゲージ詳細」＋試合選択 | ✕ | ○ | 不採用（試合ごとの URL を持てない） |

### ラウンド勝敗の保持先

| 方式 | 集計・分析 | 実装 | 判定 |
|------|-----------|------|------|
| A. `round_stats.parquet` に列追加（＋ gauges JSON に試合結果） | ◎ | ○ | **採用** |
| B. `gauges/{matchId}.json` にのみ保持 | ✕ | ◎ | 不採用（検索・集計できない） |
| C. Web が battlelog から都度 JOIN | △ | ◎ | 不採用（`round_stats` に載せない理由が無い） |

### 派生指標の算出場所

| 方式 | Web の負荷 | 集計 | 判定 |
|------|-----------|------|------|
| A. ローカル生成時に `round_stats` へ列として持つ | 軽い | ◎ | **採用** |
| B. Web が `gauges` JSON から描画時に計算 | やや重い | ✕ | 不採用 |

## リスクと対策

| リスク | 内容 | 対策 |
|--------|------|------|
| ラウンド勝敗のサイド対応 | Battlelog の p1/p2 と動画の 1P/2P の対応はキャラクター名に依存する（ADR-048 の既知制約） | 既存の自分視点変換（ADR-046/047 の `MY_PLAYER_ID` 判定）と同様の前提を踏襲。未マッチは試合単位の `result` にフォールバックし、ラウンド勝敗は null 表示 |
| `round_results` と検出ラウンド数の不一致 | 検出漏れ・マッピングずれでラウンド数が一致しない試合がある | 既存の `roundCountMatch` フラグと注記を維持（ADR-048 決定4）。不一致時も各ラウンドに結果が引ける範囲で表示する |
| 最大被弾の定義 | 10Hz サンプルの変化点の最大落差であり、複数ヒットをまとめて 1 件と数えうる | 「最大の単発被弾」ではなく「最大のまとまった被弾」の目安としてラベル・ツールチップで明示 |
| スキーマ変更 | `round_stats.parquet` の列削除は後方互換でない | R2 の `round_stats.parquet` は作り直す（既存は当該 3 本のみ）。Web は新列が無い旧 Parquet でも列参照しないようガードする |
| 直接 URL アクセス | `/matches/{matchId}` を直接開くと Parquet ロードが必要 | ページ初期化時に必要なテーブルのみロードし、失敗しても描画できるよう個別に try/catch する |

## データモデル

`round_stats.parquet`（1 行 = 1 ラウンド × 1 サイド。ADR-051 適用後）:

| 列 | 型 | 内容 |
|----|----|------|
| `videoId` / `matchId` / `round` / `side` / `character` | - | 識別子（従来どおり） |
| `roundStartTime` / `roundEndTime` / `durationSec` | - | HUD 表示区間（従来どおり） |
| `roundResult` | string \| null | `win` / `loss` / `draw`（ADR-051） |
| `roundMethod` | string \| null | `V` / `C` / `T` / `OD` / `SA` / `CA` / `P`（ADR-051） |
| `driveMin` / `driveEnd` | float \| null | ドライブ本数の最小・最終（`driveAvg` は削除） |
| `saMax` / `saUsedCount` / `saLeftAtEnd` | int \| null | 最大ストック・使用回数・終了時残し（ADR-051） |
| `detectionCoverage` | float \| null | 計測率（表からは外し注記に使用） |
| `healthMin` / `healthEnd` | float \| null | 最小体力・残体力（`healthAvg` は削除） |
| `maxHitTaken` | float \| null | 最大の単発被弾％（ADR-051） |
| `burnoutCount` / `burnoutSec` | int/float \| null | バーンアウト回数・累計秒（ADR-051） |
| `counterCount` / `punishCounterCount` | int \| null | カウンター回数（ADR-049） |

`gauges/{matchId}.json` の追加フィールド（ADR-051）:

```json
{
  "videoId": "DSgD_bQhxp0",
  "matchId": "DSgD_bQhxp0_20",
  "detectedRoundCount": 2,
  "battlelogRoundCount": 2,
  "roundCountMatch": true,
  "player1Result": "loss",
  "player2Result": "win",
  "rounds": []
}
```

勝利方法コード（ADR-037 の `round_results` 値に対応）:

| コード | 値 | 意味 |
|--------|----|------|
| `V` | 1 | 通常勝利（Vanilla KO） |
| `C` | 2 | Chip KO |
| `T` | 3 | Time Up |
| `OD` | 5 | Overdrive KO |
| `SA` | 6 | Super Art KO |
| `CA` | 7 | Critical Art KO |
| `P` | 8 | Perfect |

## 実装状況（2026-10-10）

| ファイル | 内容 |
|---------|------|
| `packages/local/src/detection/gauge.py` | `build_round_stats_rows` に `roundResult` / `roundMethod` / `maxHitTaken` / `burnoutCount` / `burnoutSec` / `saLeftAtEnd` を追加し、`driveAvg` / `healthAvg` を削除 |
| `packages/local/src/storage/r2_uploader.py` | `round_stats.parquet` のスキーマ更新 |
| `packages/local/src/battlelog_matcher.py` | マッチ結果に `player1_round_results` / `player2_round_results` を追加 |
| `packages/local/main.py` | ゲージ詳細 JSON に試合勝敗を付与、`round_results` を集計行へマージ |
| `packages/local/scripts/upload_gauge_data.py` | Battlelog からラウンド結果・LP/MR を解決して反映 |
| `packages/local/scripts/analyze_counters.py` | ゲージ中間ファイル（`gauges/`）も出力 |
| `packages/web/src/server/routes/pages.tsx` | `/matches/:matchId` を追加（`/` と同じ HTML シェル） |
| `packages/web/src/client/main.ts` | パス判定によるルーティング、結果行クリックで遷移 |
| `packages/web/src/client/components/MatchDetailPage.ts` | 独立ページ（試合サマリ＋チャート＋集計表） |
| `packages/web/src/client/components/RoundGaugeChart.ts` | 集計テーブルの項目を再設計 |
| `packages/web/src/client/search.ts` | `queryMatchById`、`round_stats` の新列クエリ、Battlelog の LP/MR 取得 |

反映結果（手元 3 本を `scripts/upload_gauge_data.py --all` で再生成）:

| 動画 | ラウンド統計行 | roundResult（win/loss/null） | roundMethod の例 |
|------|---------------|------------------------------|------------------|
| `DSgD_bQhxp0` | 84 | - | V / OD / SA / CA / P |
| `JzKWGcwFt2w` | 52 | - | - |
| `Ndwu08Q--_M` | 48 | - | - |
| 合計 | 184 | 91 / 91 / 2 | V=126, OD=28, SA=12, P=10, CA=4, C=2 |

- `maxHitTaken` / `burnoutCount` / `burnoutSec` は全 184 行で非 null
- Web は `pnpm typecheck` / `pnpm test`（140 件）/ `pnpm build` が成功

## 実装チェックリスト

- [x] `build_round_stats_rows`: 勝敗・勝利方法・改善指標の追加と `driveAvg` / `healthAvg` の削除
- [x] `round_stats.parquet` スキーマ更新と再生成（手元 3 本）
- [x] ラウンド勝敗・勝利方法の取得（`battlelog_matcher` / `upload_gauge_data.py`）
- [x] ゲージ詳細 JSON への試合勝敗の付与（`player1Result` / `player2Result`）
- [x] `/matches/:matchId` ルートと独立ページ、検索結果クリックの遷移化
- [x] ラウンド集計テーブルの項目再設計、低計測率の注記
- [x] ユニットテスト更新（local / web）
- [ ] R2 実データでの Web 描画の目視確認

## 関連ADR

- [ADR-048: ラウンド単位のドライブゲージ・SAゲージ時系列取得](048-round-drive-sa-gauge-timeline-capture.md) - ラウンド境界・HUD 判定・保存の基盤（本 ADR が集計列を再設計）
- [ADR-049: ラウンド単位のカウンター・パニッシュカウンター回数取得](049-round-counter-count-capture.md) - カウンター列
- [ADR-050: ラウンド単位の体力ゲージ時系列取得と3ゲージ統合表示](050-health-gauge-timeline-and-integrated-view.md) - 体力列（`healthAvg` は本 ADR で削除）
- [ADR-026: 対戦動画からの勝敗検出](026-result-screen-match-outcome-detection.md) - 試合単位の勝敗
- [ADR-037: Battlelog round_results の値の意味](037-battlelog-round-results-value-semantics.md) - ラウンド勝敗・勝利方法コード
- [ADR-047: 対戦履歴へのラウンド単位結果表示](047-match-history-round-results-display.md) - ラウンド勝敗表示の前例
- [ADR-046: LP推移グラフのWeb表示機能](046-lp-history-chart.md) - 自分視点判定・チャートの前例
