# SF6 Chapter - プロジェクト概要

## このプロジェクトについて

SF6（ストリートファイター6）のYouTube配信動画から対戦シーンを自動検出し、YouTubeチャプターを生成するシステム。

## アーキテクチャ

**Google Cloud + Cloudflare ハイブリッド構成**を採用。

```
[Google Cloud]
Cloud Scheduler (2時間毎)
    → Cloud Functions (新動画検知、OAuth2認証、Firestore重複防止)
    → Cloud Pub/Sub (メッセージキュー、7日間保持)

[ローカルPC]
Python常駐スクリプト
    → Pub/SubからPull
    → yt-dlpで動画ダウンロード
    → OpenCVでフレーム抽出・テンプレートマッチング
    → Gemini APIでキャラクター認識
    → YouTube Data APIでチャプター更新
    → Cloudflare R2へJSON/Parquetアップロード

[Cloudflare]
R2 (ストレージ、非公開)
    → Pages Functions (Hono) - APIエンドポイント
    → DuckDB-WASMでParquetをクエリ
    → Pages (静的サイト) - フロントエンド
    → Access (認証)
```

**注**: Cloudflare部分は現在Pages Functionsを使用していますが、将来的にWorkersへの移行可能性があります。詳細は[ADR-009](docs/adr/009-cloudflare-pages-to-workers-migration-strategy.md)を参照。

## 技術選定の理由

詳細は `docs/adr/` を参照。

- **Google Cloud**: YouTube/Gemini APIとの親和性、Pub/Subの信頼性
- **Cloudflare Pages**: R2の無料エグレス、Accessの簡便な認証、Git連携CI/CD、自動プレビュー環境
- **Hono**: 軽量なWebフレームワーク、Pages/Workers両対応、TypeScript完全サポート
- **Parquet + DuckDB-WASM**: 高速検索、柔軟なSQLクエリ、R2非公開との両立
- **ローカルPC処理**: コスト$0、重い処理をクラウドに依存しない

## リポジトリ構成

```
sf6-chapter/
├── packages/
│   ├── local/                # ローカルPC用Python (uv)
│   ├── gcp-functions/        # Google Cloud Functions
│   └── web/                  # Cloudflare Pages + Functions
├── schema/                   # 共通JSONスキーマ
├── docs/
│   ├── adr/                  # アーキテクチャ決定記録
│   └── *.md                  # セットアップ手順等
└── CLAUDE.md                 # このファイル
```

## 現在のステータス

- [x] アーキテクチャ設計完了
- [x] ADR作成（001〜013）
- [x] スキーマ定義 (`schema/`)
- [x] ローカル処理実装 (`packages/local/`)
- [x] ローカル処理のDocker化（ADR-013）
- [x] GCP Functions実装 (`packages/gcp-functions/`)
- [x] Firestore統合による重複防止
- [x] OAuth2認証実装（ローカル＋Cloud Functions）
- [x] Cloud Scheduler 2時間間隔最適化
- [x] Webフロントエンド基本実装 (`packages/web/`)
- [x] Pages Functions APIエンドポイント実装（Presigned URL方式）
- [ ] R2へのテストデータアップロード
- [ ] ローカルでの統合テスト
- [ ] Cloudflare Pagesデプロイ

## 次のタスク

1. **R2テストデータ準備**: ローカル処理でサンプルParquetを生成しR2にアップロード
2. **ローカル統合テスト**: Pages Functions + フロントエンドの動作確認
3. **Cloudflare Pagesデプロイ**: 本番環境へのデプロイとCloudflare Access設定

## 重要な設計判断

### 処理フロー

- **Cloud Scheduler**: 2時間毎に実行（API quota効率化）
- **Firestore**: 処理済み動画の追跡、重複防止
- **Pub/Sub**: 7日間保持、ローカルPC停止中も検知漏れなし

### データ構造

- JSONファイルを累積保存（生データ保全）
- Parquetファイルを都度更新（検索用）
- R2は完全非公開、Presigned URL経由でParquetをフロントエンドに配信
- Presigned URL有効期限: 1時間（詳細: [ADR-010](docs/adr/010-parquet-presigned-url.md)）

### 中間ファイル保存（人間確認用）

- **目的**: 自動検出・認識の誤検知を人間が確認・修正できるようにする
- **保存先**: `./intermediate/{video_id}/` （環境変数 `INTERMEDIATE_DIR` で変更可能）
- **保存内容**:
  - `detection_summary.json` - 検出サマリー（タイムスタンプ、信頼度など）
  - `frame_XXX_YYYs.png` - 検出フレーム画像（視覚的確認用）
  - `video_data.json` / `matches.json` / `chapters.json` - 最終結果データ
