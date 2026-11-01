import { describe, it, expect } from 'vitest';
import { buildRoundScoreHtml, formatRate } from './components/RoundScorePanel';
import { roundMethodCode } from './search';
import type { RoundScore } from '@shared/types';

/** テスト用の集計結果 */
function sampleScore(overrides: Partial<RoundScore> = {}): RoundScore {
  return {
    totalMatches: 10,
    firstRound: [
      { won: true, total: 6, wins: 4 },
      { won: false, total: 4, wins: 1 },
    ],
    sides: [
      { side: '1P', total: 4, wins: 2, fullRoundTotal: 2, fullRoundWins: 1 },
      { side: '2P', total: 6, wins: 3, fullRoundTotal: 3, fullRoundWins: 2 },
    ],
    fullRoundTotal: 5,
    fullRoundWins: 3,
    wonMethods: [
      { method: 'V', count: 8 },
      { method: 'SA', count: 2 },
    ],
    lostMethods: [
      { method: 'V', count: 5 },
      { method: 'P', count: 1 },
    ],
    totalRoundsWon: 10,
    totalRoundsLost: 6,
    ...overrides,
  };
}

describe('formatRate', () => {
  it('割合を小数1桁のパーセントにする', () => {
    expect(formatRate(4, 6)).toBe('66.7%');
    expect(formatRate(0, 5)).toBe('0.0%');
    expect(formatRate(5, 5)).toBe('100.0%');
  });

  it('分母が 0 なら — を返す', () => {
    expect(formatRate(0, 0)).toBe('—');
    expect(formatRate(3, -1)).toBe('—');
  });
});

describe('roundMethodCode', () => {
  it('勝利方法IDを決まり手コードに変換する', () => {
    expect(roundMethodCode(1)).toBe('V');
    expect(roundMethodCode(2)).toBe('C');
    expect(roundMethodCode(3)).toBe('T');
    expect(roundMethodCode(5)).toBe('OD');
    expect(roundMethodCode(6)).toBe('SA');
    expect(roundMethodCode(7)).toBe('CA');
    expect(roundMethodCode(8)).toBe('P');
  });

  it('LOSS(0) と DRAW(4) は勝ちの決まり手にしない', () => {
    expect(roundMethodCode(0)).toBeNull();
    expect(roundMethodCode(4)).toBeNull();
    expect(roundMethodCode(null)).toBeNull();
    expect(roundMethodCode(undefined)).toBeNull();
  });

  it('未知の値は UNKNOWN にする', () => {
    expect(roundMethodCode(9)).toBe('UNKNOWN');
  });
});

describe('buildRoundScoreHtml', () => {
  it('データがない場合は案内を出す', () => {
    expect(buildRoundScoreHtml(null)).toContain('データがありません');
    expect(buildRoundScoreHtml(sampleScore({ totalMatches: 0 }))).toContain('データがありません');
  });

  it('1R の勝敗ごとの勝率を表示する', () => {
    const html = buildRoundScoreHtml(sampleScore());
    // 1R を取った: 4/6 = 66.7% / 落とした: 1/4 = 25.0%
    expect(html).toContain('1R を取った試合の勝率');
    expect(html).toContain('66.7%');
    expect(html).toContain('25.0%');
    expect(html).toContain('取った');
    expect(html).toContain('落とした');
  });

  it('1P / 2P 別と 3R 勝率を表示する', () => {
    const html = buildRoundScoreHtml(sampleScore());
    expect(html).toContain('1P / 2P 別');
    expect(html).toContain('>1P<');
    expect(html).toContain('>2P<');
    // 3R: 3/5 = 60.0%
    expect(html).toContain('60.0%');
    // 2P の 3R 内訳
    expect(html).toContain('(2/3)');
  });

  it('フルラウンド率を表示する', () => {
    const html = buildRoundScoreHtml(sampleScore());
    // 5/10 = 50.0%
    expect(html).toContain('フルラウンド率');
    expect(html).toContain('50.0%');
  });

  it('取った / 落としたラウンドの決まり手を表示する', () => {
    const html = buildRoundScoreHtml(sampleScore());
    expect(html).toContain('取ったラウンド（自分が決めた）');
    expect(html).toContain('落としたラウンド（相手に決められた）');
    expect(html).toContain('通常KO');
    expect(html).toContain('SA KO');
    expect(html).toContain('パーフェクト');
    // 合計（won 10 / lost 6）
    expect(html).toContain('10');
    expect(html).toContain('6');
  });

  it('決まり手がない側はデータなしを出す', () => {
    const html = buildRoundScoreHtml(sampleScore({ lostMethods: [], totalRoundsLost: 0 }));
    expect(html).toContain('データがありません');
    expect(html).toContain('取ったラウンド（自分が決めた）');
  });

  it('決まり手名はエスケープされる', () => {
    const html = buildRoundScoreHtml(
      sampleScore({ wonMethods: [{ method: '<script>', count: 1 }], totalRoundsWon: 1 }),
    );
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('対象試合数と注記を表示する', () => {
    const html = buildRoundScoreHtml(sampleScore());
    expect(html).toContain('対象: 10試合');
    expect(html).toContain('1P/2P は自分視点に正規化');
  });
});
