# Parquet の Result フィールド修復ガイド

## 問題

ADR-026（RESULT画面テンプレートマッチング）の実装により、`winner_side`が検出されるようになりましたが、既存のparquetファイルには`player1.result`と`player2.result`が反映されていません。

### 原因

- 既存の動画は処理済みとしてスキップされるため、再度処理される際にも result フィールドが更新されない
- 中間ファイルには `winner_side` が保存されているが、parquet には反映されていない

## 修復方法

### 方法1: ローカルのparquetを修復（推奨）

中間ファイルから`winner_side`を読み込んで、ローカルのparquetを修復します。

```bash
cd packages/local
python3 << 'EOF'
import sys
sys.path.insert(0, '.')

from src.repair_result_from_intermediate import ResultRepair

# 修復対象の videoId を指定
video_ids = ["FrOc1qYFXvc", "UjjHS6Akj9E"]  # 複数指定可

repair = ResultRepair(intermediate_dir="./intermediate")

for video_id in video_ids:
    repaired = repair.repair_parquet_from_local(
        video_id,
        "/Users/kajiwarayutaka/ProjectSand/sf6-chapter/.uncommit/matches.parquet"
    )
    print(f"Video {video_id}: Repaired {repaired} records")
EOF
```

### 方法2: R2のparquetを修復

R2に直接アップロードされているparquetを修復する場合：

```bash
cd packages/local
python3 << 'EOF'
import sys
import os
sys.path.insert(0, '.')

# R2認証情報を環境変数で設定
os.environ["R2_ACCESS_KEY_ID"] = "your_access_key"
os.environ["R2_SECRET_ACCESS_KEY"] = "your_secret_key"
os.environ["R2_ENDPOINT_URL"] = "your_endpoint_url"
os.environ["R2_BUCKET_NAME"] = "your_bucket_name"

from src.repair_result_from_intermediate import ResultRepair

video_ids = ["FrOc1qYFXvc", "UjjHS6Akj9E"]

repair = ResultRepair(intermediate_dir="./intermediate")

for video_id in video_ids:
    repaired = repair.repair_parquet_from_r2(video_id, key="matches.parquet")
    print(f"Video {video_id}: Repaired {repaired} records")
EOF
```

## 修復スクリプトの詳細

### ResultRepair クラス

**ファイル**: `src/repair_result_from_intermediate.py`

#### メソッド

##### `repair_parquet_from_local(video_id, parquet_path)`

ローカルのparquetを修復します。

```python
repair = ResultRepair(intermediate_dir="./intermediate")
repaired = repair.repair_parquet_from_local(
    "FrOc1qYFXvc",
    "./uncommit/matches.parquet"
)
```

**戻り値**: 修復されたレコード数

##### `repair_parquet_from_r2(video_id, key="matches.parquet")`

R2のparquetを修復してアップロードします。

```python
repair = ResultRepair(intermediate_dir="./intermediate")
repaired = repair.repair_parquet_from_r2("FrOc1qYFXvc")
```

**戻り値**: 修復されたレコード数

## 修復ロジック

修復スクリプトは以下の処理を実行します：

1. **中間ファイルから chapters.json を読み込む**
   - `intermediate/{videoId}/chapters.json` から chapters リストを取得
   - `startTime` をキーにしてマップに変換

2. **parquet ファイルを読み込む**
   - PyArrowで parquet を読み込み
   - `to_pylist()` で Python のリストに変換

3. **レコードを修復**
   - 各レコードの `startTime` で中間ファイルの chapters を検索
   - `winner_side` フィールドを確認
   - `winner_side` から `player1.result` と `player2.result` を推定

4. **修復データをセーブ**
   - 修復済みデータをスキーマ（PyArrow スキーマ）にしたがってテーブルに変換
   - Snappy圧縮でparquetに書き込み

### winner_side → result の変換ルール

| winner_side | player1.result | player2.result |
|---|---|---|
| "player1" | "win" | "loss" |
| "player2" | "loss" | "win" |
| null | （変更なし）| （変更なし）|

## 検証

修復後、以下のコマンドで検証できます：

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

**期待される出力例**:
```
┌─────────────┬───────────┬───────────┬───────────┬─────────┬─────────┐
│   videoId   │ startTime │ character │ character │ result  │ result  │
├─────────────┼───────────┼───────────┼───────────┼─────────┼─────────┤
│ FrOc1qYFXvc │       153 │ MANON     │ JP        │ loss    │ win     │
│ FrOc1qYFXvc │       310 │ MANON     │ JP        │ win     │ loss    │
│ FrOc1qYFXvc │       394 │ MANON     │ JP        │ win     │ loss    │
│ FrOc1qYFXvc │       485 │ MANON     │ JP        │ loss    │ win     │
│ FrOc1qYFXvc │       629 │ MANON     │ JP        │ win     │ loss    │
│ FrOc1qYFXvc │       792 │ MANON     │ JP        │ NULL    │ NULL    │
└─────────────┴───────────┴───────────┴───────────┴─────────┴─────────┘
```

## 注意事項

### winner_side が null の場合

`winner_side: null` のレコードは修復されません。これは RESULT 画面が検出されなかった（検出信頼度が閾値以下だった）ことを意味します。

### 中間ファイルが存在しない場合

修復スクリプトはエラーを返します。中間ファイル保存ディレクトリを確認してください。

### バックアップ

修復前にparquetファイルをバックアップすることをお勧めします：

```bash
cp .uncommit/matches.parquet .uncommit/matches.parquet.backup
```

## 今後の対策

新しい動画は `main.py` の262-276行目のロジックで自動的に `winner_side` から `result` が推定されるようになりました。これにより、新規処理時には result フィールドが正しく設定されます。

詳細は [ADR-026](docs/adr/026-result-screen-match-outcome-detection.md) を参照してください。