- **対象モード**: すべての実行モード（常駐/ワンショット/テスト）
- **詳細**: [ADR-011](docs/adr/011-intermediate-file-preservation.md)

### キャラクター名

- Gemini APIの認識結果にブレがあるため正規化テーブルを用意
- `config/character_aliases.json` で管理

### 認証

#### Google Cloud API

- **すべてのAPI呼び出しでOAuth2認証を使用** (詳細: `docs/adr/004-oauth2-authentication-for-all-gcp-apis.md`)
- `oauth.py` の `get_oauth_credentials()` で統一的に認証情報を取得
- 環境変数 `GOOGLE_APPLICATION_CREDENTIALS` は使用しない
- 対象API: YouTube Data API, Cloud Pub/Sub, Vertex AI (Gemini)
- トークンは `token.pickle` に保存（pickle形式、パスは引数で変更可能）
- クライアントシークレットは `client_secrets.json` から読み込み（パスは引数で変更可能）

#### Cloudflare R2

- **ローカルPC処理**: R2バケット専用APIトークンをSHA-256ハッシュ化してS3互換アクセス
- **Pages Functions**: R2 Bindingsで安全にアクセス
- Cloudflare Accessで自分のメールアドレスのみ許可
- R2への直接公開アクセスは不可

**詳細**: [ADR-005](docs/adr/005-r2-bucket-specific-api-token.md)

## 関連リソース

- 既存リポジトリ: https://github.com/kajiwara22/sf6chapter
- 構成図: `docs/architecture.drawio`

## 開発時の注意

- **Python**: uvを使用 (`uv sync`, `uv run`)
- **Docker**: ローカル処理のDocker化対応（詳細: [ADR-013](docs/adr/013-local-package-dockerization.md)）
- **Node.js**: pnpm使用
- **Cloudflare**: wrangler CLI使用、Pages Functionsで実装
- **GCP**: gcloud CLI使用
- **設計方針**: Cloudflare Workersへの将来的な移行を想定し、Pages固有機能への依存を最小化（詳細: [ADR-009](docs/adr/009-cloudflare-pages-to-workers-migration-strategy.md)）

## ローカル処理のデプロイ方法

`packages/local/`は開発PC・常駐PCのどちらでも動作可能です。

### 開発PC（uvを使用）

```bash
cd packages/local
uv sync
uv run python main.py --mode daemon
```

### 常駐PC（Dockerを使用、推奨）

```bash
cd packages/local
docker compose up -d
```

**詳細**: [DEPLOYMENT.md](packages/local/DEPLOYMENT.md)を参照

## ドキュメント管理

### ADR (Architecture Decision Records)

**管理場所**: `/docs/adr/`

重要なアーキテクチャ決定はすべて `/docs/adr/` に記録します。

**既存のADR**:
- [001: クラウドサービス選定](docs/adr/001-cloud-service-selection.md)
- [002: データ保存・検索基盤](docs/adr/002-data-storage-search.md)
- [003: リポジトリ構成](docs/adr/003-repository-structure.md)
- [004: OAuth2認証の統一](docs/adr/004-oauth2-authentication-for-all-gcp-apis.md)
- [005: R2バケット専用APIトークン](docs/adr/005-r2-bucket-specific-api-token.md)
- [006: Firestoreによる重複防止](docs/adr/006-firestore-for-duplicate-prevention.md)
- [007: Cloud Scheduler実行間隔最適化](docs/adr/007-cloud-scheduler-interval-optimization.md)
- [008: Cloud FunctionsでのOAuth2ユーザー認証](docs/adr/008-oauth2-user-authentication-in-cloud-functions.md)
- [009: Cloudflare PagesからWorkersへの段階的移行戦略](docs/adr/009-cloudflare-pages-to-workers-migration-strategy.md)
- [010: Parquetデータ取得方式（Presigned URL）](docs/adr/010-parquet-presigned-url.md)
- [011: 中間ファイル保存による人間確認フロー](docs/adr/011-intermediate-file-preservation.md)
- [012: check-new-video Cloud Function専用サービスアカウントの採用](docs/adr/012-check-new-video-dedicated-service-account.md)
- [013: ローカル処理パッケージのDocker化](docs/adr/013-local-package-dockerization.md)
- [014: Cloud FunctionのOIDC認証による保護](docs/adr/014-cloud-function-oidc-authentication.md)

新しいアーキテクチャ決定を記録する際は、`docs/adr/` ディレクトリに連番でファイルを追加してください。
