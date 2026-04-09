/**
 * SF6 Chapter - 対戦履歴コンポーネント
 */

import { DOM_IDS } from '../types';
import type { MatchHistoryRow, MatchHistoryFilters } from '@shared/types';

export type MatchHistoryFilterHandler = (filters: MatchHistoryFilters) => void;

/** 入力タイプ名のマッピング */
const INPUT_TYPE_NAMES: Record<number, string> = {
  0: 'Classic',
  1: 'Modern',
};

/**
 * HTMLエスケープ
 */
function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * 入力タイプのバッジHTMLを生成
 */
function createInputTypeBadge(inputType: number): string {
  const label = INPUT_TYPE_NAMES[inputType] ?? String(inputType);
  if (inputType === 0) {
    return `<span class="input-badge input-badge-classic" title="${label}">C</span>`;
  } else if (inputType === 1) {
    return `<span class="input-badge input-badge-modern" title="${label}">M</span>`;
  }
  return `<span class="input-badge">${escapeHtml(label)}</span>`;
}

/**
 * 勝敗バッジHTMLを生成
 */
function createResultBadge(result: 'win' | 'loss' | 'draw'): string {
  if (result === 'win') {
    return `<span class="result-badge result-badge-win">WIN</span>`;
  } else if (result === 'loss') {
    return `<span class="result-badge result-badge-loss">LOSS</span>`;
  }
  return `<span class="result-badge result-badge-draw">DRAW</span>`;
}

/**
 * DuckDBのTIMESTAMP値（Unixミリ秒数値文字列 or ISO文字列）をDateに変換
 */
function parseUploadedAt(dateStr: string): Date {
  const raw = Number(dateStr);
  return Number.isFinite(raw) && raw > 1e12 ? new Date(raw) : new Date(dateStr);
}

/**
 * JST絶対日時表示を生成（例: "2026/04/09 01:27"）
 */
function formatAbsoluteTime(dateStr: string): string {
  const date = parseUploadedAt(dateStr);
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  const y = jst.getUTCFullYear();
  const mo = String(jst.getUTCMonth() + 1).padStart(2, '0');
  const d = String(jst.getUTCDate()).padStart(2, '0');
  const h = String(jst.getUTCHours()).padStart(2, '0');
  const mi = String(jst.getUTCMinutes()).padStart(2, '0');
  return `${y}/${mo}/${d} ${h}:${mi}`;
}

/**
 * YouTubeリンクまたはリプレイIDテキストを生成
 */
function createReplayCell(row: MatchHistoryRow): string {
  const shortId = escapeHtml(row.replayId.slice(-8));
  if (row.videoId && row.startTime != null) {
    const url = `https://www.youtube.com/watch?v=${encodeURIComponent(row.videoId)}&t=${row.startTime}s`;
    return `<a href="${url}" target="_blank" rel="noopener" class="replay-youtube-link" title="YouTubeで視聴">
      <svg class="yt-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
        <path fill="#FF0000" d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5a3 3 0 0 0-2.1 2.1C0 8.1 0 12 0 12s0 3.9.5 5.8a3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1C24 15.9 24 12 24 12s0-3.9-.5-5.8z"/>
        <path fill="#fff" d="M9.6 15.6V8.4l6.3 3.6-6.3 3.6z"/>
      </svg>
      ${shortId}
    </a>`;
  }
  return `<span class="replay-id-text" title="${escapeHtml(row.replayId)}">${shortId}</span>`;
}

/**
 * 対戦履歴テーブルのHTMLを生成
 */
function createHistoryTable(rows: MatchHistoryRow[]): string {
  if (rows.length === 0) {
    return '<p class="history-empty">データがありません</p>';
  }

  const tableRows = rows.map((row) => `
    <tr class="history-row">
      <td class="history-my-character">${escapeHtml(row.myCharacter)}</td>
      <td class="history-my-input">${createInputTypeBadge(row.myInputType)}</td>
      <td class="history-result">${createResultBadge(row.result)}</td>
      <td class="history-opponent-name" title="${escapeHtml(row.opponentName)}">${escapeHtml(row.opponentName.slice(0, 16))}${row.opponentName.length > 16 ? '…' : ''}</td>
      <td class="history-opponent-character">${escapeHtml(row.opponentCharacter)}</td>
      <td class="history-opponent-input">${createInputTypeBadge(row.opponentInputType)}</td>
      <td class="history-battle-type">${escapeHtml(row.battleTypeName)}</td>
      <td class="history-replay">${createReplayCell(row)}</td>
      <td class="history-date">${escapeHtml(formatAbsoluteTime(row.uploadedAt))}</td>
    </tr>
  `).join('');

  return `
    <table class="history-table">
      <thead>
        <tr>
          <th>使用キャラ</th>
          <th>操作</th>
          <th>勝負</th>
          <th>相手名</th>
          <th>相手キャラ</th>
          <th>相手操作</th>
          <th>モード</th>
          <th>リプレイ</th>
          <th>試合日</th>
        </tr>
      </thead>
      <tbody>
        ${tableRows}
      </tbody>
    </table>
  `;
}

