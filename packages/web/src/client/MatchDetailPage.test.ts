/**
 * ゲージ詳細ページ（ADR-051）のユニットテスト
 *
 * DOM 非依存の純関数（パス解析・HTML 生成）のみを対象とする。
 */

import { describe, expect, it } from 'vitest';
import type { Match, RoundStatsRow } from '@shared/types';
import { buildMatchDetailPageHtml, parseMatchDetailPath } from './components/MatchDetailPage';

const match: Match = {
  id: 'vid_20',
  videoId: 'vid',
  videoTitle: 'テスト配信',
  videoPublishedAt: '2026-10-06T14:33:40Z',
  startTime: 20,
  player1: { character: 'JP', side: 'left', result: 'win' },
  player2: { character: 'GOUKI', side: 'right', result: 'loss' },
  detectedAt: '2026-10-06T15:55:41Z',
  confidence: 0.6,
};

const roundRow = (
  side: 'player1' | 'player2',
  round: number,
  result: RoundStatsRow['roundResult'],
  character: string,
): RoundStatsRow => ({
  videoId: 'vid',
  matchId: 'vid_20',
  round,
  side,
  character,
  roundStartTime: 20 * round,
  roundEndTime: 20 * round + 40,
  durationSec: 40,
  roundResult: result,
  roundMethod: 'CA',
  driveMin: 0,
  driveEnd: 3.9,
  saMax: 3,
  saUsedCount: 1,
  saLeftAtEnd: 2,
  detectionCoverage: 0.9,
  healthMin: 5,
  healthEnd: 20,
  maxHitTaken: 55,
  burnoutCount: 1,
  burnoutSec: 10,
  counterCount: 2,
  punishCounterCount: 1,
});

const labels = { player1: 'self' as const, player2: 'opponent' as const };

describe('parseMatchDetailPath', () => {
  it('matchId を取り出す', () => {
    expect(parseMatchDetailPath('/matches/vid_20')).toBe('vid_20');
    expect(parseMatchDetailPath('/matches/vid_20/')).toBe('vid_20');
    expect(parseMatchDetailPath('/matches/DSgD_bQhxp0_2094')).toBe('DSgD_bQhxp0_2094');
  });

  it('詳細ページ以外は null', () => {
    expect(parseMatchDetailPath('/')).toBeNull();
    expect(parseMatchDetailPath('/matches')).toBeNull();
    expect(parseMatchDetailPath('/matches/a/b')).toBeNull();
  });
});

describe('buildMatchDetailPageHtml', () => {
  const roundStats = [
    roundRow('player1', 1, 'win', 'JP'),
    roundRow('player2', 1, 'loss', 'GOUKI'),
    roundRow('player1', 2, 'loss', 'JP'),
    roundRow('player2', 2, 'win', 'GOUKI'),
    roundRow('player1', 3, 'win', 'JP'),
    roundRow('player2', 3, 'loss', 'GOUKI'),
  ];

  it('試合サマリ（勝敗・スコア・キャラ）を表示する', () => {
    const html = buildMatchDetailPageHtml(match, {
      gauges: { videoId: 'vid', matchId: 'vid_20', rounds: [] },
      roundStats,
      labels,
      battlelog: null,
    });

    expect(html).toContain('WIN');
    expect(html).toContain('2 - 1'); // 1P が 2 ラウンド取得
    expect(html).toContain('JP');
    expect(html).toContain('GOUKI');
    expect(html).toContain('YouTubeで見る');
  });

  it('ラウンド集計（勝敗・方法・改善指標）を含む', () => {
    const html = buildMatchDetailPageHtml(match, {
      gauges: { videoId: 'vid', matchId: 'vid_20', rounds: [] },
      roundStats,
      labels,
      battlelog: null,
    });

    expect(html).toContain('ラウンド集計');
    expect(html).toContain('gg-result-win');
    expect(html).toContain('CA');
    expect(html).toContain('1回 / 10.0s');
    expect(html).toContain('3 / 1 / 2');
  });

  it('round_results が無い場合はスコアを不明表示にする', () => {
    const html = buildMatchDetailPageHtml(match, {
      gauges: { videoId: 'vid', matchId: 'vid_20', rounds: [] },
      roundStats: [{ ...roundRow('player1', 1, null, 'JP') }],
      labels,
      battlelog: null,
    });

    expect(html).toContain('—');
  });

  it('低計測率のラウンドがあれば注記を出す', () => {
    const html = buildMatchDetailPageHtml(match, {
      gauges: { videoId: 'vid', matchId: 'vid_20', rounds: [] },
      roundStats: [{ ...roundRow('player1', 1, 'win', 'JP'), detectionCoverage: 0.3 }],
      labels,
      battlelog: null,
    });

    expect(html).toContain('計測率が低いラウンドがあります');
  });
});
