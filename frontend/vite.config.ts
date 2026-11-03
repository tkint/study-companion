import { cp } from "node:fs/promises";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// pdf.js loads fonts, character maps and image decoders at runtime; ship them under /pdfjs.
function pdfjsAssets(): Plugin {
  return {
    name: "pdfjs-assets",
    apply: "build",
    async closeBundle() {
      for (const dir of ["cmaps", "standard_fonts", "wasm", "iccs"]) {
        await cp(`node_modules/pdfjs-dist/${dir}`, `dist/pdfjs/${dir}`, { recursive: true });
      }
    },
  };
}

// Dev: run the backend on :8000 and `npm run dev`; API, files and the server-rendered
// pages (login, settings) are proxied so the session cookie works on one origin.
const backend = "http://127.0.0.1:8000";
const proxied = ["/api", "/files", "/login", "/logout", "/settings", "/status", "/calendar.ics", "/healthz"];

export default defineConfig({
  plugins: [react(), pdfjsAssets()],
  build: {
    outDir: "dist",
    // Safari 15+ / Chrome 100+: phones from the last few years.
    target: ["es2020", "safari15", "chrome100"],
    chunkSizeWarningLimit: 1500,
  },
  server: {
    proxy: Object.fromEntries(proxied.map((p) => [p, { target: backend, changeOrigin: false }])),
  },
});
