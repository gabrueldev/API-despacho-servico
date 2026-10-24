from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.contas.models import Papel
from apps.prestadores import selectors
from apps.prestadores.models import Prestador
from tests.factories import PrestadorFactory

pytestmark = pytest.mark.django_db

URL = reverse("prestadores-proximos")
SE = (-23.5503, -46.6339)  # Praça da Sé


def _em(lat: float, lng: float, **kwargs) -> Prestador:
    return PrestadorFactory.create(localizacao=Point(lng, lat, srid=4326), **kwargs)


def _ids(response) -> list[int]:
    return [p["id"] for p in response.json()]


def test_ordena_do_mais_proximo_ao_mais_distante_dentro_do_raio(cliente_api) -> None:
    longe = _em(-23.70, -46.63)  # ~16,6 km
    perto = _em(-23.56, -46.63)  # ~1,1 km
    medio = _em(-23.60, -46.63)  # ~5,5 km
    _em(-24.00, -46.63)  # ~50 km: fora do raio de 30 km

    response = cliente_api(Papel.DESPACHANTE).get(URL, {"lat": SE[0], "lng": SE[1]})

    assert response.status_code == 200
    assert _ids(response) == [perto.pk, medio.pk, longe.pk]
    distancias = [Decimal(p["distancia_km"]) for p in response.json()]
    assert distancias == sorted(distancias)
    assert Decimal("0.5") < distancias[0] < Decimal("2")


def test_raio_customizado(cliente_api) -> None:
    perto = _em(-23.56, -46.63)
    _em(-23.60, -46.63)

    response = cliente_api(Papel.DESPACHANTE).get(URL, {"lat": SE[0], "lng": SE[1], "raio": 2})

    assert _ids(response) == [perto.pk]


def test_ignora_indisponivel_sem_posicao_e_posicao_velha(cliente_api, settings) -> None:
    livre = _em(-23.56, -46.63)
    _em(-23.56, -46.63, disponivel=False)
    PrestadorFactory.create(localizacao=None)
    velho = _em(-23.56, -46.63)
    Prestador.objects.filter(pk=velho.pk).update(
        atualizado_em=timezone.now() - timedelta(minutes=settings.POSICAO_VALIDADE_MINUTOS + 1)
    )

    response = cliente_api(Papel.DESPACHANTE).get(URL, {"lat": SE[0], "lng": SE[1]})

    assert _ids(response) == [livre.pk]


def test_limita_quantidade(cliente_api, settings) -> None:
    settings.PROXIMOS_LIMITE = 3
    for i in range(5):
        _em(-23.55 - i / 1000, -46.63)

    response = cliente_api(Papel.DESPACHANTE).get(URL, {"lat": SE[0], "lng": SE[1]})

    assert len(response.json()) == 3


def test_uma_query_independente_do_volume(cliente_api, django_assert_num_queries) -> None:
    for i in range(10):
        _em(-23.55 - i / 100, -46.63)
    client = cliente_api(Papel.DESPACHANTE)

    with django_assert_num_queries(1):
        response = client.get(URL, {"lat": SE[0], "lng": SE[1]})
    assert len(response.json()) == 10


@pytest.mark.parametrize(
    "params",
    [{"lng": SE[1]}, {"lat": 91, "lng": 0}, {"lat": SE[0], "lng": SE[1], "raio": 500}],
)
def test_parametros_invalidos_retornam_400(cliente_api, params) -> None:
    assert cliente_api(Papel.DESPACHANTE).get(URL, params).status_code == 400


@pytest.mark.parametrize("papel", [Papel.PRESTADOR, Papel.FINANCEIRO])
def test_prestador_e_financeiro_nao_buscam(cliente_api, papel) -> None:
    assert cliente_api(papel).get(URL, {"lat": SE[0], "lng": SE[1]}).status_code == 403


def test_usa_o_gist_parcial_com_knn_sem_sort() -> None:
    params = {
        "lat": SE[0],
        "lng": SE[1],
        "raio_m": 30_000,
        "desde": timezone.now(),
        "limite": 20,
    }
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")  # tabela pequena: força o plano real
        cursor.execute("EXPLAIN " + selectors._SQL_PROXIMOS, params)
        plano = "\n".join(linha[0] for linha in cursor.fetchall())

    assert "Index Scan using prestador_livre_loc_gist" in plano
    assert "Order By: (localizacao <->" in plano  # o índice já devolve ordenado
    assert "Sort" not in plano
