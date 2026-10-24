from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.chamados.models import Chamado
from apps.contas.models import Papel
from core.models import IdempotencyKey
from tests.concorrencia import em_paralelo
from tests.factories import ClienteFactory, UsuarioFactory

URL = reverse("chamados")


def _payload(cliente_id: int, placa: str = "ABC1D23") -> dict[str, object]:
    return {
        "cliente_id": cliente_id,
        "placa": placa,
        "endereco_origem": "Praça da Sé",
        "origem": {"lat": -23.5503, "lng": -46.6339},
        "destino": {"lat": -23.4356, "lng": -46.4731},
    }


def _post(client: APIClient, payload: dict[str, object], chave: str | None):
    headers = {"Idempotency-Key": chave} if chave else {}
    return client.post(URL, payload, format="json", headers=headers)


@pytest.mark.django_db
def test_reenvio_com_mesma_chave_nao_duplica(cliente_api, django_assert_num_queries) -> None:
    client = cliente_api(Papel.ATENDENTE)
    payload = _payload(ClienteFactory.create().pk)

    primeira = _post(client, payload, "chave-1")
    with django_assert_num_queries(1):  # só o SELECT da chave
        segunda = _post(client, payload, "chave-1")

    assert (primeira.status_code, segunda.status_code) == (201, 201)
    assert segunda.json() == primeira.json()
    assert segunda["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in primeira
    assert Chamado.objects.count() == 1


@pytest.mark.django_db
def test_mesma_chave_com_outro_corpo_retorna_422(cliente_api) -> None:
    client = cliente_api(Papel.ATENDENTE)
    cliente_id = ClienteFactory.create().pk
    _post(client, _payload(cliente_id), "chave-1")

    response = _post(client, _payload(cliente_id, placa="XYZ9876"), "chave-1")

    assert response.status_code == 422
    assert response.json()["erro"] == "idempotency_key_reutilizada"
    assert Chamado.objects.count() == 1


@pytest.mark.django_db
def test_chave_e_por_usuario(cliente_api) -> None:
    payload = _payload(ClienteFactory.create().pk)

    a = _post(cliente_api(Papel.ATENDENTE), payload, "mesma")
    b = _post(cliente_api(Papel.ATENDENTE), payload, "mesma")

    assert a.json()["id"] != b.json()["id"]
    assert Chamado.objects.count() == 2


@pytest.mark.django_db
def test_sem_chave_cada_post_cria_um_chamado(cliente_api) -> None:
    client = cliente_api(Papel.ATENDENTE)
    payload = _payload(ClienteFactory.create().pk)

    _post(client, payload, None)
    _post(client, payload, None)

    assert Chamado.objects.count() == 2
    assert not IdempotencyKey.objects.exists()


@pytest.mark.django_db
def test_chave_expirada_vale_como_nova(cliente_api, settings) -> None:
    client = cliente_api(Papel.ATENDENTE)
    payload = _payload(ClienteFactory.create().pk)
    _post(client, payload, "chave-1")
    IdempotencyKey.objects.update(
        criado_em=timezone.now() - timedelta(hours=settings.IDEMPOTENCY_TTL_HORAS + 1)
    )

    response = _post(client, payload, "chave-1")

    assert response.status_code == 201
    assert "Idempotent-Replayed" not in response
    assert Chamado.objects.count() == 2
    assert IdempotencyKey.objects.count() == 1


@pytest.mark.django_db
def test_erro_nao_fica_gravado_e_pode_ser_reenviado(cliente_api) -> None:
    client = cliente_api(Papel.ATENDENTE)
    cliente = ClienteFactory.create(ativo=False)
    payload = _payload(cliente.pk)

    assert _post(client, payload, "chave-1").status_code == 422
    cliente.ativo = True
    cliente.save()

    assert _post(client, payload, "chave-1").status_code == 201
    assert Chamado.objects.count() == 1


@pytest.mark.django_db
def test_chave_longa_demais_retorna_422(cliente_api) -> None:
    response = _post(cliente_api(Papel.ATENDENTE), _payload(ClienteFactory.create().pk), "x" * 256)

    assert response.status_code == 422
    assert response.json()["erro"] == "idempotency_key_invalida"


@pytest.mark.django_db(transaction=True)
def test_reenvios_simultaneos_com_mesma_chave_criam_um_chamado() -> None:
    n = 5
    atendente = UsuarioFactory.create(papel=Papel.ATENDENTE)
    payload = _payload(ClienteFactory.create().pk)

    def enviar(_: int):
        client = APIClient()
        client.force_authenticate(atendente)
        return _post(client, payload, "rede-instavel")

    respostas = em_paralelo(n, enviar)

    assert all(not isinstance(r, Exception) for r in respostas), respostas
    assert {r.status_code for r in respostas} == {201}
    assert len({r.json()["id"] for r in respostas}) == 1
    assert Chamado.objects.count() == 1
    assert IdempotencyKey.objects.count() == 1
