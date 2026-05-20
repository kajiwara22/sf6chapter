# ADR-042: Geminiキャラクター認識モデルの 2.5-flash-lite → 3.1-flash-lite (Flex, バッチ送信) への移行

## ステータス

採用（Accepted） - 2026-05-20

## 文脈

[packages/local/src/character/recognizer.py](../../packages/local/src/character/recognizer.py) で使用している `gemini-2.5-flash-lite` が、公式の deprecation スケジュールにより **2026-10-16** に shutdown される予定であることが判明した。本ADRは、これを受けたモデル移行方針を記録する。

### 現状

- **使用モデル**: `gemini-2.5-flash-lite`（[recognizer.py:29](../../packages/local/src/character/recognizer.py#L29)）
- **用途**: SF6 ラウンド開始画面のキャラクター名 OCR（左右2名、JSON enum で返却）
- **入出力規模**:
  - 入力 = 1 画像 + プロンプト（数百 tokens）
  - 出力 = JSON 1 行（10〜20 tokens）
- **呼び出し頻度**: 動画 1 本あたり対戦数回 × 1 日数本程度（ADR-033 の再認識フローも含む）
- **運用形態**: 常駐 PC（Docker）でバッチ的に処理。配信終了から数時間以内にチャプターが生成されればよい（リアルタイム性は不要）

### Gemini モデル ロードマップ（2026-05-20 時点、公式ドキュメント確認済み）

| モデル | リリース | Shutdown | 公式推奨置換 |
|---|---|---|---|
| `gemini-2.5-flash-lite` (現行) | 2025-07-22 | **2026-10-16** | `gemini-3.1-flash-lite` |
| `gemini-3.1-flash-lite` | 2026-05-07 | 未定（GA stable） | - |

出典: [Gemini API Deprecations](https://ai.google.dev/gemini-api/docs/deprecations)

### サービス Tier 比較（3.1-flash-lite）

| Tier | Pricing | Latency | Interface | Reliability | Status |
|---|---|---|---|---|---|
| Standard | Full price | Seconds | Synchronous | High | GA |
| **Flex** | **50% off** | **1–15 min target** | **Synchronous** | Best-effort (sheddable) | **Preview** |
| Batch | 50% off | Up to 24h | Asynchronous | High (throughput) | GA |
| Priority | +75-100% | Seconds (low) | Synchronous | High (non-sheddable) | GA |

出典: [Gemini Flex inference](https://ai.google.dev/gemini-api/docs/flex-inference)

### 価格比較（Paid Tier, USD / 1M tokens, image input）

| モデル / Tier | Input | Output | 現行比 |
|---|---|---|---|
| `gemini-2.5-flash-lite` Standard（現行） | $0.10 | $0.40 | 1.0x（基準） |
| `gemini-3.1-flash-lite` Standard | $0.25 | $1.50 | 2.5x / 3.75x |
| **`gemini-3.1-flash-lite` Flex** | **$0.125** | **$0.75** | **1.25x / 1.875x** |
| `gemini-3.1-flash-lite` Batch | $0.125 | $0.75 | 1.25x / 1.875x |

出典: [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)

### 検討した選択肢

#### 選択肢 A: `gemini-3.1-flash-lite` Standard + `thinking_budget=0`

- **メリット**: 低レイテンシ（秒）、可用性高、GA、実装変更が最小。
- **デメリット**: 単価が現行比 2.5〜3.75 倍に値上げ。

#### 選択肢 B: `gemini-3.1-flash-lite` **Flex** + `thinking_budget=0` ★採用

- **メリット**:
  - Standard の 50% 価格 → 現行比 **1.25x / 1.875x** に抑制可能、コスト最優先の要件に最適合。
  - **同期 API**（`config={"service_tier": "flex"}` 追加のみで Standard と同じ呼び出し方法）→ 既存パイプラインへの影響が最小。
  - 1〜15 分のレイテンシは、本プロジェクトの「常駐 PC でのバッチ処理、配信終了から数時間以内のチャプター生成」という運用と整合的。
  - サポート対象モデルに `gemini-3.1-flash-lite` (GA) が含まれる。
- **デメリット / 留意点**:
  - **Preview ステータス**: 仕様変更・提供終了リスクあり。
  - **Sheddable**: 混雑時に 503/429 が返る → クライアント側でリトライ実装必須。
  - **タイムアウト**: 600 秒以上の client-side timeout が公式推奨。
  - **サーバ側フォールバックなし**: 容量不足時に Standard へ自動昇格しない → クライアントで明示的にフォールバック判断が必要。
  - **最悪ケースの累積レイテンシ**: 動画 1 本に 18 試合 × 最悪 15 分 = 約 4.5 時間。許容範囲だが配信直後の即時チャプター反映は不可。

#### 選択肢 C: `gemini-3.1-flash-lite` Batch API

- **メリット**: Flex と同価格。
- **デメリット**: 非同期 API のため、ジョブ submit / polling / 結果取得という大幅な実装変更が必要。Flex で同じコストかつ既存コードへの影響を最小化できるため不採用。

#### 選択肢 D: alias 据え置き（`gemini-2.5-flash-lite` のまま）

- **メリット**: 当面コスト現状維持。
- **デメリット**: 2026-10-16 までに alias が 3.1 系へ自動切替されるタイミング・挙動が制御できない。本番運用には不向き。

#### 選択肢 E: `gemini-2.5-flash`（上位モデル）

- **メリット**: 高精度。
- **デメリット**: OCR タスクにオーバースペック。3.1-flash-lite よりさらに高価で採用理由なし。

#### 選択肢 F: バッチ送信（複数フレームを 1 リクエストにまとめる）

現在の実装は 1 動画あたり N 試合（典型的に 10〜25 試合）を順次 1 リクエストずつ処理している。Gemini API は 1 リクエストあたり最大 3,600 画像をサポートしており、技術的には N 枚を 1 リクエストにまとめることが可能。

- **メリット**:
  - **Flex 採用時の最悪累積レイテンシを大幅短縮**: 23 試合 × 最悪 15 分 = 5.75 時間 → 1 リクエスト × 最悪 15 分。
  - リクエスト数削減によりレート制限への余裕が増す。
- **事前に懸念されたデメリット**:
  - **公式が OCR タスクで複数画像送信の精度低下を明言**: ["If you want to detect text in an image, use prompts with a single image to produce better results than prompts with multiple images."](https://firebase.google.com/docs/ai-logic/input-file-requirements#images)
  - **All-or-Nothing 失敗のリスク**: 1 リクエストで N 枚の認識を行うため、レスポンスの JSON 不正や 503 で全件再実行が必要になり得る。
  - **画像と結果の対応ずれリスク**: モデルが順序を取り違える可能性。プロンプトでインデックス付与（"image 1", "image 2"...）等の工夫が必要。
  - **リクエストサイズ制約**: inline data の総サイズが 20 MB（base64 後）を超えないこと。23 枚程度では通常問題ない。
  - **既存パイプライン構造との不整合**: 現行は「フレーム検出 → 即時 1 枚認識 → 中間ファイル保存」のフロー。バッチ化には認識タイミングを後段に移す構造変更が必要。
  - **ADR-033 の再認識フロー**: Battlelog マッチング失敗時の前処理付き再認識は個別実施が前提であり、バッチ送信と組み合わせる場合は二段構えの実装が必要。

##### 実検証結果

[packages/local/notebooks/adr042_validation.ipynb](../../packages/local/notebooks/adr042_validation.ipynb) で対象動画 `MSuTmBOo6Qo`（18 試合）について、`gemini-3.1-flash-lite` Standard で個別送信 vs バッチ送信を比較した。

| 指標 | モード A: 個別送信 | モード B: バッチ送信 |
|---|---|---|
| 1p 正解率 | 100.0% | 100.0% |
| 2p 正解率 | 100.0% | 100.0% |
| 両方正解率 | **100.0%** (18/18) | **100.0%** (18/18) |
| 合計レイテンシ | 40.24 秒（1枚平均 2.24秒） | **5.78 秒**（18枚を1リクエスト） |
| レイテンシ短縮率 | - | **85.6%** |
| 両モードで結果が異なる試合 | - | **0 / 18**（完全一致） |
| ADR-019 で対処した JP/JAMIE 混同 | 解消（10 件すべて正解） | 解消（10 件すべて正解） |

**所見**:
- 公式が警告していた OCR 精度低下は、本ユースケースでは観測されなかった。SF6 のラウンド開始画面は文字が大きくコントラストも明確なため、複数画像同時送信でも精度が落ちなかったと考えられる。
- All-or-Nothing 失敗もこの検証では発生せず、JSON は正しく構造化されて返却された。
- 画像と結果の対応ずれもなかった（プロンプトでインデックス付与 + `response_schema` で `index` フィールド必須化が効いた可能性）。
- レイテンシ短縮効果が **85.6%** と顕著。Flex Tier 採用時の最悪レイテンシ問題（23×15分=5.75h）への有力な対策となる。

- **判断**: **本 ADR で採用する**。事前懸念は実検証で解消され、レイテンシ短縮効果が大きい。ただし以下のリスクは継続して認識する:
  - 1 動画のみの検証であり、文字パターンが大きく異なる動画（特に解像度低めや短文字キャラクター比率高め）で同様の精度が出るかは未確認。
  - All-or-Nothing 失敗が確率的に発生する可能性は否定できないため、実装時にフォールバック層を設けてバッチ失敗時に個別送信へ自動切替する。

## 決定

**選択肢 B + F** を組み合わせて採用する: `gemini-3.1-flash-lite` **Flex** + `thinking_budget=0` + **バッチ送信**（動画内の全フレームを 1 リクエストにまとめる）。

### 理由

1. **コスト最優先**: 現行比 1.25x / 1.875x に抑えられ、Standard の 2.5x / 3.75x と比べて顕著にコスト効率が良い。さらにバッチ送信ではリクエスト数が削減されるためレート制限の余裕も増す。
2. **同期 API**: `service_tier="flex"` 指定以外は Standard と同じ呼び出し方法 → 既存パイプライン（ADR-021, ADR-033）への影響が最小。Batch API のような非同期化リファクタは不要。
3. **運用形態との整合**: 本プロジェクトは常駐 PC でのバッチ処理であり、1〜15 分のレイテンシは許容範囲。
4. **バッチ送信による Flex 最悪レイテンシ問題の解消**: 個別送信では 23 試合 × 最悪 15 分 = 5.75 時間に膨らみうるが、1 リクエストにまとめれば最悪でも 15 分。検証では Standard で 40.24s → 5.78s（85.6% 短縮）という顕著な短縮効果を確認。
5. **公式推奨置換モデル**: `gemini-3.1-flash-lite` は GA かつ長期サポート。Flex Tier 自体は Preview だが、Tier が変更になっても model 部分は GA のため Standard へ即座にフォールバック可能。
6. **thinking_budget=0** により OCR タスクで不要な thinking tokens 課金を完全に回避。
7. **精度退行なし**: 18 試合の検証で個別送信・バッチ送信ともに **100% 正解**。両モードの結果は完全一致し、ADR-019 で対処した JP/JAMIE 混同問題も再発しなかった。公式の「OCR で複数画像送信は精度低下」警告は、本ユースケース（大きく明瞭な文字）では当てはまらない。

### 実装方針

[recognizer.py:29](../../packages/local/src/character/recognizer.py#L29) のデフォルト model_name と [recognizer.py:33](../../packages/local/src/character/recognizer.py#L33) のデフォルト location を変更し、[recognizer.py:159-172](../../packages/local/src/character/recognizer.py#L159-L172) の `GenerateContentConfig` に `service_tier` と `thinking_config` を追加。さらにクライアント側リトライとフォールバックを実装する。

#### **重要: location の変更**

`gemini-3.1-flash-lite` は **`us-central1` などの単一リージョンでは提供されていない**。現行コードは `location="us-central1"` を使用しているため、モデル名を変更しただけでは以下のエラーが発生する:

```
404 NOT_FOUND. Publisher Model `projects/.../locations/us-central1/publishers/google/models/gemini-3.1-flash-lite` was not found
```

公式ドキュメントによる `gemini-3.1-flash-lite` の提供エンドポイント:
- `global` (グローバル、最も柔軟・推奨)
- `us` (米国マルチリージョン)
- `eu` (EUマルチリージョン)

本プロジェクトは個人用途でデータレジデンシー要件がないため **`global`** を採用する。

```python
# 変更前
model_name: str = "gemini-2.5-flash-lite",
location: str = "us-central1",

# 変更後
model_name: str = "gemini-3.1-flash-lite",
location: str = "global",
```

```python
# GenerateContentConfig
config=genai.types.GenerateContentConfig(
    temperature=0.1,
    top_p=0.95,
    top_k=40,
    thinking_config=genai.types.ThinkingConfig(thinking_budget=0),  # 追加: OCRに思考不要
    service_tier="flex",  # 追加: 50% off
    response_mime_type="application/json",
    response_schema={...},
),
```

#### バッチ送信メソッドの新設

現行の `recognize_from_frame(frame)` に加え、**`recognize_from_frames(frames: list[np.ndarray])`** を新設し、複数フレームを 1 リクエストにまとめて送信する。

- プロンプト: 検証 Notebook で 100% 一致を達成したものを採用（"image 1 から image N までの順番で提示されます" + "index フィールド必須" の指示）。
- `response_schema` は `{"results": [{"index": int, "1p": enum, "2p": enum}, ...]}` 形式。
- 戻り値は `list[tuple[dict, dict]]`（フレーム数と同じ長さ、index でソート済み）。

呼び出し側（`main.py` の認識フェーズ）は、検出済みフレーム群を集約してから 1 回 `recognize_from_frames` を呼ぶ形に変更する。

**追加実装**:

- **タイムアウト**: クライアント初期化時に `http_options={"timeout": 900000}`（900 秒）を設定。
- **リトライ**: 503/429 検知時に指数バックオフ（base_delay=5s、max_retries=3）。
- **二段階フォールバック**:
  1. **Flex リトライ枯渇時 → Standard へフォールバック**（同じバッチ送信で再試行）
  2. **バッチ送信が失敗 or 一部 index が欠損した場合 → 該当フレームのみ個別送信（`recognize_from_frame`）にフォールバック**
- **設定可能化**: ADR-017 と同様、`service_tier`・`batch_mode` を `config/detection_params.json` または環境変数で切替可能にし、緊急時に旧来の個別送信モードへ即時切替できるようにする。
- **ADR-033 (再認識フロー) との整合**: Battlelog マッチング失敗時の前処理付き再認識は **個別送信のまま維持** する。再認識は対象が 1〜数フレームに限定されるため、バッチ化のメリットが乏しい。

### 移行手順

1. **検証**: 完了。`adr042_validation.ipynb` で `MSuTmBOo6Qo`（18 試合）について個別/バッチ送信ともに 100% 正解、レイテンシ 85.6% 短縮を確認済み。
2. **実装変更**: 上記の通り `recognizer.py` の model_name・location・GenerateContentConfig を修正し、`recognize_from_frames` の新設とフォールバック層を追加。
3. **限定テスト**: `test_r2_upload` モード等で複数本の動画（特に未検証パターン: 試合数が多い、文字パターンが異なる、画質が低めの動画）を処理し、認識結果・実測レイテンシ・503 発生率・バッチ失敗時の個別フォールバック動作を中間ファイルとログで確認。
4. **本番反映**: 常駐 PC（Docker）の再ビルド・再起動。
5. **完了期限**: 2026-10-16 の shutdown までに反映完了。リスクバッファとして **2026-08 末まで** を目標とする。

### ハマりどころ・既知の落とし穴

- **location を必ず先に変更する**: model_name だけ変更して location が `us-central1` のままだと 404 NOT_FOUND になる。実装作業順序として model_name と location は **同一コミットで変更** する。
- **`gemini-2.5-flash-lite` は us-central1 で動く**: 現行コードがそれで動いているため、location 差異に気付きにくい。これは 2.5 系の提供エンドポイントが 3.1 系より広いためであり、3.1 系は global/us/eu のみ。
- **検証用 Notebook も同様**: `adr042_validation.ipynb` の `client = genai.Client(location=...)` も `global` を指定すること（修正済み）。
- **バッチ送信時の index 対応**: モデルが返す JSON の `index` は 1 始まり（プロンプトで "image 1 → index=1" と指示）。送信したフレーム順序との対応に注意し、レスポンス取得後は index でソート・突合する。
- **バッチサイズの上限**: Gemini API は 1 リクエストあたり最大 3,600 画像、合計 20 MB（inline data）。本プロジェクトでは典型的に 10〜25 試合なので問題ないが、極端に長い動画では制約に近づく可能性がある。安全策として 100 フレームを目安にバッチを分割する仕様を入れることを検討。

## 影響

### コスト

- 単価は現行比 1.25x（input）/ 1.875x（output）に増加。
- 本プロジェクトの呼び出し規模では絶対額の影響は月数ドル以内に収まる見込み。
- Standard との価格差から、推定コスト削減効果は Standard 比で 50%。

### レイテンシ

- **検証実測値（Standard, 18 試合）**:
  - 個別送信: 40.24 秒（1枚平均 2.24 秒）
  - **バッチ送信: 5.78 秒**（85.6% 短縮）
- Flex 適用時の通常想定: 数秒〜数十秒（Standard と大差ないケースが多いとされる）。
- Flex 混雑時の最悪値: 最大 15 分/リクエスト。
- 動画 1 本の最悪ケース: **バッチ送信なら最悪 15 分**（個別送信なら N×15 分に膨らみうる）。バッチ送信採用により Flex の最悪レイテンシ問題が実質解消。

### 信頼性

- 503/429 発生時のリトライとフォールバック実装が必須。
- Preview ステータスのため、提供終了・仕様変更時には Standard へ即時切替できる構造にしておく必要がある。
- バッチ送信失敗時の個別送信フォールバックにより、All-or-Nothing リスクを緩和。

### 精度

- **検証実測値**: 個別送信・バッチ送信ともに 18/18 試合（100%）正解。ADR-019 で対処した JP/JAMIE 混同も再発しなかった。
- 1 動画のみの検証であり、文字パターンが大きく異なる動画での退行可能性は残る。実運用で監視し、退行が確認された場合はプロンプトの再調整・モード切替・`gemini-3-flash-preview` への切替を検討。

### 既存 ADR との関係

- **ADR-019**（Gemini認識精度の改善）: プロンプトと temperature 設定はそのまま維持。`thinking_budget=0` は ADR-019 の方針（OCR タスクの決定性向上）と整合的。
- **ADR-033**（再認識フロー）: `recognize_with_preprocessing` も同じモデル・同じ Tier を使用するため自動的に移行対象。
- **ADR-004**（OAuth2認証）: Vertex AI 経由の認証方式は変更なし。
- **ADR-017**（検出パラメータの最適化）: `service_tier` を同様の設定機構で切替可能にすることを推奨。

## 将来の見直し条件

以下のいずれかが発生した場合、本決定を見直す:

- Flex Tier が GA を待たずに提供終了した場合 → 即座に Standard へ切替。
- 実運用で 503 発生率が想定以上に高く、リトライ＋フォールバックで吸収しきれない場合。
- レイテンシが許容範囲（動画 1 本数時間以内）を継続的に超える場合。
- Flex Tier の価格優位性が変更された場合（例: 割引率の縮小）。
- **バッチ送信の精度退行**が他の動画で観測された場合 → バッチサイズ縮小、または個別送信モードへの切戻し。設定で切替できる構造にしておく。
- 1 動画あたりのフレーム数が極端に多くなる運用変化があった場合 → バッチサイズ分割の必要性を再評価。

## 検証Notebook

[packages/local/notebooks/adr042_validation.ipynb](../../packages/local/notebooks/adr042_validation.ipynb) - 個別送信 vs バッチ送信の精度・レイテンシ比較を実施。本ADRの判断根拠となる検証結果が記録されている。

## 参考資料

- [Gemini API Deprecations](https://ai.google.dev/gemini-api/docs/deprecations)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini Flex inference](https://ai.google.dev/gemini-api/docs/flex-inference)
- [Migrate to the latest Gemini models](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/migrate)
- [ADR-017: 検出パラメータの最適化とパラメータ管理システムの導入](017-detection-parameter-optimization.md)
- [ADR-019: Geminiキャラクター認識精度の改善](019-gemini-character-recognition-improvement.md)
- [ADR-033: Battlelog未マッチ時の画像前処理による再認識](033-rerecognition-with-image-preprocessing.md)
