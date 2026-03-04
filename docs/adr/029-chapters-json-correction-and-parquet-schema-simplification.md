# ADR-029: chapters.json 手動修正のR2反映とParquetスキーマ簡素化

## ステータス

提案 - 2026-03-04

## 文脈

### 問題1: chapters.json の手動修正がParquetに反映されない

Gemini APIのキャラクター認識結果に誤りがあった場合、ユーザーは `intermediate/{video_id}/chapters.json` を手動で修正し、`--test-step chapters` でYouTubeチャプターに反映する運用を行っている（ADR-018で確立されたフロー）。

しかし、`--test-step r2 --from-intermediate` でR2上のParquetを更新する際、**キャラクター情報は `matches.json` から取得**され、`chapters.json` からは `winner_side` とBattlelog関連情報のみが取得される。そのため、`chapters.json` で修正したキャラクター名がParquetに反映されないという不整合が発生していた。

```
chapters.json（手動修正済み）: "JP VS GOUKI"   → YouTubeチャプターに反映 ✅
matches.json（未修正）:         "JAMIE VS GOUKI" → Parquetに反映         ❌
```

ユーザーが修正すべきファイルが2つ（chapters.json + matches.json）に分散しており、ADR-018の「chapters.jsonから誤検知の行を削除するだけで修正完了」という設計意図に反している。

### 問題2: ParquetにcharacterRawフィールドが不要

Parquetスキーマの `player1.characterRaw` / `player2.characterRaw` フィールドについて、以下の調査結果が得られた。

**Webアプリケーションでの使用状況**:
- DuckDBクエリで取得し、Matchオブジェクトに格納している
- しかし、**UIでは `character` フィールドのみ表示**しており、`characterRaw` はユーザーの目に触れない

**今後の利用用途**:
- `character` と `characterRaw` はほぼ同じ値（Gemini APIの認識結果と正規化結果が大半で一致）
- デバッグ・トレーサビリティは `intermediate/matches.json` で十分に担保されている
- 認識精度分析もローカルの中間ファイルで行う作業であり、Web経由での分析は現実的でない

## 決定

### 1. `--test-step r2 --from-intermediate` 実行時にchapters.jsonのキャラクター修正をmatchesに反映する

`from_intermediate` ブロックで `matches.json` を読み込んだ後、`chapters.json` の `title` フィールド（`"A VS B"` 形式）をパースし、`matches` の `player1.character` / `player2.character` を上書きする。

**反映ロジック**:
```
1. chapters.json の各エントリについて、matchId で matches のエントリを特定
2. title を "A VS B" 形式でパースし、player1.character と player2.character を取得
3. matches.json の値と異なる場合のみ上書きし、ログを出力
```

**反映対象フィールド**:
| chapters.json | matches への反映先 |
|---|---|
| `title` （パース結果） | `player1.character`, `player2.character` |
| `winner_side` | `player1.result`, `player2.result`（既存ロジック） |
| Battlelog関連 | `battlelogMatched` 等（既存ロジック） |

### 2. Parquetスキーマから `characterRaw` を削除する

`player_struct` から `characterRaw` フィールドを除去し、関連するコードを整理する。

**変更箇所**:
- `packages/local/src/storage/r2_uploader.py` - Parquetスキーマ定義
- `packages/web/src/shared/types.ts` - Player型定義
- `packages/web/src/client/search.ts` - DuckDBクエリとマッピング処理

**影響を受けないもの**:
- `intermediate/matches.json` - ローカルの中間ファイルには `characterRaw` を引き続き保存（デバッグ用途）
- `schema/match.schema.json` - JSONスキーマは中間ファイルのスキーマとして維持

## 選択肢の比較

### 問題1: chapters.json修正の反映方法

#### 選択肢A: chapters.jsonのtitleからmatchesのcharacterを上書き（採用）

