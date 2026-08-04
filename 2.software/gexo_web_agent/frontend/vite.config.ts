import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const frontendDir = dirname(fileURLToPath(import.meta.url));
const ringPageSource = resolve(
  frontendDir,
  "../../alloop/alloop_hackathon-main/web_ble/index.html",
);
const ringPageOutput = resolve(frontendDir, "../static/alloop/index.html");

function alloopRingPage(): Plugin {
  return {
    name: "alloop-ring-page",
    configureServer(server) {
      server.middlewares.use(
        "/alloop/index.html",
        (_request, response, next) => {
          try {
            response.setHeader("Content-Type", "text/html; charset=utf-8");
            response.end(readFileSync(ringPageSource));
          } catch {
            next();
          }
        },
      );
    },
    closeBundle() {
      mkdirSync(dirname(ringPageOutput), { recursive: true });
      copyFileSync(ringPageSource, ringPageOutput);
    },
  };
}

export default defineConfig({
  plugins: [react(), alloopRingPage()],
  build: {
    outDir: "../static",
    emptyOutDir: true,
    assetsDir: ".",
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "[name]-[hash].js",
        assetFileNames: (assetInfo) =>
          assetInfo.names.some((name) => name.endsWith(".css"))
            ? "style.css"
            : "[name]-[hash][extname]",
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
      },
    },
  },
});
