import { defineConfig } from "vite";

// Tauri prefers a fixed, pickable port and a frontend that doesn't watch
// src-tauri (would cause infinite reload loops during `cargo build`).
export default defineConfig({
  clearScreen: false,
  server: {
    port: 1421,
    strictPort: true,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  build: {
    target: ["es2021", "chrome100", "safari13"],
    minify: !process.env.TAURI_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
});
