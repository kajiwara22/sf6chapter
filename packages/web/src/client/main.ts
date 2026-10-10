/**
 * SF6 Chapter - クライアントエントリーポイント
 */

import { DOM_IDS } from './types';
import { initDuckDB, loadParquetData, loadBattlelogParquetData, loadRoundStatsParquetData, searchMatches, getStats, getCharacters, queryMatchupChart, getBattlelogMyCharacters, queryMatchHistory, getMatchHistoryOpponentCharacters, queryLpHistory, getLatestLp, fetchGaugesJson, queryRoundStats, queryMatchBattlelogSides, MY_PLAYER_ID } from './search';
import { initSearchForm, updateCharacterSelect } from './components/SearchForm';
import { renderResults, clearResults, showMatchDetailLoading, renderMatchDetail, showMatchDetailError, clearMatchDetail } from './components/ResultsGrid';
import { resolveGaugeSideLabels } from './components/RoundGaugeChart';
import { renderStats, clearStats } from './components/StatsPanel';
import { renderMatchupChart, clearMatchupChart, initMatchupForm, updateMatchupCharacterSelect } from './components/MatchupChart';
import { renderMatchHistory, clearMatchHistory, renderHistoryPagination, initHistoryForm, updateHistoryCharacterSelects } from './components/MatchHistory';
import { renderLpChart, clearLpChart, initLpForm, readLpChartOptions } from './components/LpChart';
import type { SearchFilters, Match, MatchupChartFilters, MatchHistoryFilters, LpHistoryFilters, LpHistoryRow } from '@shared/types';

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
 * マッチアップローディング表示
 */
function showMatchupLoading(show: boolean): void {
  const loading = document.getElementById(DOM_IDS.MATCHUP_LOADING);
  if (loading) {
    loading.style.display = show ? 'flex' : 'none';
  }
}

/**
 * マッチアップエラー表示
 */
