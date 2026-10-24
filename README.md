# Despacha

API de despacho de serviços (guincho, entregas, manutenção) em **Python / Django**. Foi feita para mostrar na prática concorrência, filas, banco otimizado, segurança, testes e arquitetura em camadas.

[![CI](https://github.com/gabrueldev/API-despacho-servico/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrueldev/API-despacho-servico/actions/workflows/ci.yml)

**Stack:** Django 5.2 + DRF · PostgreSQL 16 + PostGIS · Redis 7 · Celery 5 + Beat · OSRM (rota por estrada) · Nginx + Gunicorn · Docker Compose · GitHub Actions · pytest

**Números:** 250 testes, cobertura de 98,7% (o CI exige ≥ 95%), mypy `strict`. Todas as queries de leitura quente rodam abaixo de **0,25 ms** sobre 50 mil chamados (veja [Desempenho](#desempenho)).

Plano e decisões completas em [`despacha-plano-arquitetura.md`](despacha-plano-arquitetura.md).

## Como rodar

```bash
cp .env.example .env
docker compose up --build
docker compose exec api python manage.py seed        # dados de demonstração
```

O `seed` é determinístico (semente fixa) e cria:

- 2 tabelas de preço e 3 clientes;
- 150 prestadores espalhados pela Grande São Paulo;
- 2.000 chamados em todos os status (cancelados com e sem taxa), com itens e histórico;
- os fechamentos dos meses já encerrados.

Para medir desempenho, aumente o volume: `seed --limpar --chamados 50000 --prestadores 500` termina em cerca de 16 s, porque usa `bulk_create`, calcula o hash de senha uma vez só e espalha as datas com um UPDATE no banco. O comando só roda com `DJANGO_DEBUG=true`, a menos que receba `--forcar`.

**Logins de demonstração** (senha `despacha123`): `admin@despacha.dev`, `atendente@despacha.dev`, `despachante@despacha.dev`, `financeiro@despacha.dev` e `prestador1@despacha.dev` … `prestadorN@despacha.dev`. Ao final, o `seed` imprime um link de rastreio de exemplo.

### Rota por estrada (OSRM)

Por padrão, a distância do chamado é a linha reta (PostGIS). Para usar o km por estrada:

```bash
# no .env: DISTANCIA_PROVEDOR=osrm
docker compose --profile rota up --build
```

Na primeira vez, o compose baixa o mapa do Sudeste do Geofabrik (~860 MB) e o pré-processa uma única vez. Medido aqui (Apple M-series, 16 GB): cerca de **8 min** e pico de **6,3 GB de RAM** (reserve ~8 GB para o Docker), ocupando 5,6 GB em disco. Depois disso tudo fica no volume `osrm`, e o OSRM sobe em segundos e responde uma rota em **1–2 ms** (mediana de 50 rotas aleatórias na Grande SP). Para outra região, troque `OSRM_PBF_URL` e apague o volume.

| Situação | O que acontece | `distancia_fonte` |
|---|---|---|
| OSRM respondeu | km por estrada, guardado em cache por 30 dias (coordenadas arredondadas a ~110 m) | `ROTA` |
| Timeout (> 2 s), conexão recusada ou 5xx | linha reta × 1,3; **pausa** as consultas por 30 s (circuit breaker), para não pagar o timeout em todo chamado | `ESTIMADA` |
| Sem rota (ponto fora do mapa, no mar) | linha reta × 1,3, sem pausar: o serviço está bem | `ESTIMADA` |
| `DISTANCIA_PROVEDOR=linha_reta` | geodésica no PostGIS | `LINHA_RETA` |

Como a fonte fica gravada, o financeiro sabe quais valores previstos foram estimados.

Teste de ponta a ponta com o OSRM real (mapa do Sudeste), pela API:

| Chamado | Distância | Fonte | Valor previsto | Tempo do POST |
|---|---|---|---|---|
| Sé → Guarulhos (linha reta seria ~21 km) | 25,30 km | `ROTA` | R$ 250,00 | 52 ms (21 ms com cache) |
| Sé → Campinas | 92,91 km | `ROTA` | R$ 488,50 | 14 ms |
| Sé → Santos, com o OSRM derrubado | 71,25 km | `ESTIMADA` | R$ 394,00 | 62 ms |
| Sé → Jundiaí, durante a pausa | 63,13 km | `ESTIMADA` | R$ 358,00 | 17 ms (nem tenta o OSRM) |

### Sem Docker (macOS)

```bash
brew install postgresql@17 postgis redis
brew services start postgresql@17 && brew services start redis
createdb despacha
cp .env.example .env   # ajuste DATABASE_URL/REDIS_URL para localhost e descomente GDAL/GEOS
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate && .venv/bin/python manage.py seed
.venv/bin/python manage.py runserver

# Celery (em outros terminais). No macOS use -P threads: o prefork exige fork,
# e o macOS usa spawn por padrão. No Docker (Linux) o prefork funciona normalmente.
.venv/bin/celery -A config worker -Q critica,notificacoes,pesada -P threads -l info
.venv/bin/celery -A config beat -l info
```

## Endpoints

Documentação interativa em **`/docs/`** (Swagger) e schema OpenAPI em `/schema/`. Autenticação por JWT: access de 15 min e refresh de 7 dias, com rotação.

| Método e rota | Quem | O quê |
|---|---|---|
| `GET /health` | público | Saúde da API (banco + Redis) |
| `POST /auth/login` · `POST /auth/refresh` | público | Tokens JWT (login limitado a 10/min) |
| `POST /chamados` | atendente | Abre o chamado e calcula o valor previsto pela distância (linha reta ou km por estrada, com a fonte em `distancia_fonte`). Aceita `Idempotency-Key` |
| `GET /chamados?status=&cursor=` | equipe, prestador (só os seus) | Listagem paginada por cursor, 1 query |
| `GET /chamados/{id}` | idem | Detalhe com itens e histórico, 3 queries fixas |
| `POST /chamados/{id}/despachar` | despachante | `SELECT … FOR UPDATE NOWAIT`: quem perde a corrida recebe 409 na hora. Agenda o timeout de aceite (2 min) |
| `POST /chamados/{id}/aceitar` · `recusar` | prestador | Aceite ou recusa (recusa devolve o chamado para `ABERTO`) |
| `POST /chamados/{id}/status` | prestador | `A_CAMINHO` → `NO_LOCAL` → `EM_ATENDIMENTO` |
| `POST /chamados/{id}/itens` | prestador, despachante | Lança pedágio, espera (em minutos) ou adicional |
| `POST /chamados/{id}/concluir` · `cancelar` | prestador · equipe | Conclui (valor final = soma dos itens) ou cancela (taxa de saída a partir de `A_CAMINHO`) |
| `POST /prestadores/me/localizacao` | prestador | Posição atual: zero queries no Postgres (JWT sem estado + Redis), gravada em lote pelo Beat. 6/min |
| `GET /prestadores/proximos?lat=&lng=&raio=` | despachante, atendente | Disponíveis no raio, do mais próximo ao mais distante (KNN no GiST parcial) |
| `GET /rastreio/{token}` | público | Link do associado: status, placa mascarada e posição do prestador. Cache de 5 s, 410 quando expira |
| `GET /fechamentos?tipo=&periodo=AAAA-MM` · `GET /fechamentos/{id}` | financeiro | Fechamentos mensais por cliente e por prestador |
| `POST /fechamentos/gerar` | financeiro | Gera o mês em segundo plano (202). Pode repetir sem duplicar |

As transições de estado usam trava otimista por `version`: uma escrita concorrente recebe 409, nunca sobrescreve a outra. Os erros seguem sempre o formato `{"erro": "<codigo>", "detalhe": "..."}`.

## Decisões técnicas

| Problema | Decisão | Por quê |
|---|---|---|
| Dois despachantes mandam prestadores diferentes para o mesmo chamado | Trava pessimista `FOR UPDATE NOWAIT`, sempre na ordem chamado → prestador | Quem perde recebe 409 em menos de 0,5 s, sem fila de espera nem deadlock. Testado com 8 threads simultâneas |
| Prestador aceita enquanto o chamado é cancelado | Trava otimista: `UPDATE … WHERE version = n` | Transições curtas não seguram lock. O conflito vira 409 e a transação de quem chamou continua utilizável |
| Clique duplo ou retry de rede no "abrir chamado" | `Idempotency-Key` gravada **na mesma transação** do chamado, com chave única | 5 POSTs simultâneos geram 1 chamado. Corpo diferente com a mesma chave recebe 422. As chaves valem 24 h e são limpas por um índice BRIN |
| Prestador manda posição a cada 10 s | JWT sem estado + script Lua no Redis; o Beat grava em lote com um único `UPDATE … FROM (VALUES …)` | O caminho mais quente da API não toca no Postgres |
| "Quem está livre mais perto?" | SQL com `ST_DWithin` + `ORDER BY <->` (KNN) num GiST **parcial** (`WHERE disponivel`) | O índice entrega já ordenado e para no LIMIT. O `Distance()` do ORM calcularia a distância de todos os candidatos e ordenaria em memória |
| Fechamento mensal | Um `INSERT … SELECT … GROUP BY` em CTE que insere os itens na mesma instrução, com `ON CONFLICT DO NOTHING` | 2 queries por período, qualquer que seja o volume. Gerar de novo não duplica (4 gerações simultâneas testadas) |
| Virada de mês | Limites calculados em `America/Sao_Paulo` | Um chamado encerrado às 23h59 de 30/09 em Brasília já é 01/10 em UTC |
| Listagens grandes | Cursor por `(criado_em, id)` + índices compostos na mesma ordem | O custo da página 1.000 é igual ao da página 1. `OFFSET` leria e descartaria todas as anteriores |
| Prestador listando o próprio histórico | Subquery escalar em vez de JOIN | O Postgres resolve a subquery antes (InitPlan) e varre o índice já em ordem; com o JOIN, lia o histórico inteiro e ordenava |
| Distância por estrada | OSRM próprio atrás de uma interface, com timeout de 2 s, plano B (linha reta × 1,3, marcada `ESTIMADA`), circuit breaker de 30 s e cache de 30 dias no Redis | Abrir chamado nunca falha nem trava por causa do mapa. Sem chave de API nem custo por consulta. A chamada HTTP acontece fora da transação, e um reenvio idempotente nem chega a medir |
| Timeout de aceite | Agendado via `on_commit`; quando dispara, faz um UPDATE condicional sem ler nada antes | Se o prestador já aceitou, o UPDATE não casa linha nenhuma e nada acontece |
| Notificações | Fila própria, backoff exponencial com jitter, deduplicadas por chave no Redis | Um provedor instável não atrasa o despacho, e um retry não notifica duas vezes |
| Filas Celery | `critica` (timeouts), `notificacoes` e `pesada` (fechamento, flush de posições) com `prefetch=1` | Um fechamento pesado nunca atrasa um timeout de aceite |

## Desempenho

Os planos abaixo são reais. Foram medidos sobre o `seed` com 50.000 chamados e 500 prestadores (PostgreSQL 17 + PostGIS 3.6, Apple Silicon) e qualquer pessoa os reproduz com:

```bash
python manage.py seed --limpar --chamados 50000 --prestadores 500
python manage.py explicar            # ou: explicar --so knn
```

O `explicar` roda `EXPLAIN (ANALYZE, BUFFERS)` sobre **os mesmos selectors e SQL da API**. Ele executa cada query uma vez para aquecer a conexão, porque a primeira query PostGIS de uma conexão carrega a biblioteca e, com o pool do psycopg, isso não se repete. O plano mostrado é o da segunda execução.

| Query | Índice usado | Linhas lidas / existentes | Tempo |
|---|---|---|---|
| Listagem, 1ª página | `chamado_criado` (Index Scan Backward + Limit) | 51 / 50.000 | 0,13 ms |
| Listagem por status (`CONCLUIDO`) | `chamado_status_criado` (Backward) | 51 / 43.250 | 0,23 ms |
| Listagem do prestador | `chamado_prestador_criado` (Backward, via InitPlan) | 51 | 0,22 ms |
| Rastreio por token | índice único do token | 1 | 0,02 ms |
| Prestadores próximos (KNN, 30 km) | `prestador_livre_loc_gist` (Order By `<->`) | 20 | 0,09 ms |
| Fechamento mensal (por cliente) | `chamado_encerrado` (parcial) | 7.561 inseridos | 18,5 ms |

Nenhuma das leituras tem `Sort` nem `Seq Scan` na tabela de chamados. O KNN, por exemplo:

```
Limit  (actual time=0.034..0.087 rows=20 loops=1)
  ->  Index Scan using prestador_livre_loc_gist on prestadores_prestador p
        Index Cond: (localizacao && _st_expand('0101…'::geography, '30000'::double precision))
        Order By: (localizacao <-> '0101…'::geography)
        Filter: (disponivel AND (atualizado_em >= …) AND st_dwithin(localizacao, '0101…'::geography, '30000'::double precision, true))
Execution Time: 0.094 ms
```

A listagem do prestador mostra a subquery resolvida antes e usada como condição do índice:

```
Limit  (actual time=0.029..0.194 rows=51 loops=1)
  InitPlan 1
    ->  Index Scan using prestadores_prestador_usuario_id_key on prestadores_prestador u0
  ->  Nested Loop
        ->  Index Scan Backward using chamado_prestador_criado on chamados_chamado
              Index Cond: (prestador_id = (InitPlan 1).col1)
Execution Time: 0.219 ms
```

Os planos também são cobertos por testes. Testes de `EXPLAIN` garantem que o KNN, o filtro do fechamento e a listagem do prestador continuam usando seus índices sem `Sort`. Testes de contagem de queries (`django_assert_num_queries`) garantem que listagem, detalhe e fechamento não crescem com o volume.

## Testes e qualidade

```bash
docker compose exec api pytest --cov=apps --cov=core
docker compose exec api ruff check . && docker compose exec api mypy .
```

- **250 testes** contra PostgreSQL/PostGIS e Redis reais (sem SQLite nem mocks de banco), com cobertura de 98,7%.
- **Concorrência de verdade:** os testes de corrida usam threads e conexões separadas, com uma `Barrier` para disparar todas juntas. Foram executados 25 vezes seguidas sem nenhuma falha intermitente.
- **CI** (`.github/workflows/ci.yml`, runner fixo `ubuntu-24.04`): lint, formatação, mypy strict, migrations em dia, schema OpenAPI sem avisos e testes com piso de 95% de cobertura.

## Estrutura

```
config/          settings, urls, celery
apps/
  contas/        Usuario (login por e-mail), papéis, JWT, permissões
  clientes/      Cliente (contratante) → tabela de preços
  chamados/      criação, consulta, máquina de estados, despacho concorrente, itens e rastreio
  prestadores/   Prestador, localização (Redis + gravação em lote) e busca por proximidade
  precos/        tabela de preços (cache Redis) e cálculo em Decimal
  financeiro/    fechamentos mensais gerados em SQL (INSERT ... SELECT em CTE)
core/            idempotência, paginação por cursor, erros padronizados, notificações,
                 health e comandos `seed` / `explicar`
```

**Regra de ouro:** as views só recebem e respondem; os **services** decidem; os **selectors** consultam.

## Serviços no Docker Compose

| Serviço | Papel |
|---|---|
| `api` | Gunicorn (gthread), sem estado |
| `worker` | Celery: filas `critica` e `notificacoes` |
| `worker-pesada` | Celery: fila `pesada` (fechamento, flush de localização), `prefetch=1` |
| `beat` | Tarefas agendadas (`django-celery-beat`) |
| `db` | PostgreSQL 16 + PostGIS |
| `redis` | Broker, cache, rate limit e última posição dos prestadores |
| `nginx` | Proxy reverso, gzip e arquivos estáticos |
| `osrm-mapa` → `osrm-preparo` → `osrm` | Profile `rota`: baixa o mapa, pré-processa uma vez e serve as rotas |

---

## English summary

**Despacha** is a service-dispatch REST API (towing, deliveries, maintenance) built with Django, DRF, PostgreSQL/PostGIS, Redis and Celery. This portfolio project covers:

- **Concurrency:** pessimistic `FOR UPDATE NOWAIT` locking for dispatch and optimistic `version` locking for state transitions.
- **Idempotency:** `Idempotency-Key` stored in the same transaction as the record it protects.
- **Async processing:** prioritized Celery queues with retries, backoff and deduplication.
- **Geospatial search:** KNN nearest-provider search on a partial GiST index.
- **Location updates:** zero-Postgres-query ingestion through Redis, written to the database in batches.
- **Billing:** monthly billing generated by a single `INSERT … SELECT` CTE per type.
- **Pagination:** cursor pagination backed by composite indexes.
- **Road distance:** a self-hosted OSRM behind an interface, with a 2 s timeout, a straight-line × 1.3 fallback (recorded as `ESTIMADA`), a circuit breaker and a Redis cache. Opening a request never fails because of the map service.

All hot read paths run under 0.25 ms on 50k records. You can reproduce this with `python manage.py seed --chamados 50000` followed by `python manage.py explicar`, which prints real `EXPLAIN ANALYZE` plans. There are 250 tests against real Postgres and Redis, with 98.7% coverage, and mypy runs in strict mode.

Run it with `docker compose up --build` and then `python manage.py seed`. API docs are at `/docs/`. Licensed under MIT.
