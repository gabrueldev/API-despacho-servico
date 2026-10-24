import type { Papel } from "./api/sessao";

// As rotas do front não usam os prefixos da API (/chamados, /rastreio…): o Nginx e o proxy do
// Vite mandam esses para o Django, e o resto para o index.html.
export function telaInicial(papel: Papel | undefined): string {
  if (papel === "PRESTADOR") return "/prestador";
  if (papel === "DESPACHANTE" || papel === "ATENDENTE" || papel === "ADMIN") return "/painel";
  return "/entrar";
}
