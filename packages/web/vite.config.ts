import pages from '@hono/vite-cloudflare-pages';
import devServer from '@hono/vite-dev-server';
import { defineConfig } from 'vite';
import { resolve } from 'path';

/**
 * サーバーサイド（Pages Functions）のビルド設定
 */
export default defineConfig({
  plugins: [
    // Cloudflare Pages用ビルド
    pages({
      entry: 'src/server/index.tsx',
    }),
    // 開発サーバー
    devServer({
      entry: 'src/server/index.tsx',
      // 静的ファイルはViteから配信（Honoをバイパス）
      exclude: [
        /^\/static\/.+/,
        /^\/src\/.+/,
        /^\/@.+/,
        /^\/node_modules\/.+/,
      ],
    }),
  ],
  resolve: {
    alias: {
      '@shared': resolve(__dirname, 'src/shared'),
      '@client': resolve(__dirname, 'src/client'),
      '@server': resolve(__dirname, 'src/server'),
    },
  },
  // publicディレクトリの設定
  publicDir: 'public',
});
