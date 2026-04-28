import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPort =
  process.env.STACK_UI_PORT ?? process.env.BENCHMARK_UI_PORT ?? "8765";
const apiTarget = `http://127.0.0.1:${apiPort}`;
const vitePort = Number(
  process.env.STACK_UI_VITE_PORT ?? process.env.BENCHMARK_UI_VITE_PORT ?? "5173",
);
const exposeDev =
  process.env.STACK_UI_EXPOSE_DEV === "1" ||
  process.env.BENCHMARK_UI_EXPOSE_DEV === "1";

export default defineConfig({
  plugins: [react()],
  server: {
    host: exposeDev ? true : "127.0.0.1",
    port: vitePort,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        // Long-lived SSE for launch-log stream (dev proxy defaults can time out).
        timeout: 3_600_000,
        proxyTimeout: 3_600_000,
      },
      "/v1": {
        target: apiTarget,
        changeOrigin: true,
        timeout: 3_600_000,
        proxyTimeout: 3_600_000,
      },
      "/health": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
