# RESULT画面テンプレート画像作成ガイド

ADR-026 の実装に必要なテンプレート画像を作成するためのガイドです。

## 概要

RESULT画面からの勝敗検出には、以下の 2 つのテンプレート画像が必要です：

1. **result_screen.png** - RESULT画面全体（左上の「RESULT」テキスト）
2. **win_text.png** - 「Win」テキストのテンプレート

これらのテンプレート画像は、`packages/local/config/detection_params.json` で設定・管理されます。

## 保存場所

```
packages/local/config/result_screen_template/
├── result_screen.png    # RESULT画面テンプレート
└── win_text.png         # Winテキストテンプレート
```

## 設定の流れ

1. **テンプレート画像を作成** ← このガイドで説明
2. **上記の場所に配置**
3. **`detection_params.json` で設定**（後述）
4. **動画処理を実行**

## テンプレート画像の作成手順

### 1. SF6の配信動画を用意

- 配信品質：1080p（FHD）固定
- フレームレート：30fps または 60fps
- サンプル動画：既に処理済みの YouTube チャプター動画を使用

### 2. result_screen.png の作成

#### 対象画面
- **対戦終了直後の RESULT 画面**（画面左上に「RESULT」テキスト表示）
- 通常、キャラクター対戦から 1-3 秒後に表示

#### 作成手順

1. 配信動画から RESULT 画面が表示されたフレームをキャプチャ
   - OBS、FFmpeg、VLC などで静止画を抽出
   - 解像度：1920x1080（1080p）
   - 形式：PNG（透過なし、BGR形式）

2. フレーム内の左上部分（「RESULT」テキスト周辺）を切り抜き
   - **推奨サイズ**：幅 400-600px、高さ 200-300px
   - 左上隅から、「RESULT」テキストを含む領域全体を対象
   - 周囲に若干の余白を含める（テンプレートマッチングの堅牢性向上）

3. 例：座標 (0, 0) から (600, 300) の領域を抽出

```python
import cv2

frame = cv2.imread("result_screen_full.png")
template = frame[0:300, 0:600]  # [y1:y2, x1:x2]
cv2.imwrite("result_screen.png", template)
```

#### 画像例（イメージ）

```
┌─────────────────────────────┐
│ ███  RESULT  ███            │ ← RESULT テキスト周辺
│ ─────────────────────────    │
│                             │ ← この領域全体をキャプチャ
│                             │
└─────────────────────────────┘
```

### 3. win_text.png の作成

#### 対象画像
- **「Win」テキストのみ**（左側または右側）
- RESULT 画面内の左右どちらかに表示

#### 作成手順

1. RESULT 画面から「Win」テキストのみを抽出
   - 左側（Player 1 勝利）と右側（Player 2 勝利）の場所を確認

2. 「Win」テキストの周辺領域を切り抜き
   - **推奨サイズ**：幅 100-200px、高さ 80-150px
   - テキストを中心に周囲に 20px 程度の余白

3. 例：

```python
import cv2

frame = cv2.imread("result_screen_full.png")

# 左側の「Win」テキストを抽出（座標例）
win_template = frame[400:550, 150:280]
cv2.imwrite("win_text.png", win_template)
```

#### 画像例（イメージ）

```
┌─────────────────────┐
│   W i n             │ ← このテキスト領域全体
└─────────────────────┘
```

## FFmpeg を使用した自動抽出（オプション）

動画ファイルから自動的にフレームを抽出する方法：

```bash
# RESULT画面推定時刻（例：2秒）のフレームを抽出
ffmpeg -i input_video.mp4 -ss 2 -frames:v 1 -q:v 2 result_frame.png

# 希望する解像度に統一（1080p固定）
ffmpeg -i input_video.mp4 -ss 2 -frames:v 1 -q:v 2 -vf "scale=1920:1080:force_original_aspect_ratio=decrease" result_frame.png
```

## テンプレート作成のコツ

### ✅ 推奨事項

- **複数フレーム確認**: 複数の動画から RESULT 画面をキャプチャし、最も典型的なものを選択
- **高コントラスト**: テキストと背景のコントラストが明確な画面を使用
- **統一フォーマット**: 常に 1080p、PNG 形式で保存
- **周囲にマージン**: テンプレートマッチング時のズレに対応するため、テキスト周囲に余白を含める

### ❌ 避けるべき事項

- **低解像度**: 1080p 以外での撮影・抽出（検出精度低下）
- **過度なトリミング**: テキスト中央のみ抽出（マッチング失敗のリスク）
- **ノイズ多い画面**: フレームレートが低い、または圧縮アーティファクトが多い画面
- **複数フォント混在**: フォント設定が異なる複数バージョン（SF6 アップデート時に注意）

