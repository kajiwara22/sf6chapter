# ADR-055: OPFS によるクライアントキャッシュ（Parquet バイトと DuckDB データベース）

## ステータス

採用 - 2026-10-11（実装完了 2026-10-11）

## 文脈

### きっかけ

ゲージ詳細ページ（`/matches/{matchId}`、[ADR-051](051-match-detail-page-and-round-stats-redesign.md)）と対戦検索（`/`）を行き来するたびに、同じ Parquet を毎回 R2 からダウンロードし、DuckDB-WASM を毎回初期化してテーブルを全行作り直している。更新タイミングが不定とはいえ、内容が変わっていなければ再ダウンロードは不要であり、ブラウザの OPFS にキャッシュできないかを検討する。

### 現状の動作

`/` と `/matches/:matchId` はどちらもサーバが同じ HTML シェルを返す MPA（フルページロード）で、`main.ts` がパスに応じて初期化を分岐する。どちらのページでも毎回次が走る。

1. DuckDB-WASM を jsdelivr から取得（HTTP キャッシュは効く）→ `instantiate` → `connect`
2. 各ファイルにつき **presign API → R2 ダウンロード** を直列に実行（`loadParquetData` → `loadBattlelogParquetData` → `loadRoundStatsParquetData`）
3. `registerFileBuffer`（ArrayBuffer へ全コピー）→ `CREATE TABLE AS SELECT * FROM read_parquet(...)` で**全行を毎回メモリに再マテリアライズ**
4. 詳細ページはさらに `gauges/{matchId}.json` と `config/character_health.json` を presign 経由で取得

### データ実測（R2、2026-10-11）

| ファイル | サイズ | 行数 |
|---------|-------|------|
| `matches.parquet` | 115 KB | 1,943 |
| `battlelog_replays.parquet` | 80 KB | 1,589 |
| `round_stats.parquet` | 15 KB | 222 |
| `gauges/{matchId}.json` | 26 KB | - |
| `config/character_health.json` | 0.5 KB | - |

`round_stats` は未バックフィル分を反映すると `matches × 平均ラウンド数 ≒ 6,000 行 ≒ 400 KB` 程度まで育つ見込みで、`battlelog_replays` は収集対象に比例して増え続ける。**現時点のバイト量は小さい**（合計約 210 KB）ため、問題の主因はバイト量ではなく次の 4 点である。

| # | 課題 | 内容 |
|---|------|------|
| P1 | 往復回数 | presign 3 + R2 ダウンロード 3 = 最大 6 往復。しかも直列 |
| P2 | 再マテリアライズ | 毎ロードで全行を DuckDB のメモリテーブルに作り直す（データ増加に比例して悪化） |
| P3 | 不要ロード | `/`（検索）は `round_stats.parquet` をロードするが一度もクエリしない（`queryRoundStats` は詳細ページ専用） |
| P4 | 詳細ページの過剰取得 | 1 試合の表示に 3 テーブル全件をロードする |

### 制約・前提（決定済み）

- **対応ブラウザは自分用の Chrome 系のみ**（OPFS の `FileSystemSyncAccessHandle` を worker で使える前提を許容できる）
- **`packages/local` の pipeline 変更を許容する**（`manifest.json` の書き出し等）
- **データ更新直後の即時性は不要**（数時間の stale を許容）
- R2 バケットは非公開を維持し、Presigned URL 方式（[ADR-010](010-parquet-presigned-url.md)）は変更しない

### 技術調査（インストール済み `@duckdb/duckdb-wasm` 1.32.0 で確認）

- `AsyncDuckDB.open({ path: 'opfs://...' })` が使える。worker 側で OPFS の `createSyncAccessHandle` を開き、`useDirectIO` を強制する（`worker_dispatcher` 実装）
- SQL 中の `opfs://` は `registerOPFSFileName()` / `config.opfs.fileHandling = "auto"` で自動登録できる
- `AsyncDuckDB.registerFileHandle(name, file, DuckDBDataProtocol.BROWSER_FILEREADER, false)` に OPFS の `getFile()` で得た `File` を渡すと、DuckDB は **レンジ単位で遅延読み込み**する（`FileReaderSync` + `Blob.slice`）。全 ArrayBuffer コピーも排他ロックも不要
- Presigned URL は署名クエリが毎回変わるため、**URL キーの HTTP キャッシュには乗らない**。よって「変わったかどうかを安く知る」仕組みが別途必要

