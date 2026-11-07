import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // the Python server (python -m sidekick ui) answers /api
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: {
    rollupOptions: {
      output: {
        manualChunks: { three: ['three', '@react-three/fiber', '@react-three/drei'] },
      },
    },
    chunkSizeWarningLimit: 1200,
  },
})
