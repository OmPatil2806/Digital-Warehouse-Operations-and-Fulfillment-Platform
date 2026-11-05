import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Read VITE_* variables from the shared .env in the project root
  envDir: '..',
  build: {
    // The main chunk holds the libraries every page needs (React, router, TanStack Query,
    // React Hook Form + Zod for the login form, Axios): ~160 kB gzipped. Pages are split
    // off with React.lazy (see routes/AppRoutes.tsx).
    chunkSizeWarningLimit: 600,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
})
