# ADR-042: Geminiキャラクター認識モデルの 2.5-flash-lite → 3.1-flash-lite (Vertex AI Flex PayGo, バッチ送信) への移行

## ステータス

採用（Accepted） - 2026-05-20
訂正（Revised） - 2026-05-24: Vertex AI における Flex の指定方法を「`GenerateContentConfig.service_tier`」から「`X-Vertex-AI-LLM-*` HTTP ヘッダー（Flex PayGo）」に訂正。詳細は本文末尾の「訂正履歴」を参照。

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

### サービス Tier 比較（Vertex AI 上の 3.1-flash-lite）

本プロジェクトは Vertex AI 経由（`vertexai=True`）で呼び出すため、**Vertex AI の Consumption Options** を採用する。
（Gemini Developer API (AI Studio) の Flex Tier (`service_tier="flex"`) は別物で、Vertex AI 経由では利用不可）。

| Consumption Option | Pricing | Latency | Interface | 指定方法 | Status |
|---|---|---|---|---|---|
| Standard PayGo | Full price | Seconds | Synchronous | デフォルト | GA |
| **Flex PayGo** | **50% off** | 最大 30 min target | Synchronous | **HTTP ヘッダー** `X-Vertex-AI-LLM-Request-Type: shared` + `X-Vertex-AI-LLM-Shared-Request-Type: flex` | GA |
| Batch prediction | 50% off | Up to 24h | Asynchronous | バッチジョブ API | GA |
| Priority PayGo | +75-100% | Seconds (low) | Synchronous | ヘッダー | GA |
| Provisioned Throughput | 月額予約 | Seconds | Synchronous | リソース予約 | GA |

