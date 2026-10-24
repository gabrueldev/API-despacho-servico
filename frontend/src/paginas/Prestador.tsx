import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, ErroApi } from "../api/cliente";
import type { ChamadoDetalhe, ChamadoResumo, MeuPerfil, Pagina, Ponto, Status } from "../api/tipos";
import { Mapa, type Marcador } from "../componentes/Mapa";
import { Placa } from "../componentes/Placa";
import { Topo } from "../componentes/Topo";
import { EM_ANDAMENTO, haQuanto, quilometros, reais, ROTULO_STATUS } from "../lib/formatos";
import { avancarAte, distanciaM } from "../lib/geo";

// A API aceita 6 posições por minuto por prestador; 12 s deixa folga.
const INTERVALO_GPS_MS = 12_000;
// Acelerado para a demonstração: ~210 km/h em linha reta.
const PASSO_M = 700;

type Proximo = { rotulo: string; acao: () => Promise<unknown> } | null;

function mensagem(erro: unknown): string {
  return erro instanceof Error ? erro.message : "Falha inesperada.";
}

/** Para onde o guincho está indo em cada fase: retirada do veículo e depois a entrega. */
function alvoDoStatus(chamado: ChamadoDetalhe | undefined): Ponto | null {
  if (!chamado) return null;
  if (chamado.status === "ACEITO" || chamado.status === "A_CAMINHO") return chamado.origem;
  if (chamado.status === "EM_ATENDIMENTO") return chamado.destino;
  return null;
}

