"""`python manage.py explicar`: EXPLAIN (ANALYZE, BUFFERS) das queries críticas.

Usa os mesmos selectors/SQL da API, então o plano mostrado é o que roda em produção.
Rode depois do `seed` (ou em uma cópia do banco real) para os números fazerem sentido.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction
from django.db.models import Count, QuerySet
from django.utils import timezone

from apps.chamados import selectors as chamados
from apps.chamados.models import Chamado, Status
from apps.contas.models import Papel, Usuario
from apps.financeiro import services as financeiro
from apps.financeiro.models import Fechamento, TipoFechamento
from apps.prestadores import selectors as prestadores
from apps.prestadores.models import Prestador
from core.pagination import CriadoEmCursorPagination

CENTRO = {"lat": -23.5503, "lng": -46.6339}
PAGINA = CriadoEmCursorPagination.page_size + 1  # o cursor busca 1 a mais para saber se há próxima


def _pagina(qs: QuerySet[Any]) -> QuerySet[Any]:
    return qs.order_by(*CriadoEmCursorPagination.ordering)[:PAGINA]


def _explicar_orm(qs: QuerySet[Any]) -> str:
    return qs.explain(analyze=True, buffers=True)


def _explicar_sql(sql: str, params: dict[str, Any]) -> str:
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql, params)
        return "\n".join(linha[0] for linha in cursor.fetchall())


class Command(BaseCommand):
    help = "Mostra o plano real (EXPLAIN ANALYZE) das queries críticas."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--so", help="Roda só a query cujo nome contém este texto.")

    def handle(self, *args: Any, **opcoes: Any) -> None:
        if not Chamado.objects.exists():
            raise CommandError("Sem chamados. Rode `python manage.py seed` antes.")
        atendente = Usuario(papel=Papel.ATENDENTE)
        consultas: dict[str, Callable[[], str]] = {
            "listagem de chamados (1ª página)": lambda: _explicar_orm(
                _pagina(chamados.listar_chamados(atendente))
            ),
            "listagem filtrada por status (o maior: CONCLUIDO)": lambda: _explicar_orm(
                _pagina(chamados.listar_chamados(atendente, Status.CONCLUIDO))
            ),
            "listagem do prestador": self._do_prestador,
            "rastreio por token": self._rastreio,
            "prestadores próximos (KNN)": lambda: _explicar_sql(
                prestadores._SQL_PROXIMOS,
                {
                    **CENTRO,
                    "raio_m": 30_000,
                    "desde": timezone.now() - timedelta(minutes=10),
                    "limite": 20,
                },
            ),
            "fechamento mensal (por cliente)": self._fechamento,
        }
        for nome, explicar in consultas.items():
            if opcoes["so"] and opcoes["so"].lower() not in nome.lower():
                continue
            # A 1ª execução numa conexão paga a carga do PostGIS e o cache frio; com o pool
            # de conexões isso não se repete, então o plano mostrado é o da 2ª.
            explicar()
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n== {nome}"))
            self.stdout.write(explicar())

    def _do_prestador(self) -> str:
        mais_ativo = (
            Prestador.objects.annotate(n=Count("chamados"))
            .order_by("-n")
            .values("usuario_id")
            .first()
        )
        if not mais_ativo:
            return "(sem prestadores)"
        usuario = Usuario(pk=mais_ativo["usuario_id"], papel=Papel.PRESTADOR)
        return _explicar_orm(_pagina(chamados.listar_chamados(usuario)))

    def _rastreio(self) -> str:
        token = Chamado.objects.values_list("rastreio_token", flat=True).last()
        qs = (
            Chamado.objects.select_related("prestador")
            .only("status", "placa", "origem", "rastreio_expira_em", "prestador__nome")
            .filter(rastreio_token=token)
        )
        return _explicar_orm(qs)

    def _fechamento(self) -> str:
        """Roda o INSERT de verdade e desfaz: EXPLAIN ANALYZE executa a instrução."""
        periodo = financeiro.Periodo.mes_anterior(timezone.localdate())
        desde, ate = periodo.limites()
        with transaction.atomic():
            Fechamento.objects.filter(periodo_inicio=periodo.inicio).delete()
            plano = _explicar_sql(
                financeiro._POR_TIPO[TipoFechamento.CLIENTE],
                {
                    "tipo": TipoFechamento.CLIENTE,
                    "inicio": periodo.inicio,
                    "fim": periodo.fim,
                    "desde": desde,
                    "ate": ate,
                    "status": "GERADO",
                    "percentual": 100,
                },
            )
            transaction.set_rollback(True)
        return plano
