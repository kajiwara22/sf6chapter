/**
 * SF6 Chapter - バックラー公開統計クライアント（ADR-072）
 *
 * R2 の `stats/manifest.json` から最新データ月を決め、`matchup_stats` /
 * `matchup_details` の Parquet を Presigned URL 経由で取得して DuckDB に載せる。
 * マッチアップタブで「同ランク帯の平均勝率」を出すために使う。
 *
 * 既存の manifest キャッシュ（ADR-055）とは分離している。統計は月次で
 * オブジェクトが増えるため、共通 manifest に混ぜると全キャッシュが無効化される。
 */

import { benchmarkKey } from '@shared/characters';
import { getLeagueIdForLp, LEAGUES } from '@shared/leagues';
import type { MatchupBenchmark, StatsManifest } from '@shared/types';

import { getLatestLp, initDuckDB } from './search';

const STATS_TABLE = 'ext_matchup_stats';
const DETAILS_TABLE = 'ext_matchup_details';

/** dia API の input_type（C/M）→ マッチアップ表の表記 */
const DIA_INPUT_LABELS: Record<string, string> = {
  C: 'Classic',
  M: 'Modern',
};

const cache = new Map<string, MatchupBenchmark>();

/** stats/manifest.json を取得する。未配置なら null */
export async function fetchStatsManifest(): Promise<StatsManifest | null> {
  const response = await fetch('/api/data/stats-manifest');
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Failed to fetch stats manifest: ${response.status}`);
  }
  const manifest = (await response.json()) as StatsManifest;
  if (!manifest?.latestMonth) return null;
  return manifest;
}

async function fetchStatsParquet(dataMonth: string, kind: string): Promise<ArrayBuffer> {
  const urlResponse = await fetch(`/api/data/stats/${dataMonth}/${kind}`);
  if (!urlResponse.ok) {
    throw new Error(`Failed to get stats presigned URL (${kind}): ${urlResponse.status}`);
  }
  const { url } = (await urlResponse.json()) as { url: string };

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to download stats parquet (${kind}): ${response.status}`);
  }
  return await response.arrayBuffer();
}

/** 最新 LP から比較対象のランク ID を決める。判定できなければ MASTER */
export async function resolveRankId(): Promise<number> {
  const lp = await getLatestLp();
  if (lp !== null) {
    const rankId = getLeagueIdForLp(lp);
    if (rankId !== null) return rankId;
  }
  return LEAGUES.length;
}

/**
 * 同ランク帯の平均勝率を読み込む
 *
 * 失敗時は null を返す（統計が無くてもマッチアップ表は表示できるようにする）。
 */
export async function loadMatchupBenchmarks(): Promise<MatchupBenchmark | null> {
  try {
    const manifest = await fetchStatsManifest();
    if (!manifest) return null;

    const dataMonth = manifest.latestMonth;
    const rankId = await resolveRankId();
    const cacheKey = `${dataMonth}:${rankId}`;
    const hit = cache.get(cacheKey);
    if (hit) return hit;

    const [statsBuffer, detailsBuffer] = await Promise.all([
      fetchStatsParquet(dataMonth, 'matchup_stats'),
      fetchStatsParquet(dataMonth, 'matchup_details'),
    ]);

    const instance = await initDuckDB();
    const statsFile = `stats_matchup_stats_${dataMonth}.parquet`;
    const detailsFile = `stats_matchup_details_${dataMonth}.parquet`;

    await instance.db.registerFileBuffer(statsFile, new Uint8Array(statsBuffer));
    await instance.db.registerFileBuffer(detailsFile, new Uint8Array(detailsBuffer));
    await instance.conn.query(
      `CREATE OR REPLACE TABLE ${STATS_TABLE} AS SELECT * FROM read_parquet('${statsFile}')`
    );
    await instance.conn.query(
      `CREATE OR REPLACE TABLE ${DETAILS_TABLE} AS SELECT * FROM read_parquet('${detailsFile}')`
    );

    const stmt = await instance.conn.prepare(`
      SELECT
        s.character_alpha AS my_character,
        d.opponent_character_alpha AS opponent_character,
        d.opponent_input_type AS opponent_input_type,
        AVG(d.win_rate) * 100 AS avg_win_rate
      FROM ${DETAILS_TABLE} d
      JOIN ${STATS_TABLE} s
        ON s.data_month = d.data_month
       AND s.rank_id = d.rank_id
       AND s.character_id = d.character_id
       AND s.input_type = d.input_type
      WHERE d.data_month = $1
        AND d.rank_id = $2
        AND d.character_id <> d.opponent_character_id
      GROUP BY my_character, opponent_character, opponent_input_type
    `);
    const result = await stmt.query(dataMonth, rankId);
    await stmt.close();

    const rows = result.toArray() as unknown as {
      my_character: string;
      opponent_character: string;
      opponent_input_type: string;
      avg_win_rate: number;
    }[];

    const byMatchup = new Map<string, number>();
    for (const row of rows) {
      const inputLabel = DIA_INPUT_LABELS[row.opponent_input_type] ?? row.opponent_input_type;
      byMatchup.set(
        benchmarkKey(row.my_character, row.opponent_character, inputLabel),
        Number(row.avg_win_rate)
      );
    }

    const benchmark: MatchupBenchmark = {
      dataMonth,
      rankId,
      rankName: LEAGUES[rankId - 1]?.name ?? String(rankId),
      byMatchup,
    };
    cache.set(cacheKey, benchmark);
    console.log(
      `[Stats] バックラー統計を読み込みました: ${dataMonth} / ${benchmark.rankName} (${byMatchup.size} 件)`
    );
    return benchmark;
  } catch (error) {
    console.warn('[Stats] バックラー統計の読み込みに失敗しました:', error);
    return null;
  }
}

/** テスト用にキャッシュをクリアする */
export function clearMatchupBenchmarkCache(): void {
  cache.clear();
}
