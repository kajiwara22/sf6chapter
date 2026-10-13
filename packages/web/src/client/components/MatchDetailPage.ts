/**
 * SF6 Chapter - ゲージ詳細ページ（ADR-051）
 *
 * 対戦検索の結果行から遷移する独立ページ（`/matches/{matchId}`）。
 * 試合サマリ（勝敗・スコア・LP/MR）＋ ラウンド別ゲージチャート ＋ ラウンド集計を表示する。
 */

import type { CharacterHealthTable, GaugeData, Match, MatchBattlelogSides, RoundStatsRow } from '@shared/types';
import {
  buildGaugeNoticeHtml,
  buildGaugeRoundsHtml,
  buildGaugeSideFilterHtml,
  buildRoundStatsTableHtml,
  GAUGE_SIDE_FILTER_STORAGE_KEY,
  resolveSideCharacters,
  type GaugeChartContext,
  type GaugeSide,
  type GaugeSideLabels,
  type GaugeVisibleSide,
} from './RoundGaugeChart';
import { createYouTubeLink, formatDate, formatTime } from './ResultsGrid';
import { MY_PLAYER_ID } from '../search';

/** HTML エスケープ（DOM 非依存にしてテストしやすくする） */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** ゲージ詳細ページのコンテナ ID */
export const MATCH_DETAIL_PAGE_ID = 'match-detail-page';

/** ゲージ詳細ページに渡すデータ */
export interface MatchDetailPageData {
  /** gauges JSON（未取得・不存在時は null） */
  gauges: GaugeData | null;
  /** round_stats の行（未取得時は空配列） */
  roundStats: RoundStatsRow[];
  /** 自分視点の表示ラベル */
  labels: GaugeSideLabels;
  /** Battlelog サイド情報（LP/MR 表示用。未マッチ時は null） */
  battlelog: MatchBattlelogSides | null;
  /** キャラクター別最大体力表（ADR-050、未取得時は null） */
  characterHealth?: CharacterHealthTable | null;
}

