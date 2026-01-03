# SF6 Chapter - Web Application

Hono + TypeScript + DuckDB-WASM で構築した SF6 対戦検索 Web アプリケーション。

## 技術スタック

- **サーバーサイド**: Hono (JSX) + Cloudflare Pages Functions
- **クライアントサイド**: TypeScript + DuckDB-WASM
- **ストレージ**: Cloudflare R2
- **ビルド**: Vite
- **デプロイ**: Cloudflare Pages

## ディレクトリ構成

```
packages/web/
├── src/
│   ├── server/                    # サーバーサイド（Hono）
│   │   ├── index.tsx              # Honoアプリのエントリーポイント
│   │   ├── routes/
│   │   │   ├── api.ts             # APIルート（R2アクセス）
│   │   │   └── pages.tsx          # ページルート（JSX）
│   │   └── types.ts               # Bindings型定義
│   │
│   ├── client/                    # クライアントサイド
│   │   ├── main.ts                # エントリーポイント
│   │   ├── search.ts              # DuckDB-WASM検索ロジック
│   │   ├── components/            # UIコンポーネント
│   │   │   ├── SearchForm.ts
│   │   │   ├── ResultsGrid.ts
│   │   │   └── StatsPanel.ts
│   │   └── types.ts               # クライアント型定義
│   │
│   ├── shared/                    # サーバー・クライアント共通
│   │   └── types.ts               # データ型定義
│   │
│   └── styles/
│       └── main.css               # スタイル
│
├── public/                        # 静的アセット
├── package.json
├── tsconfig.json
├── vite.config.ts
└── wrangler.toml
```

## 開発環境セットアップ

### 依存関係のインストール

```bash
pnpm install
```

### ローカル R2 テストデータの準備

```bash
# Python + PyArrow でテストデータ生成
python3 scripts/upload-test-data.py
```

### 開発サーバー起動

```bash
pnpm dev
```

ブラウザで http://localhost:5173 を開きます。

## ビルド & デプロイ

```bash
# ビルド
pnpm build

# デプロイ
pnpm deploy
```

## API エンドポイント

### `GET /api/health`

ヘルスチェック。

### `GET /api/data/index/matches.parquet`

対戦データの Parquet ファイルを取得。

### `GET /api/data/index/videos.parquet`

動画データの Parquet ファイルを取得。

### `GET /api/data/videos/:filename`

生 JSON ファイルを取得（デバッグ用）。

## クライアントサイドの仕組み

1. ページロード時に DuckDB-WASM を初期化
2. `/api/data/index/matches.parquet` から Parquet ファイルを取得
3. DuckDB-WASM にロードして SQL でクエリ
4. フォーム送信で検索条件を指定して再クエリ

```typescript
// 検索クエリ例
const matches = await searchMatches({
  character: 'JP',
  dateFrom: '2024-12-01',
  dateTo: '2024-12-31',
});
```

## 型定義の共有

`src/shared/types.ts` にデータ型を定義し、サーバー・クライアント両方から参照できます。

```typescript
import type { Match, Video, SearchFilters } from '@shared/types';
```

## 参考資料

- [Hono ドキュメント](https://hono.dev/)
- [DuckDB-WASM ドキュメント](https://duckdb.org/docs/api/wasm/overview)
- [Cloudflare Pages Functions](https://developers.cloudflare.com/pages/functions/)
- [@hono/vite-build](https://github.com/honojs/vite-plugins)
