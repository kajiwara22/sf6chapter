/**
 * SF6 Chapter - ラウンド別ドライブ／SAゲージ推移チャート（ADR-048）
 *
 * 依存ライブラリを追加せず、SVG でステップチャートを描画する（ADR-046 の LpChart に準拠）。
 * - 1ラウンド = 1ブロック。上部がドライブ（0〜6）、下部がSA（0〜3）
 * - 横軸はラウンド開始からの経過秒。動画内の絶対時刻は roundStartTime + 経過秒
 * - 1P / 2P を色で区別し、バーンアウト期間は背景帯、CA 期間はマーカーで示す
 * - データ→SVG文字列の変換は副作用のない純関数に分割し、Vitest でテストする（ADR-040）
 *
 * 生データの 1P/2P は書き換えず、表示ラベルだけを `GaugeSideLabels` で自分視点に変換する。
 */

import type { GaugeData, GaugeRound, GaugeSideData, RoundStatsRow } from '@shared/types';

/** ゲージのサイド（生データのまま） */
export type GaugeSide = 'player1' | 'player2';

/** 表示上のサイド種別。null は「自分/相手」を判定できない（1P/2P表示）ことを表す */
export type GaugeSideLabel = 'self' | 'opponent' | null;

/** 1P/2P の表示ラベル */
export interface GaugeSideLabels {
  player1: GaugeSideLabel;
  player2: GaugeSideLabel;
}

/** ドライブゲージの最大本数 */
export const DRIVE_MAX = 6;

/** SAゲージの最大ストック数 */
export const SA_MAX = 3;

/** チャートの描画幅（viewBox 座標。drive / sa で共通） */
const CHART_WIDTH = 900;

/** ドライブチャートの高さ */
const DRIVE_HEIGHT = 150;

/** SAチャートの高さ */
const SA_HEIGHT = 110;

/** 余白（drive / sa で共通） */
const PADDING = { top: 10, right: 12, bottom: 22, left: 32 };

/** 変化点列の1要素 [経過秒, 値] */
export type GaugeEvent = [number, number];

/** バーンアウト / CA などの期間 [開始経過秒, 終了経過秒] */
export type GaugeSpan = [number, number];

/** 1つのゲージ系列 */
export interface GaugeSeries {
  side: GaugeSide;
  events: GaugeEvent[];
}

/** 期間の描画対象 */
export interface SpanWithSide {
  side: GaugeSide;
  start: number;
  end: number;
}

/** `buildGaugeSvg` の引数 */
export interface GaugeSvgParams {
  /** チャート種別（viewBox の高さとクラスに使う） */
  variant: 'drive' | 'sa';
  /** 縦軸の最大値（drive=6 / sa=3） */
  maxValue: number;
  /** 縦軸の目盛り */
  yTicks: number[];
  /** 横軸の最大値（ラウンド長・秒） */
  duration: number;
  /** 描画する系列 */
  series: GaugeSeries[];
  /** 背景帯として描く期間（バーンアウト） */
  bands?: SpanWithSide[];
  /** マーカーとして描く期間（CA） */
  markers?: SpanWithSide[];
  /** スクリーンリーダー用ラベル */
  ariaLabel: string;
}

/**
 * HTMLエスケープ（DOM非依存。ユニットテスト可能にするため文字列置換で実装）
 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * 秒数のラベル（例: "0s" / "12.5s" / "51s"）
 */
