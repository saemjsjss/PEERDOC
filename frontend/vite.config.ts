import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API runs separately (scripts\serve.cmd -> http://127.0.0.1:8000). In development the
// Vite server forwards API calls there, so the browser only ever talks to one origin. In
// production the FastAPI server serves the built UI (frontend/dist) itself.
const API = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/jobs': API,
      '/verify': API,
      '/health': API,
    },
  },
})
