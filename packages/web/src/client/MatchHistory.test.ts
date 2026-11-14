import { describe, it, expect } from 'vitest';
import { createRoundBadge, createRoundCell, createGaugeDetailCell } from './components/MatchHistory';
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

  it('カウンター回数は履歴に表示しない（ADR-075）', () => {
    const html = createRoundCell(baseRow);
    expect(html).not.toContain('round-counter');
    expect(html).not.toContain('C2');
    expect(html).not.toContain('PC1');
  });
});

describe('createGaugeDetailCell', () => {
  it('matchId があればゲージ詳細ページ（/matches/{matchId}）へのリンクを生成する', () => {
    const html = createGaugeDetailCell({ ...baseRow, matchId: 'video_20' });

    expect(html).toContain('href="/matches/video_20"');
    expect(html).toContain('history-gauge-link');
    expect(html).toContain('ゲージ詳細');
  });

  it('matchId を URL エンコードする', () => {
    const html = createGaugeDetailCell({ ...baseRow, matchId: 'video id/1' });

    expect(html).toContain('href="/matches/video%20id%2F1"');
  });

  it('matchId が無い（Battlelogのみの）行は "-"', () => {
    expect(createGaugeDetailCell({ ...baseRow, matchId: null })).toBe('<span class="text-muted">-</span>');
  });
});
