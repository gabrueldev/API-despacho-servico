import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";

import { api, ErroApi } from "../api/cliente";
import type { Rastreio } from "../api/tipos";
import { Mapa, type Marcador } from "../componentes/Mapa";
import { distanciaM } from "../lib/geo";
import { distanciaAte, FRASE_RASTREIO, haQuanto } from "../lib/formatos";

/** Página do link que o cliente recebe. Pública: só o token dá acesso, e a placa vem mascarada. */
export function Acompanhar() {
  const { token = "" } = useParams();
  const rastreio = useQuery({
    queryKey: ["acompanhar", token],
    queryFn: () => api<Rastreio>("GET", `/rastreio/${encodeURIComponent(token)}`, { autenticado: false }),
    // A API guarda a resposta por 5 s; consultar mais rápido que isso não traria nada novo.
    refetchInterval: (consulta) => {
      const status = consulta.state.data?.status;
      return status === "CONCLUIDO" || status === "CANCELADO" ? false : 5000;
    },
  });

  if (rastreio.isError) {
    const erro = rastreio.error;
    const expirado = erro instanceof ErroApi && erro.status === 410;
    const inexistente = erro instanceof ErroApi && erro.status === 404;
    return (
      <main className="acompanhar">
        <section className="sinal sinal--neutro">
          <h1>{expirado ? "Este link expirou" : inexistente ? "Link não encontrado" : "Não foi possível carregar"}</h1>
          <p>
            {expirado
              ? "O acompanhamento fica disponível até 24 horas depois do atendimento."
              : inexistente
                ? "Confira se o endereço foi copiado inteiro da mensagem que você recebeu."
                : "Verifique sua conexão. A página tenta de novo sozinha."}
          </p>
        </section>
      </main>
    );
  }

  const r = rastreio.data;
  if (!r) {
    return (
      <main className="acompanhar">
        <p className="vazio">Carregando o seu atendimento…</p>
      </main>
    );
  }

  const posicao = r.prestador?.posicao ?? null;
  const marcadores: Marcador[] = [
    { id: "origem", ponto: r.origem, tipo: "origem", rotulo: "Onde está o seu veículo" },
    { id: "destino", ponto: r.destino, tipo: "destino", rotulo: "Para onde ele será levado" },
  ];
  if (posicao) marcadores.push({ id: "guincho", ponto: posicao, tipo: "ao-vivo", rotulo: r.prestador!.nome });
  const indoBuscar = r.status === "ACEITO" || r.status === "A_CAMINHO";

  return (
    <main className="acompanhar">
      <section className={`sinal sinal--${r.status}`} aria-live="polite">
        <h1>{FRASE_RASTREIO[r.status]}</h1>
        {r.prestador && <p>{r.prestador.nome}</p>}
        {posicao && indoBuscar && <p>A {distanciaAte(distanciaM(posicao, r.origem))} de você, em linha reta</p>}
      </section>

      <Mapa marcadores={marcadores} chave={token} rotulo="Mapa do atendimento" />

      <dl className="ficha ficha--centro">
        <dt>Veículo</dt>
        <dd>{r.placa}</dd>
        {posicao?.registrado_em && (
          <>
            <dt>Posição atualizada</dt>
            <dd>{haQuanto(posicao.registrado_em)}</dd>
          </>
        )}
        {r.expira_em && (
          <>
            <dt>Link válido até</dt>
            <dd>{new Date(r.expira_em).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</dd>
          </>
        )}
      </dl>
    </main>
  );
}
