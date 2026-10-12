import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The build lands inside the Python package, so `pip install` ships the
// console without Node. The server answers any /admin route without a file
// extension (/admin/setup, /admin/invite) with index.html itself, so the build
// must not add a 404.html: StaticFiles would serve that instead, with a 404.
const outDir = fileURLToPath(new URL('../src/ira/web/admin', import.meta.url));

export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  build: { outDir, emptyOutDir: true },
  server: {
    // tokens.css lives in the Python package, outside this project root.
    fs: { allow: ['..'] },
    // xfwd sends X-Forwarded-Host, which the server's same-origin check on
    // writes accepts in place of a Host header the proxy has rewritten.
    proxy: { '/v1': { target: 'http://127.0.0.1:8790', changeOrigin: true, xfwd: true } },
  },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
});
