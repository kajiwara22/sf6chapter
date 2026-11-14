/**
 * ゲージ詳細ページ（ADR-051）のユニットテスト
 *
 * DOM 非依存の純関数（パス解析・HTML 生成）のみを対象とする。
 */

import { describe, expect, it } from 'vitest';
import type { Match, RoundStatsRow } from '@shared/types';
import { buildCounterSectionHtml, buildMatchDetailPageHtml, parseMatchDetailPath } from './components/MatchDetailPage';

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
    expect(html).toContain('SA最大');
    expect(html).toContain('SA使用');
    expect(html).toContain('SA残し');
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

  it('サイド表示フィルター（両方 / 自分 / 相手）を含む（ADR-060）', () => {
    const html = buildMatchDetailPageHtml(match, {
      gauges: { videoId: 'vid', matchId: 'vid_20', rounds: [] },
      roundStats,
      labels,
      battlelog: null,
    });

    expect(html).toContain('gg-side-filter');
    expect(html).toContain('data-side="both"');
    expect(html).toContain('自分のみ');
    expect(html).toContain('相手のみ');
  });
});

describe('buildCounterSectionHtml（ADR-075）', () => {
  const counterRow = (
    side: 'player1' | 'player2',
    round: number,
    counter: number | null,
    punish: number | null,
    character: string,
  ): RoundStatsRow => ({
    ...roundRow(side, round, 'win', character),
    counterCount: counter,
    punishCounterCount: punish,
  });

  it('自分/相手の試合合計とラウンド別内訳を表示する', () => {
    const html = buildCounterSectionHtml(
      [
        counterRow('player1', 1, 2, 1, 'JP'),
        counterRow('player2', 1, 3, 2, 'GOUKI'),
        counterRow('player1', 2, 1, 0, 'JP'),
        counterRow('player2', 2, 0, 1, 'GOUKI'),
      ],
      labels,
    );

    expect(html).toContain('カウンター / パニッシュカウンター');
    expect(html).toContain('自分（JP）');
    expect(html).toContain('相手（GOUKI）');
    // 合計: 自分 C3 PC1 / 相手 C3 PC3
    expect(html).toContain('<span class="gg-counter-num">3</span>');
    expect(html).toContain('<span class="gg-counter-num">1</span>');
    // ラウンド別: Round 1 / Round 2 の行
    expect(html).toContain('<td>Round 1</td>');
    expect(html).toContain('<td>Round 2</td>');
    expect(html).toContain('<td>2</td><td>1</td><td>3</td><td>2</td>');
    expect(html).toContain('<td>1</td><td>0</td><td>0</td><td>1</td>');
  });

  it('未計測（null）は "-"、計測済み 0 件は "0" と区別する', () => {
    const html = buildCounterSectionHtml(
      [
        counterRow('player1', 1, null, null, 'JP'),
        counterRow('player2', 1, 0, 0, 'GOUKI'),
      ],
      labels,
    );

    // 自分は未計測
    expect(html).toContain('<span class="gg-counter-num">-</span>');
    // 相手は計測済み 0 件
    expect(html).toContain('<span class="gg-counter-num">0</span>');
  });

  it('カウンター情報が無い場合はセクションを出さない', () => {
    const html = buildCounterSectionHtml([counterRow('player1', 1, null, null, 'JP')], labels);
    expect(html).toBe('');
  });

  it('自分サイドが判定できない場合は 1P / 2P 表示にする', () => {
    const html = buildCounterSectionHtml(
      [counterRow('player1', 1, 1, 0, 'JP'), counterRow('player2', 1, 2, 0, 'GOUKI')],
      { player1: 'opponent', player2: 'opponent' },
    );

    expect(html).toContain('1P（JP）');
    expect(html).toContain('2P（GOUKI）');
  });
});
