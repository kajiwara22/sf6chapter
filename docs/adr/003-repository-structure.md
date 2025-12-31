# ADR-003: リポジトリ構成

- **ステータス**: 承認
- **決定日**: 2024-12-28
- **決定者**: kajiwara22

## 1. 議論の背景

本システムは以下の3つのコンポーネントで構成される：

1. **ローカルPC用Python処理**: Pub/Sub監視、動画処理、Parquet生成
2. **Google Cloud Functions**: 新動画検知、Pub/Sub発行
3. **Cloudflare Pages + Functions**: 閲覧UI、R2アクセスAPI

これらを効率的に管理・デプロイするためのリポジトリ構成を決定する必要がある。

### 考慮すべき点

- 複数の言語（Python、TypeScript）が混在
- 複数のデプロイ先（ローカル、GCP、Cloudflare）
- 共通のデータスキーマを各コンポーネントで参照
- 個人プロジェクトのため過度に複雑な構成は避けたい

## 2. 選択肢と結論

### 結論

**モノレポ + 共通スキーマ構成**を採用する。

### 検討した選択肢

| ID | 選択肢 |
|----|--------|
| A | マルチレポ（用途別に分割） |
| B | モノレポ（フラット構成） |
| C | モノレポ + 共通スキーマ構成（採用） |

## 3. 各選択肢の比較表

| 観点 | A: マルチレポ | B: モノレポ（フラット） | C: モノレポ+スキーマ（採用） |
|------|-------------|---------------------|---------------------------|
| 全体の見通し | △ 分散 | ○ | ◎ 構造化 |
| スキーマ共有 | × 同期が困難 | △ 場所が曖昧 | ◎ 明確に分離 |
| デプロイの独立性 | ◎ | ○ | ◎ |
| 初期構築の手間 | △ 3リポジトリ | ◎ | ○ |
| ドキュメント管理 | △ 分散 | ○ | ◎ 集約 |
| GitHub連携 | ○ | ○ | ◎ Pages設定容易 |

## 4. 結論を導いた重要な観点

### 4.1 スキーマの一元管理

JSON/Parquetの構造定義を `schema/` に配置することで：
- Python側でのバリデーションに使用
- TypeScript側での型生成に使用
- ドキュメントとしても機能

### 4.2 各コンポーネントの独立性

`packages/` 配下に各コンポーネントを配置することで：
- 個別にデプロイ可能
- 依存関係が明確
- Cloudflare Pagesは `packages/web` をルートに指定

### 4.3 ドキュメントの集約

設計資料（ADR）、セットアップ手順、構成図を一箇所で管理できる。

## 5. 帰結

### 5.1 ディレクトリ構成

```
sf6-chapter/
├── packages/
│   ├── local/                    # ローカルPC用Python
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── main.py
│   │   │   ├── pubsub_client.py
│   │   │   ├── video_processor.py
│   │   │   ├── chapter_generator.py
│   │   │   ├── r2_client.py
│   │   │   └── parquet_manager.py
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── README.md
│   │
│   ├── gcp-functions/            # Google Cloud Functions
│   │   ├── check-new-video/
│   │   │   ├── main.py
│   │   │   └── requirements.txt
│   │   ├── deploy.sh
│   │   └── README.md
│   │
│   └── web/                      # Cloudflare Pages + Functions
│       ├── src/
│       │   ├── index.html
│       │   ├── app.ts
│       │   └── styles.css
│       ├── functions/
│       │   └── api/
│       │       ├── data/[[path]].ts
│       │       └── _middleware.ts
│       ├── package.json
│       ├── tsconfig.json
│       ├── wrangler.toml
│       └── README.md
│
├── schema/                       # 共通スキーマ定義
│   ├── video.schema.json
│   ├── match.schema.json
│   └── README.md
│
├── docs/                         # ドキュメント
│   ├── adr/
│   │   ├── 001-cloud-service-selection.md
│   │   ├── 002-data-storage-search.md
│   │   └── 003-repository-structure.md
│   ├── architecture.drawio
│   ├── setup-gcp.md
│   ├── setup-cloudflare.md
│   └── setup-local.md
│
├── .github/
│   └── workflows/
│       └── deploy-web.yml
│
├── .gitignore
├── LICENSE
└── README.md
```

### 5.2 各ディレクトリの責務

| ディレクトリ | 言語 | デプロイ先 | 責務 |
|-------------|------|-----------|------|
| `packages/local` | Python | ローカルPC | Pub/Sub監視、動画処理、Parquet生成、R2アップロード |
| `packages/gcp-functions` | Python | Cloud Functions | YouTube API監視、新動画検知、Pub/Sub発行 |
| `packages/web` | TypeScript | Cloudflare Pages | 閲覧UI、DuckDB-WASM、R2アクセスAPI |
| `schema` | JSON Schema | - | データ構造定義、バリデーション |
| `docs` | Markdown | - | ADR、セットアップ手順、設計資料 |

### 5.3 デプロイ設定

**Cloudflare Pages**
- ビルドコマンド: `cd packages/web && npm run build`
- 出力ディレクトリ: `packages/web/dist`
- Functions: `packages/web/functions`

**Google Cloud Functions**
```bash
cd packages/gcp-functions/check-new-video
gcloud functions deploy check-new-video \
  --runtime python311 \
  --trigger-http \
  --entry-point main
```

### 5.4 将来の見直し条件

以下の場合、構成の見直しを検討する：

1. **チームでの開発**になった場合
   - 各パッケージの責任者を明確化
   - CIの充実（lint、test、deploy）

2. **コンポーネントが大幅に増加**した場合
   - パッケージマネージャ（Turborepo等）の導入検討

3. **スキーマの複雑化**が進んだ場合
   - Protocol BuffersやAvroへの移行検討

## 6. 各選択肢の説明

### 選択肢A: マルチレポ（用途別に分割）

```
sf6-chapter-local/     # ローカルPC用
sf6-chapter-gcp/       # Cloud Functions用
sf6-chapter-web/       # Cloudflare Pages用
```

**不採用理由**:
- スキーマ定義の同期が困難（変更時に3リポジトリ更新が必要）
- ドキュメントが分散
- 個人プロジェクトでは管理オーバーヘッドが大きい

### 選択肢B: モノレポ（フラット構成）

```
sf6-chapter/
├── local/
├── gcp-functions/
├── web/
└── README.md
```

**不採用理由**:
- スキーマの配置場所が曖昧
- ドキュメントの整理方針が不明確
- 将来の拡張時に構造化が必要になる

### 選択肢C: モノレポ + 共通スキーマ構成（採用）

```
sf6-chapter/
├── packages/
│   ├── local/
│   ├── gcp-functions/
│   └── web/
├── schema/
├── docs/
└── README.md
```

**採用理由**:
- `packages/` で各コンポーネントを明確に分離
- `schema/` でデータ構造を一元管理
- `docs/` でドキュメントを集約
- Cloudflare Pagesのルート指定が容易

---

## 参考資料

- [Monorepo Explained](https://monorepo.tools/)
- [JSON Schema](https://json-schema.org/)
- [Cloudflare Pages - Monorepos](https://developers.cloudflare.com/pages/configuration/monorepos/)
