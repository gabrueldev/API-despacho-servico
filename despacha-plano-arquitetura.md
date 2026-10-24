# Despacha — Plano de Arquitetura

API de despacho de serviços (guincho, entregas, manutenção) em **Python / Django**, feita para demonstrar na prática: concorrência, filas, banco otimizado, segurança, testes e arquitetura em camadas.

**Stack:** Django + Django REST Framework · PostgreSQL + PostGIS · Redis · Celery + Celery Beat · Nginx + Gunicorn · Docker Compose · GitHub Actions · pytest

**Ordem sugerida para desenhar:** visão geral → ciclo de vida do chamado → banco → fluxos → camadas.

---

## 1. Visão geral da arquitetura

```
[Clientes: Painel web / App do prestador / Webhook externo]
          │ HTTPS (JWT)
          ▼
   [Nginx]  ──►  [API Django + DRF (gunicorn, N instâncias, sem estado)]
                     │            │              │
                     ▼            ▼              ▼
              [PostgreSQL     [Redis]        [Celery workers]
               + PostGIS]     cache, fila,   notificações, recálculo,
                              rate limit     fechamento financeiro
                                                │
                                                ▼
                                     [Celery Beat: tarefas agendadas]
```

- **API sem estado:** permite subir várias instâncias atrás do Nginx (escala horizontal).
- **Redis com 4 papéis:** broker do Celery, cache, contador de rate limit e **última posição dos prestadores** (escrita quente fora do Postgres).
- **Celery:** tudo que é lento sai do request (notificar, recalcular, fechar período).
- **Filas separadas no Celery:** `critica` (timeout de aceite), `notificacoes` e `pesada` (fechamento, flush de localização), cada uma com seus workers. Assim, um fechamento demorado nunca atrasa um timeout.
- **Pool de conexões:** pool nativo do psycopg 3 no Django 5.1+ (`OPTIONS={"pool": True}`), para não abrir uma conexão nova a cada request. PgBouncer é opcional se o número de instâncias crescer.

---

## 2. Ciclo de vida do chamado (máquina de estados)

```
ABERTO ──► DESPACHADO ──► ACEITO ──► A_CAMINHO ──► NO_LOCAL ──► EM_ATENDIMENTO ──► CONCLUIDO
                │
                └─(prestador recusa ou expira 2 min)─► ABERTO   (volta para a fila)

Qualquer status não encerrado ──► CANCELADO   (sem taxa até ACEITO; com taxa de saída a partir de A_CAMINHO)
```

- Toda transição passa por **um único serviço** (`services.transicionar`), que valida a transição na tabela `estados.TRANSICOES` (regras puras, testadas na matriz completa 8×8).
- **Trava otimista nas transições:** lê só as colunas de estado e grava com `UPDATE ... WHERE id=%s AND version=%s` (`version = version + 1`). Uma query de escrita, sem `SELECT FOR UPDATE`; se outra operação passou na frente, 0 linhas → **409** sem gravar nada. A trava pessimista fica só no despacho (Fluxo B), onde também se reserva o prestador.
- Toda transição gera um registro em **EventoChamado** (histórico / auditoria). Aceitar = **3 queries** (SELECT, UPDATE, INSERT do evento).
- **Disponibilidade do prestador:** fica `false` no despacho e volta a `true` na recusa, no timeout, na conclusão e no cancelamento.
- **Conclusão:** `valor_final = SUM(itens)` no banco; `encerrado_em = agora`; rastreio vale até `encerrado_em + 24 h`. Lançar item incrementa `version`, então um item que chegue durante a conclusão gera 409 em vez de um total errado.
- **Cancelamento:** `valor_final` = taxa (ou 0,00), `encerrado_em = agora` e o rastreio expira na hora.
- Se o prestador não aceitar em **2 minutos**, uma tarefa Celery devolve o chamado para `ABERTO`. A tarefa usa um **UPDATE condicional**, sem trava e em uma única query:
  `UPDATE chamado SET status='ABERTO', version=version+1 WHERE id=%s AND status='DESPACHADO' AND version=%s`.
  Se o prestador aceitou aos 1:59, o UPDATE afeta 0 linhas e nada acontece. Com isso a tarefa já é idempotente.

