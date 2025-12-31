# ADR-002: データストレージ・検索方式

- **ステータス**: 承認
- **決定日**: 2024-12-28
- **決定者**: kajiwara22

## 1. 議論の背景

処理結果（動画情報、対戦データ、タイムスタンプ）をクラウドに保存し、ブラウザから検索・閲覧できるようにする。特に「特定のキャラクターとの対戦を探す」というユースケースを効率的に実現したい。

### 要件

- 処理結果をクラウドに累積保存したい
- 特定キャラクターとの対戦を高速に検索したい
- 将来的には統計情報（使用キャラクターの傾向など）も可視化したい
- R2のデータを認証なしで公開する想定はない
- 閲覧者は自分のみ

### データ規模の想定（1年運用時）

| 項目 | 計算 | 結果 |
|------|------|------|
| 動画数 | 365日 × 1本/日 | 約365本 |
| 対戦数 | 365本 × 15試合/本 | 約5,500試合 |
| データサイズ | | 約3MB |

## 2. 選択肢と結論

### 結論

**Parquet形式 + DuckDB-WASM + Pages Functions経由アクセス**を採用する。

### 検討した選択肢

| ID | 選択肢 |
|----|--------|
| A | JSONファイル + キャラクター別インデックス |
| B | JSONファイル累積 + ブラウザDuckDB-WASM直接クエリ |
| C | Parquet形式 + DuckDB-WASM + Pages Functions経由（採用） |
| D | Cloudflare D1（SQLite）使用 |

## 3. 各選択肢の比較表

| 観点 | A: JSON+Index | B: JSON+DuckDB直接 | C: Parquet+DuckDB（採用） | D: D1 |
|------|---------------|-------------------|-------------------------|-------|
| 検索パフォーマンス | ○ インデックス依存 | △ JSON解析コスト | ◎ 列指向で最速 | ◎ SQL |
| データ圧縮率 | × 非圧縮 | × 非圧縮 | ◎ 高圧縮 | ○ |
| クエリの柔軟性 | △ 事前定義のみ | ◎ SQL | ◎ SQL | ◎ SQL |
| R2非公開との両立 | ◎ | × 直接アクセス必要 | ◎ Functions経由 | - |
| 実装の複雑さ | ○ | △ 認証の考慮必要 | ○ | △ スキーママイグレーション |
| 生データ保全 | ○ JSON累積 | ○ JSON累積 | ◎ JSON+Parquet両方 | △ DB内のみ |
| ブラウザ処理負荷 | ◎ 軽量 | △ JSON解析重い | ○ Parquet読込 | ◎ サーバー処理 |

## 4. 結論を導いた重要な観点

### 4.1 R2を非公開に保つ要件

ブラウザからR2に直接アクセスする構成（選択肢B）は、R2を公開設定にするか署名付きURLを使う必要がある。Pages Functions経由でアクセスすることで、R2を完全に非公開のまま運用できる。

### 4.2 DuckDBとParquetの相性

ParquetはDuckDBのネイティブフォーマットであり、以下のメリットがある：
- 列指向で特定カラムのみ読み込み可能（キャラクター検索に最適）
- 圧縮率が高く通信量を削減
- スキーマ情報を含むため型安全

### 4.3 生データの保全

JSONファイルを累積保存することで、Parquetの再生成やスキーマ変更時に元データから復元可能。データの可搬性と将来の柔軟性を確保。

### 4.4 柔軟なクエリ

DuckDB-WASMにより、ブラウザ上でSQLクエリを実行可能。事前に想定していない検索パターンにも対応できる。

```sql
-- キャラクター検索
SELECT * FROM matches WHERE opponent = 'JP'

-- 統計
SELECT opponent, COUNT(*) as count 
FROM matches 
GROUP BY opponent 
ORDER BY count DESC

-- 期間絞り込み
SELECT * FROM matches 
WHERE date BETWEEN '2024-12-01' AND '2024-12-31'
```

## 5. 帰結

### 5.1 トレードオフ

