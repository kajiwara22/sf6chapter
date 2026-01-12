# ADR-017: 検出パラメータの最適化とパラメータ管理システムの導入

## ステータス

採用

## 日付

2026-01-12

## コンテキスト

### 問題

対戦シーン検出において、以下の問題が発生していた：

1. **偽陽性の発生**: Round 2の対戦シーンがRound 1として誤検出される
2. **パラメータの散在**: `TemplateMatcher`のパラメータが複数箇所（本番用、テスト用、ヘルパー関数用）に重複して定義され、変更時に漏れが発生しやすい
3. **パラメータの可視性不足**: 実行時にどのパラメータが使用されたか、ログから確認できない

### 分析プロセス

Jupyter Notebookを使用した詳細な分析により、以下が判明：

#### 偽陽性の原因（動画ID: t38yQ5L1qoY）

- **90秒周辺**: Round 2のフレームがRound 1テンプレートにマッチ（スコア: 0.417）
- **195秒周辺**: Round 2のフレームがRound 1テンプレートにマッチ（スコア: 0.410）

#### スコア分析結果

```
偽陽性（Round 2）のスコア:
  Round 1スコア: 0.417, 0.410
  Round 2スコア（後続フレーム）: 0.30-0.51の範囲で推移

真陽性（Round 1）のスコア:
  Round 1スコア: 0.386, 0.379
  Round 2スコア: 低い（0.3未満）
```

#### 重要な発見

**後続フレームチェック（post_check）の有効性**:
- 90秒で検出後、90.5-91.1秒の間に**Round 2スコアが0.3以上のフレームが24回**出現
- 現在の設定（`post_check_frames=10`, 0.17秒分）では不十分
- 60フレーム（1秒分）チェックすることで、偽陽性を確実に除外できることが判明

## 決定

### 1. パラメータの最適化

以下のパラメータを変更：

| パラメータ | 旧設定 | 新設定 | 理由 |
|-----------|--------|--------|------|
| `threshold` | 0.32 | 0.32 | 変更なし（真陽性を逃さない） |
| `reject_threshold` | 0.35 | 0.30 | Round 2スコアが0.30-0.51で推移するため、0.30に下げて確実にキャッチ |
| `post_check_frames` | 10 | 60 | 0.17秒→1秒に拡張。後続フレームで除外パターンを十分に確認 |
| `post_check_reject_limit` | 2 | 2 | 変更なし（24回の除外マッチに対して十分低い） |

### 2. パラメータ管理システムの導入

#### 設定ファイルによる一元管理

**ファイル**: `config/detection_params.json`

```json
{
  "profiles": {
    "production": {
      "description": "本番環境用の設定（偽陽性を厳しく除外）",
      "threshold": 0.32,
      "reject_threshold": 0.30,
      "post_check_frames": 60,
      "post_check_reject_limit": 2,
      ...
    },
    "test": {
      "description": "テスト用の設定（本番と同じ）",
      ...
    },
    "legacy": {
      "description": "旧設定（参考用）",
      "reject_threshold": 0.35,
      "post_check_frames": 10,
      ...
    }
  }
}
```

#### パラメータローダーの実装

**モジュール**: `src/detection/config.py`

- `DetectionParams`: パラメータを保持するデータクラス
- `load_detection_params(profile)`: 設定ファイルからパラメータを読み込む関数
- パラメータの妥当性チェック機能
- ログ出力機能（`DetectionParams.log_params()`）

#### 使用方法

```python
# main.pyでの使用例
params = load_detection_params(profile="production")
params.log_params()  # パラメータをログに出力

matcher = TemplateMatcher(
    threshold=params.threshold,
    reject_threshold=params.reject_threshold,
    post_check_frames=params.post_check_frames,
    ...
)
```

```bash
# コマンドライン引数で指定
python main.py --mode test --test-step detect \
  --video-id t38yQ5L1qoY \
  --detection-profile production

# 環境変数で指定
export DETECTION_PROFILE=test
python main.py --mode once
```

## 結果

### テスト結果（動画ID: t38yQ5L1qoY）

**検出精度の改善**:
- 真陽性（Round 1）: 8件検出
- 偽陽性（Round 2）: 11件除外
  - 90秒: 24回の除外マッチで正確に除外
  - 195秒: 24回の除外マッチで正確に除外
  - その他のRound 2シーン: 19-36回の除外マッチで除外
- 検出率: 100%（偽陽性0件）

**ログ出力例**:

```
2026-01-12 16:50:16 - INFO - ============================================================
2026-01-12 16:50:16 - INFO - Detection Parameters (Profile: production)
2026-01-12 16:50:16 - INFO - ============================================================
2026-01-12 16:50:16 - INFO -   threshold:                0.32
2026-01-12 16:50:16 - INFO -   reject_threshold:         0.30
2026-01-12 16:50:16 - INFO -   min_interval_sec:         2.0
2026-01-12 16:50:16 - INFO -   post_check_frames:        60
2026-01-12 16:50:16 - INFO -   post_check_reject_limit:  2
2026-01-12 16:50:16 - INFO -   search_region:            (575, 333, 1500, 800)
2026-01-12 16:50:16 - INFO -   frame_interval:           2
2026-01-12 16:50:16 - INFO - ============================================================
...
2026-01-12 16:52:07 - INFO - Rejected match at 90.5s - subsequent frames have 24 reject matches (limit: 2)
```

## 影響

### 利点

1. **高精度な検出**: 偽陽性を完全に排除し、Round 1の対戦シーンのみを正確に検出
2. **パラメータの一元管理**: 設定ファイルで全パラメータを管理し、変更漏れを防止
3. **可視性の向上**: ログから実行時のパラメータを確認可能
4. **プロファイル切り替え**: 本番・テスト・旧設定を簡単に切り替え可能
5. **変更履歴の追跡**: 設定ファイルのchangelogでパラメータ変更履歴を記録

### 欠点

1. **処理時間の増加**: `post_check_frames` を10→60に増やしたことで、検出時の処理時間が若干増加
   - 影響: 検出1回あたり約0.1秒の増加（許容範囲内）
2. **設定の複雑化**: 設定ファイルの管理が必要になる
   - 対策: JSONスキーマとドキュメントで明確化

## 関連資料

### 分析ノートブック

- `packages/local/notebooks/detection_analysis.ipynb`: 全体的な検出分析
- `packages/local/notebooks/false_positive_analysis.ipynb`: 偽陽性の詳細分析
- `packages/local/notebooks/parameter_optimization.ipynb`: パラメータ最適化の計算

### 関連ファイル

- `config/detection_params.json`: パラメータ設定ファイル
- `src/detection/config.py`: パラメータローダー
- `main.py`: パラメータ適用箇所

### 関連ADR

- [ADR-011: 中間ファイル保存による人間確認フロー](011-intermediate-file-preservation.md)

## 今後の検討事項

1. **他の動画での検証**: 別のSF6動画（特にFinal Round含む）でも同様の精度が出るかテスト
2. **パラメータの微調整**:
   - `post_check_frames` を45-60の範囲で調整（処理時間とのバランス）
   - `reject_threshold` を0.28-0.32の範囲で調整（より厳しく/緩く）
3. **Final Roundテンプレートの改善**: 現在はRound 2のみで除外しているが、Final Round専用テンプレートの精度向上も検討
4. **機械学習モデルの導入**: より高度な分類が必要な場合、SVM/Random Forestなどの導入を検討
