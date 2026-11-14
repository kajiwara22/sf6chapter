/**
 * SF6 Chapter - カウンター回数バッジ（ADR-075）
 *
 * ラウンド単位のカウンター / パニッシュカウンター回数を表示する。
 * 以前は対戦履歴のラウンドバッジに併記していたが（ADR-049）、
 * 履歴は勝敗のみとし、表示はゲージ詳細ページへ集約した。
 */

/**
 * カウンター回数の表示テキストを生成する
 *
 * 0 件の項目は省略し、両方 0 件（あるいは未計測）の場合は空文字を返す。
 */
export function formatCounterText(
  counterCount: number | null | undefined,
  punishCounterCount: number | null | undefined,
): string {
  if (counterCount == null && punishCounterCount == null) return '';
  const parts: string[] = [];
  if (counterCount) parts.push(`C${counterCount}`);
  if (punishCounterCount) parts.push(`PC${punishCounterCount}`);
  return parts.join(' ');
}

/**
 * カウンター回数のバッジHTMLを生成する（0 件なら空文字）
 */
export function createCounterBadge(
  counterCount: number | null | undefined,
  punishCounterCount: number | null | undefined,
): string {
  const text = formatCounterText(counterCount, punishCounterCount);
  if (!text) return '';
  const title = `COUNTER ${counterCount ?? 0} / PUNISH COUNTER ${punishCounterCount ?? 0}`;
  const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return `<span class="round-counter" title="${title}">${escaped}</span>`;
}

/** 未計測（null）は '-'、計測済み 0 件は '0' と区別する（ADR-049） */
export function formatCounterCount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return String(Math.round(value));
}
