/**
 * SF6 Chapter - 統計パネルコンポーネント
 */

import { DOM_IDS } from '../types';
import type { Stats } from '@shared/types';

/**
 * 統計カードのHTMLを生成
 */
function createStatCard(value: string | number, label: string, icon: string): string {
  return `
    <div class="stat-card">
      <div class="stat-icon">${icon}</div>
      <div class="stat-content">
        <span class="stat-value">${value}</span>
        <span class="stat-label">${label}</span>
      </div>
    </div>
  `;
}

/**
 * 数値をフォーマット
 */
function formatNumber(num: number): string {
  return num.toLocaleString('ja-JP');
}

/**
 * 統計情報を表示
 */
export function renderStats(stats: Stats): void {
  const container = document.getElementById(DOM_IDS.STATS);

  if (!container) {
    console.error('[StatsPanel] Container not found');
    return;
  }

  // 上位5キャラクターを取得
  const topCharacters = Object.entries(stats.characterCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  const topCharacterText = topCharacters.length > 0
    ? topCharacters.map(([char]) => char).join(', ')
    : '-';

  const html = `
    ${createStatCard(
      formatNumber(stats.totalMatches),
      '総対戦数',
      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
        <circle cx="9" cy="7" r="4"/>
        <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
        <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
      </svg>`
    )}
    ${createStatCard(
      formatNumber(stats.totalVideos),
      '動画数',
      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="23 7 16 12 23 17 23 7"/>
        <rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
      </svg>`
    )}
    ${createStatCard(
      topCharacterText,
      'よく使うキャラ',
      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
      </svg>`
    )}
  `;

  container.innerHTML = html;
}

/**
 * 統計をクリア
 */
export function clearStats(): void {
  const container = document.getElementById(DOM_IDS.STATS);
  if (container) {
    container.innerHTML = '';
  }
}
