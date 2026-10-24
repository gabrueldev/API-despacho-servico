from celery import shared_task
from django.utils import timezone

from . import services


@shared_task
def gerar_fechamentos(ano: int, mes: int) -> dict[str, int]:
    resultados = services.gerar(services.Periodo.mes(ano, mes))
    return {tipo: r.fechamentos for tipo, r in resultados.items()}


@shared_task
def gerar_fechamentos_mes_anterior() -> dict[str, int]:
    periodo = services.Periodo.mes_anterior(timezone.localdate())
    return gerar_fechamentos(periodo.inicio.year, periodo.inicio.month)
