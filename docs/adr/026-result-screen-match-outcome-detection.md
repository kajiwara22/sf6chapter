# ADR-026: 対戦動画からの勝敗検出（RESULT 画面テンプレートマッチング）

## ステータス

提案（Proposed） - 2026-02-19

## 文脈

ADR-021 で YouTube チャプターと Battlelog リプレイのマッピングを実装したが、現状は以下の制限がある：

### 現在の問題

1. **Battlelog API からの取得率が低い**
   - 実装済み動画：20 件中 20 件のマッピング成功
   - しかし全対象動画では、約 369 件中 20 件のみ成功（5% の取得率）
   - 349 件は Battlelog にないか、API で取得できない（`result = NULL` 状態）

2. **ユーザーの検索ニーズに対応できない**
   - ADR-024 の Web UI で「特定キャラが勝った動画」「対戦カード検索」を実装予定
   - しかし勝敗データがないと、349 件の対戦は検索対象から除外
   - ユーザーの「苦手キャラ対策」「勝利パターン分析」というユースケースが実現できない

3. **手動修正の負担が大きい**
   - すべて手動修正では 349 件 × 24 本 = 数千件単位の修正が必要
   - 現実的ではない

### ユースケース

- 「特定キャラが負けた動画を見て、対策を検討したい」
- 「対戦カード（例：JP vs GOUKI）で自分の勝敗パターンを分析したい」
- 「得意なキャラ、苦手なキャラの勝敗比率を調べたい」

## 決定

RESULT 画面（対戦終了画面）の「Win」テキスト位置をテンプレートマッチングで検出し、勝敗を自動推定する。

### 検出アルゴリズム

#### フロー図

```
各チャプター（対戦）について：

┌────────────────────────────────┐
│ 1. Battlelog マッピング結果確認 │
│    winner_side != null?        │
│                                │
│ YES ─→ その値を採用 ✅        │
│ NO  ─→ 次へ                   │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 2. RESULT 画面検出             │
│    startTime 付近から          │
│    RESULT テキストを検出       │
│                                │
│ 見つかった ─→ 3へ             │
│ 見つからない ─→ 手動修正対象   │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 3. 「Win」位置判定             │
│    「Win」テキストの重心 X 座標│
│                                │
│ X < width/2  ─→ 'player1' ✅ │
│ X >= width/2 ─→ 'player2' ✅ │
│ 検出失敗 ─→ 手動修正対象      │
└────────────────────────────────┘
```

#### テンプレートマッチング処理

```python
def detect_result_from_frame(frame: np.ndarray) -> Optional[str]:
    """
    RESULT 画面から勝敗を検出

    Args:
        frame: 対戦画面フレーム

    Returns:
        'player1' | 'player2' | None (検出失敗)
    """
    # 1. RESULT 画面存在確認（テンプレートマッチング）
    if not has_result_screen(frame, result_template, threshold=0.3):
        return None

    # 2. 「Win」テキスト位置検出
    win_positions = find_win_text_positions(frame, win_template, threshold=0.3)
    if not win_positions:
        return None

    # 3. Win の重心計算
    centroid_x = np.mean([pos[0] for pos in win_positions])
    frame_width = frame.shape[1]

    # 4. 左右判定
    if centroid_x < frame_width / 2:
        return 'player1'  # 左側勝利
    else:
        return 'player2'  # 右側勝利
```

### 優先度階層

```
1. Battlelog マッピング結果
   ↓（失敗時）
2. 画像テンプレートマッチング
   ↓（失敗時）
3. 手動修正（ユーザー）
```

### chapters.json フォーマット変更

#### 修正前（ADR-021）

```json
{
  "videoId": "dQwqkOG2SQo",
  "chapters": [
    {
      "startTime": 30,
      "title": "GOUKI VS JP",
      "matchId": "dQwqkOG2SQo_30"
    }
  ]
}
```

#### 修正後（本ADR）

```json
{
  "videoId": "dQwqkOG2SQo",
  "chapters": [
    {
      "startTime": 30,
      "title": "GOUKI VS JP",
      "matchId": "dQwqkOG2SQo_30",
      "winner_side": null | "player1" | "player2"
    }
  ]
}
```

**フィールド説明**:

| フィールド | 型 | 説明 | 値の例 |
|-----------|-----|------|--------|
| `winner_side` | str\|null | 対戦の勝者（Player 1 または Player 2） | `"player1"` (左側勝利), `"player2"` (右側勝利), `null` (未定) |

**値の意味**（chapters.json に追加される情報）:
- `"player1"` = Player 1（左側キャラ）が勝利
- `"player2"` = Player 2（右側キャラ）が勝利
- `null` = 勝敗未定（Battlelog にもなく、画像検出も失敗）

