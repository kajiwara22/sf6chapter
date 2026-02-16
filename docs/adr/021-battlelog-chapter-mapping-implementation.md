# ADR-021: YouTube チャプターと Battlelog リプレイのマッピング実装

## ステータス

採用（Accepted） - 2026-02-17

## 文脈

YouTube配信動画から自動検出したチャプター（対戦シーン）と、Battlelog APIから取得したリプレイデータを紐付け、各チャプターに対応するキャラクターの勝敗情報を付与する機能が必要。

### 要件

1. **動画チャプターデータとリプレイデータの紐付け**
   - チャプターのタイトルからキャラクター名を抽出（例: "GOUKI VS JP"）
   - リプレイのキャラクター名と照合
   - 時間情報に基づいて最適なリプレイを選択

2. **Web検索対応**
   - 「JPが勝った動画」の検索
   - 「リュウが負けた動画」の検索
   - 各キャラクターの個別結果記録が必須

3. **マッピングの精度確保**
   - 時間差による信頼度レベル分け
   - 重複マッチングの防止
   - キャラクター名の表記揺れ吸収

## 決定

YouTube チャプターと Battlelog リプレイの紐付けを実装する。以下の仕様で実装：

### 1. マッピングロジック

**ステップ1: 絶対時刻の算出**
```
チャプターの推定絶対時刻 = 動画配信開始時刻 + startTime
```

**ステップ2: キャラクター名の照合**
- チャプターのタイトルを " VS " で分割してキャラクター名を抽出
- キャラクター名正規化テーブル（`character_aliases.json`）で表記揺れを吸収
- リプレイの `player1_info.playing_character_tool_name` / `player2_info.playing_character_tool_name` と比較
- 順序は問わない（セット比較）

**ステップ3: 時間差による最適マッチング**
- キャラクター名が一致するリプレイ候補の中から時間差が最小のものを選択
- 時間差 = `uploaded_at` - `チャプターの推定絶対時刻`
- 通常 60〜300秒の正の値（試合時間 + アップロード処理）

**ステップ4: マッチング検証と重複排除**
- 時間差が600秒（10分）を超える場合はマッチング失敗
- 一度マッチしたリプレイは候補から除外（1対1対応を確保）

### 2. 処理フロー

```
入力: チャプター配列 + リプレイ配列 + 配信開始時刻
  ↓
1. チャプター/リプレイを時系列昇順でソート
2. 既使用リプレイIDセットを初期化
3. チャプターごとに:
   - キャラクター名を "VS" で分割・抽出・正規化
   - 推定絶対時刻を計算
   - 未使用リプレイから:
     * キャラクター名が一致するものを抽出
     * 時間差が最小のものを選択
   - マッチ成功時、リプレイIDを記録
  ↓
出力: 各チャプターに player1_character/result + player2_character/result を付与
```

### 3. 信頼度レベルの定義

| 信頼度 | 時間差 | 判定 |
|--------|--------|------|
| high | ≤180秒 | キャラクター名一致 & 時間差短い |
| medium | 180〜600秒 | キャラクター名一致 & 時間差中程度 |
| low | >600秒 またはマッチなし | 信頼できない |

### 4. 動画公開日時の取得

優先度順：
1. `--video-published-at` 引数（明示的に指定）
2. **YouTube Data API** → `videos.list(part="snippet")`から `publishedAt` を取得 ← **新規追加**
3. `chapters.json` の `publishedAt` フィールド（フォールバック）
4. エラー終了

YouTube APIから取得することで、別途メタデータファイルに依存しない堅牢な実装を実現。

### 5. 勝敗データ構造

各チャプターの出力に以下を含める：

```json
{
  "matched": true,
  "confidence": "high",
  "player1_character": "GOUKI",
  "player1_result": "loss",
  "player2_character": "JP",
  "player2_result": "win",
  "replay_id": "ENJUA5KLE",
  "uploaded_at": 1771081724,
  "time_difference_seconds": 149,
  "details": "Matched (time_diff=149.0s)"
}
```

**Web検索対応**:
- `player1_character == "RYU" AND player1_result == "loss"` → 「リュウが負けた」
- `player2_character == "JP" AND player2_result == "win"` → 「JPが勝った」
- `{player1_character, player2_character} == {"GOUKI", "JP"}` → 「GOUKIとJPの対戦」

## 実装ファイル

### 新規作成

- `packages/local/scripts/test_battlelog_mapping.py`

### 主要なクラス・メソッド

#### CharacterNormalizer
- キャラクター名の表記揺れを正規化
- `config/character_aliases.json` から読み込み

#### BattlelogMatcher
- `extract_chapter_characters()` - チャプターのタイトルからキャラクター名を抽出
- `extract_battlelog_characters()` - リプレイから各プレイヤーのキャラクター名を抽出（`playing_character_tool_name` 優先）
- `extract_battle_results()` - 各プレイヤーの勝敗を個別に判定（変更: 新規追加）
- `_determine_confidence_level()` - 時間差に基づいて信頼度を決定
- `match_chapter_with_battlelog()` - チャプターをリプレイと照合（重複排除対応）

