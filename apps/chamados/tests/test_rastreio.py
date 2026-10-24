from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.chamados.models import Chamado, Status
from apps.prestadores import localizacao
from tests.factories import ChamadoFactory, PrestadorFactory

pytestmark = pytest.mark.django_db


def _url(chamado: Chamado) -> str:
    return reverse("rastreio", args=[chamado.rastreio_token])


def test_rastreio_publico_com_posicao_do_prestador_a_caminho() -> None:
    prestador = PrestadorFactory.create(nome="Guincho Rápido")
    chamado = ChamadoFactory.create(status=Status.A_CAMINHO, prestador=prestador, placa="ABC1D23")
    localizacao.registrar(prestador.usuario_id, -23.5612, -46.6560)

    response = APIClient().get(_url(chamado))  # sem login

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "A_CAMINHO"
    assert body["placa"] == "ABC-**23"
    assert body["prestador"]["nome"] == "Guincho Rápido"
    assert (body["prestador"]["posicao"]["lat"], body["prestador"]["posicao"]["lng"]) == (
        -23.5612,
        -46.656,
    )
    assert "telefone" not in body["prestador"]


def test_chamado_aberto_nao_tem_prestador() -> None:
    body = APIClient().get(_url(ChamadoFactory.create())).json()

    assert (body["status"], body["prestador"]) == ("ABERTO", None)


def test_despachado_mostra_prestador_mas_nao_a_posicao() -> None:
    prestador = PrestadorFactory.create()
    chamado = ChamadoFactory.create(status=Status.DESPACHADO, prestador=prestador)
    localizacao.registrar(prestador.usuario_id, -23.56, -46.65)

    body = APIClient().get(_url(chamado)).json()

    assert body["prestador"]["posicao"] is None


def test_link_expirado_retorna_410() -> None:
    chamado = ChamadoFactory.create(
        status=Status.CONCLUIDO, rastreio_expira_em=timezone.now() - timedelta(seconds=1)
    )

    response = APIClient().get(_url(chamado))

    assert response.status_code == 410
    assert response.json()["erro"] == "rastreio_expirado"


def test_concluido_dentro_da_validade_ainda_abre() -> None:
    chamado = ChamadoFactory.create(
        status=Status.CONCLUIDO, rastreio_expira_em=timezone.now() + timedelta(hours=1)
    )

    assert APIClient().get(_url(chamado)).status_code == 200


def test_token_inexistente_retorna_404() -> None:
    response = APIClient().get(reverse("rastreio", args=["nao-existe"]))

    assert response.status_code == 404


def test_varios_acessos_ao_mesmo_link_viram_uma_query(django_assert_num_queries) -> None:
    chamado = ChamadoFactory.create()
    client = APIClient()

    with django_assert_num_queries(1):
        client.get(_url(chamado))
    with django_assert_num_queries(0):  # cache de 5 s
        for _ in range(5):
            assert client.get(_url(chamado)).status_code == 200


def test_rate_limit_por_ip() -> None:
    url = _url(ChamadoFactory.create())
    client = APIClient()

    codigos = {client.get(url).status_code for _ in range(61)}

    assert codigos == {200, 429}
