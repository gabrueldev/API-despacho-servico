from datetime import date

from django.db.models import Prefetch, QuerySet

from .models import Fechamento, FechamentoItem, TipoFechamento


def listar(
    *, tipo: TipoFechamento | None = None, ano: int | None = None, mes: int | None = None
) -> QuerySet[Fechamento]:
    """Uma query: JOIN em cliente/prestador.

    Período por igualdade em `periodo_inicio` (sempre dia 1), não `__year`/`__month`: esses
    viram EXTRACT(...) no SQL e impedem o uso do índice (periodo_inicio, tipo).
    """
    qs = Fechamento.objects.select_related("cliente", "prestador")
    if ano and mes:
        qs = qs.filter(periodo_inicio=date(ano, mes, 1))
    if tipo:
        qs = qs.filter(tipo=tipo)
    return qs


def detalhe() -> QuerySet[Fechamento]:
    """2 queries fixas: fechamento e itens (placa e encerramento do chamado via JOIN)."""
    itens = (
        FechamentoItem.objects.select_related("chamado")
        .only(
            "id",
            "fechamento_id",
            "valor",
            "chamado__id",
            "chamado__placa",
            "chamado__status",
            "chamado__encerrado_em",
        )
        .order_by("chamado__encerrado_em", "id")
    )
    return listar().prefetch_related(Prefetch("itens", queryset=itens))
