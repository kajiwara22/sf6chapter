import { describe, it, expect } from 'vitest';
import {
  buildDriveSvg,
  buildGaugeNoticeHtml,
  buildGaugeRoundsHtml,
  buildRoundStatsTableHtml,
  buildSaSvg,
  buildStepPath,
  buildYoutubeUrl,
  computeTimeTicks,
  DRIVE_MAX,
  formatClock,
  formatSeconds,
  getRoundDuration,
  resolveGaugeSideLabels,
  SA_MAX,
  sideText,
  type GaugeSideLabels,
} from './components/RoundGaugeChart';
import type { GaugeData, GaugeRound, RoundStatsRow } from '@shared/types';

/** ADR-048 のデータモデル例に近いラウンド */
const round: GaugeRound = {
  round: 1,
  roundStartTime: 21.0,
  roundEndTime: 72.25,
  endReason: 'next_round',
  bannerDetected: true,
  player1: {
    visibleFrom: 0.57,
    visibleTo: 50.3,
    coverage: 0.958,
    drive: [
      [0.57, 5.88],
      [3.03, 5.16],
      [12.03, 0.0],
    ],
    driveBurnout: [[12.03, 50.18]],
    sa: [
      [0.78, 0],
      [22.32, 1],
      [47.4, 2],
    ],
    saProgress: [
      [0.78, 0.0],
      [22.2, 0.98],
    ],
    saCriticalArt: [],
  },
  player2: {
    visibleFrom: 0.5,
    visibleTo: 50.0,
    coverage: 0.9,
    drive: [
      [0.5, 6],
      [10, 3],
    ],
    driveBurnout: [],
    sa: [
      [0.5, 0],
      [20, 1],
    ],
    saProgress: [],
    saCriticalArt: [[30, 35]],
  },
};

const plainLabels: GaugeSideLabels = { player1: null, player2: null };
const selfP1Labels: GaugeSideLabels = { player1: 'self', player2: 'opponent' };

describe('formatSeconds', () => {
  it('整数に近い値は小数点なしで表示する', () => {
    expect(formatSeconds(0)).toBe('0s');
    expect(formatSeconds(51)).toBe('51s');
  });

  it('小数は1桁で表示する', () => {
    expect(formatSeconds(12.5)).toBe('12.5s');
  });

  it('不正な値は 0s にする', () => {
    expect(formatSeconds(Number.NaN)).toBe('0s');
  });
});

describe('formatClock', () => {
  it('分:秒形式に変換する', () => {
    expect(formatClock(21)).toBe('0:21');
    expect(formatClock(72.25)).toBe('1:12');
  });

  it('負の値は 0:00 にする', () => {
    expect(formatClock(-5)).toBe('0:00');
  });
});

describe('buildYoutubeUrl', () => {
  it('ラウンド開始時点のリンクを生成する', () => {
    expect(buildYoutubeUrl('DSgD_bQhxp0', 21.9)).toBe('https://www.youtube.com/watch?v=DSgD_bQhxp0&t=21s');
  });
});

describe('computeTimeTicks', () => {
  it('0〜100% を基本に目盛りを作る', () => {
    expect(computeTimeTicks(100)).toEqual([0, 25, 50, 75, 100]);
  });

  it('短いラウンドでは目盛りを間引く', () => {
    const ticks = computeTimeTicks(2);
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBe(2);
    expect(ticks.length).toBeLessThan(5);
  });

  it('不正な値でも 0 と 1 を返す', () => {
    expect(computeTimeTicks(0)).toEqual([0, 1]);
  });
});

describe('buildStepPath', () => {
  const scaleX = (t: number) => t * 10;
  const scaleY = (v: number) => v;

  it('変化点が空なら空文字', () => {
    expect(buildStepPath([], scaleX, scaleY, 10)).toBe('');
  });

  it('1点は endTime まで水平に延長する', () => {
    expect(buildStepPath([[1, 2]], scaleX, scaleY, 3)).toBe('M10.0,2.0 L30.0,2.0');
  });

  it('値の保持と変化をステップで表現する', () => {
    expect(buildStepPath([[0, 1], [2, 3]], scaleX, scaleY, 4)).toBe(
      'M0.0,1.0 L20.0,1.0 L20.0,3.0 L40.0,3.0',
    );
  });

  it('endTime が最後の変化点以前なら延長しない', () => {
    expect(buildStepPath([[0, 1], [2, 3]], scaleX, scaleY, 2)).toBe(
      'M0.0,1.0 L20.0,1.0 L20.0,3.0',
    );
  });
});