## テンプレートの検証

テンプレートを作成したら、テンプレートマッチングで動作確認：

```python
import cv2
import numpy as np

# テンプレート読み込み
template = cv2.imread("result_screen.png")
win_template = cv2.imread("win_text.png")

# テスト動画でマッチング確認
cap = cv2.VideoCapture("test_video.mp4")
cap.set(cv2.CAP_PROP_POS_FRAMES, int(2 * 30))  # 2秒目のフレーム
ret, frame = cap.read()
cap.release()

# エッジ抽出
def preprocess(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (17, 17), 0)
    edges = cv2.Canny(blurred, 50, 150)
    return edges

template_edges = preprocess(template)
win_edges = preprocess(win_template)
frame_edges = preprocess(frame)

# マッチング
result = cv2.matchTemplate(frame_edges, template_edges, cv2.TM_CCOEFF_NORMED)
win_result = cv2.matchTemplate(frame_edges, win_edges, cv2.TM_CCOEFF_NORMED)

print(f"RESULT screen match: {result.max():.3f}")
print(f"Win text match: {win_result.max():.3f}")

# 閾値チェック（0.3以上が理想）
if result.max() >= 0.3 and win_result.max() >= 0.3:
    print("✅ Templates are valid!")
else:
    print("❌ Adjust templates and retry")
```

## SF6 アップデート時の対応

SF6 がアップデートされてゲーム UI が変更された場合：

1. **新しいテンプレートを作成**
   - アップデート後の配信動画から RESULT 画面をキャプチャ
   - 既存テンプレートと同じサイズ・位置でトリミング

2. **複数バージョンの管理**（将来的）
   - `result_screen_v1.png`, `result_screen_v2.png` など
   - 動画公開日時から最適なテンプレートを自動選択

## トラブルシューティング

### Q: テンプレートマッチングが 0.3 以上のスコアを出さない

**原因**：
- テンプレートサイズが小さすぎる（< 50x50px）
- テキストが不鮮明（低フレームレートまたは圧縮ノイズ）
- 解像度が 1080p でない

**対策**：
1. テンプレートサイズを 100-200px 程度に拡大
2. 別の動画フレームから再度抽出
3. `cv2.Canny()` の閾値を調整（現在: 50, 150）

### Q: 左右の「Win」テキストを区別できない

**原因**：
- テンプレート画像が同じ（対称性）
- フレーム抽出位置が不正

**対策**：
1. 左側の「Win」テキストのフレームを明確に抽出
2. 検出後、重心（centroid）の X 座標で左右判定

## 設定ファイルでのパラメータ管理

テンプレート作成後、`packages/local/config/detection_params.json` で検出パラメータを設定します。

### 設定例

```json
{
  "profiles": {
    "production": {
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
    }
  }
}
```

### パラメータの説明

| パラメータ | 説明 |
|-----------|------|
| `enabled` | RESULT検出を有効にするか（true/false） |
| `result_template_path` | RESULT画面テンプレートのパス |
| `win_template_path` | Win テキストテンプレートのパス |
| `result_threshold` | RESULT画面検出の閾値（推奨: 0.25-0.35） |
| `win_threshold` | Win テキスト検出の閾値（推奨: 0.25-0.35） |
| `result_screen_search_region` | RESULT検出の検索領域 [x1, y1, x2, y2]、null で全体 |
| `win_text_search_region` | Win テキスト検出の検索領域 [x1, y1, x2, y2]、null で全体 |
| `target_time_offset` | RESULT表示の推定時刻（秒、推奨: 1.0-3.0） |

### 検索領域の指定

RESULT画面と「Win」テキストが出現する領域が決まっている場合、検索領域を指定することで処理を高速化できます：

```json
"result_screen_search_region": [0, 0, 800, 500],    // 左上から800x500の領域
"win_text_search_region": [300, 300, 1620, 900]     // 対象の「Win」テキスト領域
```

座標形式：`[x1, y1, x2, y2]`
- `x1, y1`: 左上隅の座標
- `x2, y2`: 右下隅の座標

### 詳細ガイド

設定ファイルの詳細な説明は [RESULT_DETECTION_CONFIG_GUIDE.md](RESULT_DETECTION_CONFIG_GUIDE.md) を参照。

## 参考資料

- [RESULT_DETECTION_CONFIG_GUIDE.md](RESULT_DETECTION_CONFIG_GUIDE.md) - パラメータ設定ガイド
- [OpenCV テンプレートマッチング](https://docs.opencv.org/4.8.0/df/dfb/group__imgproc__object.html)
- [ADR-026: 対戦動画からの勝敗検出](026-result-screen-match-outcome-detection.md)
- [ADR-017: 検出パラメータの最適化](017-detection-parameter-optimization.md)
