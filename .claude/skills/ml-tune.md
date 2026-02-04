# ml-tune - SF6 Chapter Detection Parameter Tuning Assistant

## Implementation Status

### 現在の状態
- ✅ **既存Notebookあり**: `packages/local/notebooks/` に7つのNotebookが存在
  - `detection_analysis.ipynb` - 検出結果の分析
  - `false_positive_analysis.ipynb` - 偽陽性の分析
  - `frame_quality_analysis.ipynb` - フレーム品質分析
  - `parameter_optimization.ipynb` - パラメータ最適化
  - `parameter_tuning.ipynb` - パラメータ調整
  - `recognize_frame_offset_analysis.ipynb` - オフセット分析
  - `reject_template_creator.ipynb` - 除外テンプレート作成

### このスキルの役割
⚠️ **このスキルは、既存のNotebook分析ワークフローを標準化・自動化するための仕様書です。**

実装予定（優先度順）:
1. **[最優先] ipywidgetsインタラクティブUI統合**
   - すべてのNotebookに必須実装
   - 既存Notebookで部分的に使用中のため、統一フォーマット化が必要
   - リアルタイムフィードバック機能の実装
2. **TP/FP自動分類の標準化**
   - chapters.jsonとdetection_summary.jsonの照合ロジック
   - 信頼度スコア付き分類
3. **既存Notebookをベースにしたテンプレート生成ロジック**
   - `parameter_tuning.ipynb`をベースに汎用化
   - 分析タイプごとのカスタマイズ
4. **パラメータ推奨アルゴリズムの統合**
   - F1スコア最大化アルゴリズム
   - トレードオフ可視化

## Purpose
機械学習・画像処理パラメータの調整を支援するJupyter Notebookの作成と分析を行います。
真陽性/偽陽性の分類、評価指標の計算、最適パラメータの提案を自動化します。

## Usage
/ml-tune [analysis-type] --video-id VIDEO_ID [options]

## Arguments
- `analysis-type`: 分析タイプを指定
  - `threshold`: 閾値調整（検出スコア、除外スコアなど）
  - `offset`: フレームオフセット調整
  - `template`: テンプレートマッチング評価
  - `quality`: フレーム品質分析
  - `custom`: カスタム分析（ユーザー指定）

## Options
- `--video-id VIDEO_ID`: 分析対象の動画ID（必須）
- `--create-notebook`: 新規Notebookを生成（デフォルト: true）
- `--interactive`: ipywidgetsスライダーUIを含める（**デフォルト: true、常に有効推奨**）
- `--output-path PATH`: Notebook出力先（デフォルト: packages/local/notebooks/）
- `--config-path PATH`: 設定ファイルパス（デフォルト: packages/local/config/detection_params.json）

### 重要: インタラクティブUIについて
⚠️ **`--interactive`オプションは必須機能です。**

**理由**:
- パラメータ調整は試行錯誤が前提であり、リアルタイムフィードバックが不可欠
- スライダーによる直感的な操作で、最適値を素早く発見できる
- 静的なグラフだけでは、パラメータの影響範囲を把握しづらい

**実装時の注意**:
- ipywidgetsは必ず依存関係に含める
- Notebook生成時、スライダーUIセルを必ず含める
- 無効化オプション（`--no-interactive`）は提供しない

## Execution Steps

### 1. データ構造の分析
- 中間ファイル（detection_summary.json, chapters.json）の読み込み
- 現在のパラメータ設定の確認
- データの基本統計（検出数、TP/FP比率など）

### 2. Notebook生成
分析タイプに応じたNotebookを生成：

**共通セクション:**
- セットアップ（パス、インポート、パラメータ）
  ```python
  # 日本語フォント設定（環境自動判定）
  import matplotlib.pyplot as plt
  import matplotlib.font_manager as fm
  import warnings
  import platform
  
  warnings.filterwarnings('ignore', category=UserWarning, module='matplotlib')
  
  # 環境に応じたフォント選択
  system = platform.system()
  if system == 'Darwin':  # macOS
      plt.rcParams['font.family'] = 'Hiragino Sans'
  elif system == 'Linux':
      # 利用可能なフォントを検索
      fonts = [f.name for f in fm.fontManager.ttflist]
      if 'Noto Sans CJK JP' in fonts:
          plt.rcParams['font.family'] = 'Noto Sans CJK JP'
      elif 'IPAexGothic' in fonts:
          plt.rcParams['font.family'] = 'IPAexGothic'
  elif system == 'Windows':
      plt.rcParams['font.family'] = 'Yu Gothic'
  
  plt.rcParams['axes.unicode_minus'] = False
  ```
