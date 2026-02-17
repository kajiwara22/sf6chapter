/**
 * SF6 Chapter - 検索フォームコンポーネント
 */

import { DOM_IDS } from '../types';
import type { SearchFilters, SortOrder } from '@shared/types';

export type SearchHandler = (filters: SearchFilters) => void;

/**
 * 検索フォームを初期化
 */
export function initSearchForm(onSearch: SearchHandler): void {
  const form = document.getElementById(DOM_IDS.SEARCH_FORM) as HTMLFormElement | null;
  const characterSelect = document.getElementById(DOM_IDS.CHARACTER_SELECT) as HTMLSelectElement | null;

  if (!form) {
    console.error('[SearchForm] Form element not found');
    return;
  }

  // キャラクター1変更時にラベルを動的更新
  if (characterSelect) {
    characterSelect.addEventListener('change', (e) => {
      const selectedChar = (e.target as HTMLSelectElement).value;
      const contextSpan = document.getElementById(DOM_IDS.PLAYER_RESULT_CONTEXT);

      if (contextSpan) {
        if (selectedChar) {
          contextSpan.textContent = ` (${selectedChar}の)`;
        } else {
          contextSpan.textContent = '';
        }
      }
    });
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();

    const formData = new FormData(form);
    const filters: SearchFilters = {
      character: formData.get('character') as string || undefined,
      character2: formData.get('character2') as string || undefined,
      videoTitle: formData.get('videoTitle') as string || undefined,
      dateFrom: formData.get('dateFrom') as string || undefined,
      dateTo: formData.get('dateTo') as string || undefined,
      sortBy: (formData.get('sortBy') as SortOrder) || 'publishedAt_desc',
      playerResult: formData.get('playerResult') as 'win' | 'loss' | undefined,
    };

    // 空文字列をundefinedに変換
    if (filters.character === '') filters.character = undefined;
    if (filters.character2 === '') filters.character2 = undefined;
    if (filters.videoTitle === '') filters.videoTitle = undefined;
    if (filters.dateFrom === '') filters.dateFrom = undefined;
    if (filters.dateTo === '') filters.dateTo = undefined;

    onSearch(filters);
  });
}

/**
 * キャラクターセレクトを更新
 */
export function updateCharacterSelect(characters: string[]): void {
  const select1 = document.getElementById(DOM_IDS.CHARACTER_SELECT) as HTMLSelectElement | null;
  const select2 = document.getElementById(DOM_IDS.CHARACTER_SELECT_2) as HTMLSelectElement | null;

  if (!select1) {
    console.error('[SearchForm] Character select 1 not found');
    return;
  }

  if (!select2) {
    console.error('[SearchForm] Character select 2 not found');
    return;
  }

  // 両方のセレクトを更新
  for (const select of [select1, select2]) {
    // 既存のオプションをクリア（最初のオプション以外）
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
}
