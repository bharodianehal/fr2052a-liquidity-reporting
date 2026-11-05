import { defineConfig } from 'vite'

// JSX is compiled by Vite's built-in esbuild (automatic runtime); no React plugin needed.
export default defineConfig({
  esbuild: {
    jsx: 'automatic',
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
