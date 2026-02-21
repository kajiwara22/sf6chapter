# テストモードガイド

## 概要

`--mode test` を使用することで、個別の処理ステップをテストできます。

### 新規処理との違い

テストモード（`--mode test --test-step all`）は、**新規処理と同様の流れ**を実行します：

1. ✅ 動画ダウンロード
2. ✅ テンプレートマッチングで対戦シーン検出
3. ✅ Gemini APIでキャラクター認識
4. ✅ YouTubeチャプター更新
5. ✅ Battlelog マッピング実行
6. ✅ **RESULT検出結果から result を推定** ← ADR-026 実装
7. ✅ R2へのデータアップロード
8. ✅ Parquetの更新

## 重要: winner_side から result への変換

ADR-026 の実装により、RESULT画面から検出された `winner_side` の値は自動的に `player1.result` と `player2.result` に変換されます。

### 変換ルール

| winner_side | player1.result | player2.result |
|---|---|---|
| "player1" | "win" | "loss" |
| "player2" | "loss" | "win" |
| null | （変更なし）| （変更なし）|

### 優先順位

1. **Battlelog マッピング結果** - `player1_result`, `player2_result` が存在する場合はそれを使用
2. **RESULT検出結果** - result が None の場合、`winner_side` から推定
3. **result = None** - どちらも利用不可の場合

## テストモードの使用方法

### 全ステップの実行

```bash
cd packages/local
uv run python main.py --mode test --test-step all --video-id FrOc1qYFXvc
```

このコマンドで以下が実行されます：

1. ✅ 動画をダウンロード
2. ✅ テンプレートマッチングで対戦シーン検出
3. ✅ Gemini APIでキャラクター認識
4. ✅ YouTubeチャプター更新
5. ✅ Battlelog マッピング（SF6_PLAYER_ID が設定されている場合）
6. ✅ **RESULT検出結果から result を推定**
7. ✅ R2へデータをアップロード（ENABLE_R2=true の場合）
8. ✅ Parquetを更新

### 個別ステップの実行

#### ダウンロード
```bash
uv run python main.py --mode test --test-step download --video-id FrOc1qYFXvc
```

#### 検出
```bash
uv run python main.py --mode test --test-step detect --video-id FrOc1qYFXvc
```

#### キャラクター認識
```bash
uv run python main.py --mode test --test-step recognize --video-id FrOc1qYFXvc
```

#### チャプター生成
```bash
uv run python main.py --mode test --test-step chapters --video-id FrOc1qYFXvc
```

#### R2 アップロード
```bash
uv run python main.py --mode test --test-step r2 --video-id FrOc1qYFXvc
```

## 中間ファイルからの処理

すでに中間ファイルが存在する場合、`--from-intermediate` フラグを使用して中間ファイルから結果を読み込めます：

```bash
# 中間ファイルからチャプターを生成（新たに動画処理をスキップ）
uv run python main.py --mode test --test-step chapters --video-id FrOc1qYFXvc --from-intermediate

# 中間ファイルからR2へアップロード
uv run python main.py --mode test --test-step r2 --video-id FrOc1qYFXvc --from-intermediate
```

## result フィールドの検証

修復後のparquetを確認する場合：

```bash
duckdb << 'EOF'
SELECT
    videoId,
    startTime,
    player1.character,
    player2.character,
    player1.result,
    player2.result
FROM read_parquet('./.uncommit/matches.parquet')
WHERE videoId = 'FrOc1qYFXvc'
ORDER BY startTime;
EOF
```

## テストモード実行時の注意事項

### 環境変数

```bash
# Battlelog マッピングを有効化（オプション）
export SF6_PLAYER_ID="your_player_id"
export BUCKLER_ID_COOKIE="your_cookie"
export BATTLELOG_CACHE_DB="./battlelog_cache.db"

# R2 アップロードを有効化
export ENABLE_R2=true
export R2_ACCESS_KEY_ID="your_access_key"
export R2_SECRET_ACCESS_KEY="your_secret_key"
export R2_ENDPOINT_URL="your_endpoint"
export R2_BUCKET_NAME="your_bucket"

# テスト実行
uv run python main.py --mode test --test-step all --video-id FrOc1qYFXvc
```

### Firestore の更新

テストモード実行時、Firestore に記録は**保存されません**。これにより、同じ動画を何度でもテストできます。

### R2アップロードの無効化

`--no-r2` フラグで、チャプターステップのR2アップロードをスキップできます：

```bash
uv run python main.py --mode test --test-step chapters --video-id FrOc1qYFXvc --no-r2
```

## トラブルシューティング

### result が NULL のままの場合

1. **RESULT画面が検出されていない**
   - `detection_params.json` の `result_detection` セクションを確認
   - テンプレート画像のパスが正しいか確認
   - 閾値（`result_threshold`, `win_threshold`）を調整

2. **winner_side が null**
   - 中間ファイルの `chapters.json` を確認して `winner_side` が null でないかチェック

3. **Battlelog マッピング結果が優先される**
   - `player1_result`, `player2_result` が既に設定されている場合は、RESULT検出は実行されません
   - Battlelog マッピングが必要ない場合は、`SF6_PLAYER_ID` を設定しないでください

## 参考資料

- [ADR-026: 対戦動画からの勝敗検出](docs/adr/026-result-screen-match-outcome-detection.md)
- [Parquet Result フィールド修復ガイド](docs/REPAIR_RESULT_FIELD.md)
