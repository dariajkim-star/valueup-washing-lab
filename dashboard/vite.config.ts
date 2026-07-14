import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// AD-11: 프론트는 REST API로만 데이터 접근. dev proxy로 /api → FastAPI(127.0.0.1:8000)에
// 넘겨 CORS·하드코딩 URL을 피한다. 프로덕션은 리버스 프록시가 동일 경로를 담당.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
  },
  server: {
    port: 5175,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