### detection_summary.json への追加情報

chapters.json はユーザーが手動修正するため情報は最小化し、検出過程の詳細情報は `detection_summary.json` に記録：

```json
{
  "videoId": "-rtrvdTT0nU",
  "detections": [
    {
      "index": 1,
      "timestamp": 44.03333333333333,
      "frameNumber": 2642,
      "confidence": 0.6419310569763184,

      // ADR-026 新規追加
      "result_detection": {
        "winner_side": "player1" | "player2" | null,
        "detection_method": "image_template_matching" | "battlelog" | null,
        "detection_confidence": 0.85,
        "win_position": "left" | "right" | "unknown"
      }
    }
  ]
}
```

## 実装方針

### 1. テンプレート画像の準備

以下の 2 つのテンプレート画像をユーザーが手作業で作成：

```
packages/local/config/result_screen_template/
├── result_screen.png    # RESULT 画面全体（左上の「RESULT」テキスト）
└── win_text.png         # 「Win」テキストのテンプレート
```

**対象解像度**: 1080p（配信環境が 1080p 固定）

### 2. ResultScreenDetector クラス実装

```python
from pathlib import Path
import cv2
import numpy as np

class ResultScreenDetector:
    """RESULT 画面からの勝敗検出"""

    def __init__(
        self,
        result_template_path: str,
        win_template_path: str,
        result_threshold: float = 0.3,
        win_threshold: float = 0.3,
    ):
        self.result_template = cv2.imread(result_template_path, cv2.IMREAD_COLOR)
        self.win_template = cv2.imread(win_template_path, cv2.IMREAD_COLOR)

        if self.result_template is None:
            raise FileNotFoundError(f"Result template not found: {result_template_path}")
        if self.win_template is None:
            raise FileNotFoundError(f"Win template not found: {win_template_path}")

        # テンプレート前処理（エッジ抽出）
        self.result_template_edges = self._preprocess_for_matching(self.result_template)
        self.win_template_edges = self._preprocess_for_matching(self.win_template)

        self.result_threshold = result_threshold
        self.win_threshold = win_threshold

    @staticmethod
    def _preprocess_for_matching(image: np.ndarray) -> np.ndarray:
        """画像前処理：エッジ抽出"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        blurred = cv2.GaussianBlur(gray, (17, 17), 0)
        edges = cv2.Canny(blurred, 50, 150)
        return edges

    def detect_result(self, frame: np.ndarray) -> dict:
        """
        RESULT 画面から勝敗を検出

        Args:
            frame: 対戦画面フレーム（1080p 推定）

        Returns:
            {
                "winner_side": "player1" | "player2" | None,
                "detection_confidence": float (0.0-1.0),
                "win_position": "left" | "right" | "unknown",
                "detection_method": "image_template_matching"
            }
        """
        result = {
            "winner_side": None,
            "detection_confidence": 0.0,
            "win_position": "unknown",
            "detection_method": "image_template_matching",
        }

        # 1. RESULT 画面の存在確認
        if not self._has_result_screen(frame):
            return result

        # 2. 「Win」テキスト位置検出
        win_position = self._get_win_position(frame)
        result["win_position"] = win_position

        if win_position in ["left", "right"]:
            result["winner_side"] = "player1" if win_position == "left" else "player2"
            result["detection_confidence"] = 0.8  # テンプレートマッチング信頼度

        return result

    def _has_result_screen(self, frame: np.ndarray) -> bool:
        """RESULT 画面テンプレートマッチング"""
        frame_edges = self._preprocess_for_matching(frame)
        match_result = cv2.matchTemplate(
            frame_edges,
            self.result_template_edges,
            cv2.TM_CCOEFF_NORMED
        )

        return match_result.max() >= self.result_threshold

    def _get_win_position(self, frame: np.ndarray) -> str:
        """「Win」テキストの左右位置を判定"""
        frame_edges = self._preprocess_for_matching(frame)
        matches = cv2.matchTemplate(
            frame_edges,
            self.win_template_edges,
            cv2.TM_CCOEFF_NORMED
        )

        # マッチした位置をすべて取得
        win_matches = np.argwhere(matches >= self.win_threshold)

        if len(win_matches) == 0:
            return "unknown"

        # 重心計算
        centroid_x = np.mean(win_matches[:, 1])
        frame_width = frame.shape[1]

        return "left" if centroid_x < frame_width / 2 else "right"
```

### 3. main.py への統合

`_run_battlelog_matching()` メソッド内に以下を追加：

