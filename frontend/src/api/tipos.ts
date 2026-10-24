// Formatos das respostas da API (ver /docs/ para o schema OpenAPI completo).

export type Status =
  | "ABERTO"
  | "DESPACHADO"
  | "ACEITO"
  | "A_CAMINHO"
  | "NO_LOCAL"
  | "EM_ATENDIMENTO"
  | "CONCLUIDO"
  | "CANCELADO";

export type FonteDistancia = "LINHA_RETA" | "ROTA" | "ESTIMADA";

export interface Ponto {
  lat: number;
  lng: number;
}

export interface Pagina<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface ChamadoResumo {
  id: number;
  status: Status;
  placa: string;
  cliente: { id: number; nome: string };
  prestador: { id: number; nome: string } | null;
  valor_previsto: string;
  valor_final: string | null;
  criado_em: string;
}

export interface Item {
  id: number;
  tipo: string;
  descricao: string;
  quantidade: string;
  valor_unitario: string;
  total: string;
}

export interface Evento {
  id: number;
  usuario_id: number | null;
  de_status: Status | null;
  para_status: Status;
  dados: Record<string, unknown>;
  criado_em: string;
}

export interface ChamadoDetalhe extends ChamadoResumo {
  endereco_origem: string;
  origem: Ponto;
  destino: Ponto;
  distancia_km: string;
  distancia_fonte: FonteDistancia;
  rastreio_token: string;
  atualizado_em: string;
  encerrado_em: string | null;
  version: number;
  itens: Item[];
  eventos: Evento[];
}

export interface EstadoChamado {
  id: number;
  status: Status;
  version: number;
  valor_final: string | null;
  encerrado_em: string | null;
}

export interface PrestadorProximo {
  id: number;
  nome: string;
  telefone: string;
  lat: number;
  lng: number;
  distancia_km: string;
}

export interface Posicao extends Ponto {
  registrado_em: string | null;
}

export interface MeuPerfil {
  id: number;
  nome: string;
  disponivel: boolean;
  posicao: Posicao | null;
}

export interface Rastreio {
  status: Status;
  placa: string;
  origem: Ponto;
  destino: Ponto;
  prestador: { nome: string; posicao: Posicao | null } | null;
  expira_em: string | null;
}
