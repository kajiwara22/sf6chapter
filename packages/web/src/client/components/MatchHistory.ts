/**
 * SF6 Chapter - 対戦履歴コンポーネント
 */

import { DOM_IDS } from '../types';
import type { MatchHistoryRow, MatchHistoryFilters, RoundCounterRow } from '@shared/types';
import { getRound, parseRoundIds } from '@shared/rounds';

export type MatchHistoryFilterHandler = (filters: MatchHistoryFilters) => void;

/** 入力タイプ名のマッピング */
const INPUT_TYPE_NAMES: Record<number, string> = {
  0: 'Classic',
  1: 'Modern',
};

/**
 * HTMLエスケープ（DOM非依存。ユニットテスト可能にするため文字列置換で実装）
 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * 入力タイプのバッジHTMLを生成
 */
function createInputTypeBadge(inputType: number | null): string {
  if (inputType == null) return '<span class="text-muted">-</span>';
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
function createResultBadge(result: 'win' | 'loss' | 'draw' | null): string {
  if (result === 'win') {
    return `<span class="result-badge result-badge-win">WIN</span>`;
  } else if (result === 'loss') {
    return `<span class="result-badge result-badge-loss">LOSS</span>`;
  } else if (result === 'draw') {
    return `<span class="result-badge result-badge-draw">DRAW</span>`;
  }
  return '<span class="text-muted">-</span>';
}

/**
 * ラウンドバッジ1つ分のHTMLを生成する（sfbuff 準拠、ADR-047）
 */
export function createRoundBadge(id: number): string {
  const round = getRound(id);
  const title = `${round.name}: ${round.description}`;
  return `<span class="round-badge" style="background-color: ${round.backgroundColor}; color: ${round.textColor}" title="${escapeHtml(title)}">${escapeHtml(round.name)}</span>`;
}

/**
 * カウンター回数の表示テキストを生成する（ADR-049）
 *
 * 0 件の項目は省略し、両方 0 件（あるいは未計測）の場合は空文字を返す。
 */
export function formatCounterText(
  counterCount: number | null,
  punishCounterCount: number | null,
): string {
  if (counterCount == null && punishCounterCount == null) return '';
  const parts: string[] = [];
  if (counterCount) parts.push(`C${counterCount}`);
  if (punishCounterCount) parts.push(`PC${punishCounterCount}`);
  return parts.join(' ');
}

/**
 * カウンター回数のバッジHTMLを生成する（0 件なら空文字）
 */
export function createCounterBadge(counterCount: number | null, punishCounterCount: number | null): string {
  const text = formatCounterText(counterCount, punishCounterCount);
  if (!text) return '';
  const title = `COUNTER ${counterCount ?? 0} / PUNISH COUNTER ${punishCounterCount ?? 0}`;
  return `<span class="round-counter" title="${escapeHtml(title)}">${escapeHtml(text)}</span>`;
}

/**
 * 対戦履歴の「ラウンド」セルを生成する（ADR-047 / ADR-049）
 *
 * 上段に自分、下段に相手のラウンドバッジを並べ、各バッジにそのラウンドの
 * カウンター回数（ADR-049）を併記する。
 * round_results がない（YouTube側のみの）行でもカウンター回数があれば表示する。
 */
export function createRoundCell(row: MatchHistoryRow): string {
  const myRounds = parseRoundIds(row.myRounds);
  const oppRounds = parseRoundIds(row.oppRounds);

  const mySide = row.selfSide ?? 'player1';
  const oppSide: 'player1' | 'player2' = mySide === 'player1' ? 'player2' : 'player1';
  const roundCounters = row.roundCounters ?? [];

  const countersByRound = (side: 'player1' | 'player2'): Map<number, RoundCounterRow> =>
    new Map(roundCounters.filter((counter) => counter.side === side).map((counter) => [counter.round, counter]));
  const myCounters = countersByRound(mySide);
  const oppCounters = countersByRound(oppSide);

  if (myRounds.length === 0 && oppRounds.length === 0) {
    const totalOf = (side: 'player1' | 'player2') => {
      const list = roundCounters.filter((counter) => counter.side === side);
      return {
        measured: list.some((counter) => counter.counterCount != null || counter.punishCounterCount != null),
        counter: list.reduce((acc, counter) => acc + (counter.counterCount ?? 0), 0),
        punish: list.reduce((acc, counter) => acc + (counter.punishCounterCount ?? 0), 0),
      };
    };
    const myTotal = totalOf(mySide);
    const oppTotal = totalOf(oppSide);
    if (!myTotal.measured && !oppTotal.measured) {
      return '<span class="text-muted">-</span>';
    }
    const myHtml = createCounterBadge(myTotal.counter, myTotal.punish) || '<span class="text-muted">-</span>';
    const oppHtml = createCounterBadge(oppTotal.counter, oppTotal.punish) || '<span class="text-muted">-</span>';
    return `<div class="round-list">
      <div class="round-side round-side-self" title="自分">${myHtml}</div>
      <div class="round-side round-side-opponent" title="相手">${oppHtml}</div>
    </div>`;
  }

  const badgeWithCounter = (id: number, round: number, counters: Map<number, RoundCounterRow>): string => {
    const counter = counters.get(round);
    const annotation = counter ? createCounterBadge(counter.counterCount, counter.punishCounterCount) : '';
    return `${createRoundBadge(id)}${annotation}`;
  };

  const myBadges = myRounds
    .map((id, index) => badgeWithCounter(id, index + 1, myCounters))
    .join('');
  const oppBadges = oppRounds
    .map((id, index) => badgeWithCounter(id, index + 1, oppCounters))
    .join('');

  return `<div class="round-list">
      <div class="round-side round-side-self" title="自分">${myBadges}</div>
      <div class="round-side round-side-opponent" title="相手">${oppBadges}</div>
    </div>`;
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
 * YouTubeリンクセルを生成
 */
function createYoutubeCell(row: MatchHistoryRow): string {
  if (row.videoId && row.startTime != null) {
    const url = `https://www.youtube.com/watch?v=${encodeURIComponent(row.videoId)}&t=${row.startTime}s`;
    return `<a href="${url}" target="_blank" rel="noopener" class="replay-youtube-link" title="YouTubeで視聴">
      <svg class="yt-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
        <path fill="#FF0000" d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5a3 3 0 0 0-2.1 2.1C0 8.1 0 12 0 12s0 3.9.5 5.8a3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1C24 15.9 24 12 24 12s0-3.9-.5-5.8z"/>
        <path fill="#fff" d="M9.6 15.6V8.4l6.3 3.6-6.3 3.6z"/>
      </svg>
    </a>`;
  }
  return '<span class="text-muted">-</span>';
}

/**
 * 対戦履歴テーブルのHTMLを生成
 */
function createHistoryTable(rows: MatchHistoryRow[]): string {
  if (rows.length === 0) {
    return '<p class="history-empty">データがありません</p>';
  }

  const tableRows = rows.map((row) => {
    const opponentNameDisplay = row.opponentName
      ? `${escapeHtml(row.opponentName.slice(0, 16))}${row.opponentName.length > 16 ? '…' : ''}`
      : '<span class="text-muted">-</span>';
    const opponentNameTitle = row.opponentName ? escapeHtml(row.opponentName) : '';

    return `
    <tr class="history-row">
      <td class="history-my-character">${escapeHtml(row.myCharacter)}</td>
      <td class="history-my-input">${createInputTypeBadge(row.myInputType)}</td>
      <td class="history-result">${createResultBadge(row.result)}</td>
      <td class="history-round">${createRoundCell(row)}</td>
      <td class="history-opponent-name" title="${opponentNameTitle}">${opponentNameDisplay}</td>
      <td class="history-opponent-character">${escapeHtml(row.opponentCharacter)}</td>
      <td class="history-opponent-input">${createInputTypeBadge(row.opponentInputType)}</td>
      <td class="history-battle-type">${row.battleTypeName ? escapeHtml(row.battleTypeName) : '<span class="text-muted">-</span>'}</td>
      <td class="history-replay">${createYoutubeCell(row)}</td>
      <td class="history-date">${escapeHtml(formatAbsoluteTime(row.uploadedAt))}</td>
    </tr>`;
  }).join('');

  return `
    <table class="history-table">
      <thead>
        <tr>
          <th>使用キャラ</th>
          <th>操作</th>
          <th>勝負</th>
          <th>ラウンド</th>
          <th>相手名</th>
          <th>相手キャラ</th>
          <th>相手操作</th>
          <th>モード</th>
          <th>YouTube</th>
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
