/**
 * SF6 Chapter - ラウンドスコア分析コンポーネント（ADR-070）
 *
 * `battlelog_replays` の `round_results` から、1R の勝敗・1P/2P 別・3R 勝率・
 * 決まり手の内訳を表示する。描画は文字列生成の純粋関数に分け、テスト可能にする。
 */

import { DOM_IDS } from '../types';
import type { RoundScore, RoundScoreFilters, RoundScoreMethodRow } from '@shared/types';

export type RoundScoreFilterHandler = (filters: RoundScoreFilters) => void;

/** 決まり手コードの表示名 */
const METHOD_LABELS: Record<string, string> = {
  V: '通常KO',
  C: 'Chip KO',
  T: '時間切れ',
  OD: 'OD KO',
  SA: 'SA KO',
  CA: 'CA KO',
  P: 'パーフェクト',
  UNKNOWN: '不明',
};

/** 勝率から CSS クラスを決める（マッチアップ表と共通の色分け） */
function winRateClass(winRate: number): string {
  if (winRate >= 60) return 'winrate-high';
  if (winRate >= 40) return 'winrate-mid';
  return 'winrate-low';
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case '&':
        return '&amp;';
      case '<':
        return '&lt;';
      case '>':
        return '&gt;';
      case '"':
        return '&quot;';
      default:
        return '&#39;';
    }
  });
}

/** 割合を「72.6%」形式にする。分母が 0 なら「—」 */
export function formatRate(numerator: number, denominator: number): string {
  if (denominator <= 0) return '—';
  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}

/** 決まり手の表を組み立てる */
function buildMethodTable(title: string, rows: RoundScoreMethodRow[], total: number): string {
  if (rows.length === 0 || total <= 0) {
    return `
      <div class="round-score-method">
        <h3 class="round-score-heading">${escapeHtml(title)}</h3>
        <p class="round-score-empty">データがありません</p>
      </div>
    `;
  }

  const body = rows
    .map(
      (row) => `
        <tr>
          <td class="round-score-method-name">
            ${escapeHtml(row.method)}
            <span class="round-score-method-label">${escapeHtml(METHOD_LABELS[row.method] ?? row.method)}</span>
          </td>
          <td class="round-score-number">${row.count.toLocaleString()}</td>
          <td class="round-score-number">${formatRate(row.count, total)}</td>
        </tr>
      `,
    )
    .join('');

  return `
    <div class="round-score-method">
      <h3 class="round-score-heading">${escapeHtml(title)}</h3>
      <table class="round-score-table">
        <thead>
          <tr><th>決まり手</th><th>回数</th><th>割合</th></tr>
        </thead>
        <tbody>${body}</tbody>
        <tfoot>
          <tr class="round-score-total">
            <td>合計</td>
            <td class="round-score-number">${total.toLocaleString()}</td>
            <td class="round-score-number">100.0%</td>
          </tr>
        </tfoot>
      </table>
    </div>
  `;
}

/**
 * ラウンドスコア分析の HTML を組み立てる（純粋関数）
 */
