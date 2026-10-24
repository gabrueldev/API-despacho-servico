from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse

from apps.chamados import services
from apps.chamados.models import Chamado
from apps.contas.models import Papel
from tests.factories import ClienteFactory, PrestadorFactory, UsuarioFactory

pytestmark = pytest.mark.django_db

URL = reverse("chamados")


class DistanciaFixa:
    def distancia_km(self, origem: Point, destino: Point) -> Decimal:
        return Decimal("58")


def _criar(n: int = 1, prestador=None) -> list[Chamado]:
    atendente = UsuarioFactory(papel=Papel.ATENDENTE)
    cliente = ClienteFactory()
    chamados = []
    for _ in range(n):
        chamado = services.criar_chamado(
            atendente=atendente,
            dados=services.NovoChamado(
                cliente_id=cliente.pk,
                placa="ABC1234",
                endereco_origem="Rua A",
                origem=Point(-46.63, -23.55, srid=4326),
                destino=Point(-46.47, -23.43, srid=4326),
            ),
            calculadora=DistanciaFixa(),
        ).chamado
        if prestador:
            Chamado.objects.filter(pk=chamado.pk).update(prestador=prestador)
        chamados.append(chamado)
    return chamados


def test_listagem_usa_uma_query_independente_do_volume(
    cliente_api, django_assert_num_queries
) -> None:
    _criar(5, prestador=PrestadorFactory())
    client = cliente_api(Papel.DESPACHANTE)

    with django_assert_num_queries(1):
        response = client.get(URL)

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 5
    assert body["results"][0]["prestador"]["nome"].startswith("Guincho")
    assert "next" in body and "count" not in body  # cursor, sem COUNT(*)


def test_listagem_ordena_do_mais_recente_e_pagina_por_cursor(cliente_api) -> None:
    ids = [c.pk for c in _criar(3)]
    client = cliente_api(Papel.ATENDENTE)

    pagina1 = client.get(URL, {"page_size": 2}).json()
    pagina2 = client.get(pagina1["next"]).json()

    assert [c["id"] for c in pagina1["results"]] == ids[::-1][:2]
    assert [c["id"] for c in pagina2["results"]] == ids[::-1][2:]


def test_filtro_por_status(cliente_api) -> None:
    _criar(2)
    client = cliente_api(Papel.ATENDENTE)

    assert len(client.get(URL, {"status": "ABERTO"}).json()["results"]) == 2
    assert client.get(URL, {"status": "CONCLUIDO"}).json()["results"] == []
    assert client.get(URL, {"status": "xpto"}).status_code == 400


def test_prestador_ve_so_os_proprios(cliente_api) -> None:
    prestador = PrestadorFactory()
    meus = _criar(2, prestador=prestador)
    _criar(3, prestador=PrestadorFactory())

    response = cliente_api(usuario=prestador.usuario).get(URL)

    assert {c["id"] for c in response.json()["results"]} == {c.pk for c in meus}


def test_financeiro_nao_acessa_chamados(cliente_api) -> None:
    assert cliente_api(Papel.FINANCEIRO).get(URL).status_code == 403


def test_detalhe_com_itens_e_historico_em_3_queries(cliente_api, django_assert_num_queries) -> None:
    (chamado,) = _criar(1)
    client = cliente_api(Papel.ATENDENTE)

    with django_assert_num_queries(3):
        response = client.get(reverse("chamado-detalhe", args=[chamado.pk]))

    body = response.json()
    assert response.status_code == 200
    assert body["valor_previsto"] == "331.00"
    assert body["origem"] == {"lat": -23.55, "lng": -46.63}
    assert [i["tipo"] for i in body["itens"]] == ["SAIDA", "KM_EXCEDENTE"]
    assert [e["para_status"] for e in body["eventos"]] == ["ABERTO"]


def test_prestador_nao_ve_detalhe_de_outro(cliente_api) -> None:
    (chamado,) = _criar(1, prestador=PrestadorFactory())
    outro = PrestadorFactory()

    response = cliente_api(usuario=outro.usuario).get(reverse("chamado-detalhe", args=[chamado.pk]))

    assert response.status_code == 404
    assert response.json()["erro"] == "nao_encontrado"
