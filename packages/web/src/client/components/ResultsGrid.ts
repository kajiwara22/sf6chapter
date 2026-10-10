/**
 * SF6 Chapter - 検索結果グリッドコンポーネント
 *
 * 結果カードのクリックでゲージ詳細パネルを表示する（ADR-048）。
 */

import { DOM_IDS } from '../types';
import type { Match, GaugeData, RoundStatsRow, CharacterHealthTable } from '@shared/types';
import {
  buildGaugeNoticeHtml,
  buildGaugeRoundsHtml,
  buildRoundStatsTableHtml,
  resolveSideCharacters,
  sideText,
  type GaugeChartContext,
  type GaugeSideLabels,
} from './RoundGaugeChart';

/**
 * 秒数を「分:秒」形式に変換
 */
function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * YouTube動画へのリンクを生成
 */
function createYouTubeLink(videoId: string, startTime: number): string {
  return `https://www.youtube.com/watch?v=${videoId}&t=${startTime}s`;
}

/**
 * 日付をフォーマット
 */
function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString('ja-JP', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

/**
 * 対戦カードのHTMLを生成
 */
function createMatchCard(match: Match): string {
  const youtubeLink = createYouTubeLink(match.videoId, match.startTime);

  return `
    <article class="match-card match-card-clickable" data-match-id="${escapeHtml(match.id)}" role="button" tabindex="0" aria-label="ゲージ詳細を表示">
      <div class="match-header">
        <h3 class="video-title">${escapeHtml(match.videoTitle)}</h3>
        <span class="match-date">${formatDate(match.videoPublishedAt)}</span>
      </div>
      <div class="match-players">
        <div class="player player-1p">
          <span class="player-character">${escapeHtml(match.player1.character)}</span>
          <span class="player-side">1P</span>
          ${match.player1.result ? `<span class="player-result result-${match.player1.result}">${match.player1.result === 'win' ? 'Wins' : 'Loses'}</span>` : ''}
        </div>
        <div class="match-vs">VS</div>
        <div class="player player-2p">
          <span class="player-character">${escapeHtml(match.player2.character)}</span>
          <span class="player-side">2P</span>
          ${match.player2.result ? `<span class="player-result result-${match.player2.result}">${match.player2.result === 'win' ? 'Wins' : 'Loses'}</span>` : ''}
        </div>
      </div>
      <div class="match-meta">
        <span class="match-time">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
          ${formatTime(match.startTime)}
        </span>
        ${match.battlelogMatched ? `<span class="battlelog-badge confidence-${match.battlelogConfidence}">BL: ${match.battlelogConfidence}</span>` : ''}
        <span class="match-detail-hint">ゲージ詳細</span>
      </div>
      <a href="${youtubeLink}" target="_blank" rel="noopener" class="match-link">
        <svg class="icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
        </svg>
        動画で見る
      </a>
    </article>
  `;
}

/**
 * HTMLエスケープ
 */
function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/** 結果カードのクリックハンドラ */
export type MatchSelectHandler = (match: Match) => void;

/**
 * 検索結果を表示
 *
 * @param matches 検索結果
 * @param onSelect カードクリック時のハンドラ（省略時はクリック無効）
 */
export function renderResults(matches: Match[], onSelect?: MatchSelectHandler): void {
  const container = document.getElementById(DOM_IDS.RESULTS);
  const noResults = document.getElementById(DOM_IDS.NO_RESULTS);

  if (!container || !noResults) {
    console.error('[ResultsGrid] Container elements not found');
    return;
  }

  if (matches.length === 0) {
    container.innerHTML = '';
    noResults.style.display = 'block';
    return;
  }

  noResults.style.display = 'none';
  container.innerHTML = matches.map(createMatchCard).join('');

  if (!onSelect) return;

  const matchById = new Map(matches.map((match) => [match.id, match]));
  const cards = container.querySelectorAll<HTMLElement>('.match-card');
  for (const card of cards) {
    const matchId = card.dataset.matchId;
    const match = matchId ? matchById.get(matchId) : undefined;
    if (!match) continue;

    const activate = () => onSelect(match);
    card.addEventListener('click', (event) => {
      // カード内のリンク・ボタン操作は詳細表示に横取りしない
      const target = event.target as HTMLElement | null;
      if (target?.closest('a, button')) return;
      activate();
    });
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        activate();
      }
    });
  }
}

/**
 * 検索結果をクリア
 */
export function clearResults(): void {
  const container = document.getElementById(DOM_IDS.RESULTS);
  const noResults = document.getElementById(DOM_IDS.NO_RESULTS);

  if (container) {
    container.innerHTML = '';
  }
  if (noResults) {
    noResults.style.display = 'none';
  }
}

