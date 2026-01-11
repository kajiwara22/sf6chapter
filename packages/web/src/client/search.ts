/**
 * SF6 Chapter - DuckDB-WASM検索ロジック
 */

import * as duckdb from '@duckdb/duckdb-wasm';
import type { DuckDBInstance, MatchRow, StatsRow, CharacterCountRow } from './types';
import type { SearchFilters, Match, Stats, PresignedUrlResponse } from '@shared/types';

let instance: DuckDBInstance | null = null;

/**
 * DuckDB-WASMを初期化
 */
export async function initDuckDB(): Promise<DuckDBInstance> {
  if (instance) {
    return instance;
  }

  console.log('[DuckDB] Initializing...');

  // CDN経由でWASMバンドルを取得
  const JSDELIVR_BUNDLES = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(JSDELIVR_BUNDLES);

  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' })
  );

  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger();

  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  const conn = await db.connect();

  instance = { db, conn };
  console.log('[DuckDB] Initialized successfully');

  return instance;
}

/**
 * Presigned URLを取得
 */
async function getPresignedUrl(apiPath: string): Promise<string> {
  console.log(`[DuckDB] Fetching presigned URL from ${apiPath}...`);
  
  const response = await fetch(apiPath);
  if (!response.ok) {
    throw new Error(`Failed to get presigned URL: ${response.status}`);
  }

  const data: PresignedUrlResponse = await response.json();
  console.log(`[DuckDB] Got presigned URL (expires in ${data.expiresIn}s)`);
  
  return data.url;
}

/**
 * Presigned URLからParquetデータをダウンロード
 */
async function downloadParquet(presignedUrl: string): Promise<ArrayBuffer> {
  console.log('[DuckDB] Downloading Parquet from presigned URL...');
  
  const response = await fetch(presignedUrl);
  if (!response.ok) {
    throw new Error(`Failed to download Parquet: ${response.status}`);
  }

  const data = await response.arrayBuffer();
  console.log(`[DuckDB] Downloaded ${data.byteLength} bytes`);
  
  return data;
}

/**
 * Parquetファイルをロード
 */
export async function loadParquetData(): Promise<void> {
  if (!instance) {
    throw new Error('DuckDB not initialized');
  }

  console.log('[DuckDB] Loading Parquet data...');

  // 1. APIからPresigned URLを取得
  const presignedUrl = await getPresignedUrl('/api/data/index/matches.parquet');

  // 2. Presigned URLからParquetデータをダウンロード
  const parquetData = await downloadParquet(presignedUrl);

  // 3. DuckDBに登録
  await instance.db.registerFileBuffer('matches.parquet', new Uint8Array(parquetData));

  // 4. matchesテーブルを作成
  await instance.conn.query(`
    CREATE TABLE IF NOT EXISTS matches AS
    SELECT * FROM read_parquet('matches.parquet')
  `);

  console.log('[DuckDB] Parquet data loaded (matches table)');
}

/**
 * 対戦データを検索
 */
export async function searchMatches(filters: SearchFilters): Promise<Match[]> {
  if (!instance) {
    throw new Error('DuckDB not initialized');
  }

  const conditions: string[] = [];
  const params: unknown[] = [];

  // キャラクターフィルター
  if (filters.character) {
    conditions.push(`(player1.character = ? OR player2.character = ?)`);
    params.push(filters.character, filters.character);
  }

  // 日付フィルター（YouTube公開日ベース）
  if (filters.dateFrom) {
    conditions.push(`videoPublishedAt >= ?`);
    params.push(filters.dateFrom);
  }

  if (filters.dateTo) {
    conditions.push(`videoPublishedAt <= ?`);
    params.push(filters.dateTo + 'T23:59:59Z');
  }

  const whereClause = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';
  const limit = filters.limit || 100;

  const query = `
    SELECT
      id,
      videoId,
      videoTitle,
      videoPublishedAt,
      startTime,
      player1.character as player1_character,
      player1.characterRaw as player1_characterRaw,
      player1.side as player1_side,
      player2.character as player2_character,
      player2.characterRaw as player2_characterRaw,
      player2.side as player2_side,
      detectedAt,
      confidence
    FROM matches
    ${whereClause}
    ORDER BY videoPublishedAt DESC, startTime ASC
    LIMIT ${limit}
  `;

  const result = await instance.conn.query(query);
  const rows = result.toArray() as unknown as MatchRow[];

  return rows.map((row) => ({
    id: row.id,
    videoId: row.videoId,
    videoTitle: row.videoTitle,
    videoPublishedAt: row.videoPublishedAt,
    startTime: Number(row.startTime),
    endTime: row.endTime ? Number(row.endTime) : undefined,
    player1: {
      character: row.player1_character,
      characterRaw: row.player1_characterRaw,
      side: row.player1_side as 'left' | 'right',
    },
    player2: {
      character: row.player2_character,
      characterRaw: row.player2_characterRaw,
      side: row.player2_side as 'left' | 'right',
    },
    detectedAt: row.detectedAt,
    confidence: row.confidence,
  }));
}

/**
 * 統計情報を取得
 */
export async function getStats(): Promise<Stats> {
  if (!instance) {
    throw new Error('DuckDB not initialized');
  }

  // 基本統計
  // total_matches: 全動画のchapters配列に含まれる対戦数の合計
  // (matchesテーブルの各行が1つのchapterに対応)
  const statsResult = await instance.conn.query(`
    SELECT
      COUNT(*) as total_matches,
      COUNT(DISTINCT videoId) as total_videos,
      MAX(detectedAt) as latest_detected
    FROM matches
  `);
  const statsRow = statsResult.toArray()[0] as unknown as StatsRow;

  // キャラクター別集計（両プレイヤーをカウント）
  const charResult = await instance.conn.query(`
    WITH all_characters AS (
      SELECT player1.character as character FROM matches
      UNION ALL
      SELECT player2.character as character FROM matches
    )
    SELECT character, COUNT(*) as count
    FROM all_characters
    GROUP BY character
    ORDER BY count DESC
  `);
  const charRows = charResult.toArray() as unknown as CharacterCountRow[];

  const characterCounts: Record<string, number> = {};
  for (const row of charRows) {
    characterCounts[row.character] = Number(row.count);
  }

  return {
    totalMatches: Number(statsRow.total_matches),
    totalVideos: Number(statsRow.total_videos),
    characterCounts,
    latestDetectedAt: statsRow.latest_detected || undefined,
  };
}

/**
 * キャラクター一覧を取得
 */
export async function getCharacters(): Promise<string[]> {
  if (!instance) {
    throw new Error('DuckDB not initialized');
  }

  const result = await instance.conn.query(`
    WITH all_characters AS (
      SELECT DISTINCT player1.character as character FROM matches
      UNION
      SELECT DISTINCT player2.character as character FROM matches
    )
    SELECT character FROM all_characters ORDER BY character
  `);

  const rows = result.toArray() as unknown as { character: string }[];
  return rows.map((row) => row.character);
}

/**
 * DuckDBインスタンスをクリーンアップ
 */
export async function closeDuckDB(): Promise<void> {
  if (instance) {
    await instance.conn.close();
    await instance.db.terminate();
    instance = null;
  }
}
