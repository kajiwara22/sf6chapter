# ADR-031: Battlelog Parquet 変換・アップロードの main.py パイプライン統合

## ステータス

提案 - 2026-03-08

## 文脈

### 現状

ADR-030 で Battlelog キャッシュ（SQLite）→ Parquet 変換 → R2 アップロードの仕組みを導入した。現在は以下の2つのスタンドアロンスクリプトとして実装されている：

```bash
# 1. SQLite → Parquet 変換
uv run python scripts/convert_battlelog_to_parquet.py

# 2. R2 にアップロード
uv run python scripts/upload_to_r2.py --battlelog
```

### 課題

- 動画処理パイプライン（`main.py`）で Battlelog マッチングが実行されるとキャッシュが更新されるが、Parquet の変換・アップロードは別途手動実行が必要
- `--mode once`（Pub/Sub Pull）や `--mode test`（テストモード）でキャッシュが更新されても、Parquet の更新を忘れる可能性がある
- 結果、Web UI のマッチアップチャートが古いデータのまま残る

### 要件

- `--mode once` でも `--mode test` でも、Battlelog キャッシュが更新された場合に自動的に Parquet 変換 + R2 アップロードを実行したい
- 既存のスタンドアロンスクリプトも引き続き独立して使えるようにしたい

## 決定

### `main.py` に Battlelog Parquet パイプラインを統合する

#### 統合ポイント

Battlelog マッチングが実行される箇所は2つ：

1. **`SF6ChapterProcessor._run_battlelog_matching()`**（`--mode once` / `--mode daemon`）
2. **`test_r2_upload()`関数内の Battlelog マッチングブロック**（`--mode test --test-step r2`）

いずれもキャッシュ更新後に `convert_battlelog_to_parquet` + R2 アップロードを実行する。

#### 実装方針

**A. 共通ヘルパー関数の追加**

`main.py` に以下の関数を追加する：

```python
def _update_battlelog_parquet(
    battlelog_cache_db: str,
    r2_uploader: R2Uploader | None,
    output_dir: Path,
) -> None:
```

この関数は：
1. `convert_battlelog_to_parquet()` を呼び出して SQLite → Parquet 変換
2. R2 が有効な場合は `R2Uploader.upload_parquet()` で R2 にアップロード
3. R2 が無効な場合はローカルの `output/` に Parquet を保存（ログのみ）

**B. `SF6ChapterProcessor` への統合**

`process_video()` 内の `_run_battlelog_matching()` 呼び出し後に `_update_battlelog_parquet()` を呼ぶ。`SF6_PLAYER_ID` が未設定でマッチング自体がスキップされた場合は、Parquet 更新もスキップする。

**C. `test_r2_upload()` への統合**

Battlelog マッチングブロックの末尾に `_update_battlelog_parquet()` を呼ぶ。`sf6_player_id` が設定されている場合のみ実行。

#### import の追加

```python
from scripts.convert_battlelog_to_parquet import (
    convert_battlelog_to_parquet,
    get_battlelog_replays_schema,
)
```

`scripts/` ディレクトリからの import が必要なため、`sys.path` に追加するか、関数内で遅延 import する。遅延 import を採用し、Battlelog 処理が不要な場合の起動時間への影響を避ける。

#### エラーハンドリング

Parquet 変換・アップロードの失敗は動画処理のメインフローをブロックしない。`try/except` で囲み、エラーログを出力して続行する。

## 選択肢の比較

### 選択肢A: main.py に直接統合（採用）

| 観点 | 評価 |
|------|------|
| 自動化 | ◎ キャッシュ更新時に自動実行 |
| 保守性 | ○ 処理フロー内で一貫 |
| 既存スクリプトとの関係 | ○ スタンドアロンスクリプトも併存 |
| 障害分離 | ○ try/except で動画処理に影響なし |

### 選択肢B: post-process hook として外部スクリプトを呼び出す

| 観点 | 評価 |
|------|------|
| 自動化 | ○ subprocess で呼び出し |
| 保守性 | △ プロセス間の状態共有が困難 |
| 既存スクリプトとの関係 | ◎ スクリプトをそのまま利用 |
| 障害分離 | ○ 別プロセスなので分離は良い |

### 選択肢C: main.py への統合は行わず、手動実行のみ

| 観点 | 評価 |
|------|------|
| 自動化 | ✕ 毎回手動実行が必要 |
| 保守性 | ◎ main.py の変更不要 |
| 既存スクリプトとの関係 | ◎ そのまま |
| 障害分離 | ◎ 完全に独立 |

### 結論

選択肢A を採用。キャッシュ更新の自動追従が最優先の要件であり、関数レベルの統合で十分シンプルに実現できる。

## トレードオフと帰結

### メリット

- Battlelog キャッシュ更新時に自動的に Parquet が最新化される
- Web UI のマッチアップチャートが常に最新データを反映
- 手動でのスクリプト実行忘れを防止

### デメリット・注意点

- `main.py` の処理時間が若干増加する（Parquet 変換 + R2 アップロード分）
- `convert_battlelog_to_parquet` は全キャッシュデータを毎回変換するため、データ量が増えた場合は差分更新の検討が必要
- `scripts/convert_battlelog_to_parquet.py` の関数を `main.py` から import するため、モジュール構成の整理が将来的に必要になる可能性がある

### 互換性

- 既存のスタンドアロンスクリプト（`scripts/convert_battlelog_to_parquet.py`, `scripts/upload_to_r2.py --battlelog`）は引き続き単独実行可能
- 既存の動画処理フローには影響なし（Parquet 更新失敗時もメインフローは継続）

## 実装チェックリスト

- [x] `main.py`: `_update_battlelog_parquet()` ヘルパー関数の追加
- [x] `main.py`: `SF6ChapterProcessor.process_video()` に Battlelog Parquet 更新の呼び出しを追加
- [x] `main.py`: `test_r2_upload()` に Battlelog Parquet 更新の呼び出しを追加

## 関連 ADR

- [ADR-022: Battlelog API キャッシング機構（SQLite）](022-battlelog-api-caching-with-sqlite.md) - キャッシュ DB の設計
- [ADR-030: Battlelogキャッシュデータを活用したマッチアップチャート機能](030-matchup-chart-from-battlelog-cache.md) - Parquet 変換・R2 アップロードの元となる設計