| 観点 | 評価 |
|------|------|
| ユーザー体験 | 高（chapters.jsonのみ修正すればよい） |
| 実装複雑度 | 低（titleパースと上書きのみ） |
| 後方互換性 | 高（既存の未修正データに影響なし） |
| リスク | 低（titleの "A VS B" 形式は既に確立された規約） |

#### 選択肢B: matches.jsonも手動で修正する運用

| 観点 | 評価 |
|------|------|
| ユーザー体験 | 低（2ファイルを修正する必要あり） |
| 実装複雑度 | なし（コード変更不要） |
| 後方互換性 | 高 |
| リスク | 中（修正漏れが発生しやすい） |

#### 選択肢C: chapters.jsonをParquetの唯一のデータソースにする

| 観点 | 評価 |
|------|------|
| ユーザー体験 | 高 |
| 実装複雑度 | 高（chapters.jsonにconfidence等のフィールドを追加する必要あり） |
| 後方互換性 | 低（chapters.jsonのスキーマ変更が必要） |
| リスク | 中（大規模なリファクタリングが必要） |

### 問題2: characterRawの扱い

#### 選択肢A: Parquetから削除（採用）

| 観点 | 評価 |
|------|------|
| スキーマの簡素さ | 高 |
| デバッグ能力 | 維持（中間ファイルに残る） |
| 既存データへの影響 | R2上のParquet再生成が必要 |
| 将来性 | 問題なし（必要になればフィールド追加は容易） |

#### 選択肢B: Parquetに残す

| 観点 | 評価 |
|------|------|
| スキーマの簡素さ | 低（不要なフィールドが残る） |
| デバッグ能力 | 維持 |
| 既存データへの影響 | なし |
| 将来性 | 使用されないフィールドの保守コスト |

## トレードオフと帰結

### メリット

- **修正フローの一元化**: `chapters.json` のみを修正すれば、YouTubeチャプターとR2 Parquetの両方に反映される
- **ADR-018の設計意図との整合**: 「chapters.jsonを修正するだけ」という運用が完全に実現
- **スキーマの簡素化**: 使用されていないフィールドの除去によるコードの見通し改善

### デメリット・注意点

- **既存Parquetデータの再生成**: `characterRaw` フィールド削除後、R2上のParquetは再アップロードが必要（影響を受ける動画を `--test-step r2` で再実行）
- **titleパースへの依存**: `"A VS B"` 形式が崩れた場合のフォールバックが必要（パース失敗時はmatches.jsonの値を維持）

### 互換性

- Webフロントエンドの `characterRaw` 参照箇所の更新が必要
- `intermediate/matches.json` のフォーマットは変更なし
- YouTubeチャプター更新フロー（`--test-step chapters`）は影響なし

## 実装チェックリスト

- [ ] `main.py`: `from_intermediate` ブロックでchapters.jsonのtitleからmatchesのcharacterを上書きする処理を追加
- [ ] `r2_uploader.py`: Parquetスキーマから `characterRaw` を削除
- [ ] `repair_result_from_intermediate.py`: Parquetスキーマから `characterRaw` を削除
- [ ] `packages/web/src/shared/types.ts`: Player型から `characterRaw` を削除
- [ ] `packages/web/src/client/search.ts`: DuckDBクエリとマッピングから `characterRaw` を削除
- [ ] 既存のR2 Parquetデータの再アップロード（影響を受ける動画）

## 関連ADR

- [ADR-011: 中間ファイル保存による人間確認フロー](011-intermediate-file-preservation.md) - 中間ファイルの設計
- [ADR-018: 中間ファイル形式の改善](018-intermediate-file-format-improvement.md) - chapters.json手動修正の運用確立
- [ADR-019: Geminiキャラクター認識精度の改善](019-gemini-character-recognition-improvement.md) - 認識精度とcharacterRawの関係
- [ADR-023: Battlelogデータ統合とParquet Web検索機能の実装](023-battlelog-data-integration-with-parquet-search.md) - Parquetスキーマの定義元
