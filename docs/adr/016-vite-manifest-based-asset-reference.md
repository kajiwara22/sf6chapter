# ADR-016: Viteマニフェストを利用したクライアントサイドアセット参照

## ステータス

採用

## コンテキスト

Cloudflare Pages + Honoの構成で、サーバーサイドレンダリング（SSR）されたHTMLから、ViteでビルドされたクライアントサイドのJavaScriptを正しく参照する必要がある。

### 課題

1. **開発環境**: Viteが `/src/client/main.ts` を動的にトランスパイル
2. **本番環境**: Viteがビルド時にハッシュ付きファイル名（例: `/assets/main-V2yyVumV.js`）を生成
3. **ハッシュの可変性**: クライアントコードの変更ごとにハッシュ値が変わる
4. **両環境での動作保証**: 開発環境と本番環境の両方で正しく動作する必要がある

### 検討した選択肢

#### 選択肢A: 静的HTMLファイルとして配信

- **方法**: ビルド済み `index.html` をCloudflare Pagesの静的ファイルとして配信
- **利点**: シンプル、Viteが自動的にパスを解決
- **欠点**: サーバーサイドでの動的HTML生成ができない、開発環境でPages Functionsが動作しない

#### 選択肢B: 固定パスを使用

- **方法**: `/assets/main.js` のような固定パスを使用し、ビルド設定で固定化
- **利点**: 実装がシンプル
- **欠点**: キャッシュバスティングができない、ブラウザキャッシュの問題

#### 選択肢C: マニフェストファイルを利用（採用）

- **方法**: Viteが生成する `manifest.json` を読み込み、動的にアセットパスを解決
- **利点**: キャッシュバスティング対応、開発・本番両対応、サーバーサイドレンダリング可能
- **欠点**: ビルドプロセスが若干複雑

## 決定

**選択肢C: Viteマニフェストを利用した動的アセット参照**を採用する。

## 実装詳細

### ビルドプロセス

```bash
1. pnpm run build:client
   → dist/.vite/manifest.json 生成
   → dist/assets/main-{hash}.js 生成

2. pnpm run build:copy-manifest
   → dist/.vite/manifest.json を src/server/manifest.json にコピー

3. pnpm run build:server
   → src/server/manifest.json を読み込み
   → Pages Functions (_worker.js) にバンドル
```

### manifest.json の構造

```json
{
  "index.html": {
    "file": "assets/main-V2yyVumV.js",
    "name": "main",
    "src": "index.html",
    "isEntry": true
  }
}
```

### サーバーサイドの実装

```typescript
// src/server/routes/pages.tsx
import manifest from '../manifest.json';

pages.get('/', (c) => {
  // 開発環境判定
  const isDevelopment = typeof process !== 'undefined' &&
                        (!process.env.NODE_ENV || process.env.NODE_ENV === 'development');

  let scriptSrc = '/src/client/main.ts'; // 開発時のデフォルト

  // 本番環境の場合のみマニフェストを使用
  if (!isDevelopment) {
    try {
      if (manifest && manifest['index.html']) {
        scriptSrc = '/' + manifest['index.html'].file;
      }
    } catch {
      // マニフェストがない場合は開発用パスをフォールバック
    }
  }

  return c.html(html`
    <script type="module" src="${scriptSrc}"></script>
  `);
});
```

### package.json スクリプト

```json
{
  "scripts": {
    "build:client": "vite build --config vite.config.client.ts",
    "build:copy-manifest": "cp dist/.vite/manifest.json src/server/manifest.json",
    "build:server": "vite build --config vite.config.ts",
    "build": "pnpm run build:client && pnpm run build:copy-manifest && pnpm run build:server"
  }
}
```

## ハッシュの可変性

### ハッシュが変わるタイミング

クライアントサイドのコードが変更されると、ビルド時にファイルの内容ハッシュが再計算され、新しいファイル名が生成される。