出典: [Vertex AI Flex PayGo](https://docs.cloud.google.com/vertex-ai/docs/flex-paygo), [Consumption options](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/deploy/consumption-options), [gemini-3.1-flash-lite モデル仕様](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-lite) — `gemini-3.1-flash-lite` は Flex PayGo 対応モデル。

#### Vertex AI Flex PayGo を指定する正しい方法

Vertex AI では `GenerateContentConfig` の `service_tier` パラメータは無効で、リクエスト時に渡すと `400 INVALID_ARGUMENT` で拒否される。
代わりに **HTTP ヘッダー** をクライアントの `HttpOptions` 経由で付与する:

```python
from google import genai
from google.genai.types import HttpOptions

client = genai.Client(
    vertexai=True,
    project=project_id,
    location="global",
    credentials=creds,
    http_options=HttpOptions(
        api_version="v1",
        timeout=1_800_000,  # 最大30分（Flex PayGo の上限）
        headers={
            "X-Vertex-AI-LLM-Request-Type": "shared",         # PayGo 用（Provisioned Throughput なし）
            "X-Vertex-AI-LLM-Shared-Request-Type": "flex",   # Flex を選択
        },
    ),
)
```

レスポンスの `usage_metadata.traffic_type == ON_DEMAND_FLEX` で Flex が適用されたことを確認できる。

### 価格比較（Vertex AI, USD / 1M tokens, image input）

| モデル / Tier | Input | Output | 現行比 |
|---|---|---|---|
| `gemini-2.5-flash-lite` Standard（現行） | $0.10 | $0.40 | 1.0x（基準） |
| `gemini-3.1-flash-lite` Standard PayGo | $0.25 | $1.50 | 2.5x / 3.75x |
| **`gemini-3.1-flash-lite` Flex PayGo** | **$0.125** | **$0.75** | **1.25x / 1.875x** |
| `gemini-3.1-flash-lite` Batch prediction | $0.125 | $0.75 | 1.25x / 1.875x |

出典: [Vertex AI Pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)

### 検討した選択肢

#### 選択肢 A: `gemini-3.1-flash-lite` Standard PayGo + `thinking_budget=0`

- **メリット**: 低レイテンシ（秒）、可用性高、GA、実装変更が最小。
- **デメリット**: 単価が現行比 2.5〜3.75 倍に値上げ。

#### 選択肢 B: `gemini-3.1-flash-lite` **Vertex AI Flex PayGo** + `thinking_budget=0` ★採用

- **メリット**:
  - Standard PayGo の 50% 価格 → 現行比 **1.25x / 1.875x** に抑制可能、コスト最優先の要件に最適合。
  - **同期 API**（クライアントの `HttpOptions.headers` に Flex PayGo 用ヘッダーを足すだけで Standard と同じ呼び出し方法）→ 既存パイプラインへの影響が最小。
  - 最大 30 分のレイテンシ許容は、本プロジェクトの「常駐 PC でのバッチ処理、配信終了から数時間以内のチャプター生成」という運用と整合的。
  - `gemini-3.1-flash-lite` は Vertex AI Flex PayGo の **サポート対象モデル**（公式ドキュメントの Consumption options に明記、GA）。
- **デメリット / 留意点**:
  - **Sheddable**: 混雑時に 503/429 が返る → クライアント側でリトライ実装必須。
  - **タイムアウト**: 最大 30 分の client-side timeout を設定する（Vertex AI Flex PayGo の上限）。
  - **サーバ側フォールバックなし**: 容量不足時に Standard へ自動昇格しない → クライアントで明示的にフォールバック判断が必要。
  - **最悪ケースの累積レイテンシ**: 動画 1 本に 18 試合 × 最悪 30 分 = 約 9 時間。許容範囲だが配信直後の即時チャプター反映は不可。
  - **指定方法が Vertex AI 固有**: AI Studio の `service_tier="flex"` とは別物。Vertex AI で `GenerateContentConfig.service_tier` を渡すと `400 INVALID_ARGUMENT` で拒否される（→ 訂正履歴）。

#### 選択肢 C: `gemini-3.1-flash-lite` Batch prediction

- **メリット**: Flex PayGo と同価格。
- **デメリット**: 非同期 API のため、ジョブ submit / polling / 結果取得という大幅な実装変更が必要。Flex PayGo で同じコストかつ既存コードへの影響を最小化できるため不採用。

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

[packages/local/notebooks/adr042_validation.ipynb](../../packages/local/notebooks/adr042_validation.ipynb) で対象動画 `MSuTmBOo6Qo`（18 試合）について、`gemini-3.1-flash-lite` **Standard PayGo** で個別送信 vs バッチ送信を比較した（バッチ vs 個別の精度差を見るためにTier の影響を分離する意図。Flex PayGo の精度差は理論上ゼロ）。

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
- レイテンシ短縮効果が **85.6%** と顕著。Flex PayGo 採用時の最悪レイテンシ問題（23×30分=11.5h）への有力な対策となる。

- **判断**: **本 ADR で採用する**。事前懸念は実検証で解消され、レイテンシ短縮効果が大きい。ただし以下のリスクは継続して認識する:
  - 1 動画のみの検証であり、文字パターンが大きく異なる動画（特に解像度低めや短文字キャラクター比率高め）で同様の精度が出るかは未確認。
  - All-or-Nothing 失敗が確率的に発生する可能性は否定できないため、実装時にフォールバック層を設けてバッチ失敗時に個別送信へ自動切替する。

## 決定

**選択肢 B + F** を組み合わせて採用する: `gemini-3.1-flash-lite` **Vertex AI Flex PayGo** + `thinking_budget=0` + **バッチ送信**（動画内の全フレームを 1 リクエストにまとめる）。

### 理由

1. **コスト最優先**: 現行比 1.25x / 1.875x に抑えられ、Standard PayGo の 2.5x / 3.75x と比べて顕著にコスト効率が良い。さらにバッチ送信ではリクエスト数が削減されるためレート制限の余裕も増す。
2. **同期 API**: HTTP ヘッダー2行（`X-Vertex-AI-LLM-Request-Type: shared` + `X-Vertex-AI-LLM-Shared-Request-Type: flex`）を `HttpOptions` 経由でクライアントに設定するだけで、Standard と同じ呼び出し方法 → 既存パイプライン（ADR-021, ADR-033）への影響が最小。Batch prediction のような非同期化リファクタは不要。
3. **運用形態との整合**: 本プロジェクトは常駐 PC でのバッチ処理であり、最大 30 分のレイテンシは許容範囲。
4. **バッチ送信による Flex 最悪レイテンシ問題の解消**: 個別送信では 23 試合 × 最悪 30 分 = 11.5 時間に膨らみうるが、1 リクエストにまとめれば最悪でも 30 分。検証では Standard PayGo で 40.24s → 5.78s（85.6% 短縮）という顕著な短縮効果を確認。
5. **公式サポート対象**: `gemini-3.1-flash-lite` は Vertex AI Flex PayGo のサポート対象モデル（GA）。Flex PayGo 自体も GA。容量不足時には Standard PayGo へクライアント側で即座にフォールバック可能。
6. **thinking_budget=0** により OCR タスクで不要な thinking tokens 課金を完全に回避。
7. **精度退行なし**: 18 試合の検証で個別送信・バッチ送信ともに **100% 正解**。両モードの結果は完全一致し、ADR-019 で対処した JP/JAMIE 混同問題も再発しなかった。公式の「OCR で複数画像送信は精度低下」警告は、本ユースケース（大きく明瞭な文字）では当てはまらない。

### 実装方針

[recognizer.py](../../packages/local/src/character/recognizer.py) の `CharacterRecognizer` クラスを以下のように変更する:
- デフォルト `model_name` を `gemini-3.1-flash-lite` に、デフォルト `location` を `global` に変更
- Flex PayGo 用クライアントと Standard PayGo 用クライアントを **両方** 構築する（フォールバック時に切り替える）
- `GenerateContentConfig` に `thinking_config=ThinkingConfig(thinking_budget=0)` を追加
- バッチ送信メソッド `recognize_from_frames` を新設し、リトライとフォールバックを実装

#### **重要 1: location の変更**

`gemini-3.1-flash-lite` は **`us-central1` などの単一リージョンでは提供されていない**。現行コードは `location="us-central1"` を使用しているため、モデル名を変更しただけでは以下のエラーが発生する:

```
404 NOT_FOUND. Publisher Model `projects/.../locations/us-central1/publishers/google/models/gemini-3.1-flash-lite` was not found
```

公式ドキュメントによる `gemini-3.1-flash-lite` の提供エンドポイント:
- `global` (グローバル、最も柔軟・推奨)
- `us` (米国マルチリージョン)
- `eu` (EUマルチリージョン)

本プロジェクトは個人用途でデータレジデンシー要件がないため **`global`** を採用する。

#### **重要 2: Vertex AI で Flex PayGo を有効化する方法**

Vertex AI では `GenerateContentConfig.service_tier="flex"` は **無効**（`400 INVALID_ARGUMENT` で拒否される）。
これは Gemini Developer API (AI Studio) 専用のパラメータであり、Vertex AI では **HTTP ヘッダー** を `HttpOptions` 経由でクライアントに設定する必要がある。

```python
from google import genai
from google.genai.types import HttpOptions

# Flex PayGo クライアント（ヘッダー付き）
flex_client = genai.Client(
    vertexai=True,
    project=project_id,
    location="global",
    credentials=creds,
    http_options=HttpOptions(
        api_version="v1",
        timeout=1_800_000,  # 30分（Vertex AI Flex PayGo の上限）
        headers={
            "X-Vertex-AI-LLM-Request-Type": "shared",
            "X-Vertex-AI-LLM-Shared-Request-Type": "flex",
        },
    ),
)

# Standard PayGo クライアント（ヘッダー無し、フォールバック用）
standard_client = genai.Client(
    vertexai=True,
    project=project_id,
    location="global",
    credentials=creds,
    http_options=HttpOptions(api_version="v1", timeout=1_800_000),
)

# GenerateContentConfig には service_tier を含めない
config = genai.types.GenerateContentConfig(
    temperature=0.1,
    top_p=0.95,
    top_k=40,
    thinking_config=genai.types.ThinkingConfig(thinking_budget=0),  # OCRに思考不要
    response_mime_type="application/json",
    response_schema={...},
)
```

レスポンスの `usage_metadata.traffic_type == ON_DEMAND_FLEX` で Flex PayGo が適用されたことを検証できる。

#### バッチ送信メソッドの新設

現行の `recognize_from_frame(frame)` に加え、**`recognize_from_frames(frames: list[np.ndarray])`** を新設し、複数フレームを 1 リクエストにまとめて送信する。

- プロンプト: 検証 Notebook で 100% 一致を達成したものを採用（"image 1 から image N までの順番で提示されます" + "index フィールド必須" の指示）。
- `response_schema` は `{"results": [{"index": int, "1p": enum, "2p": enum}, ...]}` 形式。
- 戻り値は `list[tuple[dict, dict]]`（フレーム数と同じ長さ、index でソート済み）。

呼び出し側（`main.py` の認識フェーズ）は、検出済みフレーム群を集約してから 1 回 `recognize_from_frames` を呼ぶ形に変更する。

**追加実装**:

- **タイムアウト**: クライアント初期化時に `http_options.timeout=1_800_000`（30 分。Vertex AI Flex PayGo の上限）を設定。
- **リトライ**: 503/429 検知時に指数バックオフ（base_delay=5s、max_retries=3）。
- **二段階フォールバック**:
  1. **Flex PayGo リトライ枯渇時 → Standard PayGo クライアントへ切替**（ヘッダー無しの `standard_client` で同じバッチ送信を再試行）
  2. **バッチ送信が失敗 or 一部 index が欠損した場合 → 該当フレームのみ個別送信（`recognize_from_frame`）にフォールバック**
- **設定可能化**: コンストラクタの `use_flex: bool` 引数で Flex の有無を切替可能。緊急時に Standard PayGo のみへ即時切替できる。
- **ADR-033 (再認識フロー) との整合**: Battlelog マッチング失敗時の前処理付き再認識は **個別送信のまま維持** する。再認識は対象が 1〜数フレームに限定されるため、バッチ化のメリットが乏しい。

### 移行手順

1. **検証**: 完了。`adr042_validation.ipynb` で `MSuTmBOo6Qo`（18 試合）について **Standard PayGo** で個別/バッチ送信ともに 100% 正解、レイテンシ 85.6% 短縮を確認済み（Flex PayGo は精度差ゼロのため Standard で検証）。
2. **実装変更**: 上記の通り `recognizer.py` の model_name・location・クライアント構築・GenerateContentConfig を修正し、`recognize_from_frames` の新設とフォールバック層を追加。
3. **限定テスト**: `test_r2_upload` モード等で複数本の動画（特に未検証パターン: 試合数が多い、文字パターンが異なる、画質が低めの動画）を処理し、認識結果・実測レイテンシ・503 発生率・バッチ失敗時の個別フォールバック動作を中間ファイルとログで確認。
4. **Flex PayGo 適用の検証**: レスポンス `usage_metadata.traffic_type == ON_DEMAND_FLEX` がログから読み取れるか確認（必要なら一時的に DEBUG ログを追加）。
5. **本番反映**: 常駐 PC（Docker）の再ビルド・再起動。
6. **完了期限**: 2026-10-16 の shutdown までに反映完了。リスクバッファとして **2026-08 末まで** を目標とする。

### ハマりどころ・既知の落とし穴

- **location を必ず先に変更する**: model_name だけ変更して location が `us-central1` のままだと 404 NOT_FOUND になる。実装作業順序として model_name と location は **同一コミットで変更** する。
- **`gemini-2.5-flash-lite` は us-central1 で動く**: 現行コードがそれで動いているため、location 差異に気付きにくい。これは 2.5 系の提供エンドポイントが 3.1 系より広いためであり、3.1 系は global/us/eu のみ。
- **Vertex AI で `GenerateContentConfig.service_tier="flex"` は NG**: これは Gemini Developer API (AI Studio) 専用のパラメータ。Vertex AI へ渡すと `400 INVALID_ARGUMENT` で拒否され、認識結果が全件空（UNKNOWN）になる。Vertex AI では HTTP ヘッダー `X-Vertex-AI-LLM-Request-Type: shared` + `X-Vertex-AI-LLM-Shared-Request-Type: flex` を `HttpOptions(headers=...)` で渡すのが正しい指定方法。
- **`_is_retryable_error` は 400 をリトライしない**: Flex の指定方法を間違えた場合、400 が返るがリトライ対象外（429/503 のみリトライ）。即時 raise されてフォールバック層も同じヘッダーを使うため全件失敗するので、初回実機投入時はまず 1 本だけ実行してログを確認する。
- **検証用 Notebook の SERVICE_TIER**: `adr042_validation.ipynb` では `SERVICE_TIER = None`（Standard PayGo）で検証している。Notebook は精度検証用なので変更不要。
- **バッチ送信時の index 対応**: モデルが返す JSON の `index` は 1 始まり（プロンプトで "image 1 → index=1" と指示）。送信したフレーム順序との対応に注意し、レスポンス取得後は index でソート・突合する。
- **バッチサイズの上限**: Gemini API は 1 リクエストあたり最大 3,600 画像、合計 20 MB（inline data）。本プロジェクトでは典型的に 10〜25 試合なので問題ないが、極端に長い動画では制約に近づく可能性がある。安全策として 100 フレームを目安にバッチを分割する仕様を入れることを検討。

## 影響

### コスト

- 単価は現行比 1.25x（input）/ 1.875x（output）に増加。
- 本プロジェクトの呼び出し規模では絶対額の影響は月数ドル以内に収まる見込み。
- Standard PayGo との価格差から、推定コスト削減効果は Standard PayGo 比で 50%。

### レイテンシ

- **検証実測値（Standard PayGo, 18 試合）**:
  - 個別送信: 40.24 秒（1枚平均 2.24 秒）
  - **バッチ送信: 5.78 秒**（85.6% 短縮）
- **本番実測値（Flex PayGo, 15 試合, バッチ送信, 2026-05-24 22:51:33 → 22:52:04）**: **約 31 秒**。Standard PayGo の検証値と同等オーダーで、混雑時の遅延は発生せず。
- Flex PayGo 混雑時の最悪値: 最大 30 分/リクエスト（client timeout の上限）。
- 動画 1 本の最悪ケース: **バッチ送信なら最悪 30 分**（個別送信なら N×30 分に膨らみうる）。バッチ送信採用により Flex PayGo の最悪レイテンシ問題が実質解消。

### 信頼性

- 503/429 発生時のリトライとフォールバック実装が必須。
- Flex PayGo 自体は GA だが、容量逼迫で 429/503 が返ることはありうるため、Standard PayGo へのクライアント切替フォールバックは必須。
- バッチ送信失敗時の個別送信フォールバックにより、All-or-Nothing リスクを緩和。

### 精度

- **検証実測値**: 個別送信・バッチ送信ともに 18/18 試合（100%）正解。ADR-019 で対処した JP/JAMIE 混同も再発しなかった。
- 1 動画のみの検証であり、文字パターンが大きく異なる動画での退行可能性は残る。実運用で監視し、退行が確認された場合はプロンプトの再調整・モード切替・`gemini-3-flash-preview` への切替を検討。

### 既存 ADR との関係

- **ADR-019**（Gemini認識精度の改善）: プロンプトと temperature 設定はそのまま維持。`thinking_budget=0` は ADR-019 の方針（OCR タスクの決定性向上）と整合的。
- **ADR-033**（再認識フロー）: `recognize_with_preprocessing` も同じモデル・同じクライアント（Flex PayGo）を使用するため自動的に移行対象。
- **ADR-004**（OAuth2認証）: Vertex AI 経由の認証方式は変更なし。
- **ADR-017**（検出パラメータの最適化）: `use_flex` フラグなど Tier 切替を同様の設定機構で切替可能にすることを推奨。

## 将来の見直し条件

以下のいずれかが発生した場合、本決定を見直す:

- Vertex AI Flex PayGo が提供終了した場合 → 即座に Standard PayGo へ切替。
- 実運用で 503/429 発生率が想定以上に高く、リトライ＋フォールバックで吸収しきれない場合。
- レイテンシが許容範囲（動画 1 本数時間以内）を継続的に超える場合。
- Flex PayGo の価格優位性が変更された場合（例: 割引率の縮小）。
- **バッチ送信の精度退行**が他の動画で観測された場合 → バッチサイズ縮小、または個別送信モードへの切戻し。設定で切替できる構造にしておく。
- 1 動画あたりのフレーム数が極端に多くなる運用変化があった場合 → バッチサイズ分割の必要性を再評価。

## 検証Notebook

[packages/local/notebooks/adr042_validation.ipynb](../../packages/local/notebooks/adr042_validation.ipynb) - 個別送信 vs バッチ送信の精度・レイテンシ比較を実施。本ADRの判断根拠となる検証結果が記録されている。

## 訂正履歴

### 2026-05-24: Vertex AI における Flex 指定方法の訂正

**背景**: 初版実装（コミット 83e94b7）で `GenerateContentConfig.service_tier="flex"` を指定したところ、Vertex AI が `400 INVALID_ARGUMENT` で全リクエストを拒否し、認識結果が全件 UNKNOWN（空文字）になる事故が発生。

**根本原因**:
- `service_tier` パラメータは **Gemini Developer API (AI Studio) 専用** であり、Vertex AI 経由（`vertexai=True`）では未対応。
- Vertex AI で Flex を使うには **Vertex AI Flex PayGo** という別機構を利用し、HTTP ヘッダー `X-Vertex-AI-LLM-Request-Type: shared` + `X-Vertex-AI-LLM-Shared-Request-Type: flex` を `HttpOptions(headers=...)` 経由で渡すのが正しい指定方法。
- 検証 Notebook (`adr042_validation.ipynb`) は `SERVICE_TIER = None`（= Standard PayGo）で実行されていたため、本問題が事前に検知されなかった。

**訂正内容**:
1. 「Flex Tier (Gemini Developer API)」前提を「Vertex AI Flex PayGo」へ訂正。
2. Tier 一覧表を「Vertex AI Consumption Options」へ訂正。
3. 指定方法の説明・コードサンプルを HTTP ヘッダー指定へ訂正。
4. タイムアウトを 15 分 → 30 分（Vertex AI Flex PayGo の上限）へ更新。
5. 「ハマりどころ」セクションに `service_tier` パラメータ NG の警告を追加。

**修正コミット**: 動作確認完了（2026-05-24 22:47-22:52、15 試合のバッチ送信が tier=flex で約 31 秒で成功）。

## 参考資料

- [Vertex AI Flex PayGo](https://docs.cloud.google.com/vertex-ai/docs/flex-paygo)
- [Vertex AI Consumption options](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/deploy/consumption-options)
- [gemini-3.1-flash-lite モデル仕様](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-lite)
- [Vertex AI Generative AI Pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)
- [Gemini API Deprecations](https://ai.google.dev/gemini-api/docs/deprecations)
- [Migrate to the latest Gemini models](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/migrate)
- [ADR-017: 検出パラメータの最適化とパラメータ管理システムの導入](017-detection-parameter-optimization.md)
- [ADR-019: Geminiキャラクター認識精度の改善](019-gemini-character-recognition-improvement.md)
- [ADR-033: Battlelog未マッチ時の画像前処理による再認識](033-rerecognition-with-image-preprocessing.md)
