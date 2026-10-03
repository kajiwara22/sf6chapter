import { describe, it, expect } from 'vitest';
import { computeLpAxisTicks, findNearestIndex } from './components/LpChart';

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
