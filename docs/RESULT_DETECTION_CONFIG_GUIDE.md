# RESULT検出パラメータ設定ガイド

`packages/local/config/detection_params.json` の RESULT 検出パラメータを設定するためのガイドです。

## 概要

RESULT画面検出の動作は、`detection_params.json` で細かく制御できます。各プロファイル（production/test）ごとに異なる設定を用意できます。

## 設定項目

### 基本設定

```json
"result_detection": {
  "enabled": true,
  "result_template_path": "./result_screen_template/result_screen.png",
  "win_template_path": "./result_screen_template/win_text.png",
  "result_threshold": 0.3,
  "win_threshold": 0.3,
  "result_screen_search_region": null,
  "win_text_search_region": null,
  "target_time_offset": 2.0
}
```

### パラメータ詳細

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|----------|------|
| `enabled` | bool | true | RESULT検出を有効にするか |
| `result_template_path` | string | `./result_screen_template/result_screen.png` | RESULT画面テンプレート画像（相対パス） |
| `win_template_path` | string | `./result_screen_template/win_text.png` | Win テキストテンプレート（相対パス） |
| `result_threshold` | float | 0.3 | RESULT画面検出の閾値（0.0-1.0） |
| `win_threshold` | float | 0.3 | Win テキスト検出の閾値（0.0-1.0） |
| `result_screen_search_region` | [x1, y1, x2, y2] \| null | null | RESULT検出の検索領域 |
| `win_text_search_region` | [x1, y1, x2, y2] \| null | null | Win テキスト検出の検索領域 |
| `target_time_offset` | float | 2.0 | RESULT表示の推定時刻（秒） |

## 使用例

### 基本設定（全フレームで検索）

```json
"result_detection": {
  "enabled": true,
  "result_template_path": "./result_screen_template/result_screen.png",
  "win_template_path": "./result_screen_template/win_text.png",
  "result_threshold": 0.3,
  "win_threshold": 0.3,
  "result_screen_search_region": null,
  "win_text_search_region": null,
  "target_time_offset": 2.0
}
```

### RESULT画面が出現する領域が決まっている場合

```json
"result_detection": {
  "enabled": true,
  "result_template_path": "./result_screen_template/result_screen.png",
  "win_template_path": "./result_screen_template/win_text.png",
  "result_threshold": 0.3,
  "win_threshold": 0.3,
  "result_screen_search_region": [0, 0, 800, 500],
  "win_text_search_region": [300, 300, 1620, 900],
  "target_time_offset": 2.0
}
```

### 高精度検出（厳しい閾値）

```json
"result_detection": {
  "enabled": true,
  "result_template_path": "./result_screen_template/result_screen.png",
  "win_template_path": "./result_screen_template/win_text.png",
  "result_threshold": 0.4,
  "win_threshold": 0.4,
  "result_screen_search_region": null,
  "win_text_search_region": null,
  "target_time_offset": 2.0
}
```

### 低感度検出（緩い閾値）

```json
"result_detection": {
  "enabled": true,
  "result_template_path": "./result_screen_template/result_screen.png",
  "win_template_path": "./result_screen_template/win_text.png",
  "result_threshold": 0.25,
  "win_threshold": 0.25,
  "result_screen_search_region": null,
  "win_text_search_region": null,
  "target_time_offset": 2.0
}
```

## 設定のコツ

### 検索領域の指定

**なぜ検索領域を指定するのか？**
- RESULT画面が常に同じ位置に表示される場合、その領域のみを検索することで処理を高速化
- 誤検知を減らせる（背景ノイズの影響を軽減）

**検索領域の指定方法**

座標は `[x1, y1, x2, y2]` の形式：
- `x1`: 左上隅の X 座標
- `y1`: 左上隅の Y 座標
- `x2`: 右下隅の X 座標
- `y2`: 右下隅の Y 座標

例：RESULT画面が画面左上 600x400px の領域に表示される場合
```json
"result_screen_search_region": [0, 0, 600, 400]
```

### 閾値の調整

**RESULT画面検出の閾値が低い場合**
- 対症療法：`result_threshold` を 0.25-0.30 に下げる
- 根本対策：テンプレート画像を再作成（品質向上）

**Win テキスト検出の閾値が低い場合**
- 対症療法：`win_threshold` を 0.25-0.30 に下げる
- 根本対策：Win テンプレート画像を再作成

**推奨値の目安**

| 状況 | result_threshold | win_threshold |
|------|-----------------|---------------|
| 高精度（誤検知少ない） | 0.4-0.5 | 0.4-0.5 |
| バランス型 | 0.3-0.35 | 0.3-0.35 |
| 高感度（検知漏れ少ない） | 0.2-0.3 | 0.2-0.3 |

### target_time_offset の調整

RESULT画面の表示タイミングは対戦内容によって若干異なります：

```
対戦開始フレーム
  ↓（通常1-2秒）
RESULT 画面表示開始
```

例：
- 対戦時間が短い場合 → `target_time_offset: 1.5`
- 対戦時間が長い場合 → `target_time_offset: 2.5`
- 平均的 → `target_time_offset: 2.0`

## 複数プロファイルの使い分け

### production プロファイル

本番環境用の厳しい設定：

```json
"production": {
  ...
  "result_detection": {
    "enabled": true,
    "result_threshold": 0.35,
    "win_threshold": 0.35,
    ...
  }
}
```

### test プロファイル

テスト用の緩い設定：

```json
"test": {
  ...
  "result_detection": {
    "enabled": true,
    "result_threshold": 0.25,
    "win_threshold": 0.25,
    ...
  }
}
```

## 実行時の設定切り替え

### コマンドラインでプロファイルを指定

```bash
python main.py --detection-profile production
python main.py --detection-profile test
```

### 環境変数で指定

```bash
export DETECTION_PROFILE=production
python main.py
```

## トラブルシューティング

### RESULT画面が検出されない

**チェックリスト**：
1. テンプレート画像が存在するか？
2. テンプレートパスが正しいか？
3. `enabled` が `true` になっているか？
4. 閾値が高すぎないか？

**対策**：
1. `result_threshold` を 0.2 に下げてテスト
2. テンプレート画像を再作成
3. 検索領域を広げる（`null` に設定）

### Win テキストが検出されない

**対策**：
1. `win_threshold` を 0.2 に下げてテスト
2. Win テンプレート画像を再作成
3. `target_time_offset` を調整（1.5～3.0 で試す）

### 検出は成功したが勝敗が反対になる

**原因**：テンプレート画像が逆側のテキストで作成されている

**対策**：
1. Win テンプレート画像が左側のテキストから作成されているか確認
2. 必要に応じて再作成

## パラメータのログ出力

実行時に使用されているパラメータをログで確認：

```
[Result Detection]
  enabled:                  True
  result_template_path:     ./result_screen_template/result_screen.png
  win_template_path:        ./result_screen_template/win_text.png
  result_threshold:         0.30
  win_threshold:            0.30
  result_screen_search_region: None
  win_text_search_region:   None
  target_time_offset:       2.0
```

## 参考資料

- [RESULT_TEMPLATE_CREATION_GUIDE.md](RESULT_TEMPLATE_CREATION_GUIDE.md) - テンプレート作成ガイド
- [ADR-026](docs/adr/026-result-screen-match-outcome-detection.md) - 実装仕様
