import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { entrar, ErroApi } from "../api/cliente";
import { identidadeAtual } from "../api/sessao";
import { telaInicial } from "../rotas";

const SENHA_DEMO = "despacha123";

export function Entrar() {
  const navegar = useNavigate();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [numero, setNumero] = useState("1");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function acessar(emailUsado: string, senhaUsada: string) {
    setErro(null);
    setEnviando(true);
    try {
      await entrar(emailUsado, senhaUsada);
      const papel = identidadeAtual()?.papel;
      const destino = telaInicial(papel);
      if (destino === "/entrar") setErro("Este perfil ainda não tem tela no painel.");
      else navegar(destino);
    } catch (e) {
      setErro(
        e instanceof ErroApi && e.status === 401
          ? "E-mail ou senha incorretos."
          : e instanceof Error
            ? e.message
            : "Não foi possível entrar.",
      );
    } finally {
      setEnviando(false);
    }
  }

  function aoEnviar(evento: FormEvent) {
    evento.preventDefault();
    void acessar(email, senha);
  }

  return (
    <main className="entrar">
      <section className="entrar__cartao">
        <h1 className="entrar__marca">Despacha</h1>
        <p className="entrar__lema">Central de guincho e assistência 24 h</p>

        <form onSubmit={aoEnviar} className="formulario">
          <label>
            E-mail
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Senha
            <input
              type="password"
              autoComplete="current-password"
              required
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
            />
          </label>
          <button type="submit" className="botao botao--primario" disabled={enviando}>
            {enviando ? "Entrando…" : "Entrar"}
          </button>
        </form>

        {erro && (
          <p className="aviso aviso--erro" role="alert">
            {erro}
          </p>
        )}

        <div className="entrar__demo">
          <h2>Contas de demonstração</h2>
          <p>Criadas pelo comando seed, todas com a senha {SENHA_DEMO}.</p>
          <button
            type="button"
            className="botao"
            disabled={enviando}
            onClick={() => void acessar("despachante@despacha.dev", SENHA_DEMO)}
          >
            Entrar como despachante
          </button>
          <div className="entrar__prestador">
            <label>
              Prestador nº
              <input
                type="number"
                min={1}
                inputMode="numeric"
                value={numero}
                onChange={(e) => setNumero(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="botao"
              disabled={enviando || !numero}
              onClick={() => void acessar(`prestador${numero}@despacha.dev`, SENHA_DEMO)}
            >
              Entrar como prestador
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}
