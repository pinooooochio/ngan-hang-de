import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Bản build nằm trong gói Python để `nhd serve` phục vụ luôn giao diện
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/nganhangde/web", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
