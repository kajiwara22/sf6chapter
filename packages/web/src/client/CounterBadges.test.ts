import { describe, it, expect } from 'vitest';
import { createCounterBadge, formatCounterText, formatCounterCount } from './components/CounterBadges';

describe('formatCounterText', () => {
  it('0 件の項目は省略する', () => {
    expect(formatCounterText(2, 1)).toBe('C2 PC1');
    expect(formatCounterText(0, 3)).toBe('PC3');
    expect(formatCounterText(2, 0)).toBe('C2');
    expect(formatCounterText(0, 0)).toBe('');
    expect(formatCounterText(null, null)).toBe('');
  });
});

describe('createCounterBadge', () => {
  it('バッジHTMLに件数とツールチップを含める', () => {
    const html = createCounterBadge(2, 1);
    expect(html).toContain('class="round-counter"');
    expect(html).toContain('C2 PC1');
    expect(html).toContain('COUNTER 2 / PUNISH COUNTER 1');
    expect(createCounterBadge(0, 0)).toBe('');
  });
});

describe('formatCounterCount', () => {
  it('未計測（null）は "-"、計測済み 0 件は "0"', () => {
    expect(formatCounterCount(null)).toBe('-');
    expect(formatCounterCount(undefined)).toBe('-');
    expect(formatCounterCount(0)).toBe('0');
    expect(formatCounterCount(2.4)).toBe('2');
  });
});
