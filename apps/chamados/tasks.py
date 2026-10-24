from celery import shared_task

from . import services


@shared_task
def expirar_aceite(*, chamado_id: int, version: int, prestador_id: int) -> bool:
    return services.expirar_aceite(
        chamado_id=chamado_id, version=version, prestador_id=prestador_id
    )