---

## 3. Modelo de dados

| Tabela | Campos principais |
|---|---|
| **Usuario** | id, email, senha_hash, papel (ADMIN, ATENDENTE, DESPACHANTE, PRESTADOR, FINANCEIRO), ativo |
| **Cliente** (contratante, ex.: proteção veicular) | id, nome, cnpj, tabela_precos_id |
| **TabelaPrecos** | id, nome, valor_saida, valor_km_excedente, km_franquia, valor_hora_espera |
| **Prestador** | id, usuario_id (1:1), nome, telefone, disponivel, localizacao (Point/PostGIS), atualizado_em |
| **Chamado** | id, cliente_id, atendente_id, prestador_id (opcional), status, placa, endereco_origem, origem (Point), destino (Point), **distancia_km**, **distancia_fonte** (`LINHA_RETA` / `ROTA` / `ESTIMADA`), valor_previsto, valor_final, criado_em, atualizado_em, **encerrado_em** (conclusão ou cancelamento), **rastreio_token** (único), **rastreio_expira_em**, **version** |
| **ItemValor** | id, chamado_id, tipo (SAIDA, KM_EXCEDENTE, PEDAGIO, ESPERA, ADICIONAL, TAXA_CANCELAMENTO), descricao, quantidade, valor_unitario, total |
| **EventoChamado** | id, chamado_id, usuario_id, de_status, para_status, dados (JSON), criado_em |
| **Fechamento** | id, tipo (CLIENTE / PRESTADOR), cliente_id (opcional), prestador_id (opcional), periodo_inicio, periodo_fim, total, quantidade_chamados, status (GERADO / PAGO). `CHECK`: exatamente um dos dois preenchido, coerente com o tipo. Os dois são FKs reais, então permitem índice e JOIN. Únicos parciais `(cliente_id, periodo_inicio) WHERE tipo='CLIENTE'` e `(prestador_id, periodo_inicio) WHERE tipo='PRESTADOR'`. |
| **FechamentoItem** | fechamento_id, chamado_id, valor — único `(fechamento_id, chamado_id)` |
| **IdempotencyKey** | usuario_id + chave (**únicos juntos**), hash_requisicao (SHA-256 do corpo), status_code, resposta (JSON), criado_em |

**Relações:** Cliente 1—N Chamado · Prestador 1—N Chamado · Chamado 1—N ItemValor · Chamado 1—N EventoChamado · Fechamento 1—N FechamentoItem · Cliente N—1 TabelaPrecos.

### Índices

- `Chamado(criado_em, id)` → listagem sem filtro (ordem da API), sem ordenar em memória.
- `Chamado(status, criado_em, id)` → listagem por status. O `id` no fim serve de desempate para a **paginação por cursor**, e a ordenação da API é sempre `(criado_em, id)`.
- **Índice parcial** `Chamado(criado_em, id) WHERE status NOT IN ('CONCLUIDO','CANCELADO')` → fila e painel operacional. Fica pequeno porque a maioria dos chamados já terminou.
- `Chamado(prestador_id, criado_em, id)` → "meus chamados" já na ordem do cursor. O filtro do prestador é uma **subquery escalar** (`prestador_id = (SELECT id … WHERE usuario_id = ?)`), não um JOIN: o Postgres a resolve antes (InitPlan) e usa o resultado como condição do índice, varrendo-o já em ordem até o LIMIT. Com o JOIN, o `EXPLAIN ANALYZE` mostrou que ele lia todo o histórico do prestador e ordenava em memória.
- FKs `cliente_id`, `prestador_id`, `atendente_id` **sem índice próprio** (`db_index=False`): os compostos acima já começam por elas, e cada índice a menos barateia INSERT/UPDATE.
- `origem`/`destino` do chamado **sem GiST**: não há busca espacial em chamados.
- **Índice parcial** `Chamado(encerrado_em) WHERE encerrado_em IS NOT NULL` → fechamento. O período é filtrado pela data de encerramento (conclusão ou cancelamento com taxa), não pela de criação. Substituiu os compostos `(cliente_id, encerrado_em)` e `(prestador_id, encerrado_em)`: o fechamento varre o mês de **todos** os destinatários, e um índice que começa pelo destinatário não serve para esse filtro. Um índice no lugar de dois, e chamado em andamento nem entra nele.
- `Chamado(rastreio_token)` único → consulta pública de rastreio em O(log n)
- **GiST parcial** `Prestador(localizacao) WHERE disponivel = true` → proximidade só entre prestadores livres, num índice só. Dois índices separados (GiST + parcial em `disponivel`) não se combinam bem.
- `EventoChamado(chamado_id, criado_em)` → histórico no detalhe do chamado
- **BRIN** em `IdempotencyKey(criado_em)` e `EventoChamado(criado_em)` → limpeza e relatórios por data em tabelas que só recebem inserção, com um índice minúsculo

