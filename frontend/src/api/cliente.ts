import { guardarTokens, obterTokens, type Tokens } from "./sessao";

/** Erro da API já no formato do back-end: `{"erro": "<codigo>", "detalhe": "..."}`. */
export class ErroApi extends Error {
  readonly status: number;
  readonly codigo: string;

  constructor(status: number, codigo: string, mensagem: string) {
    super(mensagem);
    this.name = "ErroApi";
    this.status = status;
    this.codigo = codigo;
  }
}

const MENSAGENS_POR_STATUS: Record<number, string> = {
  401: "Sua sessão expirou. Entre de novo.",
  403: "Seu perfil não tem acesso a esta ação.",
  404: "Não encontrado.",
  429: "Muitas requisições seguidas. Aguarde alguns segundos.",
};

/** Erros de validação do DRF, `{"campo": ["mensagem"]}`: devolve o primeiro como "campo: mensagem". */
function primeiroErroDeCampo(campos: Record<string, unknown>): string | null {
  for (const [campo, valor] of Object.entries(campos)) {
    const mensagem = Array.isArray(valor) ? valor[0] : valor;
    if (typeof mensagem === "string") return campo === "non_field_errors" ? mensagem : `${campo}: ${mensagem}`;
  }
  return null;
}

async function erroDaResposta(resposta: Response): Promise<ErroApi> {
  let corpo: unknown = null;
  try {
    corpo = await resposta.json();
  } catch {
    // corpo vazio ou HTML de proxy: fica a mensagem padrão do status
  }
  if (corpo && typeof corpo === "object") {
    const c = corpo as Record<string, unknown>;
    if (typeof c.erro === "string") {
      // O detalhe é texto nos erros de domínio e um objeto de campos nos de validação.
      const detalhe =
        typeof c.detalhe === "string"
          ? c.detalhe
          : c.detalhe && typeof c.detalhe === "object"
            ? primeiroErroDeCampo(c.detalhe as Record<string, unknown>)
            : null;
      return new ErroApi(resposta.status, c.erro, detalhe ?? c.erro);
    }
    if (typeof c.detail === "string") {
      return new ErroApi(resposta.status, "erro", c.detail);
    }
    const campo = primeiroErroDeCampo(c);
    if (campo) return new ErroApi(resposta.status, "validacao", campo);
  }
  const padrao = MENSAGENS_POR_STATUS[resposta.status] ?? `Erro ${resposta.status} na API.`;
  return new ErroApi(resposta.status, "http", padrao);
}

// Várias requisições podem receber 401 juntas; todas esperam a MESMA renovação. Com a rotação
// do refresh, duas renovações paralelas com o mesmo token fariam a segunda falhar.
let renovacaoEmAndamento: Promise<boolean> | null = null;

function renovar(refresh: string): Promise<boolean> {
  renovacaoEmAndamento ??= (async () => {
    try {
      const resposta = await fetch("/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh }),
      });
      if (!resposta.ok) return false;
      const novos = (await resposta.json()) as Partial<Tokens>;
      guardarTokens({ access: novos.access ?? "", refresh: novos.refresh ?? refresh });
      return true;
    } finally {
      renovacaoEmAndamento = null;
    }
  })();
  return renovacaoEmAndamento;
}

export const SESSAO_ENCERRADA = "despacha:sessao-encerrada";

/** Sessão sem volta (refresh recusado): limpa e avisa o app, que leva para o login. */
function encerrarSessao(): void {
  guardarTokens(null);
  if (typeof window !== "undefined") window.dispatchEvent(new Event(SESSAO_ENCERRADA));
}

interface Opcoes {
  corpo?: unknown;
  autenticado?: boolean;
  cabecalhos?: Record<string, string>;
}

export async function api<T>(metodo: string, caminho: string, opcoes: Opcoes = {}): Promise<T> {
  const { corpo, autenticado = true, cabecalhos = {} } = opcoes;

  const enviar = () => {
    const headers: Record<string, string> = { Accept: "application/json", ...cabecalhos };
    if (corpo !== undefined) headers["Content-Type"] = "application/json";
    const tokens = autenticado ? obterTokens() : null;
    if (tokens) headers.Authorization = `Bearer ${tokens.access}`;
    return fetch(caminho, {
      method: metodo,
      headers,
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  };

  let resposta = await enviar();
  const refresh = obterTokens()?.refresh;
  if (resposta.status === 401 && autenticado && refresh && (await renovar(refresh))) {
    resposta = await enviar();
  }
  if (resposta.status === 401 && autenticado) encerrarSessao();
  if (!resposta.ok) throw await erroDaResposta(resposta);
  if (resposta.status === 204) return undefined as T;
  return (await resposta.json()) as T;
}

export async function entrar(email: string, senha: string): Promise<void> {
  const tokens = await api<Tokens>("POST", "/auth/login", {
    corpo: { email, password: senha },
    autenticado: false,
  });
  guardarTokens(tokens);
}

export function sair(): void {
  guardarTokens(null);
}
