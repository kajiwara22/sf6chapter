import { describe, it, expect } from 'vitest';
import {
  LEAGUES,
  getLeagueForLp,
  getLeagueEndLp,
  getStarBoundaries,
  getAllLeagueBoundaries,
  getStarSegments,
  computeYAxisRange,
} from '../shared/leagues';

const byName = (name: string) => LEAGUES.find((league) => league.name === name)!;

describe('getLeagueForLp', () => {
  it('各リーグの開始LPで切り替わる', () => {
    expect(getLeagueForLp(0)?.name).toBe('ROOKIE');
    expect(getLeagueForLp(999)?.name).toBe('ROOKIE');
    expect(getLeagueForLp(1000)?.name).toBe('IRON');
    expect(getLeagueForLp(3000)?.name).toBe('BRONZE');
    expect(getLeagueForLp(5000)?.name).toBe('SILVER');
    expect(getLeagueForLp(9000)?.name).toBe('GOLD');
    expect(getLeagueForLp(13000)?.name).toBe('PLATINUM');
    expect(getLeagueForLp(19000)?.name).toBe('DIAMOND');
    expect(getLeagueForLp(24999)?.name).toBe('DIAMOND');
    expect(getLeagueForLp(25000)?.name).toBe('MASTER');
  });

  it('負のLPは null', () => {
    expect(getLeagueForLp(-1)).toBeNull();
  });
});

describe('getLeagueEndLp', () => {
  it('次のリーグの開始LPを返す', () => {
    expect(getLeagueEndLp(byName('ROOKIE'))).toBe(1000);
    expect(getLeagueEndLp(byName('DIAMOND'))).toBe(25000);
  });

  it('最上位リーグ（Master）は null', () => {
    expect(getLeagueEndLp(byName('MASTER'))).toBeNull();
  });
});

describe('getStarBoundaries', () => {
  it('Diamond の☆境界は 1200 刻み', () => {
    expect(getStarBoundaries(byName('DIAMOND'))).toEqual([20200, 21400, 22600, 23800]);
  });

  it('Rookie の☆境界は 200 刻み', () => {
    expect(getStarBoundaries(byName('ROOKIE'))).toEqual([200, 400, 600, 800]);
  });

  it('Master は☆なしのため空配列', () => {
    expect(getStarBoundaries(byName('MASTER'))).toEqual([]);
  });
});

describe('getAllLeagueBoundaries', () => {
  it('昇順で返す', () => {
    const boundaries = getAllLeagueBoundaries();
    const sorted = [...boundaries].sort((a, b) => a - b);
    expect(boundaries).toEqual(sorted);
  });

  it('Diamond の☆境界を含む', () => {
    const boundaries = getAllLeagueBoundaries();
    for (const lp of [20200, 21400, 22600, 23800]) {
      expect(boundaries).toContain(lp);
    }
  });
});

describe('getStarSegments', () => {
  it('Diamond は5区間で☆が増える', () => {
    const diamond = getStarSegments().filter((segment) => segment.leagueName === 'DIAMOND');
    expect(diamond).toHaveLength(5);
    expect(diamond[0]).toMatchObject({
      star: 1,
      startLp: 19000,
      endLp: 20200,
      label: 'DIAMOND ☆',
    });
    expect(diamond[2]).toMatchObject({
      star: 3,
      startLp: 21400,
      endLp: 22600,
      label: 'DIAMOND ☆☆☆',
    });
  });

  it('Master は☆なしで上限なし', () => {
    const master = getStarSegments().find((segment) => segment.leagueName === 'MASTER')!;
    expect(master).toMatchObject({ star: 0, startLp: 25000, endLp: null, label: 'MASTER' });
  });
});

describe('computeYAxisRange', () => {
  it('データをリーグ境界で挟んだ範囲を返す', () => {
    // Diamond ☆3〜☆4 の範囲 → 20200〜23800
    expect(computeYAxisRange([21280, 23265])).toEqual({ min: 20200, max: 23800 });
  });

  it('単一の☆区間に収まる場合はその区間全体', () => {
    expect(computeYAxisRange([21500, 22000])).toEqual({ min: 21400, max: 22600 });
  });

  it('複数リーグにまたがる場合も境界で挟む', () => {
    expect(computeYAxisRange([8800, 19100])).toEqual({ min: 8200, max: 20200 });
  });

  it('空配列は 0,0', () => {
    expect(computeYAxisRange([])).toEqual({ min: 0, max: 0 });
  });
});
