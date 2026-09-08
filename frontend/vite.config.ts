import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const { VITE_BACKEND_TARGET: configuredBackend } = loadEnv(mode, ".", "");
  const backendTarget = configuredBackend ?? "http://127.0.0.1:8000";
  if (!/^http:\/\/127\.0\.0\.1:\d{1,5}$/.test(backendTarget)) {
    throw new Error("VITE_BACKEND_TARGET must be an explicit loopback HTTP origin");
  }
  return {
    plugins: [react()],
    build: {
      assetsDir: "assets",
      emptyOutDir: true,
      manifest: true,
      sourcemap: false,
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: backendTarget,
          changeOrigin: false,
        },
      },
    },
    preview: {
      host: "127.0.0.1",
      port: 4173,
      strictPort: true,
    },
    test: {
      environment: "jsdom",
      exclude: ["e2e/**", "node_modules/**", "dist/**"],
      globals: false,
      restoreMocks: true,
      clearMocks: true,
    },
  };
});