| メリット | デメリット |
|---------|-----------|
| 高速な検索クエリ | ローカル側でParquet生成処理が必要 |
| 柔軟なSQL検索 | DuckDB-WASMの学習コスト |
| R2完全非公開 | Pages Functions実装が必要 |
| 生データ保全 | JSONとParquetの二重管理 |

### 5.2 データフロー

```
ローカルPC（処理時）
    │
    ├─→ videos/2024-12-28_abc123.json を R2 に追加（累積）
    │
    └─→ DuckDB で全JSONを読み込み
        └─→ matches.parquet を生成して R2 に上書き

ブラウザ（閲覧時）
    │
    └─→ Pages Functions経由で matches.parquet を取得
        └─→ DuckDB-WASM でSQLクエリ実行
```

### 5.3 ファイル構成

```
R2バケット
├── videos/                          # 生データ（累積）
│   ├── 2024-12-28_abc123.json
│   ├── 2024-12-29_def456.json
│   └── ...
├── index/
│   └── matches.parquet              # クエリ用（都度更新）
└── config/
    └── character_aliases.json       # キャラクター名正規化
```

### 5.4 将来の見直し条件

以下の場合、方式の見直しを検討する：

1. **データ量が大幅に増加**した場合
   - Parquetファイルの分割（年月別など）を検討
   - DuckDB-WASMのメモリ制限に注意

2. **リアルタイム検索が必要**になった場合
   - Cloudflare D1への移行を検討
   - ただし現在の要件では過剰

3. **複数ユーザーでのデータ共有**が必要になった場合
   - ユーザー別Parquetファイルの分離
   - アクセス制御の再設計

## 6. 各選択肢の説明

### 選択肢A: JSONファイル + キャラクター別インデックス

```
R2
├── videos/abc123.json
├── index/
│   ├── meta.json
│   └── characters/
│       ├── ryu.json      # リュウが出る全試合
│       ├── ken.json      # ケンが出る全試合
│       └── ...
```

キャラクター検索時は `characters/{name}.json` を1ファイル取得するだけで完了。

**不採用理由**:
- 検索パターンが事前定義に限定される
- 「リュウ vs JP」のような複合検索でクライアント側フィルタが必要
- インデックス更新処理が煩雑

### 選択肢B: JSONファイル累積 + ブラウザDuckDB-WASM直接クエリ

```
R2（公開設定）
├── videos/abc123.json
├── videos/def456.json
└── ...

ブラウザ
└── DuckDB-WASM
    └── SELECT * FROM read_json_auto('https://r2.example.com/videos/*.json')
```

**不採用理由**:
- R2を公開設定にする必要がある（セキュリティ要件に反する）
- 署名付きURL方式は複雑化する
- JSONの解析コストが毎回発生

### 選択肢C: Parquet形式 + DuckDB-WASM + Pages Functions経由（採用）

```
R2（非公開）
├── videos/*.json         # 生データ保管
└── index/matches.parquet # クエリ用

Pages Functions
└── /api/data/* → R2バインディングでアクセス

ブラウザ
└── DuckDB-WASM
    └── fetch('/api/data/index/matches.parquet')経由でクエリ
```

**採用理由**:
- R2を非公開のまま運用可能
- Parquetの高い圧縮率と検索性能
- SQLによる柔軟なクエリ
- 生データ（JSON）も保全

### 選択肢D: Cloudflare D1（SQLite）使用

```
Cloudflare D1
└── matches テーブル
    └── SQLクエリ

Pages Functions
└── /api/search → D1にクエリ
```

**不採用理由**:
- スキーママイグレーションの管理が必要
- ローカル処理との連携がやや複雑（D1への書き込みがHTTP経由）
- 現在のデータ規模では過剰な構成
- 生データの可搬性が低下

---

## 参考資料

- [DuckDB-WASM ドキュメント](https://duckdb.org/docs/api/wasm/overview)
- [Apache Parquet フォーマット](https://parquet.apache.org/)
- [Cloudflare Pages Functions R2バインディング](https://developers.cloudflare.com/pages/functions/bindings/#r2-buckets)
