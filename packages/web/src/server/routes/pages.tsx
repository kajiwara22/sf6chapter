/**
 * SF6 Chapter - ページルート
 * Hono JSXでHTMLを生成
 */

import { Hono } from 'hono';
import { html } from 'hono/html';
// @ts-ignore - manifest.jsonは本番ビルド時に生成される
import manifest from '../manifest.json';

const pages = new Hono();

/**
 * GET /
 * メインページ
 *
 * 開発時: Viteが /src/client/main.ts を自動変換
 * 本番時: manifest.jsonからビルド済みアセットのパスを取得
 */
pages.get('/', (c) => {
  // 開発環境判定
  // Vite開発サーバー経由の場合は NODE_ENV が設定されていない、または 'development'
  // Cloudflare Pages本番環境では process が存在しないか、NODE_ENV が 'production'
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

  return c.html(
    html`<!DOCTYPE html>
    <html lang="ja">
      <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>SF6 Chapter - 対戦検索</title>
        <link rel="stylesheet" href="/static/main.css" />
      </head>
      <body>
        <div class="app">
          <header class="header">
            <div class="header-content">
              <h1 class="logo">
                <span class="logo-sf6">SF6</span>
                <span class="logo-chapter">Chapter</span>
              </h1>
              <p class="tagline">対戦動画を素早く検索</p>
            </div>
          </header>

          <main class="main">
            <!-- 検索セクション -->
            <section class="search-section">
              <form id="search-form" class="search-form">
                <div class="form-row">
                  <div class="form-group">
                    <label for="character-select">キャラクター</label>
                    <select id="character-select" name="character">
                      <option value="">すべて</option>
                      <!-- DuckDB-WASMで動的に生成 -->
                    </select>
                  </div>

                  <div class="form-group">
                    <label for="date-from">期間（開始）</label>
                    <input type="date" id="date-from" name="dateFrom" />
                  </div>

                  <div class="form-group">
                    <label for="date-to">期間（終了）</label>
                    <input type="date" id="date-to" name="dateTo" />
                  </div>

                  <div class="form-group form-group-button">
                    <button type="submit" class="btn-search">
                      検索
                    </button>
                  </div>
                </div>
              </form>
            </section>

            <!-- ステータス表示 -->
            <section class="status-section">
              <div id="loading" class="status-message status-loading" style="display: none;">
                <span class="spinner"></span>
                データを読み込み中...
              </div>
              <div id="error" class="status-message status-error" style="display: none;"></div>
            </section>

            <!-- 統計情報 -->
            <section class="stats-section">
              <div id="stats" class="stats-grid">
                <!-- JavaScriptで動的に挿入 -->
              </div>
            </section>

            <!-- 検索結果 -->
            <section class="results-section">
              <h2 class="section-title">対戦一覧</h2>
              <div id="results" class="results-grid">
                <!-- JavaScriptで動的に挿入 -->
              </div>
              <div id="no-results" class="status-message" style="display: none;">
                検索結果がありません
              </div>
            </section>
          </main>

          <footer class="footer">
            <p>
              SF6 Chapter - Powered by
              <a href="https://duckdb.org/docs/api/wasm" target="_blank" rel="noopener">DuckDB-WASM</a>
              /
              <a href="https://hono.dev" target="_blank" rel="noopener">Hono</a>
              /
              <a href="https://www.cloudflare.com" target="_blank" rel="noopener">Cloudflare</a>
            </p>
          </footer>
        </div>

        <!-- クライアントサイドスクリプト -->
        <script type="module" src="${scriptSrc}"></script>
      </body>
    </html>`
  );
});

export { pages };