describe('getRoundDuration', () => {
  it('roundEndTime - roundStartTime を返す', () => {
    expect(getRoundDuration(round)).toBeCloseTo(51.25, 5);
  });

  it('0以下なら1にフォールバックする', () => {
    expect(getRoundDuration({ ...round, roundStartTime: 10, roundEndTime: 10 })).toBe(1);
  });
});

describe('buildDriveSvg', () => {
  it('両サイドの折れ線とバーンアウト帯を含む', () => {
    const svg = buildDriveSvg(round, plainLabels);
    expect(svg).toContain('gg-line-player1');
    expect(svg).toContain('gg-line-player2');
    expect(svg).toContain('gg-band-player1');
    // 2P 側にバーンアウトは無い
    expect(svg).not.toContain('gg-band-player2');
    // 縦軸の最大値ラベル
    expect(svg).toContain(`>${DRIVE_MAX}</text>`);
  });
});

describe('buildSaSvg', () => {
  it('CA マーカーを含み、バーンアウト帯は含まない', () => {
    const svg = buildSaSvg(round, plainLabels);
    expect(svg).toContain('gg-marker-player2');
    expect(svg).not.toContain('gg-marker-player1');
    expect(svg).not.toContain('gg-band-player');
    expect(svg).toContain(`>${SA_MAX}</text>`);
  });
});

describe('sideText', () => {
  it('自分/相手/1P/2P を切り替える', () => {
    expect(sideText('self', 'player1')).toBe('自分');
    expect(sideText('opponent', 'player2')).toBe('相手');
    expect(sideText(null, 'player1')).toBe('1P');
    expect(sideText(null, 'player2')).toBe('2P');
  });
});

describe('resolveGaugeSideLabels', () => {
  const myId = 1319673732;

  it('Battlelog が無ければ 1P/2P 表示（null）', () => {
    expect(
      resolveGaugeSideLabels({ player1Character: 'GOUKI', player2Character: 'JP', myPlayerId: myId }),
    ).toEqual({ player1: null, player2: null });
  });

  it('自分の short_id が無ければ 1P/2P 表示（null）', () => {
    const labels = resolveGaugeSideLabels({
      player1Character: 'GOUKI',
      player2Character: 'JP',
      myPlayerId: myId,
      battlelog: { p1ShortId: 1, p2ShortId: 2, p1Character: 'GOUKI', p2Character: 'JP' },
    });
    expect(labels).toEqual({ player1: null, player2: null });
  });

  it('p1 が自分なら player1 を自分にする', () => {
    const labels = resolveGaugeSideLabels({
      player1Character: 'GOUKI',
      player2Character: 'JP',
      myPlayerId: myId,
      battlelog: { p1ShortId: myId, p2ShortId: 2, p1Character: 'GOUKI', p2Character: 'JP' },
    });
    expect(labels).toEqual({ player1: 'self', player2: 'opponent' });
  });

  it('p2 が自分なら player2 を自分にする（キャラで判別）', () => {
    const labels = resolveGaugeSideLabels({
      player1Character: 'JP',
      player2Character: 'GOUKI',
      myPlayerId: myId,
      battlelog: { p1ShortId: 2, p2ShortId: myId, p1Character: 'JP', p2Character: 'GOUKI' },
    });
    expect(labels).toEqual({ player1: 'opponent', player2: 'self' });
  });

  it('Battlelog の位置が動画と入れ替わっていてもキャラクターで自分のサイドを特定する', () => {
    const labels = resolveGaugeSideLabels({
      player1Character: 'GOUKI',
      player2Character: 'JP',
      myPlayerId: myId,
      battlelog: { p1ShortId: 2, p2ShortId: myId, p1Character: 'JP', p2Character: 'GOUKI' },
    });
    expect(labels).toEqual({ player1: 'self', player2: 'opponent' });
  });

  it('ミラーマッチで判別できない場合は Battlelog の位置でフォールバックする', () => {
    const labels = resolveGaugeSideLabels({
      player1Character: 'GOUKI',
      player2Character: 'GOUKI',
      myPlayerId: myId,
      battlelog: { p1ShortId: myId, p2ShortId: 2, p1Character: 'GOUKI', p2Character: 'GOUKI' },
    });
    expect(labels).toEqual({ player1: 'self', player2: 'opponent' });
  });

  it('キャラクター名の大文字小文字・空白を無視する', () => {
    const labels = resolveGaugeSideLabels({
      player1Character: 'JP',
      player2Character: ' gouki ',
      myPlayerId: myId,
      battlelog: { p1ShortId: 2, p2ShortId: myId, p1Character: 'JP', p2Character: 'Gouki' },
    });
    expect(labels).toEqual({ player1: 'opponent', player2: 'self' });
  });
});

