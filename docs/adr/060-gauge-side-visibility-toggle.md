# ADR-060: ゲージ詳細ページのサイド表示切り替え（片側のみ表示）

## ステータス

採用 - 2026-10-12（実装完了 2026-10-12）

## 文脈

### 問題: 1P / 2P の線が重なって見づらい

ADR-048〜051 で追加したゲージ詳細ページ（`/matches/{matchId}`）は、各ラウンドの体力・ドライブ・SA の推移を 1P / 2P の 2 系列で 1 つの SVG に重ねて描画している。2 系列は色（`--color-primary` / `--color-accent`）で区別しているが、次のようなケースで線が重なって読み取りづらい。

- ミラーマッチなど両者のゲージ推移が近い
- 片方だけを見たいとき（自分のドライブ管理を振り返る等）でも相手の線が常に描画される
- バーンアウトの背景帯（`gg-band-player1` / `gg-band-player2`）が重なって濃淡が分かりにくい

生データ（`GaugeData`）は両サイド分を持つ必要があるため、データ側は変更せず、表示だけを切り替えられるようにしたい。

## 決定

### 1. ページ上部にサイド表示フィルター（両方 / 自分 / 相手）を置く

ゲージ詳細ページのヘッダー直下に、表示対象サイドを選ぶトグルを 1 つ置く。選択肢は `both` / `player1` / `player2` の 3 つで、ラベルは `GaugeSideLabels` に応じて「自分 / 相手」または「1P / 2P」と表示する（ADR-048 で導入した `sideText` を再利用）。

```
表示  [両方] [自分のみ] [相手のみ]
```

### 2. グラフは両サイド分を描画したまま、CSS で片側を非表示にする

`buildGaugeSvg` は従来どおり 2 系列を描画し、コンテナ（`.match-detail-inner`）の `data-visible-side` 属性で `display: none` を切り替える。対象は系列線（`gg-line-*`）・バーンアウト帯（`gg-band-*`）・CA マーカー（`gg-marker-*`）・コンボマーカー（`gg-marker-combo-*`）・凡例（`gg-legend-item-*`）。

これにより以下を満たす。

- 切り替え時に SVG を再生成しない（innerHTML の再構築・スクロール位置リセットが不要）
- 純関数 `buildGaugeSvg` / `buildRoundGaugeHtml` のシグネチャを変えない（既存テスト・呼び出し元に影響しない）
- 生データ（`GaugeData` / Parquet / R2）は一切変更しない

### 3. 選択状態は localStorage に保存する

キー `sf6-chapter:gauge-visible-side` に保存し、ページ遷移・再読み込み後も選択を復元する。localStorage が使えない環境では既定値（両方）にフォールバックする。

## 検討した選択肢

| 選択肢 | 概要 | 結論 |
|--------|------|------|
| A. ページ上部トグル + CSS 非表示 | `data-visible-side` で片側を隠す | **採用** |
| B. ラウンドごとにトグルを置く | 各ラウンドのヘッダーに同じトグルを付ける | 不採用 |
| C. SVG 再生成（サイド指定で描画） | `buildGaugeSvg` に表示サイドを渡す | 不採用 |
| D. サイドごとに別グラフを並べる | 1P / 2P を上下 2 段に分けて描画 | 不採用 |

### A を採用した理由

- 実装が最小で、既存の描画ロジックとテストに手を入れずに済む
- ページ全体で一貫した表示になり、ラウンドをまたいで比較しやすい
- 再描画しないため操作が軽く、スクロール位置も保たれる

### B を不採用にした理由

- ラウンド数だけトグルが並び、UI が冗長になる
- ラウンドごとに表示サイドを変える需要は現時点で想定しにくい

### C を不採用にした理由

- `buildGaugeSvg` / `buildDriveSvg` / `buildSaSvg` / `buildHealthSvg` / `buildRoundGaugeHtml` / `buildGaugeRoundsHtml` すべてに引数を追加する必要があり、変更範囲が広い
- 切り替えのたびに DOM を再構築するため、スクロール位置がリセットされ操作感が悪い

### D を不採用にした理由

- 縦方向の占有が倍になり、ラウンド数が多い試合ではページが長くなりすぎる
- 重なりが問題になっているのは同一スケール上での比較であり、分離すると比較しづらくなる

## 帰結

- 片側表示中も縦軸（0〜6 / 0〜3 / 0〜100）と横軸は共通のままなので、スケールの読み間違いは起きない
- 片側表示中は凡例の該当項目も隠れるため、「どちらの色か」の混乱は生じない
- 表示切り替えは CSS のみで完結する。将来 SVG を Canvas 等へ置き換える場合は、同等のフィルタ手段を別途用意する必要がある

## 実装状況（2026-10-12）

| ファイル | 内容 |
|---------|------|
| `packages/web/src/client/components/RoundGaugeChart.ts` | `GaugeVisibleSide` / `GAUGE_SIDE_FILTER_STORAGE_KEY` / `GAUGE_SIDE_FILTER_OPTIONS` / `buildGaugeSideFilterHtml` を追加。凡例に `gg-legend-item-player1` / `gg-legend-item-player2` を付与 |
| `packages/web/src/client/components/MatchDetailPage.ts` | `buildMatchDetailPageHtml` にトグルを挿入。`setupGaugeSideFilter`（初期化・クリック登録・localStorage 保存）を追加し、`render` から呼び出し |
| `packages/web/public/static/main.css` | `.gg-side-filter*` のスタイルと `[data-visible-side]` による非表示ルールを追加 |
| `packages/web/src/client/RoundGaugeChart.test.ts` | `buildGaugeSideFilterHtml` のテストを追加 |
| `packages/web/src/client/MatchDetailPage.test.ts` | トグルがページ HTML に含まれることのテストを追加 |

## 関連ADR

- [ADR-048: ラウンド単位のドライブゲージ・SAゲージ時系列取得](048-round-drive-sa-gauge-timeline-capture.md) - 1P/2P を色分けする元実装と `sideText`
- [ADR-050: ラウンド単位の体力ゲージ時系列取得と3ゲージ統合表示](050-health-gauge-timeline-and-integrated-view.md) - 体力グラフの追加
- [ADR-051: ゲージ詳細ページの独立化とラウンド集計項目の改善視点での再設計](051-match-detail-page-and-round-stats-redesign.md) - 本 ADR が対象とするページの構成
