import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const api = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    // Same host as the API so the session cookie and the CSRF origin check line up.
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': api, '/callback': api },
  },
})