Trade-off a explicar: índices aceleram leitura, mas deixam a escrita mais lenta e ocupam espaço. Validar com `EXPLAIN ANALYZE`.

---

## 4. Fluxos principais

### Fluxo A — Abrir chamado
1. Atendente faz `POST /chamados` com o header `Idempotency-Key`.
2. API valida, cria o chamado como `ABERTO`, calcula o `valor_previsto` pela tabela de preços do cliente e registra o evento.
3. Responde **201** imediatamente.
4. Em segundo plano, o Celery sugere os prestadores mais próximos e notifica.

### Fluxo B — Despachar (concorrência)
1. Dois despachantes tentam despachar o mesmo chamado ao mesmo tempo.
2. Dentro de `transaction.atomic()`, a API faz `select_for_update(nowait=True)` no chamado e no prestador, **sempre nessa ordem** para evitar deadlock.
3. O primeiro trava as linhas, valida e muda para `DESPACHADO`.
4. O segundo **não fica esperando**: o Postgres devolve `LockNotAvailable` na hora e a API responde **409 Conflict**. Se ele chegar depois do commit, encontra o status já alterado e também recebe 409. Sem espera, nenhum worker do gunicorn nem conexão do pool fica parado aguardando trava.
5. Após o commit (`transaction.on_commit`), o Celery agenda o timeout de 2 minutos na fila `critica`.

### Fluxo C — Atualizar localização do prestador
1. O app envia `POST /prestadores/me/localizacao` a cada ~15 s (rota com **rate limit**).
2. **Zero queries no Postgres** (garantido por teste): a autenticação é sem estado (`JWTStatelessUserAuthentication`; o `papel` vai como claim no JWT) e a posição vai **só para o Redis** (hash `loc:usuario:{id}` com lat, lng e timestamp). Um **script Lua** grava e, só se a posição mudou mais de ~1 m (5 casas decimais), marca o prestador como pendente — tudo numa ida ao Redis. Trade-off: um usuário desativado segue enviando até o access token expirar (15 min).
3. A cada **60 s**, uma tarefa do Beat (fila `pesada`) esvazia os pendentes com `SPOP` em lotes de 1000 e grava cada lote no Postgres num único `UPDATE ... FROM (VALUES ...)`. Prestador parado não gera escrita. Se o lote falhar, os ids voltam para a fila.
4. O rastreio lê a posição do Redis. A busca por proximidade usa o PostGIS, com posição de no máximo ~60 s atrás, o que é irrelevante num raio de 30 km. Prestador sem posição nova há mais de **10 min** some da busca (app fechado ou sem sinal), mesmo marcado como disponível.

