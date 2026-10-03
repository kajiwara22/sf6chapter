import { describe, it, expect } from 'vitest';
import {
  LEAGUES,
  getLeagueForLp,
  getLeagueEndLp,
  getStarBoundaries,
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

  it('Platinum の☆境界は 1200 刻み', () => {
    expect(getStarBoundaries(byName('PLATINUM'))).toEqual([14200, 15400, 16600, 17800]);
  });

  it('Master は☆なしのため空配列', () => {
    expect(getStarBoundaries(byName('MASTER'))).toEqual([]);
  });
});

describe('computeYAxisRange', () => {
  it('基準LPが属するリーグ帯を範囲に含める', () => {
    // データは Diamond の中だが、軸は Diamond 帯全体（19000〜25000）を含む
    expect(computeYAxisRange([21280, 23265], 22900)).toEqual({ min: 19000, max: 25000 });
  });

  it('基準LPが未指定ならデータ範囲のみ', () => {
    expect(computeYAxisRange([21280, 23265])).toEqual({ min: 21280, max: 23265 });
  });

  it('データがリーグ帯を超える場合はデータ範囲を優先する', () => {
    expect(computeYAxisRange([12500, 26000], 22000)).toEqual({ min: 12500, max: 26000 });
  });

  it('Master は上限なし（データ範囲を使う）', () => {
    expect(computeYAxisRange([25000, 26000], 25500)).toEqual({ min: 25000, max: 26000 });
  });

  it('空配列は 0,0', () => {
    expect(computeYAxisRange([], 22000)).toEqual({ min: 0, max: 0 });
  });
});
