# SF6 Chapter - プロジェクト概要

## このプロジェクトについて

SF6（ストリートファイター6）のYouTube配信動画から対戦シーンを自動検出し、YouTubeチャプターを生成するシステム。

## アーキテクチャ

**Google Cloud + Cloudflare ハイブリッド構成**を採用。

```
[Google Cloud]
Cloud Scheduler (15分毎)
    → Cloud Functions (新動画検知)
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
    → Pages Functions経由でアクセス
    → DuckDB-WASMでParquetをクエリ
    → Pages (静的サイト)
    → Access (認証)
```

## 技術選定の理由

詳細は `docs/adr/` を参照。

- **Google Cloud**: YouTube/Gemini APIとの親和性、Pub/Subの信頼性
- **Cloudflare**: R2の無料エグレス、Accessの簡便な認証、Pagesの開発体験
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
- [x] ADR作成（001〜003）
- [ ] スキーマ定義 (`schema/`)
- [ ] ローカル処理実装 (`packages/local/`)
- [ ] GCP Functions実装 (`packages/gcp-functions/`)
- [ ] Webフロントエンド実装 (`packages/web/`)

## 次のタスク

1. **スキーマ定義**: `schema/video.schema.json`, `schema/match.schema.json` を作成
2. **各パッケージの初期化**: `pyproject.toml`, `package.json`, `wrangler.toml`
3. **既存コードの移行**: https://github.com/kajiwara22/sf6chapter から `packages/local/` へ

## 重要な設計判断

### データ構造

- JSONファイルを累積保存（生データ保全）
- Parquetファイルを都度更新（検索用）
- R2は完全非公開、Pages Functions経由でのみアクセス

### キャラクター名

- Gemini APIの認識結果にブレがあるため正規化テーブルを用意
- `config/character_aliases.json` で管理

### 認証

- Cloudflare Accessで自分のメールアドレスのみ許可
- R2への直接アクセスは不可

## 関連リソース

- 既存リポジトリ: https://github.com/kajiwara22/sf6chapter
- 構成図: `docs/architecture.drawio`

## 開発時の注意

- Python: uvを使用 (`uv sync`, `uv run`)
- Node: pnpm使用
- Cloudflare: wrangler CLI使用
- GCP: gcloud CLI使用