### Fluxo D — Concluir e fechar
1. De `A_CAMINHO` a `EM_ATENDIMENTO`, o prestador (ou o despachante) lança os itens via `POST /chamados/{id}/itens`: pedágio e adicionais por valor, espera por minutos (calculada pela tabela do cliente, em frações de 15 min). Cada lançamento incrementa `version` e gera um `EventoChamado`. Ao concluir, o `valor_final` é recalculado com `SUM` no banco e gravado no chamado (desnormalizado para leitura rápida).
2. No dia 1 às 03:00 (horário de Brasília), o **Celery Beat** gera os fechamentos do mês anterior por cliente (o que cobrar) e por prestador (o que repassar). Cada tipo é **um único comando SQL**: `INSERT ... SELECT ... GROUP BY ... ON CONFLICT DO NOTHING RETURNING` numa CTE que, na mesma instrução, insere os itens. Nada é carregado para o Python: **2 queries por período, seja qual for o volume** (verificado em teste). As restrições únicas tornam a geração idempotente, inclusive com execuções simultâneas (testado com threads). Os limites do mês são calculados no fuso de Brasília: um chamado encerrado às 23:59 do dia 30 (02:59 UTC do dia 1º) entra no mês certo. Mês ainda em andamento → 422.
3. **Repasse ao prestador:** `REPASSE_PRESTADOR_PERCENTUAL` (padrão 100%) aplicado e arredondado por chamado; o total do fechamento é sempre a soma exata dos itens.

---

## 5. Decisões técnicas (o que explicar na entrevista)

1. **Concorrência no despacho:** trava pessimista (`select_for_update(nowait=True)`), porque o conflito é raro mas precisa ser 100% correto. Com `nowait`, quem perde recebe 409 na hora em vez de segurar conexão esperando (teste: < 0,5 s com a linha travada por outra transação). Testado com threads reais: 8 despachantes no mesmo chamado → 1 vence, 7 recebem 409, 1 evento; mesmo prestador em 2 chamados → só 1 despacho. O campo `version` é usado pela trava otimista nas demais transições e no timeout de aceite.
2. **Idempotência:** com `Idempotency-Key` (escopo usuário + chave), se o cliente reenviar a requisição por falha de rede, o chamado não é criado duas vezes. A resposta é gravada **na mesma transação** do chamado; o reenvio custa 1 SELECT e volta com o header `Idempotent-Replayed: true`. Dois envios **simultâneos** com a mesma chave: o segundo esbarra na constraint única, a operação dele é desfeita inteira e ele devolve a resposta do primeiro. Mesma chave com corpo diferente → 422. Só sucesso é gravado (um 422 pode ser corrigido e reenviado). As chaves expiram em 24 h; a limpeza periódica pelo Beat entra na etapa 5. Tarefas Celery também são idempotentes.
3. **Retry com backoff:** notificações com falha transitória são reenviadas com intervalo crescente (2 s, 4 s, 8 s… até 5 min, com jitter, 6 tentativas). A notificação é **idempotente por chave** (`despachado:{chamado}:{version}`): a marca de "enviada" fica no Redis e só é gravada após o sucesso, então reentrega (`acks_late`) não duplica e retry não pula o envio. O timeout de aceite não lê nada do banco: o UPDATE condicional por `version` decide sozinho (2 UPDATEs + 1 INSERT); timeout atrasado de um despacho antigo não desfaz um redespacho.
4. **Sem N+1:** listagens usam `select_related("cliente", "prestador")` e `prefetch_related("itens")`; testes com `assertNumQueries` garantem o número de queries.
5. **Dinheiro em `Decimal`:** nunca `float`; cálculo feito no back-end e testado.
6. **Paginação por cursor:** estável e rápida em tabelas grandes, sem `COUNT(*)` nem `OFFSET`. A ordenação `(criado_em, id)` bate com os índices.
7. **Cache com invalidação:** tabela de preços em cache, invalidada quando alguém a edita. A resposta pública de `/rastreio/{token}` fica em cache por 5 s (só respostas 200), o que absorve vários associados abrindo o mesmo link: acesso repetido = 0 queries. Rate limit de 60/min por IP. Expirado → **410**; inexistente → 404. Placa mascarada (`ABC-**23`), sem telefone do prestador; posição só de `ACEITO` a `EM_ATENDIMENTO`.
8. **Proximidade com índice:** `ST_DWithin` (usa o GiST) para filtrar o raio e o operador KNN `<->` para ordenar por distância, em SQL explícito — o `Distance()` do ORM ordena por `ST_Distance`, que calcula para todo candidato e ordena em memória. O `EXPLAIN` (verificado em teste) mostra um único `Index Scan using prestador_livre_loc_gist` com `Order By: <->` e **nenhum Sort**: o índice devolve os 20 mais próximos já em ordem e para. Nunca `ST_Distance(...) < raio` no `WHERE`, que não usa índice.
9. **Serializers enxutos:** um serializer de listagem (poucos campos, `only()`) e outro de detalhe (itens + histórico).
10. **Auditoria:** `EventoChamado` registra toda mudança de status e de valor.
11. **Permissões por papel:** prestador só vê os próprios chamados; financeiro só vê fechamentos.
12. **Celery bem configurado:** filas separadas por prioridade, `acks_late=True` e `worker_prefetch_multiplier=1` na fila `pesada` (uma tarefa longa não segura as outras), tarefas enfileiradas só após o commit (`transaction.on_commit`).
13. **Segurança:** JWT com access curto + refresh, senhas com hash, segredos em variáveis de ambiente, validação de toda entrada.
14. **Rota por estrada sem acoplar o chamado ao mapa:** OSRM próprio (Docker, OpenStreetMap, sem chave nem cobrança por chamada) atrás da interface `CalculadoraDistancia`. Timeout de 2 s, plano B em linha reta × 1,3 (`ESTIMADA`) e circuit breaker: uma falha de rede pausa as consultas por 30 s, para um OSRM fora do ar não custar 2 s em cada chamado. "Sem rota" (ponto fora do mapa) estima sem pausar, porque o serviço está bem. Rotas em cache no Redis por 30 dias, com as coordenadas arredondadas a ~110 m. A medição roda **fora da transação**: com `Idempotency-Key`, o `executar` chama `preparar()` depois de checar o reenvio e antes do `atomic()`, então um HTTP lento não segura transação aberta e um reenvio não paga a medição.

