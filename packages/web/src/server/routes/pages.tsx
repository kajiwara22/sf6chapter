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
            <!-- タブナビゲーション -->
            <nav class="tab-nav">
              <button id="tab-search" class="tab-btn tab-btn-active" data-view="view-search">対戦検索</button>
              <button id="tab-matchup" class="tab-btn" data-view="view-matchup">マッチアップ</button>
              <button id="tab-history" class="tab-btn" data-view="view-history">対戦履歴</button>
            </nav>

            <!-- ========== 対戦検索ビュー ========== -->
            <div id="view-search" class="tab-view tab-view-active">

            <!-- 検索セクション -->
            <section class="search-section">
              <form id="search-form" class="search-form">
                <div class="form-row">
                  <div class="form-group">
                    <label for="character-select">キャラクター1</label>
                    <select id="character-select" name="character">
                      <option value="">すべて</option>
                    </select>
                  </div>

                  <div class="form-group">
                    <label for="character-select-2">キャラクター2（オプション）</label>
                    <select id="character-select-2" name="character2">
                      <option value="">指定しない</option>
                    </select>
                  </div>

                  <div class="form-group">
                    <label for="video-title">タイトル検索</label>
                    <input type="text" id="video-title" name="videoTitle" placeholder="動画タイトルを検索..." />
                  </div>
                </div>

                <div class="form-row">
                  <div class="form-group">
                    <label for="date-from">期間（開始）</label>
                    <input type="date" id="date-from" name="dateFrom" />
                  </div>

                  <div class="form-group">
                    <label for="date-to">期間（終了）</label>
                    <input type="date" id="date-to" name="dateTo" />
                  </div>

                  <div class="form-group">
                    <label for="sort-by">並び順</label>
                    <select id="sort-by" name="sortBy">
                      <option value="publishedAt_desc">公開日（新しい順）</option>
                      <option value="publishedAt_asc">公開日（古い順）</option>
                      <option value="confidence_desc">信頼度（高い順）</option>
                    </select>
                  </div>
                </div>

                <div class="form-row">
                  <div class="form-group">
                    <label for="player-result">
                      Result<span id="player-result-context"></span>
                    </label>
                    <select id="player-result" name="playerResult">
                      <option value="">All</option>
                      <option value="win">Wins</option>
                      <option value="loss">Loses</option>
                    </select>
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
              </div>
            </section>

            <!-- 検索結果 -->
            <section class="results-section">
              <h2 class="section-title">対戦一覧</h2>
              <div id="results" class="results-grid">
              </div>
              <div id="no-results" class="status-message" style="display: none;">
                検索結果がありません
              </div>
            </section>

            </div><!-- /view-search -->

            <!-- ========== マッチアップチャートビュー ========== -->
            <div id="view-matchup" class="tab-view">

            <!-- マッチアップフィルター -->
            <section class="search-section">
              <form id="matchup-form" class="search-form">
                <div class="form-row">
                  <div class="form-group">
                    <label for="matchup-my-character">自キャラクター</label>
                    <select id="matchup-my-character" name="myCharacter">
                      <option value="">すべて</option>
                    </select>
                  </div>

                  <div class="form-group">
                    <label for="matchup-battle-type">マッチタイプ</label>
                    <select id="matchup-battle-type" name="battleType">
                      <option value="0">All</option>
                      <option value="1">Ranked</option>
                      <option value="3">Battle Hub</option>
                      <option value="4">Custom Room</option>
                    </select>
                  </div>
                </div>

                <div class="form-row">
                  <div class="form-group">
                    <label for="matchup-date-from">期間（開始）</label>
                    <div class="date-time-group">
                      <input type="date" id="matchup-date-from" name="dateFrom" />
                      <input type="time" id="matchup-time-from" name="timeFrom" />
                    </div>
                  </div>

                  <div class="form-group">
                    <label for="matchup-date-to">期間（終了）</label>
                    <div class="date-time-group">
                      <input type="date" id="matchup-date-to" name="dateTo" />
                      <input type="time" id="matchup-time-to" name="timeTo" />
                    </div>
                  </div>

                  <div class="form-group form-group-button">
                    <button type="submit" class="btn-search">
                      集計
                    </button>
                  </div>
                </div>
              </form>
            </section>

            <!-- マッチアップチャート ステータス -->
            <section class="status-section">
              <div id="matchup-loading" class="status-message status-loading" style="display: none;">
                <span class="spinner"></span>
                集計中...
              </div>
              <div id="matchup-error" class="status-message status-error" style="display: none;"></div>
            </section>

            <!-- マッチアップチャート -->
            <section class="matchup-section">
              <h2 class="section-title">マッチアップチャート</h2>
              <div id="matchup-chart">
              </div>
            </section>

            </div><!-- /view-matchup -->

            <!-- ========== 対戦履歴ビュー ========== -->
            <div id="view-history" class="tab-view">

            <!-- 対戦履歴フィルター -->
            <section class="search-section">
              <form id="history-form" class="search-form">
                <div class="form-row">
                  <div class="form-group">
                    <label for="history-my-character">自キャラクター</label>
                    <select id="history-my-character" name="myCharacter">
                      <option value="">すべて</option>
                    </select>
                  </div>

                  <div class="form-group">
                    <label for="history-my-input-type">自操作タイプ</label>
                    <select id="history-my-input-type" name="myInputType">
                      <option value="">すべて</option>
                      <option value="0">Classic</option>
                      <option value="1">Modern</option>
                    </select>
                  </div>

                  <div class="form-group">
                    <label for="history-opponent-character">相手キャラクター</label>
                    <select id="history-opponent-character" name="opponentCharacter">
                      <option value="">すべて</option>
                    </select>
                  </div>

                  <div class="form-group">
                    <label for="history-opponent-input-type">相手操作タイプ</label>
                    <select id="history-opponent-input-type" name="opponentInputType">
                      <option value="">すべて</option>
                      <option value="0">Classic</option>
                      <option value="1">Modern</option>
                    </select>
                  </div>

                  <div class="form-group">
                    <label for="history-battle-type">マッチタイプ</label>
                    <select id="history-battle-type" name="battleType">
                      <option value="0">All</option>
                      <option value="1">Ranked</option>
                      <option value="3">Battle Hub</option>
                      <option value="4">Custom Room</option>
                    </select>
                  </div>
                </div>

                <div class="form-row">
                  <div class="form-group">
                    <label for="history-date-from">期間（開始）</label>
                    <div class="date-time-group">
                      <input type="date" id="history-date-from" name="dateFrom" />
                      <input type="time" id="history-time-from" name="timeFrom" />
                    </div>
                  </div>

                  <div class="form-group">
                    <label for="history-date-to">期間（終了）</label>
                    <div class="date-time-group">
                      <input type="date" id="history-date-to" name="dateTo" />
                      <input type="time" id="history-time-to" name="timeTo" />
                    </div>
                  </div>

                  <div class="form-group form-group-button">
                    <button type="submit" class="btn-search">
                      絞り込み
                    </button>
                  </div>
                </div>
              </form>
            </section>

            <!-- 対戦履歴 ステータス -->
            <section class="status-section">
              <div id="history-loading" class="status-message status-loading" style="display: none;">
                <span class="spinner"></span>
                読み込み中...
              </div>
              <div id="history-error" class="status-message status-error" style="display: none;"></div>
            </section>

            <!-- 対戦履歴テーブル -->
            <section class="history-section">
              <h2 class="section-title">対戦履歴</h2>
              <div id="history-table"></div>
              <div id="history-pagination"></div>
            </section>

            </div><!-- /view-history -->

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
