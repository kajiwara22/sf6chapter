import { describe, it, expect } from 'vitest';
import { computeLpAxisTicks, computeEquidistantPositions, buildLinePath, findNearestIndex } from './components/LpChart';

describe('computeLpAxisTicks', () => {
  it('通常の値域は200刻みで目盛りを作る', () => {
    const result = computeLpAxisTicks(21280, 23265);
    expect(result.min).toBe(21200);
    expect(result.max).toBe(23400);
    expect(result.ticks[0]).toBe(21200);
    expect(result.ticks[result.ticks.length - 1]).toBe(23400);
    expect(result.ticks.length).toBe(12);
  });

  it('狭い値域でも200刻みになる', () => {
    const result = computeLpAxisTicks(21000, 21300);
    expect(result.min).toBe(21000);
    expect(result.max).toBe(21400);
    expect(result.ticks).toEqual([21000, 21200, 21400]);
  });

  it('目盛りが多くなりすぎる場合はステップを拡大する', () => {
    const result = computeLpAxisTicks(20000, 24000);
    expect(result.min).toBe(20000);
    expect(result.max).toBe(24000);
    // 200刻みだと21本になるため、400刻みに拡大される
    expect(result.ticks.length).toBe(11);
    expect(result.ticks[1] - result.ticks[0]).toBe(400);
  });

  it('最小値と最大値が同じでも目盛りを返す', () => {
    const result = computeLpAxisTicks(22000, 22000);
    expect(result.min).toBe(22000);
    expect(result.max).toBe(22000);
    expect(result.ticks).toEqual([22000]);
  });
});

describe('findNearestIndex', () => {
  const values = [0, 10, 20, 30];

  it('最も近い要素のインデックスを返す', () => {
    expect(findNearestIndex(values, 12)).toBe(1);
    expect(findNearestIndex(values, 18)).toBe(2);
    expect(findNearestIndex(values, 29)).toBe(3);
  });

  it('ちょうど中間の場合は小さい側を返す', () => {
    expect(findNearestIndex(values, 15)).toBe(1);
  });

  it('範囲外は端のインデックスを返す', () => {
    expect(findNearestIndex(values, -5)).toBe(0);
    expect(findNearestIndex(values, 100)).toBe(3);
  });

  it('空配列は -1', () => {
    expect(findNearestIndex([], 10)).toBe(-1);
  });
});

describe('computeEquidistantPositions', () => {
  it('各点を等間隔に配置する（時刻の長さは考慮しない）', () => {
    expect(computeEquidistantPositions(3, 100, 300)).toEqual([100, 250, 400]);
  });

  it('両端は left と left + width になる', () => {
    const positions = computeEquidistantPositions(5, 0, 400);
    expect(positions[0]).toBe(0);
    expect(positions[positions.length - 1]).toBe(400);
    expect(positions).toEqual([0, 100, 200, 300, 400]);
  });

  it('1点のみの場合は中央に配置する', () => {
    expect(computeEquidistantPositions(1, 100, 300)).toEqual([250]);
  });

  it('0点の場合は空配列', () => {
    expect(computeEquidistantPositions(0, 100, 300)).toEqual([]);
  });
});

describe('buildLinePath', () => {
  it('2点未満は空文字', () => {
    expect(buildLinePath([])).toBe('');
    expect(buildLinePath([{ x: 0, y: 0 }])).toBe('');
  });

  it('2点は直線になる', () => {
    expect(buildLinePath([{ x: 0, y: 0 }, { x: 10, y: 10 }])).toBe('M0.0,0.0 L10.0,10.0');
  });

  it('3点以上は3次ベジェ（C）で補間される', () => {
    const path = buildLinePath([
      { x: 0, y: 0 },
      { x: 10, y: 20 },
      { x: 20, y: 0 },
    ]);
    expect(path.startsWith('M0.0,0.0')).toBe(true);
    expect((path.match(/C/g) ?? []).length).toBe(2);
  });

  it('水平に並んだ点は水平の曲線になる', () => {
    const path = buildLinePath([
      { x: 0, y: 50 },
      { x: 10, y: 50 },
      { x: 20, y: 50 },
    ]);
    // 制御点の y も 50 になる
    expect(path).toContain('C');
    expect(path.match(/50\.0/g)?.length).toBeGreaterThanOrEqual(4);
  });
});