---

## 6. Endpoints

```
POST   /auth/login                 -> access + refresh (JWT)
POST   /auth/refresh

POST   /chamados                   (atendente)   cria; aceita Idempotency-Key
GET    /chamados?status=&cursor=   lista paginada
GET    /chamados/{id}              detalhe + itens + histórico
POST   /chamados/{id}/despachar    (despachante) {prestador_id}  -> 200 / 409
POST   /chamados/{id}/aceitar      (prestador)
POST   /chamados/{id}/recusar      (prestador)
POST   /chamados/{id}/status       (prestador)   A_CAMINHO / NO_LOCAL / EM_ATENDIMENTO
POST   /chamados/{id}/itens        lança pedágio, espera, adicionais
POST   /chamados/{id}/concluir
POST   /chamados/{id}/cancelar

GET    /prestadores/proximos?lat=&lng=&raio=   (despachante, atendente) 1 query, KNN no GiST
POST   /prestadores/me/localizacao (rate limit)
GET    /rastreio/{token}           público, sem login (link para o associado)

GET    /fechamentos?tipo=&periodo=
POST   /fechamentos/gerar          (financeiro) -> dispara tarefa Celery
GET    /health
```

---

## 7. Estrutura do código (camadas)

```
despacha/
├── config/              settings, urls, celery.py
├── apps/
│   ├── contas/          Usuario, papéis, JWT, permissões
│   ├── clientes/        Cliente (contratante)
│   ├── chamados/
│   │   ├── models.py
│   │   ├── services.py      ← regra de negócio (transições, despacho, cálculo)
│   │   ├── selectors.py     ← consultas otimizadas (sem N+1)
│   │   ├── api/             serializers + views (finas: só chamam services)
│   │   ├── tasks.py         Celery (timeout, notificação)
│   │   └── tests/
│   ├── prestadores/
│   ├── precos/
│   └── financeiro/
├── core/                idempotência, paginação, erros padronizados
├── docker-compose.yml   api, worker, beat, postgres (postgis), redis, nginx
└── .github/workflows/ci.yml   lint + mypy + pytest
```

**Regra de ouro:** views só recebem e respondem; **services** decidem; **selectors** consultam.

---

## 8. Etapas de desenvolvimento

