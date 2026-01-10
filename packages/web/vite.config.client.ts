import { defineConfig } from 'vite';
import { resolve } from 'path';

/**
 * クライアントサイドのビルド設定
 * index.htmlとクライアントJS/CSSをビルド
 */
export default defineConfig({
  resolve: {
    alias: {
      '@shared': resolve(__dirname, 'src/shared'),
      '@client': resolve(__dirname, 'src/client'),
    },
  },
  publicDir: 'public',
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
      },
    },
    // アセットをassetsディレクトリに配置
    assetsDir: 'assets',
    // マニフェストを生成（デバッグ用）
    manifest: true,
  },
});
