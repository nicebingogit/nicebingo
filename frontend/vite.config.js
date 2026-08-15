import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The built app is served by Flask (server.py) from frontend/dist.
// `npm run dev` proxies /api to the local Flask server for development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5000',
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
