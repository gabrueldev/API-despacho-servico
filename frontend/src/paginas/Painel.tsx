import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { api, ErroApi } from "../api/cliente";
import { identidadeAtual } from "../api/sessao";
import type {
  ChamadoDetalhe,
  ChamadoResumo,
  EstadoChamado,
  Pagina,
  PrestadorProximo,
  Rastreio,
} from "../api/tipos";
import { Mapa, type Marcador } from "../componentes/Mapa";
import { Placa } from "../componentes/Placa";
import { Topo } from "../componentes/Topo";
import {
  EM_ANDAMENTO,
  haQuanto,
  horario,
  loginDemo,
  quilometros,
  reais,
  ROTULO_FONTE,
  ROTULO_STATUS,
} from "../lib/formatos";

type Filtro = "ABERTO" | "TODOS";
type Aviso = { tipo: "ok" | "erro"; texto: string } | null;

const despachar = (chamadoId: number, prestadorId: number) =>
  api<EstadoChamado>("POST", `/chamados/${chamadoId}/despachar`, {
    corpo: { prestador_id: prestadorId },
  });

function mensagem(erro: unknown): string {
  if (erro instanceof ErroApi && erro.status === 409) return `Conflito (409): ${erro.message}`;
  return erro instanceof Error ? erro.message : "Falha inesperada.";
}

