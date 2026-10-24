from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from core import tasks
from core.models import IdempotencyKey
from core.notificacoes import ErroTransitorio
from tests.factories import UsuarioFactory


class NotificadorFalso:
    def __init__(self, falhas: int = 0) -> None:
        self.falhas = falhas
        self.tentativas = 0
        self.enviadas: list[dict[str, Any]] = []

    def enviar(self, *, usuario_id: int, tipo: str, dados: dict[str, Any]) -> None:
        self.tentativas += 1
        if self.tentativas <= self.falhas:
            raise ErroTransitorio("provedor fora do ar")
        self.enviadas.append({"usuario_id": usuario_id, "tipo": tipo, "dados": dados})


@pytest.fixture
def usar_notificador(monkeypatch):
    def _usar(notificador: NotificadorFalso) -> NotificadorFalso:
        monkeypatch.setattr(tasks, "obter_notificador", lambda: notificador)
        return notificador

    return _usar


KWARGS = {"usuario_id": 1, "tipo": "chamado_despachado", "dados": {"chamado_id": 7}, "chave": "k1"}


def test_notificacao_reentregue_nao_envia_duas_vezes(usar_notificador) -> None:
    notificador = usar_notificador(NotificadorFalso())

    assert tasks.notificar.apply(kwargs=KWARGS).get() is True
    assert tasks.notificar.apply(kwargs=KWARGS).get() is False

    assert len(notificador.enviadas) == 1


def test_falha_transitoria_e_reenviada_com_backoff(usar_notificador) -> None:
    notificador = usar_notificador(NotificadorFalso(falhas=2))

    resultado = tasks.notificar.apply(kwargs=KWARGS)

    assert resultado.get() is True
    assert notificador.tentativas == 3
    assert len(notificador.enviadas) == 1


def test_desiste_apos_max_retries(usar_notificador) -> None:
    notificador = usar_notificador(NotificadorFalso(falhas=100))

    resultado = tasks.notificar.apply(kwargs=KWARGS)

    assert resultado.failed()
    assert notificador.tentativas == (tasks.notificar.max_retries or 0) + 1


def test_retry_configurado_com_backoff_exponencial() -> None:
    assert tasks.notificar.autoretry_for == (ErroTransitorio,)
    assert tasks.notificar.retry_backoff == 2
    assert tasks.notificar.retry_jitter is True


@pytest.mark.django_db
def test_limpeza_apaga_so_chaves_expiradas(settings) -> None:
    usuario = UsuarioFactory.create()
    for chave in ("velha", "nova"):
        IdempotencyKey.objects.create(
            usuario=usuario, chave=chave, hash_requisicao="h", status_code=201, resposta={}
        )
    IdempotencyKey.objects.filter(chave="velha").update(
        criado_em=timezone.now() - timedelta(hours=settings.IDEMPOTENCY_TTL_HORAS + 1)
    )

    assert tasks.limpar_idempotency_keys.apply().get() == 1
    assert list(IdempotencyKey.objects.values_list("chave", flat=True)) == ["nova"]
