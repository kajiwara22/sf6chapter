# ADR-019: Geminiキャラクター認識精度の改善

## ステータス

採用（Accepted） - 2026-02-04

## 文脈

Video ID `MSuTmBOo6Qo`の処理において、18試合中8試合（44%）で「JP」を「JAMIE」と誤認識する問題が発生した。両キャラクター名とも"J"で始まるため、Gemini APIが混同していると考えられる。

### 問題の詳細

**誤認識の例**:
- 試合5 (585s): JP → JAMIE（vs TERRY）
- 試合6 (683s): JP → JAMIE（vs RYU）
- 試合12 (1436s): JP → JAMIE（vs KEN）
- その他、計8試合で同様の誤認識

**確認事項**:
- 中間ファイル（`intermediate/MSuTmBOo6Qo/frame_*.png`）で画像を目視確認
- 画像には明確に「JP」と表示されている
- Geminiの応答は「JAMIE」となっている

### 現在の実装（改善前）

```python
# プロンプト
prompt = (
    "この画像はストリートファイター6のラウンド開始画面です。\n"
    "左側のキャラクターを1p、右側のキャラクターを2pとし、"
    "それぞれのキャラクター名をJSONで返してください。\n\n"
    f"有効なキャラクター名（必ずこの中から選んでください）:\n{char_list}\n\n"
    '出力形式: {"1p": "RYU", "2p": "KEN"}'
)

# 推論パラメータ（デフォルト）
config=genai.types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema={...},
)
```

**問題点**:
1. OCRタスクであることを明示していない
2. 推論パラメータがデフォルト（temperature=1.0）で変動性が高い
3. JP vs JAMIEの混同を防ぐ指示がない
4. 文字数の違い（2文字 vs 5文字）に注意を促していない

## 決定

**Phase 1**: プロンプトエンジニアリングと推論パラメータ最適化による改善

### 1. プロンプトの改善

OCRタスクであることを明示し、類似キャラクター名の混同を防ぐ明示的な指示を追加：

```python
prompt = (
    "この画像はストリートファイター6のラウンド開始画面です。\n"
    "画面に表示されているキャラクター名のテキストを正確に読み取ってください。\n"
    "OCRタスク: 左側のキャラクター名を1p、右側のキャラクター名を2pとして認識してください。\n\n"
    "重要な注意事項:\n"
    "- 画面に表示されているテキストを正確に読み取ってください。文字数が重要です。\n"
    "- 'JP' と 'JAMIE' は異なるキャラクターです。'JP'は2文字、'JAMIE'は5文字です。\n"
    "- 'E.HONDA' と 'ED' も異なるキャラクターです。\n"
    "- 'A.K.I.' と 'AKUMA' も異なるキャラクターです。\n\n"
    f"有効なキャラクター名（必ずこの中から選んでください）:\n{char_list}\n\n"
    '出力形式: {"1p": "RYU", "2p": "KEN"}'
)
```

### 2. 推論パラメータの最適化

OCRタスクに適した低温度設定（temperature=0.1）を採用：

```python
config=genai.types.GenerateContentConfig(
    temperature=0.1,  # OCRタスクに最適（決定性向上、変動性低減）
    top_p=0.95,      # 累積確率のカットオフ
    top_k=40,        # 候補数の制限
    response_mime_type="application/json",
    response_schema={...},
)
```

**パラメータの根拠**:
- **temperature=0.1**: OCRタスクには低温度が適切。決定性を高め、変動性を低減
- **top_p=0.95**: 累積確率95%のトークンのみを候補とする
- **top_k=40**: 上位40個のトークンのみを候補とする（enumスキーマと併用）

## 検討した代替案

### 代替案1: モデルのアップグレード

より高性能なモデル（`gemini-2.0-flash-exp`または`gemini-2.5-flash`）に変更。

**却下理由**:
- コスト増加の可能性
- まずは無料で実施可能な改善（プロンプト・パラメータ）を試すべき
- 効果不十分な場合はPhase 2として検討

### 代替案2: 画像前処理の追加

CLAHE（コントラスト強調）、シャープネス強調、ノイズ除去などの前処理を追加。

**却下理由**:
- 実装複雑度が高い
- まずは簡単な改善を試すべき
- 効果不十分な場合はPhase 2として検討

### 代替案3: 複数フレーム推論と多数決

同じ試合の複数フレームで推論し、多数決で最終結果を決定。

**却下理由**:
- API呼び出し3倍（コスト増）
- 実装複雑度が高い
- 効果不十分な場合はPhase 3として検討

### 代替案4: OCRとの併用

Tesseract等のOCRエンジンで文字列を抽出し、Gemini結果と照合。

**却下理由**:
- 追加の依存関係
- OCR精度の問題
- 実装複雑度が高い
- 効果不十分な場合はPhase 3として検討

## 結果

### 期待される効果

- **目標**: 誤認識率 44% → 20%以下
- **コスト**: 0円（追加コストなし）
- **実装期間**: 1日

### 検証方法

1. **変更前の結果保存**:
   ```bash
   cp intermediate/MSuTmBOo6Qo/matches.json \
      intermediate/MSuTmBOo6Qo/matches_before_improvement.json
   ```

2. **Phase 1実装後の再テスト**:
   ```bash
   uv run python main.py --mode oneshot --video-id MSuTmBOo6Qo
   ```

3. **効果測定**:
   - JP精度の変化
   - JAMIE精度の変化
   - その他のキャラクター精度の変化（劣化がないことを確認）

### 成功基準

- JP vs JAMIE誤認識率が20%以下
- 他のキャラクター認識精度も維持（劣化なし）
- 実行時間の大幅な増加なし

### リスク管理

| リスク | 対策 |
|-------|------|
| 改善効果が限定的 | Phase 2（モデルアップグレード、画像前処理）を検討 |
| 他キャラクター精度の劣化 | 変更前後でA/Bテスト、混同行列で全キャラクター監視 |
| 新たな誤認識パターンの発生 | 複数動画でクロスバリデーション |

## 実装ファイル

### 変更したファイル

- `packages/local/src/character/recognizer.py`
  - Line 129-143: プロンプト改善（OCRタスク明示、JP/JAMIE混同防止）
  - Line 147-156: 推論パラメータ最適化（temperature=0.1等）

### 新規作成ファイル

- `docs/adr/019-gemini-character-recognition-improvement.md` (このファイル)

## 参考資料

- [Gemini API - Temperature and Sampling](https://ai.google.dev/gemini-api/docs/models/generative-models#temperature)
- [ADR-011: 中間ファイル保存による人間確認フロー](011-intermediate-file-preservation.md)
- [ADR-017: 検出パラメータの最適化](017-detection-parameter-optimization.md)

## 次のステップ

1. **Phase 1の効果測定** - Video MSuTmBOo6Qoでの再テスト
2. **汎用性確認** - 他の動画5-10本での検証
3. **目標達成判定** - 誤認識率20%以下を達成できたか
4. **Phase 2の検討** - 必要に応じてモデルアップグレードと画像前処理を実施
