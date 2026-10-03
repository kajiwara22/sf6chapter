/**
 * SF6 Chapter - LP推移チャートコンポーネント
 *
 * 依存ライブラリを追加せず、SVG で折れ線グラフを描画する（ADR-046）。
 * - 1試合 = 1点（全プロット）
 * - y軸は LP を 200 区切りで表示（目盛りが多すぎる場合はステップを拡大）
 * - グラフ上に勝敗は表現せず、ツールチップにテキストで表示する
 */

import { DOM_IDS } from '../types';
import type { LpHistoryRow, LpHistoryFilters } from '@shared/types';

export type LpFilterHandler = (filters: LpHistoryFilters) => void;

/** 描画領域（viewBox 座標） */
const CHART_WIDTH = 960;
const CHART_HEIGHT = 420;
const PADDING = { top: 16, right: 24, bottom: 56, left: 72 };

/** x軸ラベルの最大数 */
const MAX_X_LABELS = 6;

/** x軸ラベル同士の最小間隔（viewBox座標）。これより近い場合は間引く */
const MIN_X_LABEL_GAP = 140;

/**
 * y軸の目盛りを計算する
 *
 * LP は 200 区切りを基本とし、目盛りが多くなりすぎる場合は
 * 400 / 500 / 1000 / 2000 区切りへ段階的に広げる。
 *
 * @returns 目盛り値の配列と、軸の下端・上端
 */
export function computeLpAxisTicks(
  minLp: number,
  maxLp: number,
): { ticks: number[]; min: number; max: number } {
  const candidates = [200, 400, 500, 1000, 2000, 5000];

  let step = candidates[candidates.length - 1];
  let min = minLp;
  let max = maxLp;

  for (const candidate of candidates) {
    min = Math.floor(minLp / candidate) * candidate;
    max = Math.ceil(maxLp / candidate) * candidate;
    step = candidate;
    if ((max - min) / candidate <= 12) break;
  }

  const ticks: number[] = [];
  for (let value = min; value <= max; value += step) {
    ticks.push(value);
  }
  // 端数（浮動小数の誤差）で最後の目盛りが欠けないようにする
  if (ticks[ticks.length - 1] !== max) ticks.push(max);

  return { ticks, min, max };
}

/**
 * 昇順に並んだ数値配列から、target に最も近い要素のインデックスを返す（二分探索）
 */
export function findNearestIndex(sortedValues: number[], target: number): number {
  if (sortedValues.length === 0) return -1;

  let lo = 0;
  let hi = sortedValues.length - 1;

  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (sortedValues[mid] < target) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }

  // lo は target 以上の最小インデックス
  if (lo > 0 && Math.abs(sortedValues[lo - 1] - target) <= Math.abs(sortedValues[lo] - target)) {
    return lo - 1;
  }
  return lo;
}

/**
 * DuckDBのTIMESTAMP値（Unixミリ秒数値文字列 or ISO文字列）をDateに変換
 */
function parseUploadedAt(dateStr: string): Date {
  const raw = Number(dateStr);
  return Number.isFinite(raw) && raw > 1e12 ? new Date(raw) : new Date(dateStr);
}

/**
 * JST絶対日時表示（例: "2026/09/02 01:43"）
 */
function formatJstDateTime(date: Date): string {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  const y = jst.getUTCFullYear();
  const mo = String(jst.getUTCMonth() + 1).padStart(2, '0');
  const d = String(jst.getUTCDate()).padStart(2, '0');
  const h = String(jst.getUTCHours()).padStart(2, '0');
  const mi = String(jst.getUTCMinutes()).padStart(2, '0');
  return `${y}/${mo}/${d} ${h}:${mi}`;
}

/**
 * x軸ラベル用の短いJST表示（例: "09/02 01:43"）
 */
function formatJstShort(date: Date): string {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  const mo = String(jst.getUTCMonth() + 1).padStart(2, '0');
  const d = String(jst.getUTCDate()).padStart(2, '0');
  const h = String(jst.getUTCHours()).padStart(2, '0');
  const mi = String(jst.getUTCMinutes()).padStart(2, '0');
  return `${mo}/${d} ${h}:${mi}`;
}

/**
 * 勝敗バッジHTML
 */
function resultBadge(result: 'win' | 'loss' | 'draw'): string {
  if (result === 'win') return '<span class="result-badge result-badge-win">WIN</span>';
  if (result === 'loss') return '<span class="result-badge result-badge-loss">LOSS</span>';
  return '<span class="result-badge result-badge-draw">DRAW</span>';
}

/**
 * HTMLエスケープ
 */
function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/** プロット済みの座標 */
interface ChartCoord {
  x: number;
  y: number;
  ts: number;
  row: LpHistoryRow;
}

/**
 * SVG本体のHTMLを生成
 */
