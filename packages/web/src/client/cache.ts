/**
 * SF6 Chapter - OPFS キャッシュ（ADR-055）
 *
 * - Parquet バイトを ETag で content-addressed に OPFS へ保存する（immutable）
 * - DuckDB データベースを manifest.version ごとに OPFS へ永続化する
 * - いずれも失敗しても正確性に影響しない（次のロードで再取得するだけ）
 *
 * OPFS が使えない環境では `available === false` となり、呼び出し側が
 * in-memory ロードへフォールバックする。
 */

import type { DataManifest, ManifestFileEntry, PresignedUrlResponse } from '@shared/types';
import { MANIFEST_PARQUET_KEYS, type ManifestParquetKey } from '@shared/manifest';

/** DuckDB データベースのスキーマ世代（列構成を変えたら上げる） */
export const DB_SCHEMA_VERSION = 1;

const CACHE_ROOT = 'sf6';
const BLOBS_DIR = 'blobs';
const DB_DIR = 'db';

/** Web が参照する Parquet テーブル名（拡張子つき） */
export const PARQUET_KEYS: readonly ManifestParquetKey[] = MANIFEST_PARQUET_KEYS;

/** DuckDB データベースの完了マーカー */
export interface DbMarker {
  /** DB スキーマ世代 */
  schema: number;
  /** manifest のバージョン */
  version: string;
  /** テーブル名 -> 行数（ビルド完了時の検証用） */
  tables: Record<string, number>;
}

/** OPFS のファイル書き込みストリーム（最小限のインターフェース） */
export interface OpfsWritableLike {
  write(data: BlobPart): Promise<void>;
  close(): Promise<void>;
}

/** OPFS のファイルハンドル（最小限のインターフェース） */
export interface OpfsFileHandleLike {
  getFile(): Promise<File>;
  createWritable(options?: { keepExistingData?: boolean }): Promise<OpfsWritableLike>;
}

/** OPFS のディレクトリハンドル（最小限のインターフェース） */
export interface OpfsDirectoryHandleLike {
  getFileHandle(name: string, options?: { create?: boolean }): Promise<OpfsFileHandleLike>;
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<OpfsDirectoryHandleLike>;
  removeEntry(name: string, options?: { recursive?: boolean }): Promise<void>;
  /** Chrome が提供する列挙 API（GC 用。無い環境では GC をスキップする） */
  keys?(): AsyncIterableIterator<string>;
}

/** OPFS のルートディレクトリを取得する（利用できなければ null） */
async function getOpfsRoot(): Promise<OpfsDirectoryHandleLike | null> {
  try {
    if (typeof navigator === 'undefined') return null;
    const storage = (navigator as Navigator & { storage?: StorageManager }).storage;
    if (!storage || typeof storage.getDirectory !== 'function') return null;
    return (await storage.getDirectory()) as unknown as OpfsDirectoryHandleLike;
  } catch (error) {
    console.warn('[Cache] OPFS を利用できません:', error);
    return null;
  }
}

/** Web Locks があれば排他実行する（同一 ETag の同時書き込み対策） */
async function runExclusive<T>(name: string, fn: () => Promise<T>): Promise<T> {
  try {
    const locks = (globalThis.navigator as Navigator | undefined)?.locks;
    if (!locks || typeof locks.request !== 'function') return await fn();
    return (await locks.request(name, fn)) as T;
  } catch (error) {
    console.warn(`[Cache] lock(${name}) を取得できませんでした。直接実行します:`, error);
    return await fn();
  }
}

/** removeEntry の失敗を握りつぶす（別タブで使用中・存在しない等） */
async function safeRemove(
  dir: OpfsDirectoryHandleLike,
  name: string,
  recursive = false,
): Promise<void> {
  try {
    await dir.removeEntry(name, { recursive });
  } catch (error) {
    console.warn(`[Cache] ${name} を削除できませんでした:`, error);
  }
}

/** Presigned URL を取得する */
export async function getPresignedUrl(apiPath: string): Promise<string> {
  const response = await fetch(apiPath);
  if (!response.ok) {
    throw new Error(`Failed to get presigned URL: ${response.status}`);
  }
  const data: PresignedUrlResponse = await response.json();
  return data.url;
}

/** データマニフェストを取得する（ADR-055） */
export async function fetchDataManifest(): Promise<DataManifest> {
  const response = await fetch('/api/data/manifest');
  if (!response.ok) {
    throw new Error(`Failed to fetch data manifest: ${response.status}`);
  }
  const manifest = (await response.json()) as DataManifest;
  if (!manifest?.version || !manifest?.files) {
    throw new Error('Invalid data manifest');
  }
  return manifest;
}

