# Despacha

API de despacho de serviços (guincho, entregas, manutenção) em **Python / Django**, feita para demonstrar na prática concorrência, filas, banco otimizado, segurança, testes e arquitetura em camadas.

> **Status:** em construção — etapas 1 a 7 concluídas (base, domínio, ciclo de vida, concorrência/idempotência, processamento assíncrono, proximidade/rastreio e financeiro). Plano completo em [`despacha-plano-arquitetura.md`](despacha-plano-arquitetura.md).

**Stack:** Django 5.2 + DRF · PostgreSQL 16 + PostGIS · Redis 7 · Celery 5 + Beat · Nginx + Gunicorn · Docker Compose · GitHub Actions · pytest

## Como rodar

```bash
cp .env.example .env
docker compose up --build
docker compose exec api python manage.py createsuperuser
```

| URL | O quê |
|---|---|
| http://localhost:8000/health | Saúde da API (banco + Redis) |
| http://localhost:8000/docs/ | Swagger |
| http://localhost:8000/admin/ | Admin do Django |
| `POST /auth/login` · `POST /auth/refresh` | JWT (access 15 min, refresh 7 dias com rotação) |
| `POST /chamados` · `GET /chamados?status=&cursor=` · `GET /chamados/{id}` | Abrir (aceita `Idempotency-Key`), listar e detalhar chamados |
| `POST /chamados/{id}/despachar` | Despacho com `SELECT ... FOR UPDATE NOWAIT`: quem perde a corrida recebe 409 na hora; agenda o timeout de aceite (2 min) |
| `POST /prestadores/me/localizacao` | Posição do prestador: zero queries no Postgres (JWT sem estado + Redis), gravada em lote pelo Beat |
| `GET /prestadores/proximos?lat=&lng=&raio=` | Disponíveis no raio, do mais próximo ao mais distante (KNN no GiST parcial, 1 query) |
| `GET /rastreio/{token}` | Link público do associado: status e posição do prestador, cache de 5 s, 410 quando expira |
| `POST /chamados/{id}/itens` | Lança pedágio, espera (por minutos) ou adicional |
| `GET /fechamentos?tipo=&periodo=AAAA-MM` · `GET /fechamentos/{id}` · `POST /fechamentos/gerar` | Fechamento mensal por cliente e por prestador (2 queries por período, idempotente) |
| `POST /chamados/{id}/aceitar` · `recusar` · `status` · `concluir` · `cancelar` | Ciclo de vida (trava otimista por `version`, 409 em conflito) |

### Sem Docker (macOS)

```bash
brew install postgresql@17 postgis redis
brew services start postgresql@17 && brew services start redis
createdb despacha
cp .env.example .env   # ajuste DATABASE_URL/REDIS_URL para localhost e descomente GDAL/GEOS
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate && .venv/bin/python manage.py runserver

# Celery (em outros terminais). No macOS use -P threads: o prefork exige fork,
# e o macOS usa spawn por padrão. No Docker (Linux) o prefork funciona normalmente.
.venv/bin/celery -A config worker -Q critica,notificacoes,pesada -P threads -l info
.venv/bin/celery -A config beat -l info
```

## Testes e qualidade

```bash
docker compose exec api pytest
docker compose exec api ruff check .
docker compose exec api mypy .
```

O CI (`.github/workflows/ci.yml`) roda lint, formatação, mypy, checagem de migrations e testes com PostGIS e Redis reais.

## Estrutura

```
config/          settings, urls, celery
apps/
  contas/        Usuario (login por e-mail), papéis, JWT, permissões
  clientes/      Cliente (contratante) → tabela de preços
  chamados/      criação, consulta, máquina de estados e despacho concorrente
  prestadores/   Prestador, localização (Redis + gravação em lote) e busca por proximidade
  precos/        tabela de preços (cache Redis) e cálculo em Decimal
  financeiro/    fechamentos mensais gerados em SQL (INSERT ... SELECT em CTE)
core/            idempotência, paginação por cursor, erros padronizados, health, PontoField
```

**Regra de ouro:** views só recebem e respondem; **services** decidem; **selectors** consultam.

## Serviços no Docker Compose

| Serviço | Papel |
|---|---|
| `api` | Gunicorn (gthread), sem estado |
| `worker` | Celery — filas `critica` e `notificacoes` |
| `worker-pesada` | Celery — fila `pesada` (fechamento, flush de localização), `prefetch=1` |
| `beat` | Tarefas agendadas (`django-celery-beat`) |
| `db` | PostgreSQL 16 + PostGIS |
| `redis` | Broker, cache, rate limit e última posição dos prestadores |
| `nginx` | Proxy reverso, gzip e arquivos estáticos |

---

## English summary

**Despacha** is a service-dispatch REST API (towing, deliveries, maintenance) built with Django, DRF, PostgreSQL/PostGIS, Redis and Celery. It is a portfolio project focused on concurrency (pessimistic locking with `NOWAIT`), idempotency, async processing with prioritized queues, geospatial queries with GiST indexes, cursor pagination and layered architecture (views → services → selectors). Run it with `docker compose up --build`; API docs at `/docs/`. Licensed under MIT.