export function buildRoundScoreHtml(score: RoundScore | null): string {
  if (!score || score.totalMatches <= 0) {
    return '<p class="round-score-empty">データがありません（round_results が揃っている試合がありません）</p>';
  }

  const wonR1 = score.firstRound.find((row) => row.won);
  const lostR1 = score.firstRound.find((row) => !row.won);
  const wonR1Rate = wonR1 ? (wonR1.wins / wonR1.total) * 100 : 0;
  const lostR1Rate = lostR1 ? (lostR1.wins / lostR1.total) * 100 : 0;
  const fullRoundRate = (score.fullRoundTotal / score.totalMatches) * 100;
  const threeRounderRate = score.fullRoundTotal > 0 ? (score.fullRoundWins / score.fullRoundTotal) * 100 : 0;

  const tiles = `
    <div class="round-score-tiles">
      <div class="round-score-tile">
        <span class="round-score-tile-label">対象試合</span>
        <span class="round-score-tile-value">${score.totalMatches.toLocaleString()}</span>
        <span class="round-score-tile-sub">round_results が揃っている試合</span>
      </div>
      <div class="round-score-tile">
        <span class="round-score-tile-label">1R を取った試合の勝率</span>
        <span class="round-score-tile-value ${winRateClass(wonR1Rate)}">${wonR1 ? formatRate(wonR1.wins, wonR1.total) : '—'}</span>
        <span class="round-score-tile-sub">${wonR1 ? `${wonR1.wins} / ${wonR1.total}` : '—'}</span>
      </div>
      <div class="round-score-tile">
        <span class="round-score-tile-label">1R を落とした試合の勝率</span>
        <span class="round-score-tile-value ${winRateClass(lostR1Rate)}">${lostR1 ? formatRate(lostR1.wins, lostR1.total) : '—'}</span>
        <span class="round-score-tile-sub">${lostR1 ? `${lostR1.wins} / ${lostR1.total}` : '—'}</span>
      </div>
      <div class="round-score-tile">
        <span class="round-score-tile-label">フルラウンド率</span>
        <span class="round-score-tile-value">${formatRate(score.fullRoundTotal, score.totalMatches)}</span>
        <span class="round-score-tile-sub">${score.fullRoundTotal} / ${score.totalMatches} 試合</span>
      </div>
      <div class="round-score-tile">
        <span class="round-score-tile-label">3R の勝率</span>
        <span class="round-score-tile-value ${winRateClass(threeRounderRate)}">${formatRate(score.fullRoundWins, score.fullRoundTotal)}</span>
        <span class="round-score-tile-sub">${score.fullRoundWins} / ${score.fullRoundTotal} 試合</span>
      </div>
    </div>
  `;

  const firstRoundRows = score.firstRound
    .map(
      (row) => `
        <tr>
          <td class="round-score-side">${row.won ? '取った' : '落とした'}</td>
          <td class="round-score-number">${row.total.toLocaleString()}</td>
          <td class="round-score-number">${row.wins.toLocaleString()}</td>
          <td class="round-score-number ${winRateClass((row.wins / row.total) * 100)}">${formatRate(row.wins, row.total)}</td>
        </tr>
      `,
    )
    .join('');

  const sideRows = score.sides
    .map(
      (row) => `
        <tr>
          <td class="round-score-side">${escapeHtml(row.side)}</td>
          <td class="round-score-number">${row.total.toLocaleString()}</td>
          <td class="round-score-number">${row.wins.toLocaleString()}</td>
          <td class="round-score-number ${winRateClass((row.wins / row.total) * 100)}">${formatRate(row.wins, row.total)}</td>
          <td class="round-score-number">${formatRate(row.fullRoundWins, row.fullRoundTotal)}${
            row.fullRoundTotal > 0 ? ` <span class="round-score-n">(${row.fullRoundWins}/${row.fullRoundTotal})</span>` : ''
          }</td>
        </tr>
      `,
    )
    .join('');

  return `
    <div class="round-score-summary">
      <p class="round-score-note">
        対象: ${score.totalMatches.toLocaleString()}試合（round_results が揃っている試合）。1P/2P は自分視点に正規化しています。
      </p>
      ${tiles}
      <h3 class="round-score-heading">1ラウンド目の勝敗と試合勝率</h3>
      <table class="round-score-table">
        <thead>
          <tr><th>1R</th><th>試合数</th><th>勝利</th><th>勝率</th></tr>
        </thead>
        <tbody>${firstRoundRows}</tbody>
      </table>
      <h3 class="round-score-heading">1P / 2P 別</h3>
      <table class="round-score-table">
        <thead>
          <tr><th>サイド</th><th>試合数</th><th>勝利</th><th>勝率</th><th>3R 勝率 (n)</th></tr>
        </thead>
        <tbody>${sideRows}</tbody>
      </table>
      <div class="round-score-methods">
        ${buildMethodTable('取ったラウンド（自分が決めた）', score.wonMethods, score.totalRoundsWon)}
        ${buildMethodTable('落としたラウンド（相手に決められた）', score.lostMethods, score.totalRoundsLost)}
      </div>
      <p class="round-score-footnote">
        決まり手は Battlelog の round_results（V=通常KO / C=Chip KO / T=時間切れ / OD=OD KO / SA=SA KO / CA=CA KO / P=パーフェクト）。
        引き分けラウンドは勝ち・負けのどちらにも数えません。
      </p>
    </div>
  `;
}

/** ラウンドスコア分析を表示 */
export function renderRoundScore(score: RoundScore | null): void {
  const container = document.getElementById(DOM_IDS.ROUND_SCORE);
  if (!container) {
    console.error('[RoundScorePanel] Container not found');
    return;
  }
  container.innerHTML = buildRoundScoreHtml(score);
}

/** ラウンドスコア分析をクリア */
export function clearRoundScore(): void {
  const container = document.getElementById(DOM_IDS.ROUND_SCORE);
  if (container) {
    container.innerHTML = '';
  }
}

/** ラウンドスコア分析のフィルターフォームを初期化 */
export function initRoundScoreForm(onFilter: RoundScoreFilterHandler): void {
  const form = document.getElementById(DOM_IDS.ROUND_FORM) as HTMLFormElement | null;
  if (!form) {
    console.error('[RoundScorePanel] Form not found');
    return;
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const formData = new FormData(form);

    const filters: RoundScoreFilters = {
      dateFrom: (formData.get('dateFrom') as string) || undefined,
      dateTo: (formData.get('dateTo') as string) || undefined,
      timeFrom: (formData.get('timeFrom') as string) || undefined,
      timeTo: (formData.get('timeTo') as string) || undefined,
      battleType: Number(formData.get('battleType')) || undefined,
      myCharacter: (formData.get('myCharacter') as string) || undefined,
    };

    if (filters.battleType === 0) filters.battleType = undefined;
    // 日付なしの時間指定は無視
    if (!filters.dateFrom) filters.timeFrom = undefined;
    if (!filters.dateTo) filters.timeTo = undefined;

    onFilter(filters);
  });
}

/** ラウンドスコア分析フォームのキャラクターセレクトを更新 */
export function updateRoundScoreCharacterSelect(characters: string[]): void {
  const select = document.getElementById(DOM_IDS.ROUND_MY_CHARACTER) as HTMLSelectElement | null;
  if (!select) return;

  while (select.options.length > 1) {
    select.remove(1);
  }

  for (const character of characters) {
    const option = document.createElement('option');
    option.value = character;
    option.textContent = character;
    select.appendChild(option);
  }
}