- データ読み込みと基本統計
- TP/FP自動分類（chapters.jsonとの照合）

**分析タイプ別セクション:**

#### threshold分析
- スコア分布のヒストグラム
- TP/FPのスコア散布図
- ROC曲線（オプション）
- 最適閾値の提案（TP最大化、FP最小化）

#### offset分析
- 複数オフセット値でのフレーム抽出
- グリッド表示（オフセット×検出インデックス）
- 各オフセットでの認識成功率
- 推奨オフセット値の提案

#### template分析
- テンプレートマッチスコアの時系列分析
- post_check_frames期間のスコア変動
- 新規テンプレート候補の抽出
- テンプレート有効性評価

#### quality分析
- フレーム品質指標の計算（標準偏差、エッジ密度など）
- 品質指標の比較と相関分析
- 最適な品質指標の選定

### 3. インタラクティブUI（必須実装）
**すべてのNotebookに以下を含める:**

- **ipywidgetsスライダー**: パラメータのリアルタイム調整
  - 閾値: 0.0〜1.0（0.01刻み）
  - オフセット: 0〜30フレーム（1フレーム刻み）
  - その他パラメータ: 分析タイプに応じて動的生成
- **リアルタイムプレビュー**: スライダー変更時に即座にグラフ更新
- **微調整ボタン**:
  - 大幅調整: -10, +10
  - 微調整: -1, +1
  - リセットボタン: デフォルト値に戻す
- **確定ボタン**: 選択した値をJSON形式でエクスポート
- **フィードバック表示**:
  - 現在の評価指標（Precision, Recall, F1）
  - パラメータ変更による影響の可視化

### 4. 評価指標の計算
- 精度（Precision）: TP / (TP + FP)
- 再現率（Recall）: TP / (TP + FN)
- F1スコア: 2 * (Precision * Recall) / (Precision + Recall)
- 混同行列の表示

### 5. パラメータ推奨
- 分析結果に基づく推奨値の算出
- トレードオフの可視化（精度 vs 再現率など）
- 複数の候補値の提示

### 6. 設定ファイルへの反映
- 推奨パラメータのJSON形式エクスポート
- detection_params.jsonへのマージコード生成
- 変更内容のdiff表示

## Claude Code Integration

### 使用するツール
- **Read**: 中間ファイル、設定ファイル、既存Notebookの読み込み
- **NotebookEdit**: Jupyter Notebookの生成・編集
  - **必須実装**: ipywidgetsを含むインタラクティブUIセルの生成
  - セルタイプ: `code`（スライダー、ボタン）と`markdown`（説明）
  - ipywidgetsの依存関係チェックと警告表示
- **Bash**: 動画ファイルの存在確認、ディレクトリ作成、ipywidgetsインストール確認
- **Edit**: 設定ファイルの更新（ユーザー承認後）

### インタラクティブUI実装の詳細

NotebookEditツールで以下のセルを生成する必要があります:

1. **ipywidgetsインポートセル**（必須）
```python
import ipywidgets as widgets
from IPython.display import display, clear_output
```

2. **スライダーUIセル**（分析タイプごとにカスタマイズ）
```python
# 例: threshold分析の場合
threshold_slider = widgets.FloatSlider(
    value=0.32, min=0.0, max=1.0, step=0.01,
    description='閾値:', continuous_update=True
)
# 他のパラメータも同様に定義
```

3. **リアルタイム更新セル**
```python
def update_plot(threshold):
    # グラフ更新ロジック
    pass

# スライダーと関数を連携
widgets.interactive(update_plot, threshold=threshold_slider)
```

## Output
- 分析用Jupyter Notebook（.ipynb）
- 推奨パラメータのサマリー（Markdown）
- 設定ファイル更新用のJSONスニペット

## Example Usage

### Skillツール経由での呼び出し

```
User: /ml-tune threshold --video-id c8d4kvO3ei4

User: ml-tune スキルを使って、動画c8d4kvO3ei4のオフセット値を分析してください

User: テンプレートマッチングの評価用Notebookを作成（動画ID: abc123）
```

**注**: `--interactive`はデフォルトで有効なため、明示的に指定する必要はありません。

### 将来的なCLIツール実装（予定）