**例**:
- 初回ビルド: `assets/main-V2yyVumV.js`
- コード変更後: `assets/main-DSkWrUVN.js`

### ハッシュが変わる要因

1. `/src/client/main.ts` やその依存ファイルの変更
2. TypeScript設定の変更
3. 依存ライブラリ（DuckDB-WASM等）のバージョンアップ
4. Viteビルド設定の変更

### 自動的に最新ハッシュが適用される仕組み

ビルドプロセスにより、以下が保証される：

1. `build:client` で新しいハッシュのファイルとマニフェストが生成
2. `build:copy-manifest` でマニフェストがサーバーコードに配置
3. `build:server` で最新マニフェストが `_worker.js` にバンドル
4. デプロイ時には常に最新のハッシュが使用される

## 環境別の動作

### 開発環境 (`pnpm run dev`)

- **判定条件**: `process.env.NODE_ENV` が未設定または `'development'`
- **動作**: `/src/client/main.ts` を参照
- **理由**: Viteが動的にトランスパイルするため、ソースファイルを直接参照

**確認コマンド**:
```bash
curl -s http://localhost:5173/ | grep '<script'
# 出力: <script type="module" src="/src/client/main.ts">
```

### 本番環境 (`pnpm run build` + デプロイ)

- **判定条件**: `process.env.NODE_ENV` が `'production'` または `process` が存在しない
- **動作**: `manifest.json` から取得したハッシュ付きパスを参照
- **理由**: ビルド済みアセットを参照し、ブラウザキャッシュを活用

**確認コマンド**:
```bash
curl -s https://fb38a0df.sf6-chapter.pages.dev/ | grep '<script'
# 出力: <script type="module" src="/assets/main-V2yyVumV.js">
```

### ローカルプレビュー (`pnpm run preview`)

- **判定条件**: Wranglerがビルド済みWorkerを実行するため本番と同じ
- **動作**: ビルド時のマニフェストに基づくハッシュ付きパスを参照

**確認コマンド**:
```bash
curl -s http://localhost:8788/ | grep '<script'
# 出力: <script type="module" src="/assets/main-V2yyVumV.js">
```

## 利点

1. **キャッシュバスティング**: ファイル内容が変わるとハッシュも変わり、ブラウザキャッシュの問題を回避
2. **環境透過性**: 開発環境と本番環境で同じコードベースが動作
3. **自動化**: ビルドプロセスで自動的に最新のハッシュが適用される
4. **SSR対応**: サーバーサイドでHTMLを動的生成可能
5. **型安全性**: TypeScriptのimportでマニフェストを読み込む

## 欠点

1. **ビルドプロセスの複雑性**: 3ステップのビルドが必要
2. **manifest.jsonの管理**: ソースコード内にビルド成果物（manifest.json）をコミットする必要がある
3. **環境判定ロジック**: `process.env.NODE_ENV` に依存する環境判定が必要

## 代替案との比較

| 項目 | 静的HTML配信 | 固定パス | マニフェスト（採用） |
|------|-------------|---------|---------------------|
| キャッシュバスティング | ○ | × | ○ |
| SSR対応 | × | ○ | ○ |
| 開発環境対応 | △ | ○ | ○ |
| 実装の複雑さ | 低 | 低 | 中 |
| 保守性 | 中 | 低 | 高 |

## 関連決定

- [ADR-009: Cloudflare PagesからWorkersへの段階的移行戦略](009-cloudflare-pages-to-workers-migration-strategy.md)
  - Pages Functionsを使用する前提

## 参考資料

- [Vite - Backend Integration](https://vitejs.dev/guide/backend-integration.html)
- [Vite - Build Manifest](https://vitejs.dev/guide/backend-integration.html#manifest-json)
- [Cloudflare Pages - Functions](https://developers.cloudflare.com/pages/functions/)

## 更新履歴

- 2026-01-10: 初版作成
