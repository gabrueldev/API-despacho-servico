// Tokens JWT do usuário logado. O access vale 15 min e o refresh 7 dias (com rotação):
// o cliente HTTP renova sozinho quando o access expira.

export type Papel = "ADMIN" | "ATENDENTE" | "DESPACHANTE" | "PRESTADOR" | "FINANCEIRO";

export interface Tokens {
  access: string;
  refresh: string;
}

export interface Identidade {
  usuarioId: number;
  papel: Papel;
}

const CHAVE = "despacha.sessao";
// sessionStorage (por aba), não localStorage: dá para operar como despachante numa aba e como
// prestador em outra, e a sessão some ao fechar a aba.
let emMemoria: Tokens | null = null;

// O storage pode faltar ou lançar (aba anônima, cookies bloqueados): a sessão então vive só
// na memória da aba, e o app continua funcionando.
function lerStorage(): Tokens | null {
  try {
    const bruto = sessionStorage.getItem(CHAVE);
    return bruto ? (JSON.parse(bruto) as Tokens) : null;
  } catch {
    return null;
  }
}

export function obterTokens(): Tokens | null {
  emMemoria ??= lerStorage();
  return emMemoria;
}

export function guardarTokens(tokens: Tokens | null): void {
  emMemoria = tokens;
  try {
    if (tokens) sessionStorage.setItem(CHAVE, JSON.stringify(tokens));
    else sessionStorage.removeItem(CHAVE);
  } catch {
    // sem storage: fica só em memória
  }
}

/** Lê as claims do JWT (sem validar a assinatura: quem valida é a API). */
export function decodificar(token: string): Identidade | null {
  try {
    const parte = token.split(".")[1];
    if (!parte) return null;
    const base64 = parte.replace(/-/g, "+").replace(/_/g, "/");
    const json = JSON.parse(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "=")));
    if (typeof json.user_id !== "number" && typeof json.user_id !== "string") return null;
    return { usuarioId: Number(json.user_id), papel: json.papel as Papel };
  } catch {
    return null;
  }
}

export function identidadeAtual(): Identidade | null {
  const tokens = obterTokens();
  return tokens ? decodificar(tokens.access) : null;
}