```bash
# 閾値調整用Notebookを作成（インタラクティブUIは常に含まれる）
uv run ml-tune threshold --video-id c8d4kvO3ei4

# オフセット値を分析
uv run ml-tune offset --video-id V75US_DthX4

# テンプレート評価（カスタム出力先）
uv run ml-tune template --video-id abc123 --output-path ./analysis/

# フレーム品質分析（既存Notebookを更新）
uv run ml-tune quality --video-id xyz789 --create-notebook false
```

## Notes
- 中間ファイルが存在しない場合は、まず検出処理の実行を促す
- 動画ファイルが必要な分析（offset, quality）では、ファイルの存在を事前確認
- 生成されたNotebookは手動での微調整を想定（完全自動化ではない）
- パラメータ変更後は、必ずテスト実行して効果を検証すること
- 複数の動画IDで横断分析する場合は、--video-id を複数回指定可能

## Best Practices

### 必須プラクティス
1. **インタラクティブUIの活用（最重要）**
   - スライダーを使って複数のパラメータ値を試す
   - リアルタイムフィードバックで最適値を素早く発見
   - 静的なグラフだけでなく、動的な変化を観察する
   - 確定ボタンで選択した値を必ず記録する

### 推奨プラクティス
- **段階的アプローチ**: 調査用Notebook作成 → 結果確認 → 本実装の順で進める
- **可視化重視**: 数値だけでなく、必ずグラフや画像で視覚的に確認
- **複数の評価指標**: Precision, Recall, F1スコアをバランスよく確認
- **コスト意識**: API呼び出し回数を増やす変更は、事前にコスト影響を評価
- **設定の外部化**: ハードコードせず、必ず設定ファイルで管理
- **バージョン管理**: パラメータ変更前後で、中間ファイルを比較できるようにする
- **トレードオフの理解**: 精度と再現率のトレードオフを視覚的に確認

## Workflow Example

### 典型的な使用フロー

1. **問題の特定**
   ```
   ユーザー: 「偽陽性が多い」「認識精度が低い」など
   ```

2. **分析Notebookの作成**
   ```
   /ml-tune threshold --video-id c8d4kvO3ei4
   ```
   （インタラクティブUIは自動的に含まれます）

3. **Notebookでの調査**
   - セルを順次実行
   - スライダーで値を調整
   - グラフで傾向を確認
   - 推奨値をメモ

4. **実装判断**
   ```
   ユーザー: 「閾値5.0で実装してください」
   ```

5. **本実装（別のSkillまたは手動）**
   - 設定ファイル更新
   - コード修正
   - テスト実行
   - Git commit

## Error Handling

### 一般的なエラーと対処

**中間ファイルが存在しない:**
```
エラー: intermediate/{video_id}/detection_summary.json が見つかりません

対処: まず検出処理を実行してください
$ uv run python main.py --mode test --test-step detect --video-id {video_id}
```

**動画ファイルが存在しない（offset/quality分析時）:**
```
エラー: download/{video_id}.mp4 が見つかりません

対処: 動画をダウンロードしてください
$ uv run python main.py --mode test --test-step download --video-id {video_id}
```

**設定ファイルが不正:**
```
エラー: detection_params.json の形式が不正です

対処: JSONの構文エラーを修正してください
```

**ipywidgetsが使えない（重大エラー）:**
```
エラー: ipywidgets がインストールされていません

このスキルはipywidgetsを必須とします。以下を実行してインストールしてください:

$ cd packages/local
$ uv pip install ipywidgets
$ jupyter nbextension enable --py widgetsnbextension

# JupyterLabを使用している場合
$ jupyter labextension install @jupyter-widgets/jupyterlab-manager
```

**注意**: ipywidgetsなしではNotebookは生成されません。事前に依存関係を確認してください。

**依存関係チェック:**
このスキルを実行する前に、以下で確認できます:
```bash
$ uv pip list | grep ipywidgets
ipywidgets        8.1.1  # インストール済みの場合
```

## Integration with Other Skills

### `/sc:git` との連携
分析完了後、設定変更をコミット：
```
/sc:ml-tune threshold --video-id abc123
# → Notebookで分析
# → 設定ファイル更新

/sc:git commit --smart-commit
# → 適切なコミットメッセージで自動コミット
```

### `/sc:phased-impl` との連携（将来実装予定）
```
/sc:phased-impl create-plan
# Phase 1: 調査
/sc:ml-tune offset --video-id xyz789

# Phase 2: 実装
# （設定変更、コード修正）

/sc:phased-impl review-results
```

