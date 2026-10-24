import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router";

import { SESSAO_ENCERRADA } from "./api/cliente";
import { identidadeAtual, type Papel } from "./api/sessao";
import { Entrar } from "./paginas/Entrar";
import { telaInicial } from "./rotas";

// Uma parte do bundle por tela: quem abre o link de acompanhamento (cliente na estrada, rede
// móvel) não baixa o painel nem o app do prestador.
const Painel = lazy(() => import("./paginas/Painel").then((m) => ({ default: m.Painel })));
const Prestador = lazy(() => import("./paginas/Prestador").then((m) => ({ default: m.Prestador })));
const Acompanhar = lazy(() => import("./paginas/Acompanhar").then((m) => ({ default: m.Acompanhar })));

function Exige({ papeis, children }: { papeis: Papel[]; children: ReactNode }) {
  const quem = identidadeAtual();
  if (!quem) return <Navigate to="/entrar" replace />;
  if (!papeis.includes(quem.papel)) return <Navigate to={telaInicial(quem.papel)} replace />;
  return children;
}

export function App() {
  const navegar = useNavigate();
  useEffect(() => {
    const aoEncerrar = () => navegar("/entrar", { replace: true });
    window.addEventListener(SESSAO_ENCERRADA, aoEncerrar);
    return () => window.removeEventListener(SESSAO_ENCERRADA, aoEncerrar);
  }, [navegar]);

  return (
    <Suspense fallback={<p className="vazio">Carregando…</p>}>
      <Routes>
      <Route path="/entrar" element={<Entrar />} />
      <Route
        path="/painel"
        element={
          <Exige papeis={["DESPACHANTE", "ATENDENTE", "ADMIN"]}>
            <Painel />
          </Exige>
        }
      />
      <Route
        path="/prestador"
        element={
          <Exige papeis={["PRESTADOR"]}>
            <Prestador />
          </Exige>
        }
      />
      <Route path="/acompanhar/:token" element={<Acompanhar />} />
      <Route path="*" element={<Navigate to={telaInicial(identidadeAtual()?.papel)} replace />} />
      </Routes>
    </Suspense>
  );
}
