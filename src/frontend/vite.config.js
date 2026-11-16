import { defineConfig, loadEnv } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

// The repo-root .env holds FRONTEND_API_KEY. The dev server adds it to every /api request,
// so the key never reaches the browser.
const repoRoot = fileURLToPath(new URL('../../', import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, '');
  const proxy = {
    '/api': {
      target: env.API_URL || 'http://127.0.0.1:8000',
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api/, ''),
      headers: { 'X-API-Key': env.FRONTEND_API_KEY || '' },
    },
  };
  return {
    plugins: [svelte()],
    server: { port: 5173, proxy },
    preview: { port: 5173, proxy },
  };
});