## 決定

### 1. ページロード時の無駄を先に除去する（キャッシュ以前の改善）

- `/` から `round_stats.parquet` のロードを削除する（必要なのは詳細ページのみ）
- `matches` と `battlelog` のロードを並列化する
- 3 本の presign を 1 本の manifest 取得に統合する（決定 4）

### 2. Parquet バイトを OPFS に content-addressed でキャッシュする

- 保存先は OPFS。キーは **R2 の ETag** を使い `sf6/blobs/{etag}/{name}` に置く。内容が変われば ETag が変わるため、**キャッシュ自身は無効化不要（immutable）**
- 書き込みは main thread の `getFileHandle(name, { create: true })` → `createWritable()` → `write()` → `close()`（commit は `close()` 時）
- 読み込みは `getFile()` で得た `File` を `registerFileHandle(name, file, BROWSER_FILEREADER, false)` に渡す。DuckDB が必要な範囲だけを読むため、WASM メモリへの全コピーを避けられる
- 参照されなくなった ETag のブロブは GC する

### 3. DuckDB データベースを OPFS にバージョン付きで永続化する

- `db.open({ path: 'opfs://sf6/db/sf6-v{SCHEMA}-{version}.db' })` でファイルバックの DB を開く
- 初回・更新時のみ Parquet を読み込んでテーブルを構築し、完了時に `db.flushFiles()` → 完了マーカー `sf6/db/sf6-v{SCHEMA}-{version}.ok` を書く。マーカーには**テーブルごとの行数**を記録する
- 次回起動時は、マーカーが存在し行数が一致する場合に限り DB をそのまま `open` する。**Parquet ダウンロードもテーブル構築も発生しない**
- `SCHEMA` はスキーマ世代（ADR-048〜054 級の列変更で上げる）。古い世代の DB は読まずに GC する
- 完成前にクラッシュした DB を読まないよう、**ビルドは新 version のファイルに対して行い、マーカーが書けて初めて「公開」**とする

### 4. 無効化: pipeline が書く manifest を唯一の真実とする

`packages/local` は Parquet のアップロード完了後に `manifest.json` を書く。

```json
{
  "schema": 1,
  "version": "<sha256(sorted 'name:etag') の先頭16桁>",
  "generatedAt": "2026-10-11T12:00:00Z",
  "files": {
    "matches.parquet": { "etag": "\"…\"", "size": 115418 },
    "battlelog_replays.parquet": { "etag": "\"…\"", "size": 81742 },
    "round_stats.parquet": { "etag": "\"…\"", "size": 15146 }
  }
}
```

- ETag は pipeline が `head_object` で実際のオブジェクト状態から取得する。**全ファイルの完了後に最後に manifest を書く**ため、途中失敗時に実データと manifest がずれない
- `GET /api/data/manifest` は `manifest.json` を R2 binding で読んでそのまま返す（**Presigned URL は含めない**）。欠落時は既知キーを `head()` して生成するフォールバックを持つ
- クライアントは毎ロードで manifest を 1 往復取得する（数千バイト）。`version` が変わっていなければ OPFS の DB を開くだけで終了。違えば **ETag が変わったファイルだけ**既存の presign エンドポイントで取得し、新 version の DB をビルドする
- stale 数時間可のため、manifest 取得自体に短い TTL（例: 10 分）を設けてもよいが、初期実装では毎回取得する

### 5. キャッシュは純粋な最適化とし、常にフォールバックを持つ

| 状況 | 挙動 |
|------|------|
| OPFS 非対応・無効 | 現行どおり in-memory ロード |
| DB ファイルが別タブにロックされている | in-memory ロード + ブロブキャッシュのみ利用 |
| manifest が無い / 取得失敗 | 既存の presign 3 本にフォールバック（現行と同一） |
| マーカー欠落 / 行数不一致 / `open` 例外 | DB を削除して再ビルド |
| `QuotaExceededError` | 旧 version を GC して再試行。なお失敗なら in-memory |