export function Prestador() {
  const consultas = useQueryClient();
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  const perfil = useQuery({ queryKey: ["eu"], queryFn: () => api<MeuPerfil>("GET", "/prestadores/me") });
  const meus = useQuery({
    queryKey: ["meus-chamados"],
    queryFn: () => api<Pagina<ChamadoResumo>>("GET", "/chamados"),
    refetchInterval: 5000,
  });
  const atual = meus.data?.results.find((c) => EM_ANDAMENTO.includes(c.status));
  const detalhe = useQuery({
    queryKey: ["chamado", atual?.id],
    queryFn: () => api<ChamadoDetalhe>("GET", `/chamados/${atual!.id}`),
    enabled: atual !== undefined,
    refetchInterval: 5000,
  });
  const c = atual ? detalhe.data : undefined;

  const acao = useMutation({
    mutationFn: (executar: () => Promise<unknown>) => executar(),
    onSuccess: () => {
      setAviso(null);
      void consultas.invalidateQueries({ queryKey: ["meus-chamados"] });
      void consultas.invalidateQueries({ queryKey: ["chamado"] });
    },
    onError: (erro) => setAviso({ tipo: "erro", texto: mensagem(erro) }),
  });

  const post = (caminho: string, corpo?: unknown) => () => api("POST", caminho, { corpo });
  const avancar = (status: Status) => post(`/chamados/${c!.id}/status`, { status });
  const proximo: Proximo = !c
    ? null
    : {
        ACEITO: { rotulo: "Saí para o local", acao: avancar("A_CAMINHO") },
        A_CAMINHO: { rotulo: "Cheguei ao local", acao: avancar("NO_LOCAL") },
        NO_LOCAL: { rotulo: "Comecei o atendimento", acao: avancar("EM_ATENDIMENTO") },
        EM_ATENDIMENTO: { rotulo: "Concluir atendimento", acao: post(`/chamados/${c.id}/concluir`) },
      }[c.status as "ACEITO" | "A_CAMINHO" | "NO_LOCAL" | "EM_ATENDIMENTO"] ?? null;

  const gps = useSimuladorGps(perfil.data?.posicao ?? null, alvoDoStatus(c));

  const marcadores: Marcador[] = [];
  if (c) {
    marcadores.push(
      { id: "origem", ponto: c.origem, tipo: "origem", rotulo: `Retirada: ${c.endereco_origem}` },
      { id: "destino", ponto: c.destino, tipo: "destino", rotulo: "Entrega" },
    );
  }
  if (gps.posicao) marcadores.push({ id: "eu", ponto: gps.posicao, tipo: "ao-vivo", rotulo: "Você" });

  const encerrados = meus.data?.results.filter((x) => !EM_ANDAMENTO.includes(x.status)).slice(0, 5) ?? [];

  return (
    <div className="prestador">
      <Topo titulo="Meus atendimentos" quem={perfil.data?.nome ?? "Prestador"} />

      <main className="prestador__conteudo">
        {perfil.isError && <p className="aviso aviso--erro">{mensagem(perfil.error)}</p>}

        {!atual && meus.isSuccess && (
          <section className="vazio vazio--grande">
            <h2>Nenhum chamado para você agora</h2>
            <p>Quando um despachante te escolher, o chamado aparece aqui em poucos segundos.</p>
          </section>
        )}

        {c && (
          <article className="atendimento" aria-labelledby="atendimento-titulo">
            <header className="atendimento__cabeca">
              <Placa placa={c.placa} tamanho="grande" />
              <div>
                <h2 id="atendimento-titulo">{c.cliente.nome}</h2>
                <span className={`status status--${c.status}`}>{ROTULO_STATUS[c.status]}</span>
              </div>
            </header>
            <p className="atendimento__endereco">{c.endereco_origem}</p>
            <p className="atendimento__meta">
              Reboque de {quilometros(c.distancia_km)}, previsto {reais(c.valor_previsto)}
            </p>

            {c.status === "DESPACHADO" ? (
              <div className="atendimento__acoes">
                <button
                  type="button"
                  className="botao botao--primario botao--grande"
                  disabled={acao.isPending}
                  onClick={() => acao.mutate(post(`/chamados/${c.id}/aceitar`))}
                >
                  Aceitar chamado
                </button>
                <button
                  type="button"
                  className="botao botao--grande"
                  disabled={acao.isPending}
                  onClick={() => acao.mutate(post(`/chamados/${c.id}/recusar`, { motivo: "Recusado pelo app" }))}
                >
                  Recusar
                </button>
                <p className="atendimento__prazo">Sem resposta em 2 minutos, o chamado volta para a fila.</p>
              </div>
            ) : (
              proximo && (
                <button
                  type="button"
                  className="botao botao--primario botao--grande"
                  disabled={acao.isPending}
                  onClick={() => acao.mutate(proximo.acao)}
                >
                  {proximo.rotulo}
                </button>
              )
            )}

            {aviso && (
              <p className={`aviso aviso--${aviso.tipo}`} role="alert">
                {aviso.texto}
              </p>
            )}

            {(c.status === "A_CAMINHO" || c.status === "NO_LOCAL" || c.status === "EM_ATENDIMENTO") && (
              <LancarItem chamadoId={c.id} />
            )}

            {c.itens.length > 0 && (
              <table className="itens">
                <caption>Valores do atendimento</caption>
                <tbody>
                  {c.itens.map((i) => (
                    <tr key={i.id}>
                      <th scope="row">{i.descricao || i.tipo}</th>
                      <td>{reais(i.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </article>
        )}

        <section className="gps" aria-labelledby="gps-titulo">
          <h2 id="gps-titulo">Simulador de GPS</h2>
          <p>
            Envia sua posição a cada 12 segundos, andando em direção à retirada e, durante o atendimento, à entrega.
            O despachante e o cliente veem você se mover.
          </p>
          <label className="alternar">
            <input type="checkbox" checked={gps.ligado} onChange={(e) => gps.ligar(e.target.checked)} />
            {gps.ligado ? "Enviando posição" : "Simulador desligado"}
          </label>
          {gps.restanteM !== null && gps.ligado && (
            <p className="gps__restante">Faltam {quilometros(gps.restanteM / 1000)} até o próximo ponto.</p>
          )}
          {gps.erro && <p className="aviso aviso--erro">{gps.erro}</p>}
        </section>

        <Mapa marcadores={marcadores} trajeto={c ? [c.origem, c.destino] : undefined} chave={`p${c?.id ?? 0}`} rotulo="Seu mapa" />

        {encerrados.length > 0 && (
          <section aria-labelledby="recentes-titulo">
            <h2 id="recentes-titulo">Atendimentos recentes</h2>
            <ul className="recentes">
              {encerrados.map((x) => (
                <li key={x.id}>
                  <Placa placa={x.placa} />
                  <span>{ROTULO_STATUS[x.status]}</span>
                  <span>{reais(x.valor_final ?? x.valor_previsto)}</span>
                  <span>{haQuanto(x.criado_em)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>
    </div>
  );
}

function useSimuladorGps(inicial: Ponto | null, alvo: Ponto | null) {
  const [ligado, setLigado] = useState(false);
  const [posicao, setPosicao] = useState<Ponto | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  // O intervalo lê sempre os valores mais recentes sem ser recriado a cada render.
  const atual = useRef<{ posicao: Ponto | null; alvo: Ponto | null }>({ posicao: null, alvo: null });
  atual.current.alvo = alvo;

  useEffect(() => {
    if (inicial && !atual.current.posicao) {
      atual.current.posicao = inicial;
      setPosicao(inicial);
    }
  }, [inicial]);

  useEffect(() => {
    if (!ligado) return;
    let cancelado = false;
    const enviar = async () => {
      const de = atual.current.posicao;
      if (!de) return;
      const para = atual.current.alvo ? avancarAte(de, atual.current.alvo, PASSO_M) : de;
      try {
        await api("POST", "/prestadores/me/localizacao", { corpo: { posicao: para } });
        if (cancelado) return;
        atual.current.posicao = para;
        setPosicao(para);
        setErro(null);
      } catch (e) {
        if (!cancelado) {
          setErro(e instanceof ErroApi && e.status === 429 ? "Envio muito frequente; tentando de novo." : mensagem(e));
        }
      }
    };
    void enviar();
    const timer = setInterval(() => void enviar(), INTERVALO_GPS_MS);
    return () => {
      cancelado = true;
      clearInterval(timer);
    };
  }, [ligado]);

  return {
    ligado,
    ligar: setLigado,
    posicao,
    erro,
    restanteM: posicao && alvo ? distanciaM(posicao, alvo) : null,
  };
}

function LancarItem({ chamadoId }: { chamadoId: number }) {
  const consultas = useQueryClient();
  const [tipo, setTipo] = useState<"PEDAGIO" | "ESPERA" | "ADICIONAL">("PEDAGIO");
  const [valor, setValor] = useState("");
  const [descricao, setDescricao] = useState("");

  const lancar = useMutation({
    mutationFn: () =>
      api("POST", `/chamados/${chamadoId}/itens`, {
        corpo:
          tipo === "ESPERA"
            ? { tipo, minutos: Number(valor) }
            : { tipo, valor: valor.replace(",", "."), descricao },
      }),
    onSuccess: () => {
      setValor("");
      setDescricao("");
      void consultas.invalidateQueries({ queryKey: ["chamado", chamadoId] });
    },
  });

  function aoEnviar(evento: FormEvent) {
    evento.preventDefault();
    lancar.mutate();
  }

  return (
    <form className="formulario formulario--linha" onSubmit={aoEnviar} aria-label="Lançar valor extra">
      <label>
        Valor extra
        <select value={tipo} onChange={(e) => setTipo(e.target.value as typeof tipo)}>
          <option value="PEDAGIO">Pedágio</option>
          <option value="ESPERA">Tempo de espera</option>
          <option value="ADICIONAL">Adicional</option>
        </select>
      </label>
      <label>
        {tipo === "ESPERA" ? "Minutos" : "Valor (R$)"}
        <input
          required
          inputMode="decimal"
          value={valor}
          onChange={(e) => setValor(e.target.value)}
          placeholder={tipo === "ESPERA" ? "35" : "12,40"}
        />
      </label>
      {tipo === "ADICIONAL" && (
        <label>
          Descrição
          <input value={descricao} onChange={(e) => setDescricao(e.target.value)} placeholder="Patins, remoção…" />
        </label>
      )}
      <button type="submit" className="botao" disabled={lancar.isPending}>
        Lançar
      </button>
      {lancar.isError && <p className="aviso aviso--erro">{mensagem(lancar.error)}</p>}
    </form>
  );
}