function createChartSvg(coords: ChartCoord[], yAxis: { ticks: number[]; min: number; max: number }): string {
  const innerW = CHART_WIDTH - PADDING.left - PADDING.right;
  const innerH = CHART_HEIGHT - PADDING.top - PADDING.bottom;
  const right = CHART_WIDTH - PADDING.right;
  const bottom = CHART_HEIGHT - PADDING.bottom;

  const scaleY = (lp: number) =>
    PADDING.top + innerH - ((lp - yAxis.min) / (yAxis.max - yAxis.min)) * innerH;

  // y軸: グリッド線とラベル
  const yGrid = yAxis.ticks
    .map((value) => {
      const y = scaleY(value);
      return `<line class="lp-grid-line" x1="${PADDING.left}" y1="${y.toFixed(1)}" x2="${right}" y2="${y.toFixed(1)}" />
        <text class="lp-axis-label lp-axis-label-y" x="${PADDING.left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end">${value.toLocaleString('en-US')}</text>`;
    })
    .join('');

  // x軸: ラベルを間引いて表示
  const xTickIndexes: number[] = [];
  const step = Math.max(1, Math.ceil(coords.length / MAX_X_LABELS));
  for (let i = 0; i < coords.length; i += step) {
    xTickIndexes.push(i);
  }
  const lastIndex = coords.length - 1;
  if (xTickIndexes[xTickIndexes.length - 1] !== lastIndex) {
    // 直前のラベルと近すぎる場合は置き換えて重なりを防ぐ
    const prevIndex = xTickIndexes[xTickIndexes.length - 1];
    if (coords[lastIndex].x - coords[prevIndex].x < MIN_X_LABEL_GAP) {
      xTickIndexes.pop();
    }
    xTickIndexes.push(lastIndex);
  }

  const xLabels = xTickIndexes
    .map((i) => {
      const coord = coords[i];
      // 両端のラベルは見切れないように内側へ寄せる
      const anchor = i === 0 ? 'start' : i === lastIndex ? 'end' : 'middle';
      return `<line class="lp-grid-line lp-grid-line-v" x1="${coord.x.toFixed(1)}" y1="${PADDING.top}" x2="${coord.x.toFixed(1)}" y2="${bottom}" />
        <text class="lp-axis-label lp-axis-label-x" x="${coord.x.toFixed(1)}" y="${bottom + 20}" text-anchor="${anchor}">${formatJstShort(new Date(coord.ts))}</text>`;
    })
    .join('');

  // 折れ線（1点のみの場合は点を表示）
  const polyline =
    coords.length > 1
      ? `<polyline class="lp-line" points="${coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')}" />`
      : '';
  const singlePoint =
    coords.length === 1
      ? `<circle class="lp-point-single" cx="${coords[0].x.toFixed(1)}" cy="${coords[0].y.toFixed(1)}" r="4" />`
      : '';

  // 軸線
  const axes = `
    <line class="lp-axis-line" x1="${PADDING.left}" y1="${PADDING.top}" x2="${PADDING.left}" y2="${bottom}" />
    <line class="lp-axis-line" x1="${PADDING.left}" y1="${bottom}" x2="${right}" y2="${bottom}" />
  `;

  return `
    <svg class="lp-chart-svg" viewBox="0 0 ${CHART_WIDTH} ${CHART_HEIGHT}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="LP推移グラフ">
      <g class="lp-grid">${yGrid}${xLabels}</g>
      ${axes}
      ${polyline}
      ${singlePoint}
      <line class="lp-crosshair" x1="0" y1="${PADDING.top}" x2="0" y2="${bottom}" style="display: none;" />
      <circle class="lp-hover-point" cx="0" cy="0" r="5" style="display: none;" />
      <rect class="lp-overlay" x="${PADDING.left}" y="${PADDING.top}" width="${innerW}" height="${innerH}" fill="transparent" />
    </svg>
  `;
}

/**
 * ツールチップのHTMLを生成
 */
function createTooltipHtml(row: LpHistoryRow): string {
  return `
    <div class="lp-tooltip-date">${escapeHtml(formatJstDateTime(parseUploadedAt(row.uploadedAt)))}</div>
    <div class="lp-tooltip-lp">
      LP <strong>${row.leaguePoint.toLocaleString('en-US')}</strong>
      <span class="lp-tooltip-note">試合開始時</span>
    </div>
    <div class="lp-tooltip-opponent">vs ${escapeHtml(row.opponentCharacter)}</div>
    <div class="lp-tooltip-result">${resultBadge(row.result)}</div>
  `;
}

/**
 * ツールチップとホバー表示のイベントを設定
 */