- ブロブの書き込みと完了マーカーの書き込みは `navigator.locks` で同一キーを直列化する（同一 ETag の同時書き込み対策）
- タブ間の DB 排他は OPFS の `createSyncAccessHandle` 自体が担う。開けないタブは in-memory にフォールバックする
- 初回ビルド時に `navigator.storage.persist()` を要求する
- キャッシュが消えても・壊れても、次のロードで再取得すれば正しい結果になる（＝正確性に影響しない）

## 選択肢の比較

### キャッシュの保存先

| 方式 | 遅延読み | 排他ロック | 実装 | 判定 |
|------|---------|-----------|------|------|
| OPFS + `BROWSER_FILEREADER` | ◎ | なし | ○ | **採用** |
| OPFS + `opfs://`（sync handle） | ◎ | **あり**（マルチタブ不可） | ○ | 不採用（DB 永続化のみで使用） |
| Cache Storage API | ✕（毎回 ArrayBuffer） | なし | ◎ | 次点（OPFS 不可時の代替） |
| IndexedDB | ✕ | なし | △ | 不採用 |

### 無効化方式

| 方式 | 追加往復 | pipeline 変更 | 判定 |
|------|---------|--------------|------|
| manifest（ETag）を毎回取得 | 1 | 小（manifest 書き出し） | **採用** |
| 各 presign レスポンスに ETag を追加 | 3 | 不要 | 次点 |
| `If-None-Match` で 304 | 3 | 不要 | 不採用（往復が減らない） |
| content-addressed なオブジェクト名 + manifest | 1 | 大（旧オブジェクト GC） | 将来の選択肢 |
| TTL のみ | 0 | 不要 | 不採用（更新を検知できない） |

### DuckDB データベースの永続化

| 方式 | テーブル再構築 | 破損リスク | 判定 |
|------|--------------|-----------|------|
| OPFS に永続化 | 初回 / 更新時のみ | あり（マーカーで検出・再構築） | **採用** |
| 毎回 in-memory | 毎回 | なし | フォールバックとして維持 |

## リスクと対策

| リスク | 内容 | 対策 |
|--------|------|------|
| DB の排他ロック | `createSyncAccessHandle` はファイル単位で排他。別タブが同じ DB を開けない | OPFS の排他ハンドルを mutex として扱い、開けないタブは in-memory にフォールバック。書き込み系（ブロブ・マーカー）は `navigator.locks` で直列化 |
| DB の破損・torn write | 書き込み途中でタブが閉じると不完全な DB が残る | 完了マーカー（＋行数）が無い / 一致しない DB は削除して再ビルド。新 version 名に書いてから公開 |
| スキーマ変更 | 古い世代の DB を開くと列がずれる | DB 名に `SCHEMA` 世代を含め、世代が違えば再ビルド |
| ストレージ逼迫・eviction | クォータ超過やブラウザによる削除 | `persist()` / `estimate()` / 旧 version GC。失敗時は in-memory |
| manifest と実データの不整合 | pipeline 途中失敗 | manifest は全ファイル完了後に最後に書く。ETag は `head_object` で実オブジェクトから取得 |
| Presigned URL の期限（1 時間） | manifest に URL を含めると期限切れの恐れ | manifest には URL を含めず、必要時に既存エンドポイントで都度発行 |
| キャッシュの残留 | Access 背後だがブラウザにはデータが残る | キャッシュクリア導線（`sf6/` の削除）を用意する |
| gauges JSON の更新 | `gauges/{matchId}.json` は再処理で書き換わる | 本 ADR の対象外（per-match 取得のまま）。必要になれば manifest に gauges 索引を追加して同様にキャッシュする |

## OPFS レイアウト

```
sf6/
  db/
    sf6-v1-<version>.db     # DuckDB データベース（排他ロックあり）
    sf6-v1-<version>.ok     # 完了マーカー（行数つき JSON）
  blobs/
    <etag>/matches.parquet
    <etag>/battlelog_replays.parquet
    <etag>/round_stats.parquet
```

- `version` は manifest の `version`、`v1` はスキーマ世代
- 現在の manifest から参照されない `db/` と `blobs/` は GC する

## 実装チェックリスト（段階導入）

### Phase 1: 往復削減（キャッシュなしでも効果がある）

