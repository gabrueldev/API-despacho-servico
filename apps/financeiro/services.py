"""Fechamento mensal — todo no banco.

Cada tipo (cliente / prestador) é **um único comando SQL**: um `INSERT ... SELECT ... GROUP BY`
cria os fechamentos e, na mesma instrução (CTE), insere os itens. Nada é carregado para o
Python; são 2 queries por período, seja qual for o volume.

Idempotência: as constraints únicas (destinatário, período) + `ON CONFLICT DO NOTHING`.
Rodar de novo (Beat reentregue, clique duplo no "gerar") não cria nada; duas gerações
simultâneas também não, porque a segunda esbarra na constraint.
"""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.chamados.models import Chamado, Status
from core.exceptions import ErroDominio

from .models import Fechamento, FechamentoItem, StatusFechamento, TipoFechamento

FECHAMENTO = Fechamento._meta.db_table
ITEM = FechamentoItem._meta.db_table
CHAMADO = Chamado._meta.db_table

# Entram: concluídos e cancelados com taxa (valor_final > 0), encerrados no período.
# `encerrado_em` usa o índice parcial `chamado_encerrado`.
_FILTRO = f"""
    c.encerrado_em >= %(desde)s AND c.encerrado_em < %(ate)s
    AND (c.status = '{Status.CONCLUIDO}' OR (c.status = '{Status.CANCELADO}' AND c.valor_final > 0))
"""

# {destino}: coluna do destinatário (cliente_id | prestador_id); {valor}: valor por chamado.
_SQL = f"""
WITH novos AS (
    INSERT INTO {FECHAMENTO}
        (tipo, cliente_id, prestador_id, periodo_inicio, periodo_fim,
         total, quantidade_chamados, status, criado_em)
    SELECT %(tipo)s, {{cliente}}, {{prestador}}, %(inicio)s, %(fim)s,
           SUM({{valor}}), COUNT(*), %(status)s, now()
    FROM {CHAMADO} AS c
    WHERE {_FILTRO} AND c.{{destino}} IS NOT NULL
    GROUP BY c.{{destino}}
    ON CONFLICT DO NOTHING
    RETURNING id, {{destino}}
),
itens AS (
    INSERT INTO {ITEM} (fechamento_id, chamado_id, valor)
    SELECT n.id, c.id, {{valor}}
    FROM novos AS n
    JOIN {CHAMADO} AS c ON c.{{destino}} = n.{{destino}}
    WHERE {_FILTRO}
    RETURNING 1
)
SELECT (SELECT count(*) FROM novos), (SELECT count(*) FROM itens)
"""  # noqa: S608 — só nomes de tabela/coluna fixos e placeholders são interpolados

_POR_TIPO = {
    TipoFechamento.CLIENTE: _SQL.format(
        destino="cliente_id", cliente="c.cliente_id", prestador="NULL", valor="c.valor_final"
    ),
    # ROUND(numeric, 2) arredonda .5 para longe do zero = ROUND_HALF_UP para valores positivos.
    # O total soma os itens já arredondados, então total == soma dos itens, sempre.
    TipoFechamento.PRESTADOR: _SQL.format(
        destino="prestador_id",
        cliente="NULL",
        prestador="c.prestador_id",
        valor="ROUND(c.valor_final * %(percentual)s / 100, 2)",
    ),
}


@dataclass(frozen=True, slots=True)
class Periodo:
    inicio: date
    fim: date  # inclusivo (último dia do mês)

    @classmethod
    def mes(cls, ano: int, mes: int) -> "Periodo":
        if not 1 <= mes <= 12:
            raise ErroDominio("Mês inválido.", codigo="periodo_invalido")
        return cls(date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1]))

    @classmethod
    def mes_anterior(cls, hoje: date) -> "Periodo":
        ultimo_dia = hoje.replace(day=1) - timedelta(days=1)
        return cls.mes(ultimo_dia.year, ultimo_dia.month)

    def limites(self) -> tuple[datetime, datetime]:
        """[início, fim) em horário local: o mês do cliente é o de Brasília, não o UTC."""
        fuso = ZoneInfo(settings.TIME_ZONE)
        desde = datetime.combine(self.inicio, datetime.min.time(), tzinfo=fuso)
        ate = datetime.combine(self.fim + timedelta(days=1), datetime.min.time(), tzinfo=fuso)
        return desde, ate


@dataclass(frozen=True, slots=True)
class Resultado:
    fechamentos: int
    itens: int


def exigir_periodo_encerrado(periodo: Periodo) -> None:
    if periodo.fim >= timezone.localdate():
        raise ErroDominio(
            "Só é possível fechar períodos já encerrados.", codigo="periodo_em_andamento"
        )


def gerar(periodo: Periodo) -> dict[TipoFechamento, Resultado]:
    exigir_periodo_encerrado(periodo)
    desde, ate = periodo.limites()
    params: dict[str, Any] = {
        "inicio": periodo.inicio,
        "fim": periodo.fim,
        "desde": desde,
        "ate": ate,
        "status": StatusFechamento.GERADO,
        "percentual": Decimal(settings.REPASSE_PRESTADOR_PERCENTUAL),
    }
    resultados = {}
    with transaction.atomic(), connection.cursor() as cursor:
        for tipo, sql in _POR_TIPO.items():
            cursor.execute(sql, {**params, "tipo": tipo})
            fechamentos, itens = cursor.fetchone()
            resultados[tipo] = Resultado(fechamentos, itens)
    return resultados
