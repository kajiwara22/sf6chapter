/**
 * SF6 Chapter - リーグ定義
 *
 * LP のリーグ境界と☆境界を扱う（ADR-046）。
 *
 * 出典: https://tamiz-blog.com/sf6/lp-rank/ （2024年12月末時点の LP 分布表）
 * sfbuff の marks（1000=IRON, 3000=BRONZE, 5000=SILVER, 9000=GOLD,
 * 13000=PLATINUM, 19000=DIAMOND, 25000=MASTER）とも一致する。
 */

export interface LeagueDefinition {
  /** リーグ名（表示用） */
  name: string;
  /** リーグの開始 LP */
  startLp: number;
  /** 1つ上の☆に上がるのに必要な LP 幅（Master は☆なしのため null） */
  starWidth: number | null;
}

/**
 * リーグ定義（LP の昇順）
 *
 * 各リーグは5つの☆に分かれ、☆の境界は `startLp + starWidth * i`（i = 1..4）。
 * 例: Diamond は 19000 から 1200 刻みで 20200 / 21400 / 22600 / 23800。
 */
export const LEAGUES: LeagueDefinition[] = [
  { name: 'ROOKIE', startLp: 0, starWidth: 200 },
  { name: 'IRON', startLp: 1000, starWidth: 400 },
  { name: 'BRONZE', startLp: 3000, starWidth: 400 },
  { name: 'SILVER', startLp: 5000, starWidth: 800 },
  { name: 'GOLD', startLp: 9000, starWidth: 800 },
  { name: 'PLATINUM', startLp: 13000, starWidth: 1200 },
  { name: 'DIAMOND', startLp: 19000, starWidth: 1200 },
  { name: 'MASTER', startLp: 25000, starWidth: null },
];

/**
 * LP が属するリーグを返す（どのリーグにも満たない場合は null）
 */
export function getLeagueForLp(lp: number): LeagueDefinition | null {
  let found: LeagueDefinition | null = null;
  for (const league of LEAGUES) {
    if (lp >= league.startLp) found = league;
  }
  return found;
}

/**
 * リーグの終端 LP（= 次のリーグの開始 LP）を返す
 * 最上位リーグ（Master）は null
 */
export function getLeagueEndLp(league: LeagueDefinition): number | null {
  const index = LEAGUES.indexOf(league);
  if (index < 0) return null;
  const next = LEAGUES[index + 1];
  return next ? next.startLp : null;
}

/**
 * リーグ内の☆境界 LP を返す（リーグ開始 LP は含まない）
 * Master は☆なしのため空配列
 */
export function getStarBoundaries(league: LeagueDefinition): number[] {
  if (league.starWidth === null) return [];

  const boundaries: number[] = [];
  for (let i = 1; i <= 4; i += 1) {
    boundaries.push(league.startLp + league.starWidth * i);
  }
  return boundaries;
}

/**
 * y軸の表示範囲を計算する
 *
 * データの最小・最大に加え、基準 LP（現在地点）が属するリーグの帯
 * （開始 LP 〜 次のリーグの開始 LP）を含める。これによりリーグ境界線が
 * グラフ内に表示される。
 */
export function computeYAxisRange(
  lps: number[],
  referenceLp?: number,
): { min: number; max: number } {
  if (lps.length === 0) return { min: 0, max: 0 };

  let min = Math.min(...lps);
  let max = Math.max(...lps);

  if (referenceLp !== undefined) {
    const league = getLeagueForLp(referenceLp);
    if (league) {
      min = Math.min(min, league.startLp);
      const end = getLeagueEndLp(league);
      if (end !== null) max = Math.max(max, end);
    }
  }

  return { min, max };
}
