import { describe, it, expect } from 'vitest';
import { ROUNDS, getRound, parseRoundIds, countRoundWins, determineResultFromRounds } from './rounds';

describe('ROUNDS / getRound', () => {
  it('ADR-037 / sfbuff の決着方法IDを定義している', () => {
    expect(ROUNDS.map((r) => `${r.id}:${r.name}`)).toEqual([
      '0:L',
      '1:V',
      '2:C',
      '3:T',
      '4:D',
      '5:OD',
      '6:SA',
      '7:CA',
      '8:P',
    ]);
  });

  it('勝敗は 0 のみ負け、4 のみ引き分け、それ以外は勝ち', () => {
    expect(getRound(0).outcome).toBe('loss');
    expect(getRound(4).outcome).toBe('draw');
    for (const id of [1, 2, 3, 5, 6, 7, 8]) {
      expect(getRound(id).outcome).toBe('win');
    }
  });

  it('各ラウンドにバッジの配色が定義されている', () => {
    for (const round of ROUNDS) {
      expect(round.backgroundColor).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(round.textColor).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(round.description).not.toBe('');
    }
  });

  it('未知のIDは "?" を返す', () => {
    const unknown = getRound(99);
    expect(unknown.id).toBe(99);
    expect(unknown.name).toBe('?');
  });
});

describe('parseRoundIds', () => {
  it('NULL / 空文字は空配列', () => {
    expect(parseRoundIds(null)).toEqual([]);
    expect(parseRoundIds(undefined)).toEqual([]);
    expect(parseRoundIds('')).toEqual([]);
  });

  it('不正なJSON・配列以外は空配列', () => {
    expect(parseRoundIds('invalid')).toEqual([]);
    expect(parseRoundIds('{"a":1}')).toEqual([]);
  });

  it('JSON配列を数値配列に変換する', () => {
    expect(parseRoundIds('[1,6]')).toEqual([1, 6]);
    expect(parseRoundIds('[0,2,0]')).toEqual([0, 2, 0]);
  });
});

describe('countRoundWins', () => {
  it('NULL / 空文字は 0 勝', () => {
    expect(countRoundWins(null)).toBe(0);
    expect(countRoundWins(undefined)).toBe(0);
    expect(countRoundWins('')).toBe(0);
  });

  it('不正なJSONは 0 勝', () => {
    expect(countRoundWins('invalid')).toBe(0);
    expect(countRoundWins('{"a":1}')).toBe(0);
  });

  it('通常勝利（1）を数える', () => {
    expect(countRoundWins('[1,1]')).toBe(2);
    expect(countRoundWins('[1,0,1]')).toBe(2);
  });

  it('0 は負けとして数えない', () => {
    expect(countRoundWins('[0,0]')).toBe(0);
    expect(countRoundWins('[1,0]')).toBe(1);
  });

  it('0 以外の勝利方法ID（2/3/5/6/7/8）を勝利として数える（ADR-037）', () => {
    expect(countRoundWins('[0,2,0]')).toBe(1);
    expect(countRoundWins('[5,1]')).toBe(2);
    expect(countRoundWins('[6,1,0]')).toBe(2);
    expect(countRoundWins('[8,1]')).toBe(2);
    expect(countRoundWins('[7,3]')).toBe(2);
  });
});

describe('determineResultFromRounds', () => {
  it('勝利ラウンド数が多い方を勝ちとする', () => {
    expect(determineResultFromRounds('[1,1]', '[0,0]')).toBe('win');
    expect(determineResultFromRounds('[0,0]', '[1,1]')).toBe('loss');
  });

  it('ADR-037の具体例（Chip KO の 2 を単純合計すると draw になるケース）', () => {
    // P1: [1,0,1] → 2勝 / P2: [0,2,0] → 1勝
    expect(determineResultFromRounds('[1,0,1]', '[0,2,0]')).toBe('win');
  });

  it('同数は引き分け', () => {
    expect(determineResultFromRounds('[1,0]', '[1,0]')).toBe('draw');
    expect(determineResultFromRounds('[0,0]', '[0]')).toBe('draw');
  });

  it('round_results が NULL 同士は引き分け', () => {
    expect(determineResultFromRounds(null, null)).toBe('draw');
  });
});
