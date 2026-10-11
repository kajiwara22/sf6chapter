/**
 * SF6 Chapter - データマニフェスト（ADR-055）
 *
 * R2 上の Parquet ファイルの内容を表す ETag 集合からバージョンを決める。
 * pipeline が `manifest.json` を書き、Web はそれを唯一の真実として
 * OPFS キャッシュ（Parquet バイト・DuckDB データベース）の有効性を判定する。
 */

import type { DataManifest, ManifestFileEntry } from './types';

/** manifest.json のフォーマット世代 */
export const MANIFEST_SCHEMA = 1;

/** R2 上の manifest オブジェクトキー */
export const MANIFEST_KEY = 'manifest.json';

/** manifest が追跡する Parquet ファイル（Web が参照するもの） */
export const MANIFEST_PARQUET_KEYS = [
  'matches.parquet',
  'battlelog_replays.parquet',
  'round_stats.parquet',
] as const;

export type ManifestParquetKey = (typeof MANIFEST_PARQUET_KEYS)[number];

/**
 * ファイル集合（名前 -> ETag）から決定的なバージョン文字列を計算する
 *
 * 同じ内容なら必ず同じ値になるため、この値を OPFS の DB ファイル名に使う。
 */
export async function computeManifestVersion(
  files: Record<string, Pick<ManifestFileEntry, 'etag'>>,
): Promise<string> {
  const payload = Object.keys(files)
    .sort()
    .map((key) => `${key}:${files[key].etag}`)
    .join('\n');

  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(payload));
  const hex = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');

  return hex.slice(0, 16);
}

/** manifest オブジェクトを組み立てる */
export async function buildManifest(
  files: Record<string, ManifestFileEntry>,
  generatedAt: string = new Date().toISOString(),
): Promise<DataManifest> {
  return {
    schema: MANIFEST_SCHEMA,
    version: await computeManifestVersion(files),
    generatedAt,
    files,
  };
}