/**
 * 対戦履歴テーブルを表示
 */
export function renderMatchHistory(rows: MatchHistoryRow[]): void {
  const container = document.getElementById(DOM_IDS.HISTORY_TABLE);
  if (!container) {
    console.error('[MatchHistory] Container not found');
    return;
  }
  container.innerHTML = createHistoryTable(rows);
}

/**
 * 対戦履歴テーブルをクリア
 */
export function clearMatchHistory(): void {
  const container = document.getElementById(DOM_IDS.HISTORY_TABLE);
  if (container) {
    container.innerHTML = '';
  }
}

/**
 * ページネーションを表示
 */
export function renderHistoryPagination(currentPage: number, hasNext: boolean, onPageChange: (page: number) => void): void {
  const container = document.getElementById(DOM_IDS.HISTORY_PAGINATION);
  if (!container) return;

  const prevDisabled = currentPage === 0 ? 'disabled' : '';
  const nextDisabled = !hasNext ? 'disabled' : '';

  container.innerHTML = `
    <div class="pagination">
      <button class="pagination-btn" id="history-prev-btn" ${prevDisabled}>← 前のページ</button>
      <span class="pagination-page">${currentPage + 1} ページ目</span>
      <button class="pagination-btn" id="history-next-btn" ${nextDisabled}>次のページ →</button>
    </div>
  `;

  const prevBtn = document.getElementById('history-prev-btn') as HTMLButtonElement | null;
  const nextBtn = document.getElementById('history-next-btn') as HTMLButtonElement | null;

  if (prevBtn && currentPage > 0) {
    prevBtn.addEventListener('click', () => onPageChange(currentPage - 1));
  }
  if (nextBtn && hasNext) {
    nextBtn.addEventListener('click', () => onPageChange(currentPage + 1));
  }
}

/**
 * 対戦履歴フォームを初期化
 */
export function initHistoryForm(onFilter: MatchHistoryFilterHandler): void {
  const form = document.getElementById(DOM_IDS.HISTORY_FORM) as HTMLFormElement | null;
  if (!form) {
    console.error('[MatchHistory] Form not found');
    return;
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const formData = new FormData(form);

    const myInputTypeStr = formData.get('myInputType') as string;
    const opponentInputTypeStr = formData.get('opponentInputType') as string;
    const battleTypeStr = formData.get('battleType') as string;

    const filters: MatchHistoryFilters = {
      myCharacter: (formData.get('myCharacter') as string) || undefined,
      myInputType: myInputTypeStr !== '' ? Number(myInputTypeStr) : undefined,
      opponentCharacter: (formData.get('opponentCharacter') as string) || undefined,
      opponentInputType: opponentInputTypeStr !== '' ? Number(opponentInputTypeStr) : undefined,
      battleType: Number(battleTypeStr) || undefined,
      dateFrom: (formData.get('dateFrom') as string) || undefined,
      dateTo: (formData.get('dateTo') as string) || undefined,
      timeFrom: (formData.get('timeFrom') as string) || undefined,
      timeTo: (formData.get('timeTo') as string) || undefined,
      page: 0,
    };

    // 空文字列をundefinedに変換
    if (filters.myInputType === undefined || Number.isNaN(filters.myInputType)) filters.myInputType = undefined;
    if (filters.opponentInputType === undefined || Number.isNaN(filters.opponentInputType)) filters.opponentInputType = undefined;
    if (filters.battleType === 0) filters.battleType = undefined;
    // 日付なしの時間指定は無視
    if (!filters.dateFrom) filters.timeFrom = undefined;
    if (!filters.dateTo) filters.timeTo = undefined;

    onFilter(filters);
  });
}

/**
 * 対戦履歴フォームのキャラクターセレクトを更新（自キャラと相手キャラ）
 */
export function updateHistoryCharacterSelects(myCharacters: string[], opponentCharacters: string[]): void {
  const mySelect = document.getElementById(DOM_IDS.HISTORY_MY_CHARACTER) as HTMLSelectElement | null;
  const opponentSelect = document.getElementById(DOM_IDS.HISTORY_OPPONENT_CHARACTER) as HTMLSelectElement | null;

  if (mySelect) {
    while (mySelect.options.length > 1) mySelect.remove(1);
    for (const char of myCharacters) {
      const option = document.createElement('option');
      option.value = char;
      option.textContent = char;
      mySelect.appendChild(option);
    }
  }

  if (opponentSelect) {
    while (opponentSelect.options.length > 1) opponentSelect.remove(1);
    for (const char of opponentCharacters) {
      const option = document.createElement('option');
      option.value = char;
      option.textContent = char;
      opponentSelect.appendChild(option);
    }
  }
}
