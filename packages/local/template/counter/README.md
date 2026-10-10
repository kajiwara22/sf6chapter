# カウンターバナーのテンプレート（ADR-049）

COUNTER / PUNISH COUNTER バナーのテンプレートマッチング用画像。
`config/detection_params.json` の `counter_analysis.templates` から参照される。

## 一覧

| ファイル | 種別 | サイド | サイズ (px) |
|---------|------|--------|-------------|
| `counter_left.png` | COUNTER | 1P（左） | 143 x 42 |
| `counter_right.png` | COUNTER | 2P（右） | 143 x 40 |
| `punish_left.png` | PUNISH COUNTER | 1P（左） | 307 x 42 |
| `punish_right.png` | PUNISH COUNTER | 2P（右） | 335 x 46 |

## 作成元（1080p）

すべて `packages/local/download/20261006[DSgD_bQhxp0].mp4` から切り出した。

| ファイル | 元フレーム | 切り出し領域 (x1, y1, x2, y2) |
|---------|-----------|------------------------------|
| `punish_left.png` | t=45.3s | (50, 476, 357, 518) |
| `punish_right.png` | t=1326.0s | (1560, 477, 1895, 523) |
| `counter_left.png` | t=54.5s | (57, 476, 200, 518) |
| `counter_right.png` | t=115.5s | (1730, 476, 1873, 516) |

## HUD 仕様（実測）

- バナーは「カウンターを決めた側」に表示される（左 = 1P / 右 = 2P）
- 文字の高さは約 30px、表示位置は y ≈ 478〜528 で固定
- 1P 側は左寄せ（x ≈ 55 から）、2P 側は右寄せ（x ≈ 1868 で終わる）
- 表示時間は中央値 1.7 秒。再トリガーで連続表示され、実測最長 6.7 秒
- COUNTER は細い黄バー、PUNISH COUNTER は太いオレンジのリボンで見た目が異なる

## 更新方法

HUD が変わった場合は、対象動画から該当フレームを切り出して上表の座標で作り直す。
座標は `config/detection_params.json` の `counter_analysis.roi`（1080p 基準、
`base_width` / `base_height` で比例拡大）と整合させること。

```bash
# フレームを1枚切り出す例
ffmpeg -ss 45.3 -i 'download/20261006[DSgD_bQhxp0].mp4' -frames:v 1 /tmp/frame.png
```

検証は `scripts/analyze_counters.py` が出力する
`intermediate/{video_id}/counters/banners/*.png`（バナー切り出し画像）を目視確認する。
