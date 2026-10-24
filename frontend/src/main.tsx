import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { ErroApi } from "./api/cliente";
import "./estilos.css";

const consultas = new QueryClient({
  defaultOptions: {
    queries: {
      // 4xx não melhora repetindo; falha de rede ou 5xx tenta mais uma vez.
      retry: (tentativas, erro) => !(erro instanceof ErroApi && erro.status < 500) && tentativas < 1,
      refetchOnWindowFocus: true,
    },
  },
});

const raiz = document.getElementById("raiz");
if (!raiz) throw new Error("Elemento #raiz não encontrado no index.html");

createRoot(raiz).render(
  <StrictMode>
    <QueryClientProvider client={consultas}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
