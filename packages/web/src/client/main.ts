/**
 * SF6 Chapter - クライアントエントリーポイント
 */

import { DOM_IDS } from './types';
import { initDuckDB, loadParquetData, searchMatches, getStats, getCharacters } from './search';
import { initSearchForm, updateCharacterSelect } from './components/SearchForm';
import { renderResults, clearResults } from './components/ResultsGrid';
import { renderStats, clearStats } from './components/StatsPanel';
import type { SearchFilters } from '@shared/types';

/**
 * ローディング表示
 */
function showLoading(show: boolean): void {
  const loading = document.getElementById(DOM_IDS.LOADING);
  if (loading) {
    loading.style.display = show ? 'flex' : 'none';
  }
}

/**
 * エラー表示
 */
function showError(message: string | null): void {
  const error = document.getElementById(DOM_IDS.ERROR);
  if (error) {
    if (message) {
      error.textContent = message;
      error.style.display = 'block';
    } else {
      error.style.display = 'none';
    }
  }
}

/**
 * 検索実行
 */
async function handleSearch(filters: SearchFilters): Promise<void> {
  console.log('[App] Searching with filters:', filters);

  showLoading(true);
  showError(null);
  clearResults();

  try {
    const matches = await searchMatches(filters);
    console.log(`[App] Found ${matches.length} matches`);
    renderResults(matches);
  } catch (err) {
    console.error('[App] Search error:', err);
    showError(`検索に失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
  } finally {
    showLoading(false);
  }
}

/**
 * 初期化
 */
async function init(): Promise<void> {
  console.log('[App] Initializing...');

  showLoading(true);
  showError(null);

  try {
    // DuckDB初期化
    await initDuckDB();

    // Parquetデータ読み込み
    await loadParquetData();

    // キャラクター一覧を取得してセレクトを更新
    const characters = await getCharacters();
    updateCharacterSelect(characters);

    // 統計情報を表示
    const stats = await getStats();
    renderStats(stats);

    // 初期表示（最新100件）
    const initialMatches = await searchMatches({ limit: 100 });
    renderResults(initialMatches);

    // 検索フォームを初期化
    initSearchForm(handleSearch);

    console.log('[App] Initialized successfully');
  } catch (err) {
    console.error('[App] Initialization error:', err);
    showError(`初期化に失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
    clearStats();
    clearResults();
  } finally {
    showLoading(false);
  }
}

// DOMContentLoadedで初期化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
