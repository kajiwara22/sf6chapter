# ADR-076: ラウンド長（durationSec）の両サイド共通化

## ステータス

採用 - 2026-11-08（実装完了 2026-11-08）

## 文脈

### 問題: 同じラウンドなのに側別でラウンド長が大きく異なる

ADR-057 で `visibleTo` を「HUD が 5 秒以上途切れる前の最後の可視時刻」としたため、
片側の HUD 検出だけがラウンド途中で途切れると、そのサイドの `visibleTo` が早期に確定する。
`durationSec` は `visibleTo - visibleFrom` で計算されるため、同じラウンドでもサイドによって
ラウンド長が大きく異なる値になる。

実測（`lHLbZGQ8z1E`）:

| ラウンド | player1 | player2 | 差 |
|---|---|---|---|
| `_1804` R2 | 55.8 秒 | 23.5 秒 | 32.3 秒 |
| `_2385` R1 | 63.1 秒 | 27.0 秒 | 36.1 秒 |

player2 の `detectionCoverage` は 0.57〜0.86 で、HUD が実際には表示されているのに
検出成功が散発的になっていた（フレーム目視で確認済み）。ゲーム上のラウンドは 1 つなので、
片方の 23.5 秒 / 27.0 秒は明らかに誤りである。

Web のラウンド集計（`RoundGaugeChart`）は 1 ラウンド × 1 サイドの行に「時間」列を出すため、
同じラウンドの 2 行で 63.1 秒と 27.0 秒が並び、データ不整合に見える。

また `roundStartTime` も `visibleFrom` 基準だったため、HUD の出現検出が遅れた側は
ラウンド開始が 2 秒程度ずれ、YouTube リンクの遷移先も側別にずれていた。

## 決定

### 1. ラウンドの実効開始・終端は両サイドの HUD 可視範囲を統合して決める

`build_round_stats_rows()` で、ラウンドごとに両サイドの `visibleFrom` / `visibleTo` を集約する。

- ラウンド終端: `max(visibleTo)`（片側が途切れても、もう片方の可視終端までを採用）
- ラウンド開始: `min(visibleFrom)`（HUD が一度も検出できなかったサイドは除外）
- `durationSec = ラウンド終端 - ラウンド開始`
- `roundStartTime` / `roundEndTime` も同じ共通値から算出する

### 2. boundary とパーフェクト K.O. の切り詰めは共通値に対して行う

- `boundaryEndTime`（次ラウンドバナー時刻）を超える値は、試合間画面での誤検出として
  終端を境界まで切り詰める
- パーフェクト勝利の `_perfect_ko_time`（ADR-068）による切り詰めも、共通終端に対して適用する

片側だけが長く伸びる誤検出（ADR-057 で問題になった試合間画面の誤検出）は、
`_visible_range()` の途切れ判定と `boundaryEndTime` のクリップで除外されるため、
`max` を取っても誤検出側の値は採用されない。

## 検証結果

`lHLbZGQ8z1E`（46 ラウンド / 92 行）を再計測:

| 指標 | 修正前 | 修正後 |
|---|---|---|
| 同一ラウンドで `durationSec` が異なる行 | 21 ラウンド（最大差 36.1 秒） | **0 ラウンド** |
| `roundStartTime` / `roundEndTime` の不一致 | あり（最大 2 秒） | **0 件** |
| `durationSec` の範囲 | 21.0〜65.5 秒 | 22.4〜65.45 秒（平均 42.6） |

- 99 秒を超えるラウンドは 0 件（SF6 のラウンド上限内）
- `round_count(match/mismatch/unknown)=18/0/0` を維持
- ユニットテスト: 片側の HUD が途切れるケース、boundary クリップのケースを追加

## 影響と残課題

- ラウンド長・開始終了時刻がサイド共通になるため、既存動画の `round_stats` は
  再計測（`scripts/analyze_counters.py` → `scripts/upload_gauge_data.py`）で更新が必要
- 片側の HUD 検出成功率が低い根本原因（右側 HUD のマスク照合が散発的に失敗する）は未解決。
  本 ADR は「表示されるラウンド長の整合性」を担保するもので、検出そのものの改善は別課題とする

## 実装状況（2026-11-08）

| ファイル | 内容 |
|---|---|
| `packages/local/src/detection/gauge.py` | `build_round_stats_rows()` で両サイドの可視範囲を統合し、`roundStartTime` / `roundEndTime` / `durationSec` を共通化 |
| `packages/local/tests/test_gauge.py` | `test_round_duration_is_shared_between_sides` / `test_round_end_is_clipped_by_boundary` を追加 |

## 関連ADR

- [ADR-048: ラウンド単位のドライブゲージ・SAゲージ時系列取得](048-round-drive-sa-gauge-timeline-capture.md) - ラウンド分割と `round_stats` の元実装
- [ADR-051: ゲージ詳細ページの独立化とラウンド集計項目の改善視点での再設計](051-match-detail-page-and-round-stats-redesign.md) - Web のラウンド集計テーブル
- [ADR-057: ラウンド終端のHUD途切れ検出によるdurationSecの正確化](057-round-end-hud-gap-detection.md) - `visibleTo` の途切れ判定
- [ADR-068: パーフェクト勝利ラウンドの残体力・ラウンド長補正](068-perfect-round-health-and-duration-correction.md) - `_perfect_ko_time` による切り詰め
