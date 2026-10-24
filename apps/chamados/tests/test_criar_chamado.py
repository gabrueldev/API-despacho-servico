from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse

from apps.chamados import services
from apps.chamados.distancia import Distancia, LinhaRetaPostGIS
from apps.chamados.models import Chamado, EventoChamado, FonteDistancia, Status
from apps.contas.models import Papel
from apps.precos.tipos import TipoItem
from tests.factories import ClienteFactory, UsuarioFactory

pytestmark = pytest.mark.django_db

URL = reverse("chamados")
# Praça da Sé -> Aeroporto de Guarulhos (~22 km em linha reta)
SE = {"lat": -23.5503, "lng": -46.6339}
GRU = {"lat": -23.4356, "lng": -46.4731}
# ~1 grau de latitude (~110,6 km): força km excedente
LONGE = {"lat": -22.5503, "lng": -46.6339}


def _payload(cliente_id: int, destino: dict[str, float] = GRU) -> dict[str, object]:
    return {
        "cliente_id": cliente_id,
        "placa": "abc-1d23",
        "endereco_origem": "Praça da Sé, São Paulo",
        "origem": SE,
        "destino": destino,
    }


def test_service_calcula_valor_previsto_e_registra_evento() -> None:
    atendente = UsuarioFactory(papel=Papel.ATENDENTE)
    cliente = ClienteFactory()

    criado = services.criar_chamado(
        atendente=atendente,
        dados=services.NovoChamado(
            cliente_id=cliente.pk,
            placa="ABC1D23",
            endereco_origem="Rua A",
            origem=Point(-46.63, -23.55, srid=4326),
            destino=Point(-46.47, -23.43, srid=4326),
        ),
        distancia=Distancia(Decimal("58"), FonteDistancia.ROTA),
    )

    chamado = criado.chamado
    assert chamado.status == Status.ABERTO
    assert chamado.valor_previsto == Decimal("331.00")  # 250 + 18 × 4,50
    assert [(i.tipo, i.total) for i in criado.itens] == [
        (TipoItem.SAIDA, Decimal("250.00")),
        (TipoItem.KM_EXCEDENTE, Decimal("81.00")),
    ]
    evento = EventoChamado.objects.get(chamado=chamado)
    assert (evento.de_status, evento.para_status) == (None, Status.ABERTO)
    assert evento.usuario_id == atendente.pk
    assert chamado.distancia_fonte == FonteDistancia.ROTA
    assert evento.dados["distancia_fonte"] == "ROTA"


def test_distancia_linha_reta_postgis() -> None:
    medida = LinhaRetaPostGIS().medir(
        Point(SE["lng"], SE["lat"], srid=4326), Point(GRU["lng"], GRU["lat"], srid=4326)
    )

    assert Decimal("20") < medida.km < Decimal("22")
    assert medida.fonte == FonteDistancia.LINHA_RETA


def test_post_cria_chamado_201(cliente_api) -> None:
    cliente = ClienteFactory()

    response = cliente_api(Papel.ATENDENTE).post(URL, _payload(cliente.pk, LONGE), format="json")

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "ABERTO"
    assert body["placa"] == "ABC1D23"
    distancia = Decimal(body["distancia_km"])
    km_excedente = (distancia - 40).to_integral_value(rounding="ROUND_CEILING")
    assert Decimal(body["valor_previsto"]) == Decimal("250.00") + km_excedente * Decimal("4.50")
    assert [i["tipo"] for i in body["itens"]] == ["SAIDA", "KM_EXCEDENTE"]
    assert body["distancia_fonte"] == "LINHA_RETA"  # provedor padrão
    assert len(body["rastreio_token"]) >= 20


def test_post_numero_de_queries_fixo(cliente_api, django_assert_num_queries) -> None:
    client = cliente_api(Papel.ATENDENTE)
    cliente = ClienteFactory()

    # cliente, tabela (cache miss), distância, SAVEPOINT, INSERT chamado,
    # INSERT itens (bulk), INSERT evento, RELEASE SAVEPOINT
    with django_assert_num_queries(8):
        response = client.post(URL, _payload(cliente.pk), format="json")
    assert response.status_code == 201


@pytest.mark.parametrize("papel", [Papel.PRESTADOR, Papel.DESPACHANTE, Papel.FINANCEIRO])
def test_so_atendente_cria(cliente_api, papel: Papel) -> None:
    response = cliente_api(papel).post(URL, _payload(ClienteFactory().pk), format="json")

    assert response.status_code == 403
    assert response.json()["erro"] == "sem_permissao"


def test_cliente_inexistente_ou_inativo_retorna_422(cliente_api) -> None:
    client = cliente_api(Papel.ATENDENTE)
    inativo = ClienteFactory(ativo=False)

    for cliente_id in (999_999, inativo.pk):
        response = client.post(URL, _payload(cliente_id), format="json")
        assert response.status_code == 422
        assert response.json()["erro"] == "cliente_invalido"
    assert not Chamado.objects.exists()


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("placa", "AB12345"),
        ("origem", {"lat": 91, "lng": 0}),
        ("destino", {"lat": "x"}),
        ("destino", [1, 2]),
    ],
)
def test_entrada_invalida_retorna_400(cliente_api, campo: str, valor: object) -> None:
    payload = _payload(ClienteFactory().pk) | {campo: valor}

    response = cliente_api(Papel.ATENDENTE).post(URL, payload, format="json")

    assert response.status_code == 400
    assert response.json()["erro"] == "validacao"
    assert campo in response.json()["detalhe"]
