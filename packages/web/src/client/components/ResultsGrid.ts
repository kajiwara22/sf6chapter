/**
 * SF6 Chapter - 検索結果グリッドコンポーネント
 */

import { DOM_IDS } from '../types';
import type { Match } from '@shared/types';

/**
 * 秒数を「分:秒」形式に変換
 */
function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * YouTube動画へのリンクを生成
 */
function createYouTubeLink(videoId: string, startTime: number): string {
  return `https://www.youtube.com/watch?v=${videoId}&t=${startTime}s`;
}

/**
 * 日付をフォーマット
 */
function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString('ja-JP', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

/**
 * 対戦カードのHTMLを生成
 */
function createMatchCard(match: Match): string {
  const youtubeLink = createYouTubeLink(match.videoId, match.startTime);

  return `
    <article class="match-card">
      <div class="match-header">
        <h3 class="video-title">${escapeHtml(match.videoTitle)}</h3>
        <span class="match-date">${formatDate(match.videoPublishedAt)}</span>
      </div>
      <div class="match-players">
        <div class="player player-1p">
          <span class="player-character">${escapeHtml(match.player1.character)}</span>
          <span class="player-side">1P</span>
        </div>
        <div class="match-vs">VS</div>
        <div class="player player-2p">
          <span class="player-character">${escapeHtml(match.player2.character)}</span>
          <span class="player-side">2P</span>
        </div>
      </div>
      <div class="match-meta">
        <span class="match-time">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
          ${formatTime(match.startTime)}
        </span>
      </div>
      <a href="${youtubeLink}" target="_blank" rel="noopener" class="match-link">
        <svg class="icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
        </svg>
        動画で見る
      </a>
    </article>
  `;
}

/**
 * HTMLエスケープ
 */
function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * 検索結果を表示
 */
export function renderResults(matches: Match[]): void {
  const container = document.getElementById(DOM_IDS.RESULTS);
  const noResults = document.getElementById(DOM_IDS.NO_RESULTS);

  if (!container || !noResults) {
    console.error('[ResultsGrid] Container elements not found');
    return;
  }

  if (matches.length === 0) {
    container.innerHTML = '';
    noResults.style.display = 'block';
    return;
  }

  noResults.style.display = 'none';
  container.innerHTML = matches.map(createMatchCard).join('');
}

/**
 * 検索結果をクリア
 */
export function clearResults(): void {
  const container = document.getElementById(DOM_IDS.RESULTS);
  const noResults = document.getElementById(DOM_IDS.NO_RESULTS);

  if (container) {
    container.innerHTML = '';
  }
  if (noResults) {
    noResults.style.display = 'none';
  }
}
