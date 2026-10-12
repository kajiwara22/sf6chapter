# ADR-057: ラウンド終端のHUD途切れ検出によるdurationSecの正確化

## ステータス

採用 - 2026-10-12（実装完了 2026-10-12）

## 文脈

### 問題: durationSec が非現実的な値になる

ADR-048 の実装では、ラウンドの終端（`boundary_time`）を「次のラウンドバナー時刻 or 試合終端（次試合の開始時刻）」としていた。このため最終ラウンドでは、ラウンド終了（K.O.）後の勝利ポーズ・次試合待ちまでの時間がラウンド範囲に含まれる。

さらに `visibleTo`（ラウンドの実終端として使う）は「最後に drive / sa_stock が検出された時刻」だったため、**試合間画面で HUD が誤検出されると、その時刻まで `visibleTo` が伸びていた**。

実測（`DSgD_bQhxp0` / `_2457` R3）:

| 指標 | 値 |
|------|-----|
| `durationSec`（修正前） | 178.1 秒 |
| 実際のラウンド時間 | 約 40 秒（`health` イベントの最終記録が 37.45 秒） |
| `detectionCoverage` | 0.236（178 秒中の大半で HUD 未検出） |

HUD 可視区間（`gauges_samples.csv`）を確認すると、R3 は 2554.3〜2593.9 秒（39.6 秒）で終了しており、その後 **2725.5〜2732.9 秒（7.3 秒）** に試合間画面での誤検出が発生していた。この約 130 秒後の誤検出が `visibleTo` を 178 秒まで押し上げていた。

SF6 のラウンドはタイムアップでも 99 秒であり、178 秒は明らかに不正である。

## 決定

### 1. visibleTo を「HUD が長く途切れる前の最後の可視時刻」とする

`_visible_range()` を新設し、ラウンド内のサンプルを時系列で走査して、**HUD が `round_end_gap_sec`（5.0 秒）を超えて途切れた後の可視は無視**する。

- ラウンド中の短い HUD 途切れ（ヒット演出・CA カットイン等、通常 1〜2 秒）は同一区間として扱い、`visibleTo` に含める。
- K.O. 後の永続的な途切れ（次のラウンドまで数秒〜数十秒）は区間の終端とみなし、その後の誤検出を `visibleTo` から除外する。

`visibleFrom` は従来どおり最初の可視時刻を使う。

また、`visibleTo` を超えるサンプルは health / drive / sa / saProgress / healthRecoverable のイベント記録からも除外する。勝利演出中に消えたゲージを演出・キャラクターから誤計測した値が、ラウンド終端の最終値として残るのを防ぐ。

### 2. 閾値は設定ファイルで管理する

`round_end_gap_sec = 5.0` を `gauge_analysis.thresholds` に追加する。既存の `hud_flicker_tolerance_sec`（0.5 秒）や `drive_max_gap_sec`（1.0 秒）はサンプル間の短い欠損補完用であり、ラウンド終端判定にはより長い 5 秒を使う。

## 検証結果

| 動画 | 対象 | 修正前 | 修正後 |
|------|------|--------|--------|
| `DSgD_bQhxp0` | `_2457` R3 `durationSec` | 178.1 秒 | **39.2 秒** |

全体の `durationSec` 分布（再処理後）:

| 動画 | n | 最大 | 平均 | 中央値 | 99 秒超 |
|------|-----|------|------|--------|---------|
| `DSgD_bQhxp0` | 102 | 73.0 秒 | 46.3 秒 | 47.0 秒 | **0 件** |
| `f36vyEepil4` | 108 | 69.9 秒 | 48.3 秒 | 49.6 秒 | **0 件** |

両動画とも SF6 のラウンド時間上限（99 秒）を超えるケースがなくなった。残る 70 秒台のラウンドは、タイムアップ間際まで続いた実ラウンドである可能性が高い。

勝者 `healthEnd` の改善（`f36vyEepil4`、54 勝者ラウンド）:

- `_2614` R3 player1: 1.2% → 23.65%（勝利演出中の誤読を除去）
- `healthEnd` <= 5% の件数: 16 → 13 件

残る低 `healthEnd` は、実際にギリギリまで削られて逆転勝ちしたケース（例: `_1304` R1 player2 の 1.0%）であり、計測は正しい（ユーザー目視確認済み）。

## 実装状況（2026-10-12）

| ファイル | 内容 |
|---------|------|
| `packages/local/src/detection/gauge.py` | `_visible_range()` 追加、`_side_round_payload` の `visibleFrom` / `visibleTo` 計算を変更、イベント記録を `visibleTo` までに制限、`round_end_gap_sec` 追加 |
| `packages/local/config/detection_params.json` | `gauge_analysis.thresholds.round_end_gap_sec` を追加 |
| `packages/local/scripts/reprocess_gauge.py` | `scripts/` 移動に伴う `app_root` 修正 |

## 関連ADR

- [ADR-048: ラウンド単位のドライブゲージ・SAゲージ時系列取得](048-round-drive-sa-gauge-timeline-capture.md) - ラウンド分割と `visibleTo` の元実装
- [ADR-056: バーンアウト判定の白/グレー回復バー検出による高精度化](056-burnout-detection-recover-bar.md) - 同一の色ベース ROI 計測基盤の改善