function attachTooltip(container: HTMLElement, coords: ChartCoord[]): void {
  const svg = container.querySelector('.lp-chart-svg') as SVGSVGElement | null;
  const overlay = container.querySelector('.lp-overlay') as SVGRectElement | null;
  const tooltip = container.querySelector('.lp-tooltip') as HTMLDivElement | null;
  const hoverPoint = container.querySelector('.lp-hover-point') as SVGCircleElement | null;
  const crosshair = container.querySelector('.lp-crosshair') as SVGLineElement | null;

  if (!svg || !overlay || !tooltip || !hoverPoint || !crosshair) return;

  const xs = coords.map((c) => c.x);

  const hide = () => {
    tooltip.style.display = 'none';
    hoverPoint.style.display = 'none';
    crosshair.style.display = 'none';
  };

  const showAt = (clientX: number) => {
    const svgRect = svg.getBoundingClientRect();
    if (svgRect.width === 0) return;

    const scale = svgRect.width / CHART_WIDTH;
    const svgX = (clientX - svgRect.left) / scale;
    const index = findNearestIndex(xs, svgX);
    if (index < 0) return;

    const coord = coords[index];

    hoverPoint.setAttribute('cx', coord.x.toFixed(1));
    hoverPoint.setAttribute('cy', coord.y.toFixed(1));
    hoverPoint.style.display = '';
    crosshair.setAttribute('x1', coord.x.toFixed(1));
    crosshair.setAttribute('x2', coord.x.toFixed(1));
    crosshair.style.display = '';

    tooltip.innerHTML = createTooltipHtml(coord.row);
    tooltip.style.display = 'block';

    const containerRect = container.getBoundingClientRect();
    const pointLeft = (svgRect.left - containerRect.left) + coord.x * scale;
    const pointTop = (svgRect.top - containerRect.top) + coord.y * scale;

    const tooltipWidth = tooltip.offsetWidth;
    const tooltipHeight = tooltip.offsetHeight;

    let left = pointLeft + 14;
    if (left + tooltipWidth > containerRect.width) {
      left = pointLeft - tooltipWidth - 14;
    }
    if (left < 0) left = 0;

    let top = pointTop - tooltipHeight / 2;
    if (top < 0) top = 0;

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  };

  overlay.addEventListener('mousemove', (event) => showAt((event as MouseEvent).clientX));
  overlay.addEventListener('mouseleave', hide);
  overlay.addEventListener('touchstart', (event) => {
    const touch = (event as TouchEvent).touches[0];
    if (touch) showAt(touch.clientX);
  });
  overlay.addEventListener('touchmove', (event) => {
    const touch = (event as TouchEvent).touches[0];
    if (touch) showAt(touch.clientX);
  });
  overlay.addEventListener('touchend', hide);
}

/**
 * LP推移チャートを描画
 */
export function renderLpChart(rows: LpHistoryRow[]): void {
  const container = document.getElementById(DOM_IDS.LP_CHART);
  if (!container) {
    console.error('[LpChart] Container not found');
    return;
  }

  if (rows.length === 0) {
    container.innerHTML = '<p class="lp-empty">データがありません</p>';
    return;
  }

  const parsed = rows.map((row) => ({ row, ts: parseUploadedAt(row.uploadedAt).getTime() }));
  const tsMin = parsed[0].ts;
  const tsMax = parsed[parsed.length - 1].ts;

  const lps = rows.map((row) => row.leaguePoint);
  let lpMin = Math.min(...lps);
  let lpMax = Math.max(...lps);
  if (lpMin === lpMax) {
    lpMin -= 100;
    lpMax += 100;
  }

  const yAxis = computeLpAxisTicks(lpMin, lpMax);

  const innerW = CHART_WIDTH - PADDING.left - PADDING.right;
  const innerH = CHART_HEIGHT - PADDING.top - PADDING.bottom;

  const scaleX = (ts: number) =>
    tsMax === tsMin
      ? PADDING.left + innerW / 2
      : PADDING.left + ((ts - tsMin) / (tsMax - tsMin)) * innerW;
  const scaleY = (lp: number) =>
    PADDING.top + innerH - ((lp - yAxis.min) / (yAxis.max - yAxis.min)) * innerH;

  const coords: ChartCoord[] = parsed.map((item) => ({
    x: scaleX(item.ts),
    y: scaleY(item.row.leaguePoint),
    ts: item.ts,
    row: item.row,
  }));

  container.innerHTML =
    createChartSvg(coords, yAxis) +
    '<div class="lp-tooltip" style="display: none;"></div>';

  attachTooltip(container, coords);
}

/**
 * LP推移チャートをクリア
 */
export function clearLpChart(): void {
  const container = document.getElementById(DOM_IDS.LP_CHART);
  if (container) {
    container.innerHTML = '';
  }
}

/**
 * LP推移フォームを初期化
 */
export function initLpForm(onFilter: LpFilterHandler): void {
  const form = document.getElementById(DOM_IDS.LP_FORM) as HTMLFormElement | null;
  if (!form) {
    console.error('[LpChart] Form not found');
    return;
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const formData = new FormData(form);

    const filters: LpHistoryFilters = {
      dateFrom: (formData.get('dateFrom') as string) || undefined,
      dateTo: (formData.get('dateTo') as string) || undefined,
      timeFrom: (formData.get('timeFrom') as string) || undefined,
      timeTo: (formData.get('timeTo') as string) || undefined,
    };

    // 日付なしの時間指定は無視（既存タブと同じ挙動）
    if (!filters.dateFrom) filters.timeFrom = undefined;
    if (!filters.dateTo) filters.timeTo = undefined;

    onFilter(filters);
  });
}
