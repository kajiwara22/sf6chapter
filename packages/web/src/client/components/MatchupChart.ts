/**
 * SF6 Chapter - マッチアップチャートコンポーネント
 */

import { DOM_IDS } from '../types';
import type { MatchupChartRow, MatchupChartFilters } from '@shared/types';
import { queryMatchupChart, getBattlelogMyCharacters } from '../search';

export type MatchupFilterHandler = (filters: MatchupChartFilters) => void;

/**
 * 入力タイプのバッジHTMLを生成
 * クラシック(0): 紫六角形「C」 / モダン(1): オレンジ四角「M」
 */
function createInputTypeBadge(inputType: number, label: string): string {
  if (inputType === 0) {
    return `<span class="input-badge input-badge-classic" title="${label}">C</span>`;
  } else if (inputType === 1) {
    return `<span class="input-badge input-badge-modern" title="${label}">M</span>`;
  }
  return `<span class="input-badge">${escapeHtml(label)}</span>`;
}

/**
 * 勝率に応じたCSSクラスを返す
 */
function getWinRateClass(winRate: number): string {
  if (winRate >= 60) return 'winrate-high';
  if (winRate >= 40) return 'winrate-mid';
  return 'winrate-low';
}

/**
 * マッチアップチャートテーブルのHTMLを生成
 */
function createMatchupTable(rows: MatchupChartRow[]): string {
  if (rows.length === 0) {
    return '<p class="matchup-empty">データがありません</p>';
  }

  // キャラクター別に集約（入力タイプをまとめた合計も計算）
  const byCharacter = new Map<string, MatchupChartRow[]>();
  for (const row of rows) {
    const existing = byCharacter.get(row.opponentCharacter) || [];
    existing.push(row);
    byCharacter.set(row.opponentCharacter, existing);
  }

  // 合計行を計算
  let totalAll = 0;
  let winsAll = 0;
  let lossesAll = 0;
  let drawsAll = 0;

  const tableRows: string[] = [];

  for (const [character, charRows] of byCharacter) {
    // キャラ合計
    const charTotal = charRows.reduce((sum, r) => sum + r.total, 0);
    const charWins = charRows.reduce((sum, r) => sum + r.wins, 0);
    const charLosses = charRows.reduce((sum, r) => sum + r.losses, 0);
    const charDraws = charRows.reduce((sum, r) => sum + r.draws, 0);
    const charWinRate = charTotal > 0 ? Math.round((charWins / charTotal) * 1000) / 10 : 0;

    totalAll += charTotal;
    winsAll += charWins;
    lossesAll += charLosses;
    drawsAll += charDraws;

    // 入力タイプバッジの組み合わせを生成
    const inputBadges = charRows.map((r) => createInputTypeBadge(r.opponentInputType, r.opponentInputTypeName)).join('');

    // キャラクター合計行
    tableRows.push(`
      <tr class="matchup-row matchup-row-character">
        <td class="matchup-character">${escapeHtml(character)}</td>
        <td class="matchup-input-type">${inputBadges}</td>
        <td class="matchup-total">${charTotal}</td>
        <td class="matchup-wins">${charWins}</td>
        <td class="matchup-losses">${charLosses}</td>
        <td class="matchup-draws">${charDraws}</td>
        <td class="matchup-winrate ${getWinRateClass(charWinRate)}">${charWinRate}%</td>
      </tr>
    `);

    // 入力タイプ別の内訳（2種類以上ある場合のみ）
    if (charRows.length > 1) {
      for (const row of charRows) {
        tableRows.push(`
          <tr class="matchup-row matchup-row-detail">
            <td class="matchup-character"></td>
            <td class="matchup-input-type">${createInputTypeBadge(row.opponentInputType, row.opponentInputTypeName)}</td>
            <td class="matchup-total">${row.total}</td>
            <td class="matchup-wins">${row.wins}</td>
            <td class="matchup-losses">${row.losses}</td>
            <td class="matchup-draws">${row.draws}</td>
            <td class="matchup-winrate ${getWinRateClass(row.winRate)}">${row.winRate}%</td>
          </tr>
        `);
      }
    }
  }

  // 合計行
  const totalWinRate = totalAll > 0 ? Math.round((winsAll / totalAll) * 1000) / 10 : 0;

  return `
    <table class="matchup-table">
      <thead>
        <tr>
          <th>対戦キャラ</th>
          <th>入力タイプ</th>
          <th>対戦数</th>
          <th>勝</th>
          <th>敗</th>
          <th>引分</th>
          <th>勝率</th>
        </tr>
      </thead>
      <tbody>
        ${tableRows.join('')}
      </tbody>
      <tfoot>
        <tr class="matchup-row-total">
          <td>合計</td>
          <td></td>
          <td>${totalAll}</td>
          <td>${winsAll}</td>
          <td>${lossesAll}</td>
          <td>${drawsAll}</td>
          <td class="${getWinRateClass(totalWinRate)}">${totalWinRate}%</td>
        </tr>
      </tfoot>
    </table>
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
 * マッチアップチャートを表示
 */
export function renderMatchupChart(rows: MatchupChartRow[]): void {
  const container = document.getElementById(DOM_IDS.MATCHUP_CHART);
  if (!container) {
    console.error('[MatchupChart] Container not found');
    return;
  }

  container.innerHTML = createMatchupTable(rows);
}

/**
 * マッチアップチャートをクリア
 */
export function clearMatchupChart(): void {
  const container = document.getElementById(DOM_IDS.MATCHUP_CHART);
  if (container) {
    container.innerHTML = '';
  }
}

/**
 * マッチアップフォームを初期化
 */
export function initMatchupForm(onFilter: MatchupFilterHandler): void {
  const form = document.getElementById(DOM_IDS.MATCHUP_FORM) as HTMLFormElement | null;
  if (!form) {
    console.error('[MatchupChart] Form not found');
    return;
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const formData = new FormData(form);

    const filters: MatchupChartFilters = {
      dateFrom: formData.get('dateFrom') as string || undefined,
      dateTo: formData.get('dateTo') as string || undefined,
      timeFrom: formData.get('timeFrom') as string || undefined,
      timeTo: formData.get('timeTo') as string || undefined,
      battleType: Number(formData.get('battleType')) || undefined,
      myCharacter: formData.get('myCharacter') as string || undefined,
    };

    // 空文字列をundefinedに変換
    if (filters.dateFrom === '') filters.dateFrom = undefined;
    if (filters.dateTo === '') filters.dateTo = undefined;
    if (filters.timeFrom === '') filters.timeFrom = undefined;
    if (filters.timeTo === '') filters.timeTo = undefined;
    if (filters.battleType === 0) filters.battleType = undefined;
    if (filters.myCharacter === '') filters.myCharacter = undefined;
    // 日付なしの時間指定は無視
    if (!filters.dateFrom) filters.timeFrom = undefined;
    if (!filters.dateTo) filters.timeTo = undefined;

    onFilter(filters);
  });
}

/**
 * マッチアップフォームのキャラクターセレクトを更新
 */
export function updateMatchupCharacterSelect(characters: string[]): void {
  const select = document.getElementById(DOM_IDS.MATCHUP_MY_CHARACTER) as HTMLSelectElement | null;
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
