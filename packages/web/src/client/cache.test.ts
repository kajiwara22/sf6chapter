import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  ParquetCache,
  type OpfsDirectoryHandleLike,
  type OpfsFileHandleLike,
  type OpfsWritableLike,
} from './cache';
import type { DataManifest } from '@shared/types';

/** メモリ上の OPFS を模したファイルハンドル */
class MockFileHandle implements OpfsFileHandleLike {
  constructor(
    private readonly files: Map<string, Blob>,
    private readonly name: string,
  ) {}

  async getFile(): Promise<File> {
    const blob = this.files.get(this.name);
    if (!blob) throw new DOMException('NotFound', 'NotFoundError');
    return new File([blob], this.name);
  }

  async createWritable(): Promise<OpfsWritableLike> {
    const files = this.files;
    const name = this.name;
    return {
      async write(data: BlobPart) {
        files.set(name, new Blob([data]));
      },
      async close() {
        /* noop */
      },
    };
  }
}

/** メモリ上の OPFS を模したディレクトリハンドル */
class MockDirHandle implements OpfsDirectoryHandleLike {
  readonly files = new Map<string, Blob>();
  readonly dirs = new Map<string, MockDirHandle>();

  async getFileHandle(name: string, options?: { create?: boolean }): Promise<OpfsFileHandleLike> {
    if (!this.files.has(name)) {
      if (!options?.create) throw new DOMException('NotFound', 'NotFoundError');
      this.files.set(name, new Blob([]));
    }
    return new MockFileHandle(this.files, name);
  }

  async getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<OpfsDirectoryHandleLike> {
    let dir = this.dirs.get(name);
    if (!dir) {
      if (!options?.create) throw new DOMException('NotFound', 'NotFoundError');
      dir = new MockDirHandle();
      this.dirs.set(name, dir);
    }
    return dir;
  }

  async removeEntry(name: string): Promise<void> {
    if (this.files.delete(name)) return;
    if (this.dirs.delete(name)) return;
    throw new DOMException('NotFound', 'NotFoundError');
  }

  async *keys(): AsyncIterableIterator<string> {
    for (const name of this.files.keys()) yield name;
    for (const name of this.dirs.keys()) yield name;
  }
}

function makeManifest(version: string, etags: string[]): DataManifest {
  const files: DataManifest['files'] = {};
  etags.forEach((etag, index) => {
    files[`file${index}.parquet`] = { etag, size: etag.length };
  });
  return { schema: 1, version, generatedAt: '2026-10-11T00:00:00.000Z', files };
}

describe('ParquetCache', () => {
  let root: MockDirHandle;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    root = new MockDirHandle();
    fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/data/index/')) {
        const key = url.split('/').pop();
        return new Response(JSON.stringify({ url: `https://r2.example/${key}`, expiresIn: 3600 }));
      }
      if (url.startsWith('https://r2.example/')) {
        return new Response(new Blob([`body:${url.split('/').pop()}`]));
      }
      return new Response(JSON.stringify({ version: 'ignored', files: {} }));
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('OPFS が無い場合は available=false になる', () => {
    const cache = ParquetCache.fromRoot(null);
    expect(cache.available).toBe(false);
  });

  it('DB のファイル名と opfs:// パスを manifest から導出する', () => {
    const cache = ParquetCache.fromRoot(root);
    const manifest = makeManifest('abc123', ['e1']);
    expect(cache.dbFileName(manifest)).toBe('sf6-v1-abc123.db');
    expect(cache.dbPath(manifest)).toBe('opfs://sf6/db/sf6-v1-abc123.db');
  });

  it('完了マーカーを書き込んで読み戻せる', async () => {
    const cache = ParquetCache.fromRoot(root);
    const manifest = makeManifest('abc123', ['e1']);

    expect(await cache.readMarker(manifest)).toBeNull();

    await cache.writeMarker(manifest, { schema: 1, version: 'abc123', tables: { matches: 10 } });

    expect(await cache.readMarker(manifest)).toEqual({
      schema: 1,
      version: 'abc123',
      tables: { matches: 10 },
    });
  });

  it('Parquet は初回のみダウンロードし、2 回目は OPFS から読む', async () => {
    const cache = ParquetCache.fromRoot(root);
    const entry = { etag: 'e1', size: 4 };

    const first = await cache.getParquet('matches.parquet', entry);
    expect(await first.text()).toBe('body:matches.parquet');
    const callsAfterFirst = fetchMock.mock.calls.length;
    expect(callsAfterFirst).toBe(2); // presign + download

    const second = await cache.getParquet('matches.parquet', entry);
    expect(await second.text()).toBe('body:matches.parquet');
    expect(fetchMock.mock.calls.length).toBe(callsAfterFirst); // 追加の fetch なし
  });

  it('ETag が変われば別のブロブとして保存する', async () => {
    const cache = ParquetCache.fromRoot(root);

    await cache.getParquet('matches.parquet', { etag: 'e1', size: 4 });
    await cache.getParquet('matches.parquet', { etag: 'e2', size: 4 });

    const blobs = root.dirs.get('sf6')?.dirs.get('blobs');
    expect([...(blobs?.dirs.keys() ?? [])].sort()).toEqual(['e1', 'e2']);
  });

  it('evict は現在の manifest で参照されないブロブと DB を削除する（同一 version の WAL は残す）', async () => {
    const cache = ParquetCache.fromRoot(root);
    await cache.getParquet('matches.parquet', { etag: 'old', size: 4 });
    await cache.getParquet('matches.parquet', { etag: 'new', size: 4 });

    const sf6 = await root.getDirectoryHandle('sf6', { create: true });
    const db = await sf6.getDirectoryHandle('db', { create: true });
    await db.getFileHandle('sf6-v1-v1.db', { create: true });
    await db.getFileHandle('sf6-v1-v2.db.wal', { create: true });

    const current = makeManifest('v2', ['new']);
    await cache.writeMarker(current, { schema: 1, version: 'v2', tables: {} });

    await cache.evict(current);

    const blobs = root.dirs.get('sf6')?.dirs.get('blobs');
    expect([...(blobs?.dirs.keys() ?? [])]).toEqual(['new']);
    const dbDir = root.dirs.get('sf6')?.dirs.get('db');
    expect([...(dbDir?.files.keys() ?? [])].sort()).toEqual([
      'sf6-v1-v2.db.ok',
      'sf6-v1-v2.db.wal',
    ]);
  });

  it('clear はキャッシュ全体を削除する', async () => {
    const cache = ParquetCache.fromRoot(root);
    await cache.getParquet('matches.parquet', { etag: 'e1', size: 4 });

    await cache.clear();

    expect(root.dirs.has('sf6')).toBe(false);
  });
});
