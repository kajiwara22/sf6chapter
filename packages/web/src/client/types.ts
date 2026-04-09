/**
 * SF6 Chapter - クライアント型定義
 */

import type { AsyncDuckDB, AsyncDuckDBConnection } from '@duckdb/duckdb-wasm';

/** DuckDB-WASMのインスタンス */
export interface DuckDBInstance {
  db: AsyncDuckDB;
  conn: AsyncDuckDBConnection;
}

/** DOM要素のID */
export const DOM_IDS = {
  SEARCH_FORM: 'search-form',
  CHARACTER_SELECT: 'character-select',
  CHARACTER_SELECT_2: 'character-select-2',
  PLAYER_RESULT_CONTEXT: 'player-result-context',
  VIDEO_TITLE: 'video-title',
  DATE_FROM: 'date-from',
  DATE_TO: 'date-to',
  SORT_BY: 'sort-by',
  PLAYER_RESULT: 'player-result',
  LOADING: 'loading',
  ERROR: 'error',
  RESULTS: 'results',
  NO_RESULTS: 'no-results',
  STATS: 'stats',
  // タブナビゲーション
  TAB_SEARCH: 'tab-search',
  TAB_MATCHUP: 'tab-matchup',
  VIEW_SEARCH: 'view-search',
  VIEW_MATCHUP: 'view-matchup',
  // マッチアップチャート
  MATCHUP_FORM: 'matchup-form',
  MATCHUP_DATE_FROM: 'matchup-date-from',
  MATCHUP_TIME_FROM: 'matchup-time-from',
  MATCHUP_DATE_TO: 'matchup-date-to',
  MATCHUP_TIME_TO: 'matchup-time-to',
  MATCHUP_BATTLE_TYPE: 'matchup-battle-type',
  MATCHUP_MY_CHARACTER: 'matchup-my-character',
  MATCHUP_CHART: 'matchup-chart',
  MATCHUP_LOADING: 'matchup-loading',
  MATCHUP_ERROR: 'matchup-error',
  // 対戦履歴
  TAB_HISTORY: 'tab-history',
  VIEW_HISTORY: 'view-history',
  HISTORY_FORM: 'history-form',
  HISTORY_MY_CHARACTER: 'history-my-character',
  HISTORY_MY_INPUT_TYPE: 'history-my-input-type',
  HISTORY_OPPONENT_CHARACTER: 'history-opponent-character',
  HISTORY_OPPONENT_INPUT_TYPE: 'history-opponent-input-type',
  HISTORY_BATTLE_TYPE: 'history-battle-type',
  HISTORY_DATE_FROM: 'history-date-from',
  HISTORY_TIME_FROM: 'history-time-from',
  HISTORY_DATE_TO: 'history-date-to',
  HISTORY_TIME_TO: 'history-time-to',
  HISTORY_TABLE: 'history-table',
  HISTORY_LOADING: 'history-loading',
  HISTORY_ERROR: 'history-error',
  HISTORY_PAGINATION: 'history-pagination',
} as const;

/** クエリ結果の行 */
export interface MatchRow {
  id: string;
  videoId: string;
  videoTitle: string;
  videoPublishedAt: string;
  startTime: bigint | number;
  endTime: bigint | number | null;
  player1_character: string;
  player1_side: string;
  player2_character: string;
  player2_side: string;
  detectedAt: string;
  confidence: number;
}

/** 統計クエリ結果 */
export interface StatsRow {
  total_matches: bigint | number;
  total_videos: bigint | number;
  latest_detected: string | null;
}

/** キャラクター集計結果 */
export interface CharacterCountRow {
  character: string;
  count: bigint | number;
}

/** マッチアップチャートのDuckDBクエリ結果行 */
export interface MatchupChartQueryRow {
  opponent_character: string;
  opponent_input_type: number | bigint;
  total: number | bigint;
  wins: number | bigint;
  losses: number | bigint;
  draws: number | bigint;
}

/** 対戦履歴のDuckDBクエリ結果行 */
export interface MatchHistoryQueryRow {
  my_character: string;
  my_input_type: number | bigint;
  result: string;
  opponent_name: string;
  opponent_character: string;
  opponent_input_type: number | bigint;
  battle_type_name: string;
  replay_id: string;
  uploaded_at: string;
  video_id: string | null;
  start_time: number | bigint | null;
}