1. **Base:** Docker Compose, Django + DRF, PostgreSQL/PostGIS, JWT, papéis e CI.
2. **Domínio:** models, migrations, tabela de preços e criação de chamado com valor previsto.
3. **Ciclo de vida:** transições de status, histórico e testes das regras.
4. **Concorrência:** despacho com trava, teste simulando dois despachos simultâneos, idempotência.
5. **Assíncrono:** Celery + Redis, timeout de aceite, notificações com retry, cache de localização.
6. **Proximidade e rastreio:** busca por raio e link público de rastreio.
7. **Financeiro:** itens, valor final e fechamentos agendados (Celery Beat).
8. **Acabamento:** OpenAPI/Swagger, README com as decisões e os `EXPLAIN ANALYZE`, cobertura de testes.
   - `manage.py seed`: dados de demonstração determinísticos (semente fixa), em `bulk_create`, com um único hash de senha e as datas espalhadas por UPDATE no banco. 50 mil chamados levam cerca de 16 s.
   - `manage.py explicar`: `EXPLAIN (ANALYZE, BUFFERS)` dos mesmos selectors/SQL da API, para qualquer pessoa reproduzir os números do README. Ele mostra a 2ª execução, porque a 1ª de cada conexão paga a carga do PostGIS, e com o pool isso não se repete.
   - CI com runner fixo (`ubuntu-24.04`), actions atualizadas, piso de cobertura de 95% e cancelamento de execuções superadas.
9. **Rota por estrada:** `RotaOSRM` (httpx com keep-alive, cache, plano B e circuit breaker), campo `distancia_fonte` e OSRM no Docker Compose (`--profile rota`: baixa o mapa do Geofabrik, pré-processa com MLD e serve). Testado contra um servidor HTTP falso real (sucesso, cache, timeout, conexão recusada, 5xx, sem rota) e de ponta a ponta com o OSRM real sobre o mapa do Sudeste.

---

## 9. Testes (o que cobrir)

- **Unitários:** cálculo de valores (Decimal), transições válidas/inválidas da máquina de estados.
- **Integração:** endpoints com banco real (pytest + PostgreSQL no Docker), permissões por papel.
- **Concorrência:** duas threads tentando despachar o mesmo chamado → uma recebe 409 sem esperar a trava. Aceite aos 1:59 + timeout simultâneo → o chamado continua `ACEITO`.
- **Performance:** `assertNumQueries` nas listagens, no detalhe e na geração de fechamento. Teste que confere, via `EXPLAIN`, se a busca por proximidade e a listagem usam índice (sem `Seq Scan`).
- **Tarefas:** timeout de aceite, flush de localização e idempotência das tarefas Celery.

---

## 10. Decisões e premissas

Padrões adotados para o MVP. Qualquer item pode ser trocado depois sem mudar a arquitetura.

### Regras de negócio

| # | Tema | Decisão |
|---|---|---|
| 1 | **Cálculo do valor** | `valor_saida` inclui **franquia de 40 km**. Acima disso, cobra `valor_km_excedente` por **km inteiro iniciado** (arredonda para cima: 40,01 km → 1 km). Espera cobrada por hora, **fracionada a cada 15 min, arredondando para cima** (16 min → 0,5 h). Pedágio e adicionais lançados manualmente. Tudo em `Decimal`, arredondado para **2 casas** (`ROUND_HALF_UP`). |
| 2 | **Distância** | **Da origem ao destino**; o deslocamento do prestador até a origem está coberto pela saída. Calculada uma vez na criação e gravada em `distancia_km`, com a fonte em `distancia_fonte`. `DISTANCIA_PROVEDOR=linha_reta` (padrão, PostGIS `ST_Distance` em geography) ou `osrm` (km por estrada). Com o OSRM fora do ar ou sem rota: linha reta × 1,3, marcada `ESTIMADA`. |
| 3 | **Escolha do prestador** | Prestadores **disponíveis** num **raio de 30 km**, ordenados por distância. O despachante escolhe na lista (sugestão automática = o mais próximo). |
| 4 | **Cancelamento** | Sem taxa até `DESPACHADO`/`ACEITO`. A partir de `A_CAMINHO`, cobra **taxa de saída** (= `valor_saida` da tabela), lançada como `ItemValor` do tipo `TAXA_CANCELAMENTO`. `CONCLUIDO` não pode ser cancelado. |
| 5 | **Fechamento** | **Mensal**, gerado automaticamente pelo Celery Beat no dia 1 às 03:00 (referente ao mês anterior). Também pode ser gerado manualmente via `POST /fechamentos/gerar`. Só entram chamados `CONCLUIDO` ou cancelados com taxa. |
| 6 | **Tempos** | Aceite do prestador: **2 min** (senão volta para `ABERTO`). Envio de localização: **a cada 15 s**. Link de rastreio: válido até a **conclusão + 24 h**. |