/** 詳細パネルに渡すゲージ関連データ */
export interface MatchDetailData {
  /** gauges JSON（未取得・不存在時は null） */
  gauges: GaugeData | null;
  /** round_stats の行（未取得時は空配列） */
  roundStats: RoundStatsRow[];
  /** 自分視点の表示ラベル */
  labels: GaugeSideLabels;
  /** キャラクター別最大体力表（ADR-050、未取得時は null） */
  characterHealth?: CharacterHealthTable | null;
}

/**
 * 詳細パネルのヘッダーHTMLを生成
 */
function createDetailHeader(match: Match, labels: GaugeSideLabels): string {
  const youtubeUrl = createYouTubeLink(match.videoId, match.startTime);
  return `
    <div class="match-detail-header">
      <div class="match-detail-title">
        <h3>${escapeHtml(match.videoTitle)}</h3>
        <span class="match-detail-time">${formatTime(match.startTime)}</span>
      </div>
      <div class="match-detail-players">
        <span class="match-detail-player match-detail-player1">${escapeHtml(sideText(labels.player1, 'player1'))}: <strong>${escapeHtml(match.player1.character)}</strong></span>
        <span class="match-detail-vs">VS</span>
        <span class="match-detail-player match-detail-player2">${escapeHtml(sideText(labels.player2, 'player2'))}: <strong>${escapeHtml(match.player2.character)}</strong></span>
      </div>
      <a class="match-detail-youtube" href="${youtubeUrl}" target="_blank" rel="noopener">YouTubeで見る</a>
      <button type="button" class="match-detail-close" id="match-detail-close" aria-label="閉じる">×</button>
    </div>
  `;
}

/**
 * 詳細パネルの中身を生成する
 */
function createDetailHtml(match: Match, data: MatchDetailData): string {
  // 実 HP 表示用のキャラ名は round_stats.character を優先し、無ければ matches の値を使う（ADR-050）
  const context: GaugeChartContext = {
    characterHealth: data.characterHealth ?? null,
    characters: resolveSideCharacters(
      { player1: match.player1.character, player2: match.player2.character },
      data.roundStats,
    ),
  };
  return `
    <div class="match-detail-inner">
      ${createDetailHeader(match, data.labels)}
      ${buildGaugeNoticeHtml(data.gauges)}
      <div class="gg-rounds">${buildGaugeRoundsHtml(match.videoId, data.gauges, data.labels, context)}</div>
      ${buildRoundStatsTableHtml(data.roundStats, data.labels, data.characterHealth ?? null)}
    </div>
  `;
}

/**
 * 詳細パネルの要素を取得し、表示状態にする
 */
function showDetailContainer(html: string): void {
  const container = document.getElementById(DOM_IDS.MATCH_DETAIL);
  if (!container) {
    console.error('[ResultsGrid] Detail container not found');
    return;
  }
  container.innerHTML = html;
  container.style.display = 'block';
  container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/**
 * 詳細パネルの閉じるボタンにハンドラを付与する
 */
function attachDetailClose(): void {
  const closeButton = document.getElementById('match-detail-close');
  closeButton?.addEventListener('click', () => clearMatchDetail());
}

/**
 * ゲージ詳細パネルを表示（読み込み中）
 */
export function showMatchDetailLoading(match: Match): void {
  showDetailContainer(`
    <div class="match-detail-inner">
      ${createDetailHeader(match, { player1: null, player2: null })}
      <p class="gg-loading"><span class="spinner"></span>ゲージデータを読み込み中...</p>
    </div>
  `);
  attachDetailClose();
}

/**
 * ゲージ詳細パネルを表示（データ取得後）
 */
export function renderMatchDetail(match: Match, data: MatchDetailData): void {
  showDetailContainer(createDetailHtml(match, data));
  attachDetailClose();
}

/**
 * ゲージ詳細パネルを表示（エラー）
 */
export function showMatchDetailError(match: Match, message: string): void {
  showDetailContainer(`
    <div class="match-detail-inner">
      ${createDetailHeader(match, { player1: null, player2: null })}
      <p class="gg-error">${escapeHtml(message)}</p>
    </div>
  `);
  attachDetailClose();
}

/**
 * ゲージ詳細パネルを非表示にする
 */
export function clearMatchDetail(): void {
  const container = document.getElementById(DOM_IDS.MATCH_DETAIL);
  if (container) {
    container.innerHTML = '';
    container.style.display = 'none';
  }
}