export function Painel() {
  const quem = identidadeAtual();
  const podeDespachar = quem?.papel === "DESPACHANTE" || quem?.papel === "ADMIN";
  const [filtro, setFiltro] = useState<Filtro>("ABERTO");
  // O chamado aberto fica na URL (?chamado=123): sobrevive ao F5 e o link pode ser compartilhado.
  const [parametros, setParametros] = useSearchParams();
  const selecionado = Number(parametros.get("chamado")) || null;
  const setSelecionado = (id: number) => setParametros({ chamado: String(id) });

  const fila = useQuery({
    queryKey: ["chamados", filtro],
    queryFn: () =>
      api<Pagina<ChamadoResumo>>("GET", filtro === "ABERTO" ? "/chamados?status=ABERTO" : "/chamados"),
    refetchInterval: 5000,
  });

  return (
    <div className="painel">
      <Topo titulo="Despacho" quem={quem?.papel === "ATENDENTE" ? "Atendente" : "Despachante"} />

      <aside className="fila" aria-label="Fila de chamados">
        <div className="abas" role="tablist">
          {(["ABERTO", "TODOS"] as const).map((f) => (
            <button
              key={f}
              type="button"
              role="tab"
              aria-selected={filtro === f}
              className="abas__aba"
              onClick={() => setFiltro(f)}
            >
              {f === "ABERTO" ? "Na fila" : "Todos"}
            </button>
          ))}
        </div>

        {fila.isPending && <p className="vazio">Carregando a fila…</p>}
        {fila.isError && <p className="aviso aviso--erro">{mensagem(fila.error)}</p>}
        {fila.data?.results.length === 0 && (
          <p className="vazio">
            Nenhum chamado aguardando prestador. Os novos aparecem aqui sozinhos, a cada 5 segundos.
          </p>
        )}
        <ul className="fila__lista">
          {fila.data?.results.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className="fila__item"
                aria-current={selecionado === c.id}
                onClick={() => setSelecionado(c.id)}
              >
                <Placa placa={c.placa} />
                <span className="fila__cliente">{c.cliente.nome}</span>
                <span className={`status status--${c.status}`}>{ROTULO_STATUS[c.status]}</span>
                <span className="fila__quando">
                  Chamado {c.id}, aberto {haQuanto(c.criado_em)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {selecionado === null ? (
        <section className="palco palco--vazio">
          <Mapa marcadores={[]} chave="vazio" rotulo="Mapa da operação" />
          <p className="palco__dica">Escolha um chamado na fila para ver o local e os prestadores livres por perto.</p>
        </section>
      ) : (
        <PainelDoChamado key={selecionado} id={selecionado} podeDespachar={podeDespachar} />
      )}
    </div>
  );
}

function PainelDoChamado({ id, podeDespachar }: { id: number; podeDespachar: boolean }) {
  const consultas = useQueryClient();
  const [escolhido, setEscolhido] = useState<number | null>(null);
  const [aviso, setAviso] = useState<Aviso>(null);
  const [corrida, setCorrida] = useState<string[] | null>(null);

  const detalhe = useQuery({
    queryKey: ["chamado", id],
    queryFn: () => api<ChamadoDetalhe>("GET", `/chamados/${id}`),
    refetchInterval: 5000,
  });
  const c = detalhe.data;
  const aberto = c?.status === "ABERTO";
  const emAndamento = c ? EM_ANDAMENTO.includes(c.status) : false;

  const proximos = useQuery({
    queryKey: ["proximos", id],
    queryFn: () =>
      api<PrestadorProximo[]>(
        "GET",
        `/prestadores/proximos?lat=${c!.origem.lat}&lng=${c!.origem.lng}&raio=30`,
      ),
    enabled: aberto,
    refetchInterval: 10_000,
  });

  // A posição do prestador em atendimento vem do mesmo endpoint do link público.
  const aoVivo = useQuery({
    queryKey: ["rastreio", c?.rastreio_token],
    queryFn: () => api<Rastreio>("GET", `/rastreio/${c!.rastreio_token}`, { autenticado: false }),
    enabled: emAndamento,
    refetchInterval: 5000,
  });

  const atualizar = () => {
    void consultas.invalidateQueries({ queryKey: ["chamados"] });
    void consultas.invalidateQueries({ queryKey: ["chamado", id] });
  };

  const despacho = useMutation({
    mutationFn: (p: PrestadorProximo) => despachar(id, p.id),
    onSuccess: (_estado, p) => {
      const login = loginDemo(p.nome);
      setAviso({
        tipo: "ok",
        texto: `Despachado para ${p.nome}. Ele tem 2 minutos para aceitar.${
          login ? ` Para aceitar, entre como ${login}.` : ""
        }`,
      });
      atualizar();
    },
    onError: (erro) => setAviso({ tipo: "erro", texto: mensagem(erro) }),
  });

  async function testarCorrida(candidatos: PrestadorProximo[]) {
    setAviso(null);
    setCorrida(null);
    const resultados = await Promise.allSettled(candidatos.map((p) => despachar(id, p.id)));
    setCorrida(
      resultados.map((r, i) => {
        const nome = candidatos[i]!.nome;
        if (r.status === "rejected") return `${nome}: ${mensagem(r.reason)}`;
        const login = loginDemo(nome);
        return `${nome}: despachado${login ? ` (para aceitar, entre como ${login})` : ""}`;
      }),
    );
    atualizar();
  }

  if (detalhe.isPending) return <section className="palco"><p className="vazio">Carregando o chamado…</p></section>;
  if (detalhe.isError || !c) {
    return (
      <section className="palco">
        <p className="aviso aviso--erro">{mensagem(detalhe.error)}</p>
      </section>
    );
  }

  const marcadores: Marcador[] = [
    { id: "origem", ponto: c.origem, tipo: "origem", rotulo: `Retirada: ${c.endereco_origem}` },
    { id: "destino", ponto: c.destino, tipo: "destino", rotulo: "Entrega" },
  ];
  if (aberto) {
    for (const p of proximos.data ?? []) {
      marcadores.push({
        id: `p${p.id}`,
        ponto: p,
        tipo: "livre",
        rotulo: `${p.nome}, a ${quilometros(p.distancia_km)}`,
        destaque: escolhido === p.id,
        aoClicar: () => setEscolhido(p.id),
      });
    }
  }
  const posicao = aoVivo.data?.prestador?.posicao;
  if (emAndamento && posicao) {
    marcadores.push({ id: "ao-vivo", ponto: posicao, tipo: "ao-vivo", rotulo: c.prestador?.nome ?? "Prestador" });
  }

  const lista = proximos.data ?? [];
  return (
    <section className="palco">
      <Mapa
        marcadores={marcadores}
        trajeto={[c.origem, c.destino]}
        chave={`c${c.id}`}
        rotulo="Mapa do chamado"
        painelADireita
      />

      <article className="chamado" aria-labelledby="chamado-titulo">
        <header className="chamado__cabeca">
          <Placa placa={c.placa} tamanho="grande" />
          <div>
            <h2 id="chamado-titulo">{c.cliente.nome}</h2>
            <p className="chamado__numero">Chamado {c.id}</p>
            <span className={`status status--${c.status}`}>{ROTULO_STATUS[c.status]}</span>
          </div>
        </header>

        <dl className="ficha">
          <dt>Retirada</dt>
          <dd>{c.endereco_origem}</dd>
          <dt>Distância</dt>
          <dd>
            {quilometros(c.distancia_km)} {ROTULO_FONTE[c.distancia_fonte]}
          </dd>
          <dt>{c.valor_final ? "Valor final" : "Valor previsto"}</dt>
          <dd>{reais(c.valor_final ?? c.valor_previsto)}</dd>
          {c.prestador && (
            <>
              <dt>Prestador</dt>
              <dd>{c.prestador.nome}</dd>
            </>
          )}
        </dl>

        <a className="link" href={`/acompanhar/${c.rastreio_token}`} target="_blank" rel="noreferrer">
          Abrir o link de acompanhamento do cliente
        </a>

        {aviso && (
          <p className={`aviso aviso--${aviso.tipo}`} role="status">
            {aviso.texto}
          </p>
        )}

        {/* Fora do bloco "aberto": depois da corrida o chamado já saiu da fila. */}
        {corrida && (
          <div className="corrida" role="status">
            <h3>Dois despachos ao mesmo tempo</h3>
            <ul className="corrida__resultado">
              {corrida.map((linha) => (
                <li key={linha}>{linha}</li>
              ))}
            </ul>
          </div>
        )}

        {aberto && (
          <section className="proximos" aria-labelledby="proximos-titulo">
            <h3 id="proximos-titulo">Prestadores livres em 30 km</h3>
            {proximos.isPending && <p className="vazio">Buscando prestadores…</p>}
            {proximos.data?.length === 0 && (
              <p className="vazio">
                Ninguém livre com posição recente neste raio. Rode o comando simular_frota para manter a frota de
                demonstração em movimento.
              </p>
            )}
            <ol className="proximos__lista">
              {lista.map((p) => (
                <li key={p.id} className={escolhido === p.id ? "proximos__item proximos__item--escolhido" : "proximos__item"}>
                  <button type="button" className="proximos__nome" onClick={() => setEscolhido(p.id)}>
                    {p.nome}
                    <span>{quilometros(p.distancia_km)}</span>
                  </button>
                  {podeDespachar && (
                    <button
                      type="button"
                      className="botao botao--primario"
                      disabled={despacho.isPending}
                      onClick={() => despacho.mutate(p)}
                    >
                      Despachar
                    </button>
                  )}
                </li>
              ))}
            </ol>

            {podeDespachar && lista.length >= 2 && (
              <div className="corrida">
                <p>
                  Dois despachantes clicando ao mesmo tempo: o banco trava o chamado e só um vence. O outro recebe 409
                  na hora, sem esperar.
                </p>
                <button type="button" className="botao" onClick={() => void testarCorrida(lista.slice(0, 2))}>
                  Despachar os 2 mais próximos ao mesmo tempo
                </button>
              </div>
            )}
          </section>
        )}

        <section aria-labelledby="historico-titulo">
          <h3 id="historico-titulo">Histórico</h3>
          <ol className="historico">
            {c.eventos.map((e) => (
              <li key={e.id}>
                <time dateTime={e.criado_em}>{horario(e.criado_em)}</time>
                {e.de_status === e.para_status
                  ? `Item lançado: ${String(e.dados.item ?? "")} ${reais(String(e.dados.total ?? 0))}`
                  : ROTULO_STATUS[e.para_status]}
              </li>
            ))}
          </ol>
        </section>
      </article>
    </section>
  );
}