/** URL パスから試合IDを取り出す（`/matches/{matchId}` 以外は null） */
export function parseMatchDetailPath(pathname: string): string | null {
  const match = /^\/matches\/([^/]+)\/?$/.exec(pathname);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/** 検索タブなど通常ビューを隠し、ゲージ詳細ページを表示する */
export function enterMatchDetailPageMode(): HTMLElement {
  document.querySelector<HTMLElement>('.tab-nav')?.style.setProperty('display', 'none');
  for (const view of document.querySelectorAll<HTMLElement>('.tab-view')) {
    view.style.display = 'none';
  }

  const main = document.querySelector<HTMLElement>('.main');
  let container = document.getElementById(MATCH_DETAIL_PAGE_ID);
  if (!container) {
    container = document.createElement('div');
    container.id = MATCH_DETAIL_PAGE_ID;
    container.className = 'match-detail-page';
    (main ?? document.body).appendChild(container);
  }
  container.style.display = 'block';
  return container;
}

/** スコア（各サイドの取得ラウンド数）。round_results が無い場合は unknown */
function computeScore(roundStats: RoundStatsRow[]): { player1: number; player2: number; known: boolean } {
  const rows = roundStats.filter((row) => row.roundResult === 'win' || row.roundResult === 'loss');
  if (rows.length === 0) return { player1: 0, player2: 0, known: false };
  const player1 = rows.filter((row) => row.side === 'player1' && row.roundResult === 'win').length;
  const player2 = rows.filter((row) => row.side === 'player2' && row.roundResult === 'win').length;
  return { player1, player2, known: true };
}

/** 自分視点のサイドを返す（判定できない場合は null） */
function resolveSelfSide(labels: GaugeSideLabels): GaugeSide | null {
  if (labels.player1 === 'self') return 'player1';
  if (labels.player2 === 'self') return 'player2';
  return null;
}

/** サイドに対応する Battlelog の LP / MR を返す */
function resolveLpMr(
  battlelog: MatchBattlelogSides | null,
  side: GaugeSide | null,
): { lp: number | null; mr: number | null } {
  if (!battlelog || !side) return { lp: null, mr: null };
  const isP1 = side === 'player1';
  const shortId = isP1 ? battlelog.p1ShortId : battlelog.p2ShortId;
  if (shortId !== MY_PLAYER_ID) return { lp: null, mr: null };
  return {
    lp: (isP1 ? battlelog.p1LeaguePoint : battlelog.p2LeaguePoint) ?? null,
    mr: (isP1 ? battlelog.p1MasterRating : battlelog.p2MasterRating) ?? null,
  };
}

/** 試合サマリの HTML を生成する */
function createSummaryHtml(match: Match, data: MatchDetailPageData): string {
  const selfSide = resolveSelfSide(data.labels);
  const score = computeScore(data.roundStats);
  const selfResult = selfSide ? match[selfSide].result : undefined;
  const opponentCharacter = selfSide
    ? match[selfSide === 'player1' ? 'player2' : 'player1'].character
    : match.player2.character;
  const selfCharacter = selfSide ? match[selfSide].character : match.player1.character;
  const { lp, mr } = resolveLpMr(data.battlelog, selfSide);

  const resultBadge = selfResult
    ? `<span class="match-detail-result result-${selfResult}">${selfResult === 'win' ? 'WIN' : 'LOSE'}</span>`
    : '<span class="match-detail-result result-unknown">RESULT -</span>';

  const scoreText = score.known ? `${score.player1} - ${score.player2}` : '—';

  const lpMrText = [lp != null ? `LP ${lp}` : null, mr != null ? `MR ${mr}` : null]
    .filter((text): text is string => text !== null)
    .join(' / ');

  return `
    <div class="match-detail-summary">
      <div class="match-detail-summary-main">
        ${resultBadge}
        <span class="match-detail-score" title="ラウンドスコア（1P - 2P）">${escapeHtml(scoreText)}</span>
        <span class="match-detail-matchup">${escapeHtml(selfCharacter)} vs ${escapeHtml(opponentCharacter)}</span>
        ${lpMrText ? `<span class="match-detail-lp">${escapeHtml(lpMrText)}</span>` : ''}
      </div>
      <div class="match-detail-summary-meta">
        <span>${formatDate(match.videoPublishedAt)}</span>
        <span>${formatTime(match.startTime)}</span>
        <a class="match-detail-youtube" href="${createYouTubeLink(match.videoId, match.startTime)}" target="_blank" rel="noopener">YouTubeで見る</a>
      </div>
    </div>
  `;
}

/** ページのヘッダー HTML を生成する */
function createHeaderHtml(match: Match, data: MatchDetailPageData): string {
  return `
    <div class="match-detail-page-header">
      <a class="match-detail-back" href="/">← 対戦検索に戻る</a>
      <h2 class="match-detail-page-title">${escapeHtml(match.videoTitle)}</h2>
      ${createSummaryHtml(match, data)}
    </div>
  `;
}

/** ページ本体の HTML を生成する（DOM 非依存） */
export function buildMatchDetailPageHtml(match: Match, data: MatchDetailPageData): string {
  const context: GaugeChartContext = {
    characterHealth: data.characterHealth ?? null,
    characters: resolveSideCharacters(
      { player1: match.player1.character, player2: match.player2.character },
      data.roundStats,
    ),
  };
  // 低計測率のラウンドがあれば品質の注記を出す（ADR-051 で集計テーブルからは外した）
  const lowCoverage = data.roundStats.filter(
    (row) => row.detectionCoverage != null && row.detectionCoverage < 0.5,
  ).length;
  const coverageNotice =
    lowCoverage > 0
      ? `<p class="gg-note">計測率が低いラウンドがあります（${lowCoverage} 件）。HUD 非表示区間では値が欠損します。</p>`
      : '';

  return `
    <div class="match-detail-inner">
      ${createHeaderHtml(match, data)}
      ${buildGaugeNoticeHtml(data.gauges)}
      ${coverageNotice}
      ${buildGaugeSideFilterHtml(data.labels)}
      <div class="gg-rounds">${buildGaugeRoundsHtml(match.videoId, data.gauges, data.labels, context)}</div>
      ${buildRoundStatsTableHtml(match.videoId, data.roundStats, data.labels, data.characterHealth ?? null)}
    </div>
  `;
}

function render(html: string): void {
  const container = enterMatchDetailPageMode();
  container.innerHTML = html;
  setupGaugeSideFilter(container);
  window.scrollTo({ top: 0 });
}

/**
 * サイド表示フィルター（両方 / 自分 / 相手）を初期化する（ADR-060）
 *
 * 選択状態は `data-visible-side` としてコンテナに付与し、CSS で片側を非表示にする。
 * 前回の選択は localStorage に保存し、次回表示時に復元する。
 */
export function setupGaugeSideFilter(root: Document | HTMLElement = document): void {
  const inner = root.querySelector<HTMLElement>('.match-detail-inner');
  if (!inner) return;

  const buttons = Array.from(inner.querySelectorAll<HTMLButtonElement>('.gg-side-filter-btn'));
  if (buttons.length === 0) return;

  const apply = (side: GaugeVisibleSide): void => {
    inner.dataset.visibleSide = side;
    for (const button of buttons) {
      const active = button.dataset.side === side;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', String(active));
    }
  };

  let initial: GaugeVisibleSide = 'both';
  try {
    const stored = window.localStorage.getItem(GAUGE_SIDE_FILTER_STORAGE_KEY);
    if (stored === 'both' || stored === 'player1' || stored === 'player2') initial = stored;
  } catch {
    // localStorage が使えない環境では既定値（両方）のまま
  }
  apply(initial);

  for (const button of buttons) {
    button.addEventListener('click', () => {
      const side = button.dataset.side;
      if (side !== 'both' && side !== 'player1' && side !== 'player2') return;
      apply(side);
      try {
        window.localStorage.setItem(GAUGE_SIDE_FILTER_STORAGE_KEY, side);
      } catch {
        // 保存できなくても表示切り替え自体は機能する
      }
    });
  }
}

/** 読み込み中の表示 */
export function renderMatchDetailPageLoading(match: Match | null, matchId: string): void {
  const title = match ? match.videoTitle : matchId;
  render(`
    <div class="match-detail-inner">
      <div class="match-detail-page-header">
        <a class="match-detail-back" href="/">← 対戦検索に戻る</a>
        <h2 class="match-detail-page-title">${escapeHtml(title)}</h2>
      </div>
      <p class="gg-loading"><span class="spinner"></span>ゲージデータを読み込み中...</p>
    </div>
  `);
}

/** データ取得後の表示 */
export function renderMatchDetailPage(match: Match, data: MatchDetailPageData): void {
  render(buildMatchDetailPageHtml(match, data));
}

/** エラー表示 */
export function renderMatchDetailPageError(match: Match | null, matchId: string, message: string): void {
  const title = match ? match.videoTitle : matchId;
  render(`
    <div class="match-detail-inner">
      <div class="match-detail-page-header">
        <a class="match-detail-back" href="/">← 対戦検索に戻る</a>
        <h2 class="match-detail-page-title">${escapeHtml(title)}</h2>
      </div>
      <p class="gg-error">${escapeHtml(message)}</p>
    </div>
  `);
}