```python
async def _run_battlelog_matching(self):
    """Battlelog マッピング + 画像ベース検出の統合"""

    # ... 既存の Battlelog マッピング処理 ...
    chapters = await self.battlelog_matcher.match_chapters_with_battlelog(...)

    # 画像テンプレートマッチングで補完
    detector = ResultScreenDetector(
        result_template_path=str(
            self.app_root / "config" / "result_screen_template" / "result_screen.png"
        ),
        win_template_path=str(
            self.app_root / "config" / "result_screen_template" / "win_text.png"
        ),
    )

    # 動画ファイルを開く
    cap = cv2.VideoCapture(self.video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)

    for chapter in chapters:
        # Battlelog マッピングが成功しているならスキップ
        if chapter.get('winner_side') is not None:
            continue

        logger.info(f"Attempting image-based result detection for {chapter['matchId']}")

        # RESULT 画面の推定フレーム位置（対戦開始 + 2 秒）
        target_time = chapter['startTime'] + 2.0
        frame_number = int(target_time * fps)

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()

        if not ret:
            logger.warning(f"Failed to extract frame for {chapter['matchId']}")
            continue

        # 勝敗を検出
        detection = detector.detect_result(frame)

        if detection["winner_side"] is not None:
            chapter['winner_side'] = detection["winner_side"]
            logger.info(f"✅ Detected result: {detection['winner_side']} (win_pos={detection['win_position']})")
        else:
            logger.warning(f"❌ Result detection failed for {chapter['matchId']}")

    cap.release()
    return chapters
```

## トレードオフと帰結

### メリット ✅

- **軽量**: OpenCV のみ使用、追加依存なし
- **既存統合**: 既存の `TemplateMatcher` クラスと同じパターン（エッジ抽出 + テンプレートマッチング）
- **段階的検証**: Battlelog → 画像検出 → 手動修正で信頼度向上
- **高カバー率**: すべての対戦に試行可能（Battlelog 5% より範囲広い）
- **ユーザー負担軽減**: 自動検出で手動修正対象を大幅削減

### デメリット ⚠️

- **画面仕様変更脆弱**: SF6 アップデートで RESULT 画面レイアウト変更 → テンプレート再調整必要
- **画像品質依存**: 配信品質が低い、フレームレートが低い → 検出失敗の可能性
- **100% 精度でない**: RESULT 画面の見切れ、複数「Win」テキストなど → 手動修正必須
- **1080p 固定**: 他の解像度での対応不可（テンプレートが解像度依存）

### 互換性 ✅

- chapters.json スキーマ拡張（後方互換性あり）
- ADR-021（Battlelog マッピング）と直交した設計
- detection_summary.json への追加情報は既存フィールドに影響なし

## 将来の改善

1. **複数テンプレート対応**
   - SF6 アップデート時に複数バージョンのテンプレートを管理
   - 動画公開日時から適切なテンプレートを選択

2. **精度改善**
   - Gemini API による画像認識への段階的移行（コスト vs 精度のトレード考慮）
   - 機械学習ベースの勝敗検出（将来）

3. **マルチ解像度対応**
   - 将来的に 4K など他の解像度に対応する場合
   - テンプレートのスケーリングやテンプレート複数管理

## 実装チェックリスト

- [ ] RESULT 画面テンプレート画像作成（result_screen.png）
- [ ] 「Win」テキストテンプレート画像作成（win_text.png）
- [ ] `ResultScreenDetector` クラス実装
- [ ] `main.py` への統合
- [ ] 単体テスト：RESULT 画面検出
- [ ] 単体テスト：「Win」位置判定
- [ ] 24 本動画での検出実行
- [ ] 検出結果確認 & ユーザー手動修正（ADR-011）
- [ ] detection_summary.json への結果記録確認

## 次のステップ

1. **ADR-026 承認**
2. **テンプレート画像の準備**（手作業）
3. **`ResultScreenDetector` クラスの実装**
4. **`main.py` への統合**
5. **24 本動画での一括検出実行**
6. **ユーザーによる手動修正（ADR-011 フロー）**
7. **ADR-024（Web UI 検索フィルター）実装時にデータを活用**

## 参考資料

- [ADR-021: YouTube チャプターと Battlelog リプレイのマッピング実装](021-battlelog-chapter-mapping-implementation.md)
- [ADR-024: Web UI 検索フィルター - Battlelog 勝敗結果対応](024-web-ui-search-filter-with-match-results.md)
- [ADR-011: 中間ファイル保存による人間確認フロー](011-intermediate-file-preservation.md)
- OpenCV テンプレートマッチング: https://docs.opencv.org/4.8.0/df/dfb/group__imgproc__object.html