export function formatSeconds(value: number): string {
  if (!Number.isFinite(value)) return '0s';
  const rounded = Math.abs(value - Math.round(value)) < 0.05 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded}s`;
}

/**
 * 動画内の絶対時刻を「分:秒」形式に変換
 */
export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const total = Math.floor(seconds);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * YouTubeリンクを生成する（t は動画内の絶対秒）
 */
export function buildYoutubeUrl(videoId: string, startTime: number): string {
  const t = Number.isFinite(startTime) && startTime > 0 ? Math.floor(startTime) : 0;
  return `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}&t=${t}s`;
}

/**
 * 横軸（経過秒）の目盛りを計算する
 *
 * ラウンド長に応じて目盛り数を調整する（短いラウンドではラベルが重ならないように間引く）。
 */
export function computeTimeTicks(duration: number): number[] {
  const d = duration > 0 && Number.isFinite(duration) ? duration : 1;
  const count = d <= 3 ? 2 : d <= 8 ? 3 : 5;
  const ticks: number[] = [];
  for (let i = 0; i < count; i += 1) {
    ticks.push((d * i) / (count - 1));
  }
  return ticks;
}

/**
 * 変化点列からステップ状の SVG path を生成する
 *
 * 値は次の変化点まで一定に保たれる。最後の変化点の値は `endTime` まで延長する。
 * 変化点が空の場合は空文字を返す（描画しない）。
 */
export function buildStepPath(
  events: GaugeEvent[],
  scaleX: (time: number) => number,
  scaleY: (value: number) => number,
  endTime: number,
): string {
  if (events.length === 0) return '';

  const fmt = (value: number) => value.toFixed(1);
  const parts: string[] = [`M${fmt(scaleX(events[0][0]))},${fmt(scaleY(events[0][1]))}`];

  for (let i = 1; i < events.length; i += 1) {
    const x = scaleX(events[i][0]);
    // 値は次の変化点まで一定（横線）
    parts.push(`L${fmt(x)},${fmt(scaleY(events[i - 1][1]))}`);
    // 新しい値へ垂直に変化
    parts.push(`L${fmt(x)},${fmt(scaleY(events[i][1]))}`);
  }

  const last = events[events.length - 1];
  if (endTime > last[0]) {
    parts.push(`L${fmt(scaleX(endTime))},${fmt(scaleY(last[1]))}`);
  }

  return parts.join(' ');
}

/**
 * サイドの時系列データを取得する（欠損時は空データを返す）
 */
function getSide(round: GaugeRound, side: GaugeSide): GaugeSideData | null {
  const value = round[side];
  return value ?? null;
}

/**
 * 汎用のゲージチャート SVG を生成する（純関数）
 */
export function buildGaugeSvg(params: GaugeSvgParams): string {
  const { variant, maxValue, yTicks, duration, series, bands = [], markers = [], ariaLabel } = params;

  const height = variant === 'drive' ? DRIVE_HEIGHT : SA_HEIGHT;
  const innerW = CHART_WIDTH - PADDING.left - PADDING.right;
  const innerH = height - PADDING.top - PADDING.bottom;
  const right = CHART_WIDTH - PADDING.right;
  const bottom = height - PADDING.bottom;
  const safeDuration = duration > 0 && Number.isFinite(duration) ? duration : 1;
  const safeMax = maxValue > 0 ? maxValue : 1;
  const fmt = (value: number) => value.toFixed(1);

  const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);
  const scaleX = (time: number) => PADDING.left + (clamp(time, 0, safeDuration) / safeDuration) * innerW;
  const scaleY = (value: number) => PADDING.top + innerH - (clamp(value, 0, safeMax) / safeMax) * innerH;

  // 背景帯（バーンアウト期間）
  const bandsHtml = bands
    .map((band) => {
      const x1 = scaleX(Math.min(band.start, band.end));
      const x2 = scaleX(Math.max(band.start, band.end));
      const width = Math.max(0, x2 - x1);
      return `<rect class="gg-band gg-band-${band.side}" x="${fmt(x1)}" y="${fmt(PADDING.top)}" width="${fmt(width)}" height="${fmt(innerH)}" />`;
    })
    .join('');

  // 縦軸のグリッド線とラベル
  const gridHtml = yTicks
    .map((value) => {
      const y = scaleY(value);
      return `<line class="gg-grid-line" x1="${PADDING.left}" y1="${fmt(y)}" x2="${right}" y2="${fmt(y)}" />
        <text class="gg-axis-label gg-axis-label-y" x="${PADDING.left - 6}" y="${fmt(y + 3)}" text-anchor="end">${value}</text>`;
    })
    .join('');

  // 横軸のグリッド線とラベル
  const ticks = computeTimeTicks(safeDuration);
  const xGridHtml = ticks
    .map((time, index) => {
      const x = scaleX(time);
      const anchor = index === 0 ? 'start' : index === ticks.length - 1 ? 'end' : 'middle';
      return `<line class="gg-grid-line gg-grid-line-v" x1="${fmt(x)}" y1="${PADDING.top}" x2="${fmt(x)}" y2="${bottom}" />
        <text class="gg-axis-label gg-axis-label-x" x="${fmt(x)}" y="${bottom + 15}" text-anchor="${anchor}">${formatSeconds(time)}</text>`;
    })
    .join('');

  // 折れ線（ステップ）
  const seriesHtml = series
    .map((item) => {
      const path = buildStepPath(item.events, scaleX, scaleY, safeDuration);
      if (!path) return '';
      return `<path class="gg-line gg-line-${item.side}" d="${path}" />`;
    })
    .join('');

  // CA マーカー（SAパネル上部）
  const markersHtml = markers
    .map((marker) => {
      const x1 = scaleX(Math.min(marker.start, marker.end));
      const x2 = scaleX(Math.max(marker.start, marker.end));
      const width = Math.max(2, x2 - x1);
      return `<rect class="gg-marker gg-marker-${marker.side}" x="${fmt(x1)}" y="${fmt(PADDING.top)}" width="${fmt(width)}" height="6" />`;
    })
    .join('');

  return `
    <svg class="gg-svg gg-svg-${variant}" viewBox="0 0 ${CHART_WIDTH} ${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${escapeHtml(ariaLabel)}">
      <rect class="gg-plot-bg" x="${PADDING.left}" y="${PADDING.top}" width="${fmt(innerW)}" height="${fmt(innerH)}" />
      <g class="gg-bands">${bandsHtml}</g>
      <g class="gg-grid">${gridHtml}${xGridHtml}</g>
      <line class="gg-axis-line" x1="${PADDING.left}" y1="${PADDING.top}" x2="${PADDING.left}" y2="${bottom}" />
      <line class="gg-axis-line" x1="${PADDING.left}" y1="${bottom}" x2="${right}" y2="${bottom}" />
      <g class="gg-series">${seriesHtml}</g>
      <g class="gg-markers">${markersHtml}</g>
    </svg>
  `;
}

/**
 * ラウンド長（秒）を求める。0以下や不正値は 1 秒にフォールバックする。
 */
export function getRoundDuration(round: GaugeRound): number {
  const duration = round.roundEndTime - round.roundStartTime;
  return duration > 0 && Number.isFinite(duration) ? duration : 1;
}

/**
 * ドライブゲージの SVG を生成する
 */
export function buildDriveSvg(round: GaugeRound, labels: GaugeSideLabels): string {
  const duration = getRoundDuration(round);
  const p1 = getSide(round, 'player1');
  const p2 = getSide(round, 'player2');

  const bands: SpanWithSide[] = [
    ...(p1?.driveBurnout ?? []).map((span) => ({ side: 'player1' as const, start: span[0], end: span[1] })),
    ...(p2?.driveBurnout ?? []).map((span) => ({ side: 'player2' as const, start: span[0], end: span[1] })),
  ];

  return buildGaugeSvg({
    variant: 'drive',
    maxValue: DRIVE_MAX,
    yTicks: [0, 2, 4, 6],
    duration,
    series: [
      { side: 'player1', events: p1?.drive ?? [] },
      { side: 'player2', events: p2?.drive ?? [] },
    ],
    bands,
    ariaLabel: `Round ${round.round} ドライブゲージ推移（${sideText(labels.player1, 'player1')} / ${sideText(labels.player2, 'player2')}）`,
  });
}

/**
 * SAゲージの SVG を生成する
 */
export function buildSaSvg(round: GaugeRound, labels: GaugeSideLabels): string {
  const duration = getRoundDuration(round);
  const p1 = getSide(round, 'player1');
  const p2 = getSide(round, 'player2');

  const markers: SpanWithSide[] = [
    ...(p1?.saCriticalArt ?? []).map((span) => ({ side: 'player1' as const, start: span[0], end: span[1] })),
    ...(p2?.saCriticalArt ?? []).map((span) => ({ side: 'player2' as const, start: span[0], end: span[1] })),
  ];

  return buildGaugeSvg({
    variant: 'sa',
    maxValue: SA_MAX,
    yTicks: [0, 1, 2, 3],
    duration,
    series: [
      { side: 'player1', events: p1?.sa ?? [] },
      { side: 'player2', events: p2?.sa ?? [] },
    ],
    markers,
    ariaLabel: `Round ${round.round} SAゲージ推移（${sideText(labels.player1, 'player1')} / ${sideText(labels.player2, 'player2')}）`,
  });
}

/**
 * サイドの表示テキスト（自分 / 相手 / 1P / 2P）
 */
export function sideText(label: GaugeSideLabel, side: GaugeSide): string {
  if (label === 'self') return '自分';
  if (label === 'opponent') return '相手';
  return side === 'player1' ? '1P' : '2P';
}

/**
 * キャラクター名を比較用に正規化する（大文字・前後空白除去）
 */
function normalizeCharacter(name: string | null | undefined): string {
  return (name ?? '').trim().toUpperCase();
}

/**
 * Battlelog のサイド情報から、動画の 1P/2P を「自分 / 相手」に対応付ける（ADR-048）
 *
 * - Battlelog が未マッチ、または MY_PLAYER_ID がどちらにも無い場合は
 *   `{ player1: null, player2: null }` を返し、UI は 1P/2P 表示のままにする
 * - キャラクター名で自分のサイドを特定できる場合はそれを優先し、
 *   ミラーマッチ等で判別できない場合は short_id の位置にフォールバックする
 * - 生データ（GaugeData）は書き換えない
 */
export function resolveGaugeSideLabels(input: {
  player1Character: string;
  player2Character: string;
  myPlayerId: number;
  battlelog?: { p1ShortId: number; p2ShortId: number; p1Character: string; p2Character: string } | null;
}): GaugeSideLabels {
  const unmatched: GaugeSideLabels = { player1: null, player2: null };
  const battlelog = input.battlelog;
  if (!battlelog) return unmatched;

  let myCharacter: string;
  let myBattlelogSide: GaugeSide;
  if (battlelog.p1ShortId === input.myPlayerId) {
    myCharacter = battlelog.p1Character;
    myBattlelogSide = 'player1';
  } else if (battlelog.p2ShortId === input.myPlayerId) {
    myCharacter = battlelog.p2Character;
    myBattlelogSide = 'player2';
  } else {
    return unmatched;
  }

  const normalizedMe = normalizeCharacter(myCharacter);
  const p1IsMe = normalizeCharacter(input.player1Character) === normalizedMe;
  const p2IsMe = normalizeCharacter(input.player2Character) === normalizedMe;

  let selfSide: GaugeSide | null = null;
  if (p1IsMe && !p2IsMe) {
    selfSide = 'player1';
  } else if (p2IsMe && !p1IsMe) {
    selfSide = 'player2';
  } else {
    // ミラーマッチ等で判別できない場合は Battlelog の位置にフォールバック
    selfSide = myBattlelogSide;
  }

  return selfSide === 'player1'
    ? { player1: 'self', player2: 'opponent' }
    : { player1: 'opponent', player2: 'self' };
}

/**
 * ラウンド1ブロック分のHTMLを生成する
 *
 * ヘッダーに YouTube リンク（ラウンド開始時点）を併記する。
 */
export function buildRoundGaugeHtml(videoId: string, round: GaugeRound, labels: GaugeSideLabels): string {
  const start = round.roundStartTime;
  const end = round.roundEndTime;
  const youtubeUrl = buildYoutubeUrl(videoId, start);
  const bannerNote = round.bannerDetected ? '' : '<span class="gg-round-warning" title="ROUNDバナー未検出のため試合開始を第1ラウンドとみなしています">バナー未検出</span>';

  const legend = `
    <div class="gg-legend">
      <span class="gg-legend-item"><span class="gg-legend-swatch gg-legend-swatch-player1"></span>${escapeHtml(sideText(labels.player1, 'player1'))}</span>
      <span class="gg-legend-item"><span class="gg-legend-swatch gg-legend-swatch-player2"></span>${escapeHtml(sideText(labels.player2, 'player2'))}</span>
      <span class="gg-legend-note">帯: バーンアウト / マーカー: CA</span>
    </div>
  `;

  return `
    <section class="gg-round">
      <div class="gg-round-header">
        <span class="gg-round-title">Round ${round.round}</span>
        <span class="gg-round-time">${formatClock(start)} 〜 ${formatClock(end)}（${formatSeconds(getRoundDuration(round))}）</span>
        ${bannerNote}
        <a class="gg-round-link" href="${youtubeUrl}" target="_blank" rel="noopener">YouTubeで見る</a>
      </div>
      ${legend}
      <div class="gg-chart-block">
        <div class="gg-chart-label">ドライブ（0〜${DRIVE_MAX}）</div>
        ${buildDriveSvg(round, labels)}
      </div>
      <div class="gg-chart-block">
        <div class="gg-chart-label">SA（0〜${SA_MAX}）</div>
        ${buildSaSvg(round, labels)}
      </div>
    </section>
  `;
}

/**
 * gauges JSON の全ラウンドを描画する。データが無い場合は「ゲージデータなし」を返す。
 */
export function buildGaugeRoundsHtml(videoId: string, gauges: GaugeData | null, labels: GaugeSideLabels): string {
  if (!gauges || !Array.isArray(gauges.rounds) || gauges.rounds.length === 0) {
    return '<p class="gg-empty">ゲージデータなし</p>';
  }
  return gauges.rounds.map((round) => buildRoundGaugeHtml(videoId, round, labels)).join('');
}

/**
 * ラウンド数不一致などの注意書きを生成する（問題なければ空文字）
 */
export function buildGaugeNoticeHtml(gauges: GaugeData | null): string {
  if (!gauges || gauges.roundCountMatch !== false) return '';
  const detected = gauges.detectedRoundCount ?? gauges.rounds?.length ?? 0;
  const expected = gauges.battlelogRoundCount;
  const expectedText = expected == null ? '不明' : String(expected);
  return `<p class="gg-notice">動画のラウンド数（${detected}）と Battlelog のラウンド数（${expectedText}）が一致しません。</p>`;
}

/**
 * round_stats の集計テーブルを生成する。データが無い場合は「集計データなし」を返す。
 */
export function buildRoundStatsTableHtml(rows: RoundStatsRow[], labels: GaugeSideLabels): string {
  if (!rows || rows.length === 0) {
    return '<p class="gg-empty">集計データなし</p>';
  }

  const formatValue = (value: number | null, digits = 1): string => {
    if (value == null || !Number.isFinite(value)) return '-';
    return value.toFixed(digits);
  };
  const formatPercent = (value: number | null): string => {
    if (value == null || !Number.isFinite(value)) return '-';
    return `${Math.round(value * 100)}%`;
  };
  // 未計測（null）は '-'、計測済み 0 件は '0' と区別する（ADR-049）
  const formatInt = (value: number | null): string => {
    if (value == null || !Number.isFinite(value)) return '-';
    return String(Math.round(value));
  };

  const tableRows = rows
    .map((row) => {
      const sideLabel = sideText(labels[row.side], row.side);
      const character = row.character ? escapeHtml(row.character) : '-';
      return `
        <tr>
          <td>Round ${row.round}</td>
          <td class="gg-stats-side gg-stats-side-${row.side}">${escapeHtml(sideLabel)}</td>
          <td>${character}</td>
          <td>${formatValue(row.driveMin)}</td>
          <td>${formatValue(row.driveAvg)}</td>
          <td>${formatValue(row.driveEnd)}</td>
          <td>${row.saMax == null ? '-' : Math.round(row.saMax)}</td>
          <td>${row.saUsedCount == null ? '-' : Math.round(row.saUsedCount)}</td>
          <td>${formatPercent(row.detectionCoverage)}</td>
          <td class="gg-stats-counter">${formatInt(row.counterCount)}</td>
          <td class="gg-stats-counter">${formatInt(row.punishCounterCount)}</td>
        </tr>
      `;
    })
    .join('');

  return `
    <div class="gg-stats">
      <div class="gg-stats-label">ラウンド集計</div>
      <div class="gg-stats-scroll">
        <table class="gg-stats-table">
          <thead>
            <tr>
              <th>ラウンド</th>
              <th>サイド</th>
              <th>キャラ</th>
              <th>ドライブ最小</th>
              <th>ドライブ平均</th>
              <th>ドライブ終了</th>
              <th>SA最大</th>
              <th>SA使用</th>
              <th>計測率</th>
              <th title="COUNTER">カウンタ</th>
              <th title="PUNISH COUNTER">パニッシュ</th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>
    </div>
  `;
}
