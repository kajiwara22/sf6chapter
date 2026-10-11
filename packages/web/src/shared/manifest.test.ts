import { describe, it, expect } from 'vitest';
import { buildManifest, computeManifestVersion, MANIFEST_SCHEMA } from './manifest';

describe('computeManifestVersion', () => {
  it('同じ内容なら同じバージョンになる', async () => {
    const files = {
      'matches.parquet': { etag: 'aaa' },
      'round_stats.parquet': { etag: 'ccc' },
    };
    const a = await computeManifestVersion(files);
    const b = await computeManifestVersion({
      'round_stats.parquet': { etag: 'ccc' },
      'matches.parquet': { etag: 'aaa' },
    });
    expect(a).toBe(b);
    expect(a).toMatch(/^[0-9a-f]{16}$/);
  });

  it('ETag が変わればバージョンも変わる', async () => {
    const before = await computeManifestVersion({ 'matches.parquet': { etag: 'aaa' } });
    const after = await computeManifestVersion({ 'matches.parquet': { etag: 'bbb' } });
    expect(before).not.toBe(after);
  });
});

describe('buildManifest', () => {
  it('schema と version と files を持つ', async () => {
    const manifest = await buildManifest(
      {
        'matches.parquet': { etag: 'aaa', size: 100 },
      },
      '2026-10-11T00:00:00.000Z',
    );

    expect(manifest.schema).toBe(MANIFEST_SCHEMA);
    expect(manifest.generatedAt).toBe('2026-10-11T00:00:00.000Z');
    expect(manifest.version).toMatch(/^[0-9a-f]{16}$/);
    expect(manifest.files['matches.parquet']).toEqual({ etag: 'aaa', size: 100 });
  });
});
