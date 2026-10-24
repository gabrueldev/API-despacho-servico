from celery import shared_task

from . import localizacao


@shared_task
def gravar_localizacoes() -> int:
    return localizacao.gravar_pendentes()
