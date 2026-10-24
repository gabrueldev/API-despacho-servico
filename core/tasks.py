from datetime import timedelta
from typing import Any

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from .models import IdempotencyKey
from .notificacoes import ErroTransitorio, obter_notificador

DEDUPE_TTL_SEGUNDOS = 24 * 60 * 60


@shared_task(
    autoretry_for=(ErroTransitorio,),
    retry_backoff=2,  # 2 s, 4 s, 8 s, ... (com jitter)
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=6,
)
def notificar(*, usuario_id: int, tipo: str, dados: dict[str, Any], chave: str) -> bool:
    """Idempotente por `chave`: reentrega (acks_late) ou retry não enviam duas vezes.

    A marca de "enviado" só é gravada após o sucesso, para o retry não pular o envio.
    """
    marca = f"notificacao:enviada:{chave}"
    if cache.get(marca):
        return False
    obter_notificador().enviar(usuario_id=usuario_id, tipo=tipo, dados=dados)
    cache.set(marca, 1, timeout=DEDUPE_TTL_SEGUNDOS)
    return True


@shared_task
def limpar_idempotency_keys() -> int:
    """DELETE direto no SQL (o BRIN em criado_em acha o intervalo); sem carregar linhas."""
    limite = timezone.now() - timedelta(hours=settings.IDEMPOTENCY_TTL_HORAS)
    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {IdempotencyKey._meta.db_table} WHERE criado_em < %s",  # noqa: S608
            [limite],
        )
        return int(cursor.rowcount)
