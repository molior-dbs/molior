/**
 * Vite config for the molior React web UI.
 *
 * Dev mode:  `npm run dev`
 *   - Vite dev server on :5173
 *   - /api/* and /api2/* proxied to the molior FastAPI server on :9999
 *     (or to http://localhost:8000 when running through the k3d ingress)
 *   - /api/websocket is proxied as a WebSocket
 *
 * Production build: `npm run build`
 *   - Output goes to dist/ — nginx serves it as static files
 *   - All /api/* routes are handled by the same nginx reverse-proxy
 *     (see nginx-molior-web config)
 *
 * The proxy targets mirror the old Angular dev proxy:
 *   docker/dev/ng-serve.proxy.conf.json
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const MOLIOR_API = process.env.MOLIOR_API_URL || 'http://localhost:9999';

export default defineConfig({
  plugins: [react()],

  server: {
    port: 5173,
    proxy: {
      // WebSocket — must come before the /api catch-all
      '/api/websocket': {
        target: MOLIOR_API.replace(/^http/, 'ws'),
        ws: true,
        changeOrigin: true,
      },
      '/api': {
        target: MOLIOR_API,
        changeOrigin: true,
      },
      '/api2': {
        target: MOLIOR_API,
        changeOrigin: true,
      },
      '/internal': {
        target: MOLIOR_API,
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: 'dist',
    // Keep asset hashes so nginx can set long cache headers
    assetsDir: 'assets',
  },
});