## Customization

### カスタム分析の追加
`analysis-type: custom` を使用する場合：

```python
# Notebookに以下のセルが生成される
# ユーザーがカスタム分析ロジックを記述

# === カスタム分析セクション ===
# ここに独自の分析コードを記述してください

# 例: 特定の時間帯のみを分析
time_filtered = [d for d in detections if 100 <= d['timestamp'] <= 500]

# 例: 特定のキャラクターのみを分析
character_filtered = [c for c in chapters if c['character1'] == 'RYU']
```

### テンプレートのカスタマイズ
プロジェクト固有のテンプレートを追加する場合：

1. `.claude/skills/ml-tune-templates/` ディレクトリを作成
2. カスタムテンプレート（.ipynb）を配置
3. Skillから参照

## Performance Considerations

### 大量データの処理
- 検出数が100件を超える場合、サンプリングを推奨
- 全フレーム画像の読み込みはメモリを消費するため注意
- 並列処理（multiprocessing）の活用を検討

### Notebook実行時間
- offset分析: 約1-3分（動画の長さに依存）
- threshold分析: 約10-30秒
- template分析: 約30秒-2分
- quality分析: 約2-5分

## Security and Privacy

### 機密情報の扱い
- 動画ID、タイムスタンプなどはログに記録される可能性あり
- 顧客データを含む場合は、Notebookの共有に注意
- API keyなどの認証情報は、Notebookにハードコードしない

### AWS/R2への影響
- このSkillは**ローカル分析のみ**を行う
- R2へのアップロードやYouTube APIの呼び出しは行わない
- Gemini APIの呼び出しも行わない（コスト安全）

## Troubleshooting

### よくある問題

**Q: Notebookのセルが実行できない**
```
A: Jupyter kernelが正しく設定されているか確認
   - VSCode: 右上のカーネル選択で Python 3.x を選択
   - Jupyter Lab: Kernel → Change Kernel
```

**Q: グラフが表示されない**
```
A: matplotlib のバックエンド設定を確認
   %matplotlib inline
   を最初のセルに追加
```

**Q: スライダーが動かない（重要）**
```
A: インタラクティブUIは必須機能のため、必ず以下を確認してください

1. ipywidgetsのインストール確認
   $ uv pip list | grep ipywidgets

2. Jupyter extensionの有効化確認
   $ jupyter nbextension list
   widgetsnbextension が enabled になっているか確認

3. VSCodeの場合
   - Jupyter拡張機能が最新版か確認
   - カーネルの再起動を試す

4. JupyterLabの場合
   - labextensionのインストール確認
   $ jupyter labextension list | grep jupyterlab-manager

5. それでも動かない場合
   - カーネルを再起動
   - Notebookを閉じて再度開く
   - VSCode/JupyterLabを再起動
```

**Q: 推奨値が直感と合わない**
```
A: 以下を確認：
   - TP/FPの分類が正しいか（chapters.jsonの内容）
   - 評価指標の選択が適切か（精度重視 or 再現率重視）
   - データのバイアス（特定のシーンに偏っていないか）
```

## Future Enhancements

### 予定されている機能
- [ ] 複数動画の一括分析
- [ ] A/Bテスト機能（パラメータ変更前後の比較）
- [ ] 自動レポート生成（Markdown/PDF）
- [ ] 機械学習モデルの統合（閾値の自動最適化）
- [ ] Webベースのダッシュボード

### コミュニティからのフィードバック
このSkillの改善提案は、GitHubのIssueまたはDiscussionsで受け付けています。

## References

### 関連ドキュメント
- [ADR-011: 中間ファイル保存](docs/adr/011-intermediate-file-preservation.md)
- [packages/local/README.md](packages/local/README.md)
- [検出パラメータ設定](packages/local/config/detection_params.json)

### 外部リソース
- [Jupyter Notebook Documentation](https://jupyter-notebook.readthedocs.io/)
- [ipywidgets User Guide](https://ipywidgets.readthedocs.io/)
- [OpenCV Template Matching](https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html)
- [scikit-learn Metrics](https://scikit-learn.org/stable/modules/model_evaluation.html)

## Version History

### v1.0.0 (Initial Release)
- 基本的な4つの分析タイプ（threshold, offset, template, quality）
- ipywidgets統合
- 評価指標の自動計算
- 設定ファイルエクスポート

### Planned for v1.1.0
- 複数動画の横断分析
- カスタムテンプレートのサポート
- パフォーマンス改善