function showMatchupError(message: string | null): void {
  const error = document.getElementById(DOM_IDS.MATCHUP_ERROR);
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
 * タブナビゲーション初期化
 */
function initTabs(): void {
  const tabButtons = document.querySelectorAll<HTMLButtonElement>('.tab-btn');

  for (const btn of tabButtons) {
    btn.addEventListener('click', () => {
      const viewId = btn.dataset.view;
      if (!viewId) return;

      // 全タブをリセット
      for (const b of tabButtons) {
        b.classList.remove('tab-btn-active');
      }
      for (const view of document.querySelectorAll<HTMLElement>('.tab-view')) {
        view.classList.remove('tab-view-active');
      }

      // 選択タブをアクティブに
      btn.classList.add('tab-btn-active');
      const targetView = document.getElementById(viewId);
      if (targetView) {
        targetView.classList.add('tab-view-active');
      }
    });
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
  clearMatchDetail();

  try {
    const matches = await searchMatches(filters);
    console.log(`[App] Found ${matches.length} matches`);
    renderResults(matches, handleMatchSelect);
  } catch (err) {
    console.error('[App] Search error:', err);
    showError(`検索に失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
  } finally {
    showLoading(false);
  }
}

/**
 * 検索結果カードのクリックでゲージ詳細パネルを表示する（ADR-048）
 */
async function handleMatchSelect(match: Match): Promise<void> {
  console.log(`[App] Loading gauge detail for match ${match.id}`);
  showMatchDetailLoading(match);

  try {
    const [gauges, roundStats, battlelogSides] = await Promise.all([
      fetchGaugesJson(match.id),
      queryRoundStats(match.id).catch(() => []),
      queryMatchBattlelogSides(match.id).catch(() => null),
    ]);

    const labels = resolveGaugeSideLabels({
      player1Character: match.player1.character,
      player2Character: match.player2.character,
      myPlayerId: MY_PLAYER_ID,
      battlelog: battlelogSides,
    });

    renderMatchDetail(match, { gauges, roundStats, labels });
  } catch (err) {
    console.error('[App] Match detail error:', err);
    showMatchDetailError(
      match,
      `ゲージデータの取得に失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`,
    );
  }
}

/**
 * 対戦履歴ローディング表示
 */
function showHistoryLoading(show: boolean): void {
  const loading = document.getElementById(DOM_IDS.HISTORY_LOADING);
  if (loading) {
    loading.style.display = show ? 'flex' : 'none';
  }
}

/**
 * 対戦履歴エラー表示
 */
function showHistoryError(message: string | null): void {
  const error = document.getElementById(DOM_IDS.HISTORY_ERROR);
  if (error) {
    if (message) {
      error.textContent = message;
      error.style.display = 'block';
    } else {
      error.style.display = 'none';
    }
  }
}

/** 現在の対戦履歴フィルター（ページネーション用に保持） */
let currentHistoryFilters: MatchHistoryFilters = {};

/**
 * 対戦履歴を表示
 */
async function handleHistoryFilter(filters: MatchHistoryFilters): Promise<void> {
  console.log('[App] Querying match history with filters:', filters);

  currentHistoryFilters = filters;
  showHistoryLoading(true);
  showHistoryError(null);
  clearMatchHistory();

  try {
    const rows = await queryMatchHistory(filters);
    console.log(`[App] Match history: ${rows.length} rows`);
    renderMatchHistory(rows);

    const currentPage = filters.page ?? 0;
    const hasNext = rows.length === 20;
    renderHistoryPagination(currentPage, hasNext, (page) => {
      handleHistoryFilter({ ...currentHistoryFilters, page });
    });
  } catch (err) {
    console.error('[App] Match history error:', err);
    showHistoryError(`対戦履歴の取得に失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
  } finally {
    showHistoryLoading(false);
  }
}

/**
 * マッチアップチャート集計実行
 */
async function handleMatchupFilter(filters: MatchupChartFilters): Promise<void> {
  console.log('[App] Querying matchup chart with filters:', filters);

  showMatchupLoading(true);
  showMatchupError(null);
  clearMatchupChart();

  try {
    const rows = await queryMatchupChart(filters);
    console.log(`[App] Matchup chart: ${rows.length} rows`);
    renderMatchupChart(rows);
  } catch (err) {
    console.error('[App] Matchup chart error:', err);
    showMatchupError(`集計に失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
  } finally {
    showMatchupLoading(false);
  }
}

/**
 * LP推移ローディング表示
 */
function showLpLoading(show: boolean): void {
  const loading = document.getElementById(DOM_IDS.LP_LOADING);
  if (loading) {
    loading.style.display = show ? 'flex' : 'none';
  }
}

/**
 * LP推移エラー表示
 */
function showLpError(message: string | null): void {
  const error = document.getElementById(DOM_IDS.LP_ERROR);
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
 * 今日のJST日付（YYYY-MM-DD）
 */
function todayJst(): string {
  const jst = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const y = jst.getUTCFullYear();
  const mo = String(jst.getUTCMonth() + 1).padStart(2, '0');
  const d = String(jst.getUTCDate()).padStart(2, '0');
  return `${y}-${mo}-${d}`;
}

/**
 * 現在地点（右端の追加点）を描画すべきかどうか
 *
 * 期間終了が未指定、または今日以降をカバーしている場合のみ追加する
 * （sfbuff の cover_today? と同じ振る舞い）
 */
function shouldAddCurrentPoint(filters: LpHistoryFilters): boolean {
  if (!filters.dateTo) return true;
  return filters.dateTo >= todayJst();
}

/** LP推移の現在のデータ（移動平均の切替時に再描画するため保持） */
let currentLpRows: LpHistoryRow[] = [];
let currentLpValue: number | undefined;

/**
 * 保持しているデータでLP推移チャートを再描画する（移動平均の切替用）
 */
function rerenderLpChart(): void {
  if (currentLpRows.length === 0) return;
  renderLpChart(currentLpRows, currentLpValue, readLpChartOptions());
}

/**
 * LP推移を表示
 */
async function handleLpFilter(filters: LpHistoryFilters): Promise<void> {
  console.log('[App] Querying LP history with filters:', filters);

  showLpLoading(true);
  showLpError(null);
  clearLpChart();

  try {
    const rows = await queryLpHistory(filters);
    const currentLp = shouldAddCurrentPoint(filters) ? await getLatestLp() : null;
    currentLpRows = rows;
    currentLpValue = currentLp ?? undefined;
    console.log(`[App] LP history: ${rows.length} points`);
    renderLpChart(rows, currentLp ?? undefined, readLpChartOptions());
  } catch (err) {
    console.error('[App] LP history error:', err);
    showLpError(`LP推移の取得に失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
  } finally {
    showLpLoading(false);
  }
}

/**
 * 初期化
 */
async function init(): Promise<void> {
  console.log('[App] Initializing...');

  // タブナビゲーション初期化（データ読み込み前に実行可能）
  initTabs();

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
    renderResults(initialMatches, handleMatchSelect);

    // 検索フォームを初期化
    initSearchForm(handleSearch);

    console.log('[App] Search view initialized');
  } catch (err) {
    console.error('[App] Initialization error:', err);
    showError(`初期化に失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
    clearStats();
    clearResults();
  } finally {
    showLoading(false);
  }

  // マッチアップチャートと対戦履歴の初期化（検索と独立して実行）
  try {
    await loadBattlelogParquetData();

    // round_stats.parquet が無くても他タブを壊さないよう独立して試行する
    try {
      await loadRoundStatsParquetData();
    } catch (statsErr) {
      console.warn('[App] round_stats.parquet の読み込みに失敗しました（ゲージ集計は表示されません）:', statsErr);
    }

    // 自分が使ったキャラクター一覧でセレクトを更新
    const myCharacters = await getBattlelogMyCharacters();
    updateMatchupCharacterSelect(myCharacters);

    // マッチアップフォーム初期化
    initMatchupForm(handleMatchupFilter);

    // 初期表示（フィルターなし）
    const initialMatchup = await queryMatchupChart({});
    renderMatchupChart(initialMatchup);

    console.log('[App] Matchup chart initialized');

    // 対戦履歴の初期化
    const opponentCharacters = await getMatchHistoryOpponentCharacters();
    updateHistoryCharacterSelects(myCharacters, opponentCharacters);

    // 対戦履歴フォーム初期化
    initHistoryForm(handleHistoryFilter);

    // 初期表示（フィルターなし、1ページ目）
    const initialHistory = await queryMatchHistory({ page: 0 });
    renderMatchHistory(initialHistory);
    renderHistoryPagination(0, initialHistory.length === 20, (page) => {
      handleHistoryFilter({ ...currentHistoryFilters, page });
    });

    console.log('[App] Match history initialized');
  } catch (err) {
    console.error('[App] Matchup/history initialization error:', err);
    showMatchupError(`マッチアップデータの読み込みに失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
    showHistoryError(`対戦履歴データの読み込みに失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
  }

  // LP推移の初期化（battlelog_replays のみに依存。他タブの失敗に影響されないよう独立させる）
  try {
    initLpForm(handleLpFilter);

    // 移動平均の切替時は再取得せずに再描画する
    document.getElementById(DOM_IDS.LP_MA_ENABLED)?.addEventListener('change', rerenderLpChart);
    document.getElementById(DOM_IDS.LP_MA_WINDOW)?.addEventListener('change', rerenderLpChart);

    // 初期表示（フィルターなし、全期間）
    const initialLp = await queryLpHistory({});
    const currentLp = await getLatestLp();
    currentLpRows = initialLp;
    currentLpValue = currentLp ?? undefined;
    renderLpChart(initialLp, currentLp ?? undefined, readLpChartOptions());

    console.log('[App] LP history initialized');
  } catch (err) {
    console.error('[App] LP history initialization error:', err);
    showLpError(`LP推移データの読み込みに失敗しました: ${err instanceof Error ? err.message : '不明なエラー'}`);
  }
}

// DOMContentLoadedで初期化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
