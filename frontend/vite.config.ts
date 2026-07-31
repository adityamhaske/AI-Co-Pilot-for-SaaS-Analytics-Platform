import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        // Only React is grouped. Recharts is deliberately *not* named here: it is
        // reached through a dynamic import in ToolTrace, and naming it hoists it into
        // the entry's dependency graph, which loads it eagerly and defeats the split.
        // Left alone, rolldown gives the dynamic import its own chunk.
        advancedChunks: {
          groups: [
            { name: "react", test: /node_modules\/(react|react-dom|scheduler)\// },
          ],
        },
      },
    },
  },
  server: {
    port: 6002,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})