- [x] `/` から `round_stats.parquet` のロードを削除
- [x] `matches` / `battlelog` のロードを `initCachedData` に集約（並列に近い 1 経路化）

### Phase 2: manifest + ブロブキャッシュ

- [x] `r2_uploader` がアップロード完了後に `manifest.json` を書く
- [x] `GET /api/data/manifest` を追加（R2 binding 読み + `head()` フォールバック）
- [x] OPFS ブロブキャッシュ（ETag キー、`createWritable()` 書き込み）
- [x] `registerFileHandle(..., BROWSER_FILEREADER, false)` による遅延読み
- [x] フォールバック（OPFS 不可 / manifest 失敗 → 現行経路）

### Phase 3: DuckDB DB の永続化

- [x] `opfs://sf6/db/sf6-v{SCHEMA}-{version}.db` での open
- [x] 完了マーカー（行数）と整合性検証、破損時の削除再構築
- [x] `navigator.locks`（ブロブ・マーカー書き込み）、`navigator.storage.persist()`
- [x] 旧 version の GC

### Phase 4: 実環境での検証（未実施）

- [ ] `performance.mark` / `measure` による効果測定
- [ ] Chrome 実機で `/` ↔ `/matches/{matchId}` の相互遷移・リロードを確認
- [ ] 別タブ同時オープン時の in-memory フォールバックを確認

## 実装状況（2026-10-11）

| ファイル | 内容 |
|---------|------|
| `packages/web/src/shared/manifest.ts` | manifest の型・`version` 計算（Web と pipeline で同一アルゴリズム） |
| `packages/web/src/shared/types.ts` | `DataManifest` / `ManifestFileEntry` |
| `packages/web/src/client/cache.ts` | OPFS ブロブキャッシュ・完了マーカー・GC・manifest 取得 |
| `packages/web/src/client/search.ts` | `initDuckDB({ dbPath })` と `initCachedData(tables)`（永続 DB 優先 + in-memory フォールバック） |
| `packages/web/src/client/main.ts` | `/` は matches + battlelog のみ、詳細ページは 3 テーブルを `initCachedData` で取得 |
| `packages/web/src/server/routes/api.ts` | `GET /api/data/manifest` |
| `packages/local/src/storage/r2_uploader.py` | `publish_manifest()`（モジュールレベル関数 + `R2Uploader` メソッド） |
| `packages/local/main.py` | `process_video` / `_update_battlelog_parquet` / `--test-step r2` で manifest を更新 |
| `packages/local/scripts/upload_to_r2.py` / `upload_gauge_data.py` | 完了後に manifest を更新 |
| `packages/local/src/repair_result_from_intermediate.py` | matches.parquet 修復後に manifest を更新 |

テスト: web 159 件、local の manifest テスト 4 件が成功（無関係な既存失敗を除く）。

## 検証（効果測定）

`performance.mark` / `measure` で次の区間を計測し、キャッシュ有無で比較する。

- manifest 取得
- ブロブキャッシュ hit / miss とダウンロード量
- テーブル構築時間
- DB open 時間

期待値: 2 回目以降のページロードで **R2 ダウンロード 0**、**テーブル構築 0**。`/` と `/matches/{matchId}` の相互遷移、およびリロードで確認する。

## 関連ADR

- [ADR-010: Parquet データ取得方式（Presigned URL）](010-parquet-presigned-url.md) - 取得方式は維持。本 ADR は「取得済みデータの再利用」を追加する
- [ADR-002: データストレージ・検索方式](002-data-storage-search.md) - クライアントサイド検索（DuckDB-WASM）の前提
- [ADR-009: Cloudflare Pages から Workers への段階的移行戦略](009-cloudflare-pages-to-workers-migration-strategy.md) - SPA 化する場合の方向性
- [ADR-051: ゲージ詳細ページの独立化](051-match-detail-page-and-round-stats-redesign.md) - 詳細ページが毎回 Parquet をロードする前提（P4）を作った
- [ADR-048](048-round-drive-sa-gauge-timeline-capture.md) / [ADR-050](050-health-gauge-timeline-and-integrated-view.md) - `round_stats.parquet` のスキーマ世代管理が必要になった例
