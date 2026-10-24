import type { FonteDistancia, Status } from "../api/tipos";

export const ROTULO_STATUS: Record<Status, string> = {
  ABERTO: "Aguardando prestador",
  DESPACHADO: "Aguardando aceite",
  ACEITO: "Aceito",
  A_CAMINHO: "A caminho",
  NO_LOCAL: "No local",
  EM_ATENDIMENTO: "Em atendimento",
  CONCLUIDO: "Concluído",
  CANCELADO: "Cancelado",
};

// Frase do rastreio público, do ponto de vista de quem está esperando na estrada.
export const FRASE_RASTREIO: Record<Status, string> = {
  ABERTO: "Procurando um guincho perto de você",
  DESPACHADO: "Guincho encontrado, aguardando confirmação",
  ACEITO: "Guincho confirmado",
  A_CAMINHO: "Guincho a caminho",
  NO_LOCAL: "O guincho chegou",
  EM_ATENDIMENTO: "Atendimento em andamento",
  CONCLUIDO: "Atendimento concluído",
  CANCELADO: "Atendimento cancelado",
};

export const EM_ANDAMENTO: Status[] = ["DESPACHADO", "ACEITO", "A_CAMINHO", "NO_LOCAL", "EM_ATENDIMENTO"];

export const ROTULO_FONTE: Record<FonteDistancia, string> = {
  ROTA: "por estrada",
  LINHA_RETA: "em linha reta",
  ESTIMADA: "estimada (serviço de rotas indisponível)",
};

const moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
export const reais = (valor: string | number | null) =>
  valor === null ? "—" : moeda.format(Number(valor));

const km = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
export const quilometros = (valor: string | number) => `${km.format(Number(valor))} km`;

/** Distância até o cliente: em metros quando perto (arredondada de 50 em 50), em km depois de 1 km. */
export function distanciaAte(metros: number): string {
  if (metros >= 1000) return quilometros(metros / 1000);
  return `${Math.max(50, Math.round(metros / 50) * 50)} m`;
}

const relativo = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });
export function haQuanto(iso: string, agora = Date.now()): string {
  const segundos = Math.round((new Date(iso).getTime() - agora) / 1000);
  const abs = Math.abs(segundos);
  if (abs < 60) return relativo.format(segundos, "second");
  if (abs < 3600) return relativo.format(Math.round(segundos / 60), "minute");
  if (abs < 86_400) return relativo.format(Math.round(segundos / 3600), "hour");
  return relativo.format(Math.round(segundos / 86_400), "day");
}

const hora = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
export const horario = (iso: string) => hora.format(new Date(iso));

/** "Guincho 007" -> "prestador7@despacha.dev" (convenção do `seed`, só para a demonstração). */
export function loginDemo(nomePrestador: string): string | null {
  const numero = nomePrestador.match(/(\d+)\s*$/)?.[1];
  return numero ? `prestador${Number(numero)}@despacha.dev` : null;
}
