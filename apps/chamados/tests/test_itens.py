from decimal import Decimal

import pytest
from django.urls import reverse

from apps.chamados import services
from apps.chamados.models import Chamado, EventoChamado, ItemValor, Status
from apps.contas.models import Papel
from apps.precos.tipos import TipoItem
from core.exceptions import Conflito
from tests.factories import ChamadoFactory, PrestadorFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def prestador():
    return PrestadorFactory.create(disponivel=False)


def _url(chamado: Chamado) -> str:
    return reverse("chamado-itens", args=[chamado.pk])


@pytest.mark.parametrize(
    ("payload", "tipo", "total"),
    [
        ({"tipo": "PEDAGIO", "valor": "12.40"}, "PEDAGIO", "12.40"),
        ({"tipo": "PEDAGIO", "valor": "12.40", "descricao": ""}, "PEDAGIO", "12.40"),  # formulário
        ({"tipo": "ESPERA", "minutos": 35}, "ESPERA", "45.00"),  # 3 frações × 15 min × R$ 60/h
        ({"tipo": "ADICIONAL", "valor": "80.00", "descricao": "patins"}, "ADICIONAL", "80.00"),
    ],
)
def test_prestador_lanca_itens(cliente_api, prestador, payload, tipo, total) -> None:
    chamado = ChamadoFactory.create(status=Status.EM_ATENDIMENTO, prestador=prestador)

    response = cliente_api(usuario=prestador.usuario).post(_url(chamado), payload, format="json")

    assert response.status_code == 201, response.json()
    assert (response.json()["tipo"], response.json()["total"]) == (tipo, total)
    chamado.refresh_from_db()
    assert chamado.version == 2
    evento = EventoChamado.objects.get(chamado=chamado)
    assert (evento.de_status, evento.para_status) == ("EM_ATENDIMENTO", "EM_ATENDIMENTO")
    assert evento.dados == {"item": tipo, "total": total}


def test_concluir_soma_itens_lancados(cliente_api, prestador) -> None:
    chamado = ChamadoFactory.create(status=Status.EM_ATENDIMENTO, prestador=prestador)
    ItemValor.objects.create(
        chamado=chamado, tipo=TipoItem.SAIDA, quantidade=1, valor_unitario=250, total=250
    )
    client = cliente_api(usuario=prestador.usuario)
    client.post(_url(chamado), {"tipo": "PEDAGIO", "valor": "12.40"}, format="json")
    client.post(_url(chamado), {"tipo": "ESPERA", "minutos": 35}, format="json")

    response = client.post(reverse("chamado-concluir", args=[chamado.pk]))

    assert response.json()["valor_final"] == "307.40"


def test_item_lancado_durante_conclusao_gera_409(prestador) -> None:
    chamado = ChamadoFactory.create(status=Status.EM_ATENDIMENTO, prestador=prestador)
    lido_para_concluir = Chamado.objects.get(pk=chamado.pk)  # version 1
    services.lancar_item(
        usuario=prestador.usuario,
        chamado_id=chamado.pk,
        novo=services.NovoItem(tipo=TipoItem.PEDAGIO, valor=Decimal("9.90")),
    )

    with pytest.raises(Conflito):
        services.transicionar(lido_para_concluir, Status.CONCLUIDO, usuario=None)


@pytest.mark.parametrize("status", [Status.ABERTO, Status.ACEITO, Status.CONCLUIDO])
def test_fora_do_atendimento_nao_aceita_itens(cliente_api, prestador, status) -> None:
    chamado = ChamadoFactory.create(status=status, prestador=prestador)

    response = cliente_api(usuario=prestador.usuario).post(
        _url(chamado), {"tipo": "PEDAGIO", "valor": "5"}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["erro"] == "status_nao_aceita_itens"


@pytest.mark.parametrize(
    "payload",
    [
        {"tipo": "SAIDA", "valor": "10"},
        {"tipo": "ESPERA"},
        {"tipo": "PEDAGIO"},
        {"tipo": "PEDAGIO", "valor": "0"},
    ],
)
def test_payload_invalido_retorna_400(cliente_api, prestador, payload) -> None:
    chamado = ChamadoFactory.create(status=Status.EM_ATENDIMENTO, prestador=prestador)

    response = cliente_api(usuario=prestador.usuario).post(_url(chamado), payload, format="json")

    assert response.status_code == 400


def test_prestador_de_outro_chamado_recebe_404(cliente_api, prestador) -> None:
    chamado = ChamadoFactory.create(status=Status.EM_ATENDIMENTO, prestador=PrestadorFactory())

    response = cliente_api(usuario=prestador.usuario).post(
        _url(chamado), {"tipo": "PEDAGIO", "valor": "5"}, format="json"
    )

    assert response.status_code == 404


@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.FINANCEIRO])
def test_atendente_e_financeiro_nao_lancam(cliente_api, prestador, papel) -> None:
    chamado = ChamadoFactory.create(status=Status.EM_ATENDIMENTO, prestador=prestador)

    response = cliente_api(papel).post(
        _url(chamado), {"tipo": "PEDAGIO", "valor": "5"}, format="json"
    )

    assert response.status_code == 403