describe('buildGaugeRoundsHtml', () => {
  it('gauges が無ければ「ゲージデータなし」', () => {
    expect(buildGaugeRoundsHtml('vid', null, plainLabels)).toContain('ゲージデータなし');
  });

  it('rounds が空でも「ゲージデータなし」', () => {
    const gauges: GaugeData = { videoId: 'vid', matchId: 'vid_1', rounds: [] };
    expect(buildGaugeRoundsHtml('vid', gauges, plainLabels)).toContain('ゲージデータなし');
  });

  it('ラウンドごとのブロックと YouTube リンクを生成する', () => {
    const gauges: GaugeData = { videoId: 'DSgD_bQhxp0', matchId: 'DSgD_bQhxp0_21', rounds: [round] };
    const html = buildGaugeRoundsHtml('DSgD_bQhxp0', gauges, selfP1Labels);
    expect(html).toContain('Round 1');
    expect(html).toContain('https://www.youtube.com/watch?v=DSgD_bQhxp0&t=21s');
    expect(html).toContain('自分');
    expect(html).toContain('相手');
  });
});

describe('buildGaugeNoticeHtml', () => {
  it('ラウンド数不一致なら注意書きを返す', () => {
    const gauges: GaugeData = {
      videoId: 'vid',
      matchId: 'vid_1',
      detectedRoundCount: 2,
      battlelogRoundCount: 3,
      roundCountMatch: false,
      rounds: [],
    };
    expect(buildGaugeNoticeHtml(gauges)).toContain('一致しません');
  });

  it('一致・不明なら空文字', () => {
    expect(buildGaugeNoticeHtml(null)).toBe('');
    expect(
      buildGaugeNoticeHtml({ videoId: 'vid', matchId: 'vid_1', roundCountMatch: true, rounds: [] }),
    ).toBe('');
  });
});

describe('buildRoundStatsTableHtml', () => {
  const row: RoundStatsRow = {
    videoId: 'vid',
    matchId: 'vid_1',
    round: 1,
    side: 'player1',
    character: 'GOUKI',
    roundStartTime: 21,
    roundEndTime: 72,
    durationSec: 51,
    driveMin: 0,
    driveAvg: 4.2,
    driveEnd: 6,
    saMax: 2,
    saUsedCount: 1,
    detectionCoverage: 0.958,
    counterCount: 3,
    punishCounterCount: 1,
  };

  it('データが無ければ「集計データなし」', () => {
    expect(buildRoundStatsTableHtml([], plainLabels)).toContain('集計データなし');
  });

  it('集計値を表示する', () => {
    const html = buildRoundStatsTableHtml([row], selfP1Labels);
    expect(html).toContain('Round 1');
    expect(html).toContain('自分');
    expect(html).toContain('GOUKI');
    expect(html).toContain('4.2');
    expect(html).toContain('96%');
  });

  it('カウンター・パニッシュカウンター回数を表示する（ADR-049）', () => {
    const html = buildRoundStatsTableHtml([row], selfP1Labels);
    expect(html).toContain('カウンタ');
    expect(html).toContain('パニッシュ');
    expect(html).toContain('gg-stats-counter');
    expect(html).toContain('>3</td>');
    expect(html).toContain('>1</td>');
  });

  it('未計測（null）は "-"、0 件は "0" と區別する', () => {
    const unmeasured = buildRoundStatsTableHtml(
      [{ ...row, counterCount: null, punishCounterCount: null }],
      selfP1Labels,
    );
    const zero = buildRoundStatsTableHtml(
      [{ ...row, counterCount: 0, punishCounterCount: 0 }],
      selfP1Labels,
    );
    expect(unmeasured).toContain('>-</td>');
    expect(zero).toContain('>0</td>');
  });
});
