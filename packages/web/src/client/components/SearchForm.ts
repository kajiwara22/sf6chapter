/**
 * SF6 Chapter - 検索フォームコンポーネント
 */

import { DOM_IDS } from '../types';
import type { SearchFilters } from '@shared/types';

export type SearchHandler = (filters: SearchFilters) => void;

/**
 * 検索フォームを初期化
 */
export function initSearchForm(onSearch: SearchHandler): void {
  const form = document.getElementById(DOM_IDS.SEARCH_FORM) as HTMLFormElement | null;

  if (!form) {
    console.error('[SearchForm] Form element not found');
    return;
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();

    const formData = new FormData(form);
    const filters: SearchFilters = {
      character: formData.get('character') as string || undefined,
      dateFrom: formData.get('dateFrom') as string || undefined,
      dateTo: formData.get('dateTo') as string || undefined,
    };

    // 空文字列をundefinedに変換
    if (filters.character === '') filters.character = undefined;
    if (filters.dateFrom === '') filters.dateFrom = undefined;
    if (filters.dateTo === '') filters.dateTo = undefined;

    onSearch(filters);
  });
}

/**
 * キャラクターセレクトを更新
 */
export function updateCharacterSelect(characters: string[]): void {
  const select = document.getElementById(DOM_IDS.CHARACTER_SELECT) as HTMLSelectElement | null;

  if (!select) {
    console.error('[SearchForm] Character select not found');
    return;
  }

  // 既存のオプションをクリア（「すべて」以外）
  while (select.options.length > 1) {
    select.remove(1);
  }

  // キャラクターを追加
  for (const character of characters) {
    const option = document.createElement('option');
    option.value = character;
    option.textContent = character;
    select.appendChild(option);
  }
}
