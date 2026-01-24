# ADR-018: 中間ファイル形式の改善（手動修正の容易化）

## ステータス

採用

## 日付

2026-01-22

## コンテキスト

### 問題

誤検知やGeminiの認識ミスを手動で修正する際、以下の問題が発生していた：

1. **「第N戦」の採番問題**: `chapters.json`で1件削除すると、後続のすべての`title`（「第02戦」→「第01戦」など）を手動で修正する必要がある
2. **カウントフィールドの矛盾**: 削除後に`totalMatches`や`matchedFrames`を手動で修正し忘れると、データの整合性が崩れる
3. **Parquetとの不整合リスク**: 矛盾した状態でR2にアップロードすると、Parquetファイルに不正確なデータが蓄積される

### 現状のデータ構造

```json
// chapters.json
{
  "videoId": "bZ6H6qmIA1E",
  "totalMatches": 14,
  "chapters": [
    {"index": 1, "startTime": 553, "title": "第01戦 JP VS KEN", ...},
    {"index": 2, "startTime": 683, "title": "第02戦 RYU VS GUILE", ...}
  ]
}
```

1件削除すると：
- `totalMatches`: 14 → 13 （修正必要）
- 後続の`title`: 「第02戦」→「第01戦」、「第03戦」→「第02戦」... （全て修正必要）

## 決定

### 1. titleから「第N戦」を削除

**変更前**: `"第01戦 JP VS KEN"`
**変更後**: `"JP VS KEN"`

#### 理由

- 1件削除しても他の行を修正する必要がなくなる
- YouTubeチャプターは時刻順に表示されるため、視聴者は順番を認識可能
- Parquetの重複排除キー（`id` = `videoId_startTime`）はtitleと無関係なため、整合性に影響なし

### 2. chapters.jsonからtotalMatchesフィールドを削除

**変更前**:
```json
{
  "videoId": "...",
  "totalMatches": 14,
  "chapters": [...]
}
```

**変更後**:
```json
{
  "videoId": "...",
  "recognizedAt": "...",
  "chapters": [...]
}
```

#### 理由

- `chapters`配列の`.length`から動的に算出可能
- 手動修正時に更新を忘れるリスクを排除

### 3. detection_summary.jsonのtotalDetectionsは維持

```json
{
  "videoId": "...",
  "totalDetections": 14,  // 維持
  "detections": [...]
}
```

#### 理由

- OpenCVが「何件検出したか」という事実の記録として価値がある
- 手動修正の対象は`chapters.json`であり、`detection_summary.json`は通常触らない
- 「検出件数」と「最終的なチャプター数」が異なることは正常（誤検知の除外結果）

### 4. R2アップロード時のmatchedFramesは配列長から再計算

```python
# 変更前
"matchedFrames": len(detections)

# 変更後
"matchedFrames": len(chapters)  # chapters配列の実際の長さから計算
```

#### 理由

- 手動修正後の`chapters.json`から再アップロードする際、配列長から正確な値を算出
- ファイル上のカウント値に依存しないため、修正漏れによる不整合を防止

## 結果

### 変更後のデータ構造

#### chapters.json（手動修正の対象）

```json
{
  "videoId": "bZ6H6qmIA1E",
  "recognizedAt": "2026-01-21T22:59:56.288736Z",
  "chapters": [
    {
      "index": 1,
      "startTime": 553,
      "title": "JP VS KEN",
      "normalized": {"1p": "JP", "2p": "KEN"},
      "raw": {"1p": "JP", "2p": "Ken"},
      "confidence": 0.633
    }
  ]
}
```

1件削除する場合：
- 該当オブジェクトを削除するだけ
- `index`は参考値（削除後の連番修正は不要、`startTime`で順序が決まる）
- 他のフィールドの修正は不要

#### detection_summary.json（通常は手動修正しない）

```json
{
  "videoId": "bZ6H6qmIA1E",
  "totalDetections": 14,  // OpenCV検出時の事実として維持
  "detections": [...]
}
```

#### video_data.json / R2アップロードデータ

```json
{
  "videoId": "...",
  "chapters": [...],
  "detectionStats": {
    "totalFrames": 0,
    "matchedFrames": 13  // chapters配列の長さから再計算
  }
}
```

### 手動修正ワークフロー

1. `intermediate/{videoId}/chapters.json`を開く
2. 誤検知の`chapters`配列要素を削除
3. 保存
4. `python main.py --mode test --test-step r2 --video-id {videoId} --from-intermediate`で再アップロード

修正が必要な項目：
- ❌ ~~totalMatches~~ → 削除済み
- ❌ ~~後続のtitle~~ → 「第N戦」なし
- ❌ ~~matchedFrames~~ → 再計算される

## 影響

### 利点

1. **手動修正の大幅な簡素化**: 削除対象の行を消すだけで完了
2. **整合性の自動維持**: カウント値を配列長から再計算するため、不整合が発生しない
3. **Parquetの正確性向上**: 矛盾したデータがアップロードされるリスクを排除

### 欠点

1. **YouTubeチャプターから「第N戦」表記がなくなる**
   - 影響: 視聴者が何試合目かを明示的に知りたい場合、時刻から推測する必要がある
   - 対策: チャプターは時刻順に並ぶため、実用上の問題は軽微

2. **既存の中間ファイルとの互換性**
   - 影響: 過去に生成された`chapters.json`は旧形式のまま
   - 対策: 読み込み時に`totalMatches`フィールドは無視するため、旧ファイルも正常に処理可能

### 変更対象ファイル

- `packages/local/main.py`: title生成ロジック、totalMatches削除、matchedFrames再計算
- `packages/local/README.md`: ドキュメント更新（必要に応じて）

## 関連ADR

- [ADR-011: 中間ファイル保存による人間確認フロー](011-intermediate-file-preservation.md)
- [ADR-017: 検出パラメータの最適化とパラメータ管理システムの導入](017-detection-parameter-optimization.md)
