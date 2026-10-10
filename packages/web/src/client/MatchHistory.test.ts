import { describe, it, expect } from 'vitest';
import { createRoundBadge, createRoundCell, createCounterBadge, formatCounterText } from './components/MatchHistory';
import type { MatchHistoryRow } from '@shared/types';

const baseRow: MatchHistoryRow = {
  myCharacter: 'JP',
  myInputType: 0,
  result: 'win',
  myRounds: '[1,6]',
  oppRounds: '[0,0]',
  opponentName: null,
  opponentCharacter: 'Ryu',
  opponentInputType: 0,
  battleTypeName: 'Ranked',
  replayId: 'ABC123',
  uploadedAt: '2026-01-01T00:00:00Z',
  videoId: null,
  startTime: null,
  matchId: null,
  selfSide: 'player1',
  roundCounters: [],
};

describe('createRoundBadge', () => {
  it('決着方法IDに対応するバッジ（表示名・配色）を生成する', () => {
    const html = createRoundBadge(1);
    expect(html).toContain('class="round-badge"');
    expect(html).toContain('>V</span>');
    expect(html).toContain('#2C003E');
    expect(html).toContain('通常勝利');
  });

  it('OD / SA / CA / P など複数文字の表示名も生成できる', () => {
    expect(createRoundBadge(5)).toContain('>OD</span>');
    expect(createRoundBadge(6)).toContain('>SA</span>');
    expect(createRoundBadge(7)).toContain('>CA</span>');
    expect(createRoundBadge(8)).toContain('>P</span>');
  });

  it('未知のIDは "?" を表示する', () => {
    expect(createRoundBadge(99)).toContain('>?</span>');
  });
});

describe('createRoundCell', () => {
  it('自分と相手のラウンドを上下2段で表示する', () => {
    const html = createRoundCell(baseRow);

    expect(html).toContain('round-side-self');
    expect(html).toContain('round-side-opponent');
    // 自分 [1,6] → V, SA
    expect(html).toContain('>V</span>');
    expect(html).toContain('>SA</span>');
    // 相手 [0,0] → L, L
    expect(html.match(/>L<\/span>/g)?.length).toBe(2);
  });

  it('round_results が無い（YouTube側のみの）行は "-"', () => {
    const html = createRoundCell({ ...baseRow, myRounds: null, oppRounds: null });
    expect(html).toBe('<span class="text-muted">-</span>');
  });

  it('ラウンドバッジにそのラウンドのカウンター回数を併記する（ADR-049）', () => {
    const html = createRoundCell({
      ...baseRow,
      selfSide: 'player1',
      roundCounters: [
        { matchId: 'vid_1', round: 1, side: 'player1', counterCount: 2, punishCounterCount: 1 },
        { matchId: 'vid_1', round: 2, side: 'player1', counterCount: 0, punishCounterCount: 3 },
        { matchId: 'vid_1', round: 1, side: 'player2', counterCount: 0, punishCounterCount: 0 },
        { matchId: 'vid_1', round: 2, side: 'player2', counterCount: 1, punishCounterCount: 0 },
      ],
    });

    // 自分 R1: C2 PC1 / R2: PC3
    expect(html).toContain('>C2 PC1</span>');
    expect(html).toContain('>PC3</span>');
    // 相手 R2: C1（R1 は 0 件なのでバッジなし）
    expect(html).toContain('>C1</span>');
  });

  it('自分が player2 の場合はサイドを入れ替えて表示する（ADR-049）', () => {
    const html = createRoundCell({
      ...baseRow,
      selfSide: 'player2',
      roundCounters: [
        { matchId: 'vid_1', round: 1, side: 'player1', counterCount: 1, punishCounterCount: 0 },
        { matchId: 'vid_1', round: 1, side: 'player2', counterCount: 0, punishCounterCount: 2 },
      ],
    });

    // 自分（player2）側の行に PC2、相手（player1）側の行に C1
    const [selfLine, oppLine] = html.split('round-side-opponent');
    expect(selfLine).toContain('>PC2</span>');
    expect(oppLine).toContain('>C1</span>');
  });

  it('round_results が無くてもカウンター回数があれば表示する', () => {
    const html = createRoundCell({
      ...baseRow,
      myRounds: null,
      oppRounds: null,
      roundCounters: [
        { matchId: 'vid_1', round: 1, side: 'player1', counterCount: 2, punishCounterCount: 1 },
        { matchId: 'vid_1', round: 2, side: 'player1', counterCount: 1, punishCounterCount: 0 },
        { matchId: 'vid_1', round: 1, side: 'player2', counterCount: 3, punishCounterCount: 0 },
      ],
    });

    expect(html).toContain('round-side-self');
    expect(html).toContain('>C3 PC1</span>');
    expect(html).toContain('>C3</span>');
  });

  it('未計測（null のみ）の行は "-" のまま', () => {
    const html = createRoundCell({
      ...baseRow,
      myRounds: null,
      oppRounds: null,
      roundCounters: [{ matchId: 'vid_1', round: 1, side: 'player1', counterCount: null, punishCounterCount: null }],
    });
    expect(html).toBe('<span class="text-muted">-</span>');
  });
});

describe('formatCounterText / createCounterBadge', () => {
  it('0 件の項目は省略する', () => {
    expect(formatCounterText(2, 1)).toBe('C2 PC1');
    expect(formatCounterText(0, 3)).toBe('PC3');
    expect(formatCounterText(2, 0)).toBe('C2');
    expect(formatCounterText(0, 0)).toBe('');
    expect(formatCounterText(null, null)).toBe('');
  });

  it('バッジHTMLに件数とツールチップを含める', () => {
    const html = createCounterBadge(2, 1);
    expect(html).toContain('class="round-counter"');
    expect(html).toContain('C2 PC1');
    expect(html).toContain('COUNTER 2 / PUNISH COUNTER 1');
    expect(createCounterBadge(0, 0)).toBe('');
  });
});