### Exemplo de cálculo (para testes)

Tabela: saída R$ 250,00 · km excedente R$ 4,50 · franquia 40 km · espera R$ 60,00/h.
Chamado de 58 km, 35 min de espera, pedágio R$ 12,40:

| Item | Cálculo | Total |
|---|---|---|
| Saída | 1 × 250,00 | 250,00 |
| Km excedente | (58 − 40) = 18 × 4,50 | 81,00 |
| Espera | 35 min → 3 frações de 15 min = 0,75 h × 60,00 | 45,00 |
| Pedágio | 1 × 12,40 | 12,40 |
| **Total** | | **388,40** |

### Integrações (simuladas no MVP)

| # | Tema | Decisão |
|---|---|---|
| 7 | **Notificações** | Interface `Notificador` com implementação **`LogNotificador`** (grava em log/banco). WhatsApp Business API entra depois como outra implementação, sem mudar o resto. |
| 8 | **Geocoding** | Fora do MVP. O chamado recebe **latitude/longitude** direto na criação. |

### Técnico

| # | Tema | Decisão |
|---|---|---|
| 9 | **Versões** | Python 3.12 · Django 5.x · DRF · Celery 5 · PostgreSQL 16 + PostGIS · Redis 7 |
| 10 | **Autenticação** | `djangorestframework-simplejwt`. Access token **15 min**, refresh **7 dias**, com rotação de refresh. |
| 11 | **Escopo** | **Só API** (sem front-end). Demonstração via **Swagger** (`drf-spectacular`) e testes. **Uma única assistência** no sistema (sem multiempresa). |
| 12 | **Idioma** | Nomes de domínio em **português** (Chamado, Prestador, Fechamento); restante do código no padrão inglês. README em **português**, com resumo em **inglês**. |
| 13 | **Dados de demo** | Comando `python manage.py seed` cria clientes, tabelas de preço, prestadores espalhados pelo mapa e chamados em vários status. |
| 14 | **Deploy** | **Docker Compose local** como padrão. Opcional: deploy gratuito (ex.: Render ou Railway) para ter **link público no portfólio**. |
| 15 | **Licença** | **MIT** |

### Bibliotecas

| Uso | Pacote |
|---|---|
| API | `djangorestframework` |
| JWT | `djangorestframework-simplejwt` |
| Documentação | `drf-spectacular` |
| Geoespacial | `django.contrib.gis` + `psycopg[binary,pool]` |
| Filas | `celery`, `redis`, `django-celery-beat` |
| Rate limit | throttling do DRF (backend Redis via `django-redis`) |
| Config | `django-environ` |
| Testes | `pytest`, `pytest-django`, `factory-boy`, `pytest-cov` |
| Qualidade | `ruff` (lint + format), `mypy` + `django-stubs` |
| Servidor | `gunicorn` |

### Variáveis de ambiente (`.env.example`)

```
DJANGO_SECRET_KEY=troque-isto
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgis://despacha:despacha@db:5432/despacha
REDIS_URL=redis://redis:6379/0
JWT_ACCESS_MINUTES=15
JWT_REFRESH_DAYS=7
ACEITE_TIMEOUT_SEGUNDOS=120
RAIO_BUSCA_KM=30
RASTREIO_VALIDADE_HORAS=24
LOCALIZACAO_FLUSH_SEGUNDOS=60
IDEMPOTENCY_TTL_HORAS=24
DB_POOL_MAX=10
```

### Fora do MVP (próximas versões)

- WhatsApp Business API real e geocoding de endereços
- Painel web / app do prestador
- Avaliação de prestadores, antifraude e indicadores
- Multiempresa (várias assistências)
