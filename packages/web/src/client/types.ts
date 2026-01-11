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
  DATE_FROM: 'date-from',
  DATE_TO: 'date-to',
  LOADING: 'loading',
  ERROR: 'error',
  RESULTS: 'results',
  NO_RESULTS: 'no-results',
  STATS: 'stats',
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
  player1_characterRaw: string;
  player1_side: string;
  player2_character: string;
  player2_characterRaw: string;
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
