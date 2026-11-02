import { describe, it, expect } from 'vitest';
import { createMatchupTable } from './MatchupChart';
import type { MatchupChartRow } from '@shared/types';

function row(overrides: Partial<MatchupChartRow> = {}): MatchupChartRow {
  return {
    opponentCharacter: 'AKUMA',
    opponentInputType: 0,
    opponentInputTypeName: 'Classic',
    total: 10,
    wins: 5,
    losses: 5,
    draws: 0,
    winRate: 50,
    ...overrides,
  };
}

describe('createMatchupTable', () => {
  it('平均勝率がある場合だけ「バックラー平均」列を出す', () => {
    const html = createMatchupTable([row({ benchmarkWinRate: 46.7 })]);
    expect(html).toContain('バックラー平均');
    expect(html).toContain('46.7%');
  });

  it('統計がない場合は列を出さない', () => {
    const html = createMatchupTable([row()]);
    expect(html).not.toContain('バックラー平均');
  });

  it('キャラ合計は入力タイプ別の平均を出す', () => {
    const html = createMatchupTable([
      row({ opponentInputType: 0, opponentInputTypeName: 'Classic', benchmarkWinRate: 46.7 }),
      row({ opponentInputType: 1, opponentInputTypeName: 'Modern', benchmarkWinRate: 53.3 }),
    ]);
    // (46.7 + 53.3) / 2 = 50.0
    expect(html).toContain('50%');
  });

  it('ミラーなど数値がない行は - を出す', () => {
    // 列は数値のある行（AKUMA）で出る。ミラー（LUKE）は欠損として - になる
    const html = createMatchupTable([
      row({ benchmarkWinRate: 46.7 }),
      row({ opponentCharacter: 'LUKE', benchmarkWinRate: null }),
    ]);
    expect(html).toContain('<td class="matchup-benchmark">-</td>');
  });

  it('キャラ名をエスケープする', () => {
    const html = createMatchupTable([row({ opponentCharacter: '<script>' })]);
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });
});
