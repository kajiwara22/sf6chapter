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

### `GET /api/data/stats-manifest`

バックラー公開統計の manifest（`stats/manifest.json`、ADR-072）を取得。未配置なら 404。

### `GET /api/data/stats/:month/:kind`

バックラー統計 Parquet（`stats/{kind}/{YYYYMM}.parquet`）の Presigned URL を取得。
`kind` は `matchup_stats` / `matchup_details` / `character_usage`。

## タブ構成

| タブ | 主なデータ | 内容 |
|------|-----------|------|
| 対戦検索 | `matches` | 動画の対戦シーン検索 |
| マッチアップ | `battlelog_replays` | 相手キャラ・操作タイプ別の勝率（自キャラ指定時は同ランク帯平均も表示） |
| 対戦履歴 | `battlelog_replays` / `matches` | 試合単位の一覧（ラウンド結果・決まり手） |
| LP推移 | `battlelog_replays` | 試合開始時点の LP / MR の推移 |
| ラウンド分析 | `battlelog_replays` | 1R別・1P/2P別・3R勝率・決まり手（ADR-071） |

## クライアントサイドの仕組み

1. ページロード時に DuckDB-WASM を初期化
2. `/api/data/index/matches.parquet` から Parquet ファイルを取得
3. DuckDB-WASM にロードして SQL でクエリ
4. フォーム送信で検索条件を指定して再クエリ

### バックラー公開統計（ADR-072）

マッチアップタブで**自キャラを指定したとき**、`/api/data/stats-manifest` から最新データ月を得て
`matchup_stats` / `matchup_details` の Parquet を取得し、「バックラー平均」列を出す。

- 取得は初回の自キャラ指定時のみ（遅延読み込み）。失敗しても表は表示される
- 比較ランクは最新 LP から `getLeagueIdForLp` で推定する
- 既存の manifest キャッシュ（ADR-055）とは分離し、統計の更新で全キャッシュが無効化されないようにしている
- キャラ名の表記差（GOUKI/AKUMA、VEGA/M. BISON）は `shared/characters.ts` で吸収する

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
