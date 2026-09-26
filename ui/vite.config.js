import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxies /api/* to the FastAPI backend during `npm run dev` so the UI
// can just call fetch("/api/...") with no CORS/base-URL juggling. Ports
// match config.py's defaults (api_port=8000, ui_dev_port=5173); if you
// change those in .env, update this file to match.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