/** Presigned URL 経由で Parquet 1 ファイルをダウンロードする */
export async function downloadParquetBlob(key: string): Promise<Blob> {
  const url = await getPresignedUrl(`/api/data/index/${key}`);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to download ${key}: ${response.status}`);
  }
  return await response.blob();
}

/**
 * OPFS キャッシュ
 *
 * レイアウト:
 * ```
 * sf6/
 *   db/    sf6-v{schema}-{version}.db / .ok
 *   blobs/ {etag}/{name}
 * ```
 */
export class ParquetCache {
  private constructor(private readonly root: OpfsDirectoryHandleLike | null) {}

  /** OPFS の利用可否を判定して生成する */
  static async create(): Promise<ParquetCache> {
    const root = await getOpfsRoot();
    if (root) {
      try {
        const storage = (navigator as Navigator & { storage?: StorageManager }).storage;
        await storage?.persist?.();
      } catch (error) {
        console.warn('[Cache] persist() を要求できませんでした:', error);
      }
    }
    return new ParquetCache(root);
  }

  /** テスト用: 任意のディレクトリハンドルから生成する */
  static fromRoot(root: OpfsDirectoryHandleLike | null): ParquetCache {
    return new ParquetCache(root);
  }

  get available(): boolean {
    return this.root !== null;
  }

  /** manifest に対応する DuckDB データベースのファイル名 */
  dbFileName(manifest: DataManifest): string {
    return `sf6-v${DB_SCHEMA_VERSION}-${manifest.version}.db`;
  }

  /** DuckDB に渡す `opfs://` パス */
  dbPath(manifest: DataManifest): string {
    return `opfs://${CACHE_ROOT}/${DB_DIR}/${this.dbFileName(manifest)}`;
  }

  private async subDir(name: string, create: boolean): Promise<OpfsDirectoryHandleLike | null> {
    if (!this.root) return null;
    try {
      const root = await this.root.getDirectoryHandle(CACHE_ROOT, { create });
      return await root.getDirectoryHandle(name, { create });
    } catch {
      return null;
    }
  }

  /** 完了マーカーを読み込む */
  async readMarker(manifest: DataManifest): Promise<DbMarker | null> {
    const dir = await this.subDir(DB_DIR, false);
    if (!dir) return null;
    try {
      const handle = await dir.getFileHandle(`${this.dbFileName(manifest)}.ok`, { create: false });
      const file = await handle.getFile();
      return JSON.parse(await file.text()) as DbMarker;
    } catch {
      return null;
    }
  }

  /** 完了マーカーを書き込む */
  async writeMarker(manifest: DataManifest, marker: DbMarker): Promise<void> {
    const dir = await this.subDir(DB_DIR, true);
    if (!dir) return;
    await runExclusive(`sf6-marker-${this.dbFileName(manifest)}`, async () => {
      const handle = await dir.getFileHandle(`${this.dbFileName(manifest)}.ok`, { create: true });
      const writable = await handle.createWritable();
      await writable.write(JSON.stringify(marker));
      await writable.close();
    });
  }

  /** データベースとマーカーを削除する（破損・ロック時の再構築に使う） */
  async deleteDatabase(manifest: DataManifest): Promise<void> {
    const dir = await this.subDir(DB_DIR, false);
    if (!dir) return;
    await safeRemove(dir, this.dbFileName(manifest));
    await safeRemove(dir, `${this.dbFileName(manifest)}.ok`);
  }

  /** OPFS にあれば File を返し、無ければダウンロードして保存してから返す */
  async getParquet(key: string, entry: ManifestFileEntry): Promise<Blob> {
    const cached = await this.readBlob(key, entry.etag);
    if (cached) return cached;

    const blob = await downloadParquetBlob(key);
    try {
      await this.writeBlob(key, entry.etag, blob);
    } catch (error) {
      console.warn(`[Cache] ${key} のブロブ保存に失敗しました（メモリのみ使用）:`, error);
    }
    return blob;
  }

  private async readBlob(key: string, etag: string): Promise<File | null> {
    const dir = await this.subDir(BLOBS_DIR, false);
    if (!dir) return null;
    try {
      const etagDir = await dir.getDirectoryHandle(etag, { create: false });
      const handle = await etagDir.getFileHandle(key, { create: false });
      return await handle.getFile();
    } catch {
      return null;
    }
  }

  private async writeBlob(key: string, etag: string, blob: Blob): Promise<void> {
    const dir = await this.subDir(BLOBS_DIR, true);
    if (!dir) return;
    await runExclusive(`sf6-blob-${etag}-${key}`, async () => {
      const etagDir = await dir.getDirectoryHandle(etag, { create: true });
      const handle = await etagDir.getFileHandle(key, { create: true });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
    });
  }

  /**
   * 現在の manifest から参照されない DB / ブロブを削除する
   *
   * 列挙 API (`keys`) が無い環境では何もしない。
   */
  async evict(manifest: DataManifest): Promise<void> {
    if (!this.root) return;

    const keepDb = this.dbFileName(manifest);
    const keepEtags = new Set(Object.values(manifest.files).map((entry) => entry.etag));

    const dbDir = await this.subDir(DB_DIR, false);
    if (dbDir?.keys) {
      for await (const name of dbDir.keys()) {
        // 同一 version の DB と付随ファイル（.ok / .wal など）は残す
        if (name.startsWith(keepDb)) continue;
        await safeRemove(dbDir, name);
      }
    }

    const blobsDir = await this.subDir(BLOBS_DIR, false);
    if (blobsDir?.keys) {
      for await (const name of blobsDir.keys()) {
        if (keepEtags.has(name)) continue;
        await safeRemove(blobsDir, name, true);
      }
    }
  }

  /** キャッシュ全体（`sf6/`）を削除する */
  async clear(): Promise<void> {
    if (!this.root) return;
    await safeRemove(this.root, CACHE_ROOT, true);
  }
}
