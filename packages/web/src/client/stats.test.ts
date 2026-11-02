import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('./search', () => ({
  getLatestLp: vi.fn(),
  initDuckDB: vi.fn(),
}));

import { getLatestLp } from './search';
import {
  clearMatchupBenchmarkCache,
  fetchStatsManifest,
  loadMatchupBenchmarks,
  resolveRankId,
} from './stats';

const manifest = {
  schema: 1,
  generatedAt: '2026-11-02T00:00:00Z',
  latestMonth: '202609',
  months: ['202608', '202609'],
  locales: ['ja-jp', 'en'],
  counts: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  clearMatchupBenchmarkCache();
});

describe('fetchStatsManifest', () => {
  it('manifest を返す', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(manifest)));
    await expect(fetchStatsManifest()).resolves.toEqual(manifest);
  });

  it('未配置（404）なら null', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 404 })));
    await expect(fetchStatsManifest()).resolves.toBeNull();
  });

  it('latestMonth がない manifest は null', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ ...manifest, latestMonth: '' })));
    await expect(fetchStatsManifest()).resolves.toBeNull();
  });
});

describe('resolveRankId', () => {
  it.each([
    [0, 1],
    [9000, 5],
    [19000, 7],
    [25000, 8],
  ])('LP %i はランク %i', async (lp, expected) => {
    vi.mocked(getLatestLp).mockResolvedValue(lp);
    await expect(resolveRankId()).resolves.toBe(expected);
  });

  it('LP が取れないときは MASTER', async () => {
    vi.mocked(getLatestLp).mockResolvedValue(null);
    await expect(resolveRankId()).resolves.toBe(8);
  });
});

describe('loadMatchupBenchmarks', () => {
  it('統計が未配置なら null を返して失敗しない', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 404 })));
    await expect(loadMatchupBenchmarks()).resolves.toBeNull();
  });

  it('Parquet の取得に失敗しても null を返す', async () => {
    vi.mocked(getLatestLp).mockResolvedValue(9000);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url === '/api/data/stats-manifest') {
          return Promise.resolve(Response.json(manifest));
        }
        return Promise.resolve(new Response(null, { status: 500 }));
      })
    );
    await expect(loadMatchupBenchmarks()).resolves.toBeNull();
  });
});
