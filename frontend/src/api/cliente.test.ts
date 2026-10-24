import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ErroApi } from "./cliente";
import { decodificar, guardarTokens, obterTokens } from "./sessao";

function jwt(claims: Record<string, unknown>): string {
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64({ alg: "HS256" })}.${b64(claims)}.assinatura`;
}

const json = (status: number, corpo: unknown) =>
  new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } });

let fetchFalso: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchFalso = vi.fn();
  vi.stubGlobal("fetch", fetchFalso);
  guardarTokens({ access: "velho", refresh: "r1" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  guardarTokens(null);
});

describe("decodificar", () => {
  it("lê usuário e papel das claims", () => {
    expect(decodificar(jwt({ user_id: "42", papel: "PRESTADOR" }))).toEqual({ usuarioId: 42, papel: "PRESTADOR" });
  });

  it("devolve null para token malformado", () => {
    expect(decodificar("nao-e-jwt")).toBeNull();
  });
});

describe("api", () => {
  it("envia o access token e devolve o JSON", async () => {
    fetchFalso.mockResolvedValueOnce(json(200, { ok: true }));

    await expect(api("GET", "/chamados")).resolves.toEqual({ ok: true });
    const [, init] = fetchFalso.mock.calls[0]!;
    expect(init.headers.Authorization).toBe("Bearer velho");
  });

  it("renova o token uma vez só quando várias requisições recebem 401 juntas", async () => {
    fetchFalso.mockImplementation(async (url: string, init: RequestInit) => {
      if (url === "/auth/refresh") return json(200, { access: "novo", refresh: "r2" });
      const auth = (init.headers as Record<string, string>).Authorization;
      return auth === "Bearer novo" ? json(200, { url }) : json(401, { detail: "expirado" });
    });

    const respostas = await Promise.all([api("GET", "/a"), api("GET", "/b"), api("GET", "/c")]);

    expect(respostas).toEqual([{ url: "/a" }, { url: "/b" }, { url: "/c" }]);
    const renovacoes = fetchFalso.mock.calls.filter(([url]) => url === "/auth/refresh");
    expect(renovacoes).toHaveLength(1); // com rotação, uma 2ª renovação com r1 falharia
    expect(obterTokens()).toEqual({ access: "novo", refresh: "r2" });
  });

  it("refresh recusado encerra a sessão e devolve o 401", async () => {
    fetchFalso.mockImplementation(async (url: string) =>
      url === "/auth/refresh" ? json(401, { detail: "Token inválido" }) : json(401, { detail: "expirado" }),
    );

    await expect(api("GET", "/chamados")).rejects.toMatchObject({ status: 401 });
    expect(obterTokens()).toBeNull();
  });

  it("transforma o erro de domínio da API em ErroApi com código", async () => {
    fetchFalso.mockResolvedValueOnce(
      json(409, { erro: "conflito", detalhe: "Chamado ou prestador em uso por outro despacho." }),
    );

    const erro = await api<never>("POST", "/chamados/1/despachar", { corpo: { prestador_id: 2 } }).catch(
      (e: unknown) => e as ErroApi,
    );

    expect(erro).toBeInstanceOf(ErroApi);
    expect(erro).toMatchObject({ status: 409, codigo: "conflito" });
    expect(erro.message).toBe("Chamado ou prestador em uso por outro despacho.");
  });

  it("mostra o primeiro erro de validação do DRF com o nome do campo", async () => {
    fetchFalso.mockResolvedValueOnce(json(400, { valor: ["Certifique-se que este valor seja maior ou igual a 0.01."] }));

    await expect(api("POST", "/chamados/1/itens", { corpo: {} })).rejects.toThrow(/^valor: Certifique-se/);
  });

  it("lê os campos do detalhe no formato de erro do back-end", async () => {
    fetchFalso.mockResolvedValueOnce(
      json(400, { erro: "invalid", detalhe: { descricao: ["Este campo não pode ser em branco."] } }),
    );

    await expect(api("POST", "/chamados/1/itens", { corpo: {} })).rejects.toThrow(
      "descricao: Este campo não pode ser em branco.",
    );
  });

  it("resposta sem JSON (proxy) vira mensagem pelo status", async () => {
    fetchFalso.mockResolvedValueOnce(new Response("<html>Bad gateway</html>", { status: 429 }));

    await expect(api("GET", "/chamados")).rejects.toThrow("Muitas requisições seguidas");
  });
});
