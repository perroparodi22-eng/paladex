import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the API runs on :8765 (python -m paladex serve); Vite proxies /api to it.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': '/src' } },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
})
