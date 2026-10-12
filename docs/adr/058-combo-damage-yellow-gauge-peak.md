# ADR-058: 薄い黄色ゲージ（コンボダメージ表示）のピーク検出による maxComboDamage の追加

## ステータス

採用 - 2026-10-12（実装完了 2026-10-12）

## 文脈

### 前提: SF6 のコンボ中のダメージ表示

SF6 ではコンボを食らっている間、体力バーの上に**薄い黄色ゲージ（コンボダメージ表示）**が表示される。この黄色ゲージはコンボの進行に伴って伸び、コンボ確定で消える。したがって「薄い黄色ゲージが最大まで伸び切った量」が、そのコンボの正確な被ダメージ合計である。

これは、時間経過で回復する**白ゲージ（回復可能ダメージ）**とは別物である。

### 問題: maxHitTaken はコンボ合計を過小評価する

ADR-051 の `maxHitTaken` は「health 変化点列の隣接 2 点間の最大減少」として定義していた。しかし、計測は 0.1 秒サンプリング＋メディアン平滑化＋変化点抽出のため、**コンボ中の個々のヒットはなだらかになり、変化点間の減少幅はコンボ合計より大幅に小さく出る**。

実測（`f36vyEepil4` / `_282` R2 player2、SA3 込みコンボ）:

| 指標 | 値 |
|------|-----|
| 実際のコンボダメージ（health 推移 71.4% → 13.0%） | 約 58% |
| `maxHitTaken`（変化点間最大減少） | **12.4%** |
| 薄い黄色ゲージのピーク | **51.2%** |

`maxHitTaken` は 12.4% と大きく過小評価する一方、薄い黄色ゲージのピークは実際のダメージに近い値になる。

### 発見: healthRecoverable（ADR-054）は実は薄い黄色ゲージを検出していた

ADR-054 は「白ゲージ（回復可能ダメージ）」を意図して `health_recoverable_hue_ranges = [[15, 50]]`（黄〜オレンジ）で検出を実装した。しかし、白ゲージは「白＝低彩度」であり、色相 15〜50 では本来検出されない。

`f36vyEepil4` のコンボシーン（`_282` R2、t=353〜369）の画素解析で、コンボ中に伸びる**薄い黄色ゲージが hue 15〜50 に該当**し、コンボ終盤（t=367〜369）で体力ゲージ ROI の 99% 以上を占めることを確認した。

つまり、現状の `healthRecoverable` が「たまに検出される」のは、意図した白ゲージではなく、**薄い黄色ゲージ（コンボダメージ表示）を検出していた**ためである。

## 決定

### 1. round_stats に maxComboDamage を追加する

`healthRecoverable`（＝薄い黄色ゲージ）の時系列の**ピーク値**を「そのラウンドで最も大きいコンボ被ダメージ」として `round_stats.parquet` の列に追加する。

- 列名: `maxComboDamage`（%）
- 未検出（黄ゲージが出なかったラウンド）は null

### 2. maxHitTaken を「コンボ合計の近似」と再定義する

`maxHitTaken` の実態は「変化点間の最大減少」であり、コンボ合計の**近似値**である。厳密なコンボ被ダメージは `maxComboDamage` を参照する、とドキュメント・ADR-051 の解釈を更新する。

### 3. 真の白ゲージ（回復可能ダメージ）検出は将来課題とする

現状の `healthRecoverable` は薄い黄色ゲージを検出しており、**真の白ゲージ（回復可能ダメージ）の検出は実装できていない**。白ゲージは低彩度の白を対象に別途再設計する必要がある。本 ADR では対象外とし、既知の課題として記録する。

## 検証結果（`f36vyEepil4`、108 ラウンド×サイド）

- `maxComboDamage` 検出: 61 / 108 件
- 分布: min 1.2% / max 51.9% / mean 23.2% / median 24.3%

`maxHitTaken` と `maxComboDamage` の比較（上位）:

| ラウンド | maxHitTaken（近似） | maxComboDamage（黄ゲージ） |
|----------|--------------------|---------------------------|
| `_1500` R2 player2 | 47.4 | 51.9 |
| `_282` R2 player2 | 12.4 | 51.2 |
| `_2791` R2 player1 | 14.1 | 48.8 |
| `_2791` R2 player2 | 46.7 | 47.8 |

`_282` R2 player2 のように `maxHitTaken` が 12.4% しか出ないケースでも、`maxComboDamage` は 51.2% と実際のコンボダメージを捉えている。

## 既知の課題

- **真の白ゲージ（回復可能ダメージ）の未検出**: 現状の hue 15〜50 は薄い黄色ゲージ用。白ゲージは低彩度の白を対象に検出を再設計する必要がある（ADR-054 の実装は実質的に「薄い黄色ゲージ検出」だった）。
- **ピーク検出のタイミング誤差**: コンボの最初のヒットが黄ゲージに反映される前に計測が走ると、ピークが数%小さく出る場合がある。
- **薄い黄色ゲージの検出率**: 61 / 108 件。コンボが短い・画面が激しく遮蔽される場合は検出できないことがある。

## 実装状況（2026-10-12）

| ファイル | 内容 |
|---------|------|
| `packages/local/src/detection/gauge.py` | `_max_value()` 追加、`build_round_stats_rows` に `maxComboDamage` / `maxComboDamageAt` 列を追加、`_max_drop()` の docstring を「コンボ合計の近似」に修正 |
| `packages/local/src/storage/r2_uploader.py` | round_stats スキーマに `maxComboDamage` / `maxComboDamageAt` を追加 |
| `packages/web/src/shared/types.ts` / `client/types.ts` | `RoundStatsRow` / `RoundStatsQueryRow` に `maxComboDamage` / `maxComboDamageAt` を追加 |
| `packages/web/src/client/search.ts` | `queryRoundStats` にコンボ列を追加（列存在チェック付き） |
| `packages/web/src/client/components/RoundGaugeChart.ts` / `MatchDetailPage.ts` | ラウンド集計テーブルに「最大コンボ」列を追加し、該当シーンへのYouTubeリンク（`roundStartTime + maxComboDamageAt`）を表示 |

## 関連ADR

- [ADR-051: ゲージ詳細ページの独立化とラウンド集計項目の改善視点での再設計](051-match-detail-page-and-round-stats-redesign.md) - `maxHitTaken` の元定義
- [ADR-054: 回復可能ダメージ（白ゲージ）の観測と回復ゲート](054-health-recoverable-damage-observation.md) - 現状の `healthRecoverable` 実装。実質的に薄い黄色ゲージを検出していた
- [ADR-050: ラウンド単位の体力ゲージ時系列取得と3ゲージ統合表示](050-health-gauge-timeline-and-integrated-view.md) - 体力ゲージ ROI の色判定基盤
