import { useNavigate } from "react-router";

import { sair } from "../api/cliente";

export function Topo({ titulo, quem }: { titulo: string; quem?: string }) {
  const navegar = useNavigate();
  return (
    <header className="topo">
      <span className="topo__marca">Despacha</span>
      <span className="topo__titulo">{titulo}</span>
      {quem && <span className="topo__quem">{quem}</span>}
      {quem && (
        <button
          type="button"
          className="botao botao--fantasma topo__sair"
          onClick={() => {
            sair();
            navegar("/entrar");
          }}
        >
          Sair
        </button>
      )}
    </header>
  );
}