#### main()
- YouTube APIから動画公開日時を取得（OAuth2認証を使用）
- チャプターとリプレイを時系列順でソート
- 重複排除ロジックを組み込んで順次マッピング
- JSON/pretty形式で結果を出力

## 使用方法

```bash
cd packages/local

# 基本的な使用法
uv run scripts/test_battlelog_mapping.py \
  --video-id dQwqkOG2SQo \
  --player-id 1319673732 \
  --chapters-file ./intermediate/dQwqkOG2SQo/chapters.json \
  --output-format pretty

# 動画公開日時を明示的に指定
uv run scripts/test_battlelog_mapping.py \
  --video-id dQwqkOG2SQo \
  --player-id 1319673732 \
  --chapters-file ./intermediate/dQwqkOG2SQo/chapters.json \
  --video-published-at "2026-02-14T15:05:45Z"

# 許容時間差を変更
uv run scripts/test_battlelog_mapping.py \
  --video-id dQwqkOG2SQo \
  --player-id 1319673732 \
  --chapters-file ./intermediate/dQwqkOG2SQo/chapters.json \
  --tolerance-seconds 300
```

### 環境変数

```bash
# Battlelog認証クッキー（必須）
export BUCKLER_ID_COOKIE="your_buckler_id_cookie"

# Google OAuth2認証（自動で token.pickle を再利用）
# 初回は対話的に認証、以降は自動更新
```

## 実装上の重要なポイント

### 1. キャラクター名フィールドの優先度

```python
# playing_character_tool_name を優先、フォールバック として character_name
p1_char = (
    replay.get("player1_info", {}).get("playing_character_tool_name")
    or replay.get("player1_info", {}).get("character_name", "Unknown")
)
```

Battlelog APIのレスポンス仕様変更に対応。

### 2. 時間差の正負チェック

```python
# リプレイ時刻がチャプター時刻より前の場合は除外
if time_diff < 0:
    continue
```

負の時間差（チャプター後に試合がアップロードされた不自然なケース）を除外。

### 3. 重複排除ロジック

```python
used_replay_ids = set()  # マッチ済みリプレイを追跡

for chapter in sorted_chapters:
    # ... マッチング ...
    if result.get("matched") and result.get("replay_id"):
        used_replay_ids.add(result["replay_id"])  # 記録
```

時系列順処理と組み合わせて、1リプレイが複数チャプターに重複マッチしないことを保証。

## トレードオフと帰結

### メリット

- ✅ Web検索対応：各キャラクターの勝敗を個別に記録
- ✅ 堅牢性：YouTube APIから動画情報を取得、メタデータ依存を削減
- ✅ 精度：時間差による最適マッチング、信頼度レベルで結果の質を可視化
- ✅ 拡張性：キャラクター名正規化テーブルで表記揺れに対応

### デメリット

- ⚠️ Battlelog API依存：リプレイデータがなければマッチング不可能
- ⚠️ 時間精度：チャプター時刻の推定精度に依存
- ⚠️ キャラクター名照合：「VS」区切りで抽出するため、特殊な表記には未対応

### 将来の改善

1. **より高度な照合ロジック**
   - 複数候補がある場合の優先度付け
   - リプレイ内容（ラウンド結果パターン）による補完確認

2. **信頼度スコアの詳細化**
   - 複数候補数、キャラクター順序、結果パターンなどを考慮
   - スコアリングアルゴリズムの導入

3. **手動修正フロー**
   - 中間ファイルで誤マッチングを検出し、手動で修正可能にする
   - ADR-011 に基づいた人間確認ループの統合

## 参考資料

- [ADR-006: Firestoreによる重複防止](006-firestore-for-duplicate-prevention.md)
- [ADR-011: 中間ファイル保存による人間確認フロー](011-intermediate-file-preservation.md)
- [YouTube Data API - Videos](https://developers.google.com/youtube/v3/docs/videos/list)
- [Battlelog API Reference](https://github.com/kajiwara22/sf6chapter)

## 検証方法

### 動作確認

```bash
# テスト実行
uv run scripts/test_battlelog_mapping.py \
  --video-id dQwqkOG2SQo \
  --player-id 1319673732 \
  --chapters-file ./intermediate/dQwqkOG2SQo/chapters.json \
  --output-format pretty
```

### 成功基準

- ✅ YouTube APIから正しく `publishedAt` を取得できる
- ✅ チャプター内のキャラクター名が正しく抽出される
- ✅ リプレイと照合でき、`player1_character/result` / `player2_character/result` が記録される
- ✅ マッチング結果の信頼度が正しく判定される
- ✅ リプレイの重複マッチングが発生しない
- ✅ JSON/pretty形式で結果が出力される

## 次のステップ

1. **本スクリプトの本流統合**
   - `main.py` の章末処理フローに統合
   - Battlelogマッピング結果を最終的なパッケージに含める

2. **Web画面への表示機能**
   - Parquetスキーマに `player1_character/result` / `player2_character/result` を追加
   - Web UIで「JPが勝った」などの検索フィルターを実装

3. **精度検証**
   - 複数の動画でマッピング精度を検証
   - 誤マッチング率を測定し、改善が必要な場合は対策を検討
