import { describe, it, expect } from 'vitest';
import { api } from './api';
import { computeManifestVersion, MANIFEST_KEY } from '@shared/manifest';
import type { DataManifest } from '@shared/types';

/** manifest の GET/HEAD だけを実装した R2Bucket のモック */
function makeBucket(options: {
  manifest?: DataManifest;
  heads?: Record<string, { etag: string; size: number }>;
  getThrows?: boolean;
}) {
  return {
    async get(key: string) {
      if (key !== MANIFEST_KEY || !options.manifest) return null;
      if (options.getThrows) throw new Error('boom');
      return { async json() { return options.manifest; } };
    },
    async head(key: string) {
      const entry = options.heads?.[key];
      if (!entry) return null;
      return { httpEtag: `"${entry.etag}"`, size: entry.size };
    },
  };
}

function makeEnv(bucket: unknown) {
  return { SF6_DATA: bucket } as never;
}

describe('GET /api/data/manifest', () => {
  it('R2 の manifest.json をそのまま返す', async () => {
    const stored: DataManifest = {
      schema: 1,
      version: 'stored-version',
      generatedAt: '2026-10-11T00:00:00.000Z',
      files: { 'matches.parquet': { etag: 'e1', size: 100 } },
    };

    const res = await api.request('/data/manifest', { method: 'GET' }, makeEnv(makeBucket({ manifest: stored })));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(stored);
  });

  it('manifest.json が無い場合は head() から生成する（ETag の引用符を除去）', async () => {
    const bucket = makeBucket({
      heads: {
        'matches.parquet': { etag: 'abc', size: 115418 },
        'battlelog_replays.parquet': { etag: 'def', size: 81742 },
      },
    });

    const res = await api.request('/data/manifest', { method: 'GET' }, makeEnv(bucket));
    expect(res.status).toBe(200);

    const manifest = (await res.json()) as DataManifest;
    expect(manifest.files['matches.parquet']).toEqual({ etag: 'abc', size: 115418 });
    expect(manifest.files['round_stats.parquet']).toBeUndefined();
    expect(manifest.version).toBe(
      await computeManifestVersion({
        'matches.parquet': { etag: 'abc' },
        'battlelog_replays.parquet': { etag: 'def' },
      }),
    );
  });

  it('manifest.json の読み取りに失敗しても head() にフォールバックする', async () => {
    const bucket = makeBucket({
      manifest: { schema: 1, version: 'x', generatedAt: '', files: {} },
      heads: { 'matches.parquet': { etag: 'abc', size: 10 } },
      getThrows: true,
    });

    const res = await api.request('/data/manifest', { method: 'GET' }, makeEnv(bucket));
    expect(res.status).toBe(200);
    expect(((await res.json()) as DataManifest).files['matches.parquet'].etag).toBe('abc');
  });
});
