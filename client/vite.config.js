import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      // Uploaded files (maintenance photos, logos, signatures, tutorial images)
      // are stored with RELATIVE urls like /uploads/maintenance/1/abc.jpg. In
      // production nginx serves those from the same origin as the app, so the
      // path just works. In dev the app is on :5173 and Flask is on :5000, so
      // without this proxy every uploaded image 404s against Vite and appears
      // broken — which looks exactly like a bug in the feature that uploaded it.
      '/uploads': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },
})
