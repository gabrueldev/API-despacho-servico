"""Envio de notificações atrás de uma interface.

MVP: `LogNotificador` (só registra em log). WhatsApp Business entra como outra classe
apontada por `settings.NOTIFICADOR`, sem mudar quem notifica.
"""

import logging
from functools import cache
from typing import Any, Protocol

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger("despacha.notificacoes")


class ErroTransitorio(Exception):
    """Falha temporária do provedor (timeout, 5xx, rate limit): a task tenta de novo."""


class Notificador(Protocol):
    def enviar(self, *, usuario_id: int, tipo: str, dados: dict[str, Any]) -> None: ...


class LogNotificador:
    def enviar(self, *, usuario_id: int, tipo: str, dados: dict[str, Any]) -> None:
        logger.info("notificacao tipo=%s usuario=%s dados=%s", tipo, usuario_id, dados)


@cache
def obter_notificador() -> Notificador:
    classe: type[Notificador] = import_string(settings.NOTIFICADOR)
    return classe()
