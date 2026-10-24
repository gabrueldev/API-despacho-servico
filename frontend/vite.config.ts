import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Em desenvolvimento o Vite repassa as rotas da API para o Django (sem CORS).
// Em produção quem faz esse papel é o Nginx (nginx/nginx.conf), com as mesmas rotas.
const API = process.env.DESPACHA_API ?? "http://127.0.0.1:8000";
const ROTAS_DA_API = [
  "/auth",
  "/chamados",
  "/prestadores",
  "/fechamentos",
  "/rastreio",
  "/health",
  "/admin",
  "/docs",
  "/schema",
  "/static",
];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(ROTAS_DA_API.map((rota) => [rota, { target: API }])),
  },
  test: {
    environment: "node",
  },
});
