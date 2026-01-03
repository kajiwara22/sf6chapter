/**
 * SF6 Chapter - サーバーエントリーポイント
 * Hono + Cloudflare Pages Functions
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import type { Bindings } from './types';
import { api } from './routes/api';
import { pages } from './routes/pages';

const app = new Hono<{Bindings:Bindings}>();

// ミドルウェア
app.use('*', logger());
app.use(
  '/api/*',
  cors({
    origin: '*',
    allowMethods: ['GET', 'OPTIONS'],
    allowHeaders: ['Content-Type'],
  })
);

// APIルート
app.route('/api', api);

// ページルート
app.route('/', pages);

export default app;
